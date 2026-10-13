"""GitHub sign-in, the allowlist and the day's budgets.

The page sends the user to ``/auth/login``; GitHub returns them to ``/auth/callback``, which exchanges the code for
their login and, when the login is on the allowlist, sends them back to the page with a signed session token in the
URL fragment (never in a cookie: the page and the service are on different sites). The token is ``login.expiry.mac``
(HMAC-SHA256 with the service secret); the GitHub access token is used once to read the login and then dropped.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import json
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


def session_for(cfg: Config, login: str) -> str:
    return sign(cfg, {"sub": login.lower(), "exp": int(time.time()) + cfg.session_ttl_s})


def user_of(cfg: Config, header: str | None) -> str | None:
    """The allowlisted login an ``Authorization: Bearer`` header carries, else None."""
    if not header or not header.startswith("Bearer "):
        return None
    p = unsign(cfg, header[7:].strip())
    login = (p or {}).get("sub")
    return login if login and login in cfg.allowlist else None


def allowed_return(cfg: Config, url: str) -> bool:
    u = urllib.parse.urlparse(url)
    return f"{u.scheme}://{u.netloc}" in cfg.site_origins


def login_url(cfg: Config, return_to: str) -> str:
    state = sign(cfg, {"ret": return_to, "n": secrets.token_urlsafe(8), "exp": int(time.time()) + 600})
    q = {"client_id": cfg.github_client_id, "redirect_uri": f"{cfg.public_url}/auth/callback", "state": state,
         "scope": "", "allow_signup": "false"}
    return "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(q)


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
    """Jobs and questions per user and tokens over everyone, counted per UTC day, in memory (one instance)."""

    def __init__(self, cfg: Config):
        self.cfg, self.lock = cfg, threading.Lock()
        self.day, self.jobs, self.questions, self.tokens = "", {}, {}, 0

    def _today(self) -> None:
        d = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        if d != self.day:
            self.day, self.jobs, self.questions, self.tokens = d, {}, {}, 0

    def take(self, kind: str, login: str) -> str | None:
        """Count one job or question for the user; the reason it is refused, or None."""
        with self.lock:
            self._today()
            if self.tokens >= self.cfg.tokens_per_day:
                return "the service has spent today's model budget; try again tomorrow (UTC)"
            counts, limit = ((self.jobs, self.cfg.jobs_per_user_per_day) if kind == "job"
                             else (self.questions, self.cfg.questions_per_user_per_day))
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
