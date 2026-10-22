"""EZproxy fetching (library module) — used by check_paywalled_access.py and download_paywalled.py.

Plain HTTP through EZproxy host rewriting (https://pubs-acs-org.<ezproxy host>/...). On the campus network or VPN,
EZproxy recognises the institution's IP and serves subscribed content without a login. This code NEVER logs in,
never types credentials and never solves a CAPTCHA: a login page pauses everything, a usage-limit page stops
everything, a bot challenge puts the publisher in cooldown (see _ezlimit.py). Every request is counted by the limiter.
"""
import html as _html
import re
import time
import urllib.parse
import uuid

import requests

from _common import host_of, now_iso
from _download import CHALLENGE_RX, attempt, file_pdf, pdf_links_from_html

EZ_USAGE_RX = re.compile(r"(usage limit|limit (has been )?exceeded|has been suspended|account (is )?suspended|"
                         r"excessive (use|download)|too many (requests|downloads)|systematic download|blocked due to)", re.I)
EZ_NOTCONF_RX = re.compile(r"(must be included in the config|config\.txt|is not configured|not a valid starting point)", re.I)
NOT_SUB_RX = re.compile(r"(purchase (this )?(article|pdf)|buy (this )?article|get access|access through your institution|"
                        r"rent this article|subscribe to|log in via|check access|you do not have access)", re.I)
RETRYABLE = {"blocked", "network_error", "login_prompt", "ez_server_error"}


def ezrewrite(url, ez_host):
    m = re.match(r"^(https?://)([^/]+)(/.*)?$", url or "")
    if not m or ez_host in m.group(2):
        return url
    host = m.group(2).replace("-", "--").replace(".", "-")
    return m.group(1) + host + "." + ez_host + (m.group(3) or "")


def ez_patterns(doi, pub):
    suf = doi.split("/", 1)[1]
    return {
        "acs": [f"https://pubs.acs.org/doi/pdf/{doi}?download=true"],
        "wiley": [f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true"],
        "tandf": [f"https://www.tandfonline.com/doi/pdf/{doi}?download=true"],
        "science": [f"https://www.science.org/doi/pdf/{doi}?download=true"],
        "pnas": [f"https://www.pnas.org/doi/pdf/{doi}?download=true"],
        "springer": [f"https://link.springer.com/content/pdf/{doi}.pdf"],
        "nature": [f"https://www.nature.com/articles/{suf}.pdf"],
        "iop": [f"https://iopscience.iop.org/article/{doi}/pdf"],
    }.get(pub, [])  # RSC / AIP / OUP / Cambridge / De Gruyter / SAGE / Annual Reviews: landing citation_pdf_url


class TooLarge(Exception):
    pass


class EzResp:
    def __init__(self, status, url, headers, content):
        self.status_code, self.url, self.headers, self.content = status, url, headers, content

    @property
    def text(self):
        return self.content.decode("utf-8", "ignore")


def _req(sess, lim, method, url, accept, data=None):
    cap = lim.limits()["max_file_mb"] * 1e6
    r = sess.request(method, url, data=data, headers={"Accept": accept}, timeout=(20, 120), allow_redirects=True, stream=True)
    try:
        buf = bytearray()
        for chunk in r.iter_content(65536):
            buf += chunk
            if len(buf) > cap:
                lim.add_bytes(len(buf))
                raise TooLarge(f"response larger than {lim.limits()['max_file_mb']} MB — aborted")
        lim.add_bytes(len(buf))
        return EzResp(r.status_code, r.url, r.headers, bytes(buf))
    finally:
        r.close()


def ez_get(sess, lim, url, accept):
    """GET through EZproxy, following the site's own auto-submitting forms (what a browser does on page load;
    no credentials involved)."""
    r = _req(sess, lim, "GET", url, accept)
    for _ in range(3):
        if r.content[:4] == b"%PDF" or len(r.content) > 30000:
            break
        m = re.search(r"<form[^>]+method=['\"]post['\"][^>]+action=['\"]([^'\"]+)['\"]", r.text, re.I)
        if not m:
            break
        data = {a: _html.unescape(b) for a, b in re.findall(
            r"<input[^>]+type=['\"]hidden['\"][^>]+name=['\"]([^'\"]+)['\"][^>]+value=['\"]([^'\"]*)['\"]", r.text, re.I)}
        r = _req(sess, lim, "POST", _html.unescape(m.group(1)), accept, data=data)
    return r


def save_evidence(proj, r, label):
    """Keep the HTML of any response that stops or blocks the runner, for a human to review."""
    try:
        d = proj.logs / "ezproxy_evidence"
        d.mkdir(parents=True, exist_ok=True)
        name = f"{time.strftime('%Y%m%d-%H%M%S')}_{label}_{re.sub(r'[^A-Za-z0-9]+', '_', r.url)[:120]}.html"
        (d / name).write_bytes(r.content[:2_000_000])
        return proj.rel(d / name)
    except Exception:
        return None


def signal(proj, r, ez_host):
    """Classify a non-PDF EZproxy response: login_prompt | usage_limit | not_configured | blocked | ez_server_error
    | not_subscribed | None."""
    fh = host_of(r.url)
    head = r.text[:30000] if r.content[:4] != b"%PDF" else ""
    own = fh in (ez_host, f"login.{ez_host}") or (len(r.content) < 15000 and re.search(r"ezproxy", head, re.I)
                                                  and "citation_title" not in head)
    if (fh in (ez_host, f"login.{ez_host}") and urllib.parse.urlsplit(r.url).path.startswith("/login")) or \
            (own and re.search(r"(sign in|log ?in|password|single sign-on|shibboleth|duo)", head, re.I)
             and not EZ_USAGE_RX.search(head) and not EZ_NOTCONF_RX.search(head)):
        save_evidence(proj, r, "login_prompt")
        return "login_prompt"
    if own and EZ_USAGE_RX.search(head):
        save_evidence(proj, r, "usage_limit")
        return "usage_limit"
    if own and EZ_NOTCONF_RX.search(head):
        save_evidence(proj, r, "not_configured")
        return "not_configured"
    if r.status_code in (403, 429, 503) or (len(head) < 30000 and CHALLENGE_RX.search(head)):
        save_evidence(proj, r, "blocked")
        return "blocked"
    if r.status_code in (500, 502, 504):
        return "ez_server_error"
    if NOT_SUB_RX.search(head):
        return "not_subscribed"
    return None


def _save(proj, r):
    tmp = proj.tmp / f"{uuid.uuid4().hex}.part"
    tmp.write_bytes(r.content)
    return tmp


def fetch_paper(proj, led, sess, lim, ez_host, paper, pub):
    """One paper through EZproxy (the visit was already granted by the limiter) -> outcome string."""
    doi = paper["doi"]
    entry = {"src": "ezproxy", "version": "publishedVersion", "access": "Paywalled" if paper.get("access_type") == "Paywalled"
             else paper.get("access_type"), "license": paper.get("license")}
    urls = [ezrewrite(u, ez_host) for u in ez_patterns(doi, pub)]
    try:
        if not urls:  # landing first, then its citation_pdf_url
            r = ez_get(sess, lim, ezrewrite(f"https://doi.org/{doi}", ez_host), "text/html,application/xhtml+xml,*/*;q=0.8")
            if r.content[:4] == b"%PDF":
                out, why = file_pdf(proj, led, paper, entry, _save(proj, r), "ezproxy", r.url)
                attempt(proj, paper["id"], doi, step="ezproxy.landing", url=r.url[:300], outcome=out, reason=why)
                return out
            sig = signal(proj, r, ez_host)
            if sig and sig != "not_subscribed":
                attempt(proj, paper["id"], doi, step="ezproxy.landing", url=r.url[:300], outcome=sig, http_status=r.status_code)
                return sig
            urls = [l if ez_host in host_of(l) else ezrewrite(l, ez_host) for l in pdf_links_from_html(r.text, r.url)]
            if not urls:
                attempt(proj, paper["id"], doi, step="ezproxy.landing", url=r.url[:300], outcome=sig or "no_pdf_link")
                return sig or "no_pdf"
        last = "no_pdf"
        for u in urls[:2]:
            r = ez_get(sess, lim, u, "application/pdf,*/*;q=0.8")
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                out, why = file_pdf(proj, led, paper, entry, _save(proj, r), "ezproxy", r.url)
                attempt(proj, paper["id"], doi, step="ezproxy", url=u[:300], outcome=out, reason=why, bytes=len(r.content))
                return out
            sig = signal(proj, r, ez_host) or "no_pdf"
            attempt(proj, paper["id"], doi, step="ezproxy", url=u[:300], outcome=sig, http_status=r.status_code)
            if sig in ("login_prompt", "usage_limit", "not_configured", "blocked", "ez_server_error"):
                return sig
            last = sig
        return last
    except TooLarge as e:
        attempt(proj, paper["id"], doi, step="ezproxy", url=(urls[0] if urls else doi), outcome="too_large", error=str(e))
        return "too_large"
    except requests.RequestException as e:
        attempt(proj, paper["id"], doi, step="ezproxy", url=(urls[0] if urls else doi), outcome="network_error",
                error=repr(e)[:200])
        return "network_error"


def fetch_si(proj, led, sess, lim, ez_host, paper, pub, extract_si_links, ext_of, clone_or_copy):
    """SI landing visit (already granted) + one granted visit per SI file -> (outcome, n_files)."""
    doi = paper["doi"]
    try:
        land = ez_get(sess, lim, ezrewrite(f"https://doi.org/{doi}", ez_host), "text/html,*/*;q=0.8")
    except (requests.RequestException, TooLarge):
        return "network_error", 0
    sig = signal(proj, land, ez_host)
    if sig and sig != "not_subscribed":
        return sig, 0
    links = [l if ez_host in host_of(l) else ezrewrite(l, ez_host) for l in extract_si_links(land.text, land.url)][:6]
    got = []
    for k, l in enumerate(links, 1):
        while True:
            ok, wait, why = lim.acquire(pub)
            if ok or wait is None:
                break
            time.sleep(min(max(wait, 1), 300))
        if not ok:
            break
        try:
            rr = ez_get(sess, lim, l, "*/*")
        except (requests.RequestException, TooLarge):
            continue
        s2 = signal(proj, rr, ez_host) if rr.content[:4] != b"%PDF" else None
        if s2 in ("login_prompt", "usage_limit", "blocked"):
            return s2, len(got)
        low = rr.content[:512].lower()
        if rr.status_code != 200 or b"<html" in low or b"<!doctype html" in low or len(rr.content) < 200:
            continue
        got.append((rr.content, ext_of(rr.url, rr.headers.get("content-type", ""))))
    if not got:
        return "si_not_found", 0
    names = [f"{paper['id']}_SI.{e}" if len(got) == 1 else f"{paper['id']}_SI_{i}.{e}" for i, (_, e) in enumerate(got, 1)]
    acc = paper.get("access_type") or "Paywalled"
    firsts = {}
    for t in [t for t in led.topics_of(paper["id"]) if t.get("path")]:
        d = proj.si_dir(t["topic"], acc)
        d.mkdir(parents=True, exist_ok=True)
        rels = []
        for i, (content, _) in enumerate(got):
            dst = d / names[i]
            if i not in firsts:
                dst.write_bytes(content)
                firsts[i] = dst
            else:
                clone_or_copy(firsts[i], dst)
            rels.append(proj.rel(dst))
        led.set_topic(paper["id"], t["topic"], si_paths=rels)
    led.set(paper["id"], si_status="found", si_files=names)
    return "si_downloaded", len(got)
