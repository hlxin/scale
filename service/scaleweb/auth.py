"""GitHub sign-in, the allowlist and the day's budgets.

The page sends the user to ``/auth/login``; GitHub returns them to ``/auth/callback``, which exchanges the code for
their login and, when the login is on the allowlist, sends them back to the page with a signed session token in the
URL fragment (never in a cookie: the page and the service are on different sites). The token is ``login.expiry.mac``
(HMAC-SHA256 with the service secret); the GitHub access token is used once to read the login and then dropped.

A sign-in is one transaction. The page starts it with a random nonce that it keeps in its own tab, and the service
returns that nonce with its answer; the page takes a token only with the nonce it is waiting for, so a sign-in started
by someone else (a link, another tab) never signs a reader in. The OAuth state is used once.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request

from .config import Config


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(cfg: Config, payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = _b64(hmac.new(cfg.secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def unsign(cfg: Config, token: str) -> dict | None:
    try:
        body, mac = token.split(".")
    except (ValueError, AttributeError):
        return None
    good = _b64(hmac.new(cfg.secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, good):
        return None
    try:
        payload = json.loads(_unb64(body))
    except ValueError:
        return None
    return payload if payload.get("exp", 0) > time.time() else None


# Every token the service signs names what it is for ("use"), and each check accepts only its own kind: a receipt,
# which lives a week, never signs anyone in, and a session never stands for a receipt.
def session_for(cfg: Config, login: str) -> str:
    return sign(cfg, {"use": "session", "sub": login.lower(), "exp": int(time.time()) + cfg.session_ttl_s})


def admitted(cfg: Config, login: str | None) -> bool:
    """A login the service serves: one on the allowlist, or any GitHub account when the allowlist is ``*``."""
    return bool(login) and ("*" in cfg.allowlist or login.lower() in cfg.allowlist)


def user_of(cfg: Config, header: str | None) -> str | None:
    """The admitted login an ``Authorization: Bearer`` header carries, else None."""
    if not header or not header.startswith("Bearer "):
        return None
    p = unsign(cfg, header[7:].strip()) or {}
    login = p.get("sub") if p.get("use") == "session" else None
    return login if admitted(cfg, login) else None


NONCE = re.compile(r"[A-Za-z0-9_-]{16,128}")
ANSWER = ("token", "signin", "login", "nonce")      # the fragment keys the service writes back to the page


def clean_return(cfg: Config, url: str) -> str | None:
    """The page to return to, rebuilt from its parts, when it is a page of the site; else None. Anything but printable
    ASCII is refused before parsing, so nothing a caller sends can add a header to the redirect."""
    if not isinstance(url, str) or not url or any(not "!" <= c <= "~" for c in url):
        return None
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("https", "http") or f"{u.scheme}://{u.netloc}" not in cfg.site_origins:
        return None
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path or "/", u.query, u.fragment))


def answer_url(ret: str, answer: dict) -> str:
    """The page's address with the service's answer merged into its fragment, which keeps what the page had there
    (the explorer's open graph, #g=…) and drops any earlier answer."""
    u = urllib.parse.urlsplit(ret)
    kept = [(k, v) for k, v in urllib.parse.parse_qsl(u.fragment, keep_blank_values=True) if k not in ANSWER]
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, u.query, urllib.parse.urlencode(kept + list(answer.items()))))


def login_url(cfg: Config, return_to: str, nonce: str) -> str:
    state = sign(cfg, {"ret": return_to, "b": nonce, "n": secrets.token_urlsafe(12), "exp": int(time.time()) + 600})
    q = {"client_id": cfg.github_client_id, "redirect_uri": f"{cfg.public_url}/auth/callback", "state": state,
         "scope": "", "allow_signup": "false"}
    return "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(q)


class Once:
    """OAuth states already used, until they expire (in memory: one instance, as the budgets)."""

    def __init__(self):
        self.lock, self.seen = threading.Lock(), {}

    def take(self, key: str, exp: float) -> bool:
        """True the first time a key is taken; False when it was taken before."""
        with self.lock:
            now = time.time()
            self.seen = {k: e for k, e in self.seen.items() if e > now}
            if key in self.seen:
                return False
            self.seen[key] = exp
            return True


def github_login(cfg: Config, code: str, opener=urllib.request.urlopen) -> str:
    """Exchange an OAuth code for the user's GitHub login."""
    data = urllib.parse.urlencode({"client_id": cfg.github_client_id, "client_secret": cfg.github_client_secret,
                                   "code": code, "redirect_uri": f"{cfg.public_url}/auth/callback"}).encode()
    req = urllib.request.Request("https://github.com/login/oauth/access_token", data=data,
                                 headers={"Accept": "application/json"})
    with opener(req, timeout=30) as r:
        tok = json.loads(r.read()).get("access_token")
    if not tok:
        raise PermissionError("GitHub did not grant a token")
    req = urllib.request.Request("https://api.github.com/user",
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
    with opener(req, timeout=30) as r:
        return json.loads(r.read())["login"]


class Budget:
    """Jobs, questions and contributions per user and tokens over everyone, counted per UTC day, in memory (one instance)."""

    def __init__(self, cfg: Config):
        self.cfg, self.lock = cfg, threading.Lock()
        self.day, self.jobs, self.questions, self.contributions, self.tokens = "", {}, {}, {}, 0

    def _today(self) -> None:
        d = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        if d != self.day:
            self.day, self.jobs, self.questions, self.contributions, self.tokens = d, {}, {}, {}, 0

    def take(self, kind: str, login: str) -> str | None:
        """Count one job, question or contribution for the user; the reason it is refused, or None."""
        with self.lock:
            self._today()
            if self.tokens >= self.cfg.tokens_per_day:
                return "the service has spent today's model budget; try again tomorrow (UTC)"
            counts, limit = {"job": (self.jobs, self.cfg.jobs_per_user_per_day),
                             "question": (self.questions, self.cfg.questions_per_user_per_day),
                             "contribution": (self.contributions, self.cfg.contributions_per_user_per_day)}[kind]
            if counts.get(login, 0) >= limit:
                return f"you have used today's {limit} {kind}s; try again tomorrow (UTC)"
            counts[login] = counts.get(login, 0) + 1
            return None

    def spend(self, tokens: int) -> None:
        with self.lock:
            self._today()
            self.tokens += tokens

    def left(self) -> int:
        with self.lock:
            self._today()
            return max(0, self.cfg.tokens_per_day - self.tokens)


def _plain(obj):
    """A graph as JSON gives it back after a round trip through the page (a whole float reads as an integer)."""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, list):
        return [_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    return obj


def graph_digest(graph: dict) -> str:
    return hashlib.sha256(json.dumps(_plain(graph), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def receipt(cfg: Config, owner: str, graph: dict, entry: dict) -> str:
    """What the service signs for a graph it curated: whose it is, its digest and its source's rights, a week long."""
    return sign(cfg, {"use": "receipt", "sub": owner, "g": graph_digest(graph), "r": entry, "exp": int(time.time()) + 7 * 86400})


def check_receipt(cfg: Config, token: str, owner: str, graph: dict) -> dict | None:
    """The rights entry a receipt signs, when it is the owner's and for this very graph; else None."""
    p = unsign(cfg, token or "")
    if not p or p.get("use") != "receipt" or p.get("sub") != owner or p.get("g") != graph_digest(graph):
        return None
    return p.get("r")
