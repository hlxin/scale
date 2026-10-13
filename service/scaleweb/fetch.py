"""What a user gives: a DOI, or a link to a PDF (or to a page naming a DOI), fetched with care.

A link is fetched only over http(s), only from a public address (every redirect is checked again, so a link cannot
reach the service's own network), and only up to the upload limit. A doi.org link or a text holding a DOI is a DOI:
``scale source start`` resolves it (Crossref, and Unpaywall for an open-access copy under an open licence).
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
import urllib.request

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>#?]+)", re.I)
UA = "scale-catal web (https://github.com/hlxin/scale)"


class FetchError(Exception):
    pass


def doi_in(text: str) -> str | None:
    """The DOI a text names (a bare DOI, ``doi:…``, a doi.org link, a publisher link that carries one), else None."""
    m = DOI_RE.search(urllib.parse.unquote(text or ""))
    return m.group(1).rstrip(".,;)") if m else None


def arxiv_pdf(url: str) -> str | None:
    m = re.match(r"https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:\.pdf)?$", url.strip())
    return f"https://arxiv.org/pdf/{m.group(1)}" if m else None


def _public_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise FetchError(f"cannot resolve {host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise FetchError(f"{host} is not a public address")


def check_url(url: str) -> str:
    u = urllib.parse.urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise FetchError("give an http(s) link")
    _public_host(u.hostname)
    return u.geturl()


class _Checked(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get_pdf(url: str, max_bytes: int, opener=None) -> bytes:
    """The PDF a link points to (an arXiv page becomes its PDF); refused when it is not a PDF or is too large."""
    url = check_url(arxiv_pdf(url) or url)
    opener = opener or urllib.request.build_opener(_Checked())
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/pdf"})
    with opener.open(req, timeout=60) as r:
        data = r.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise FetchError(f"the file is larger than {max_bytes // 2**20} MB")
    if not data.startswith(b"%PDF"):
        raise FetchError("the link does not lead to a PDF (many publishers refuse downloads): upload the PDF instead")
    return data
