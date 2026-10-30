"""Download helpers shared by download_open.py, download_paywalled.py and fetch_si.py (library module).

- which hosts refuse scripted clients (never touched by open routes; walled publishers go through EZproxy)
- publisher URL patterns, DOI prefix -> publisher key for EZproxy pacing
- fetch(): one URL, redirects followed by hand so a bot-walled host is never requested
- file_pdf(): validate a downloaded PDF, check it is the right source, read its printed license, file it as
  sources/<topic>/<ACCESS>/<ID>.pdf for every topic that wants it (APFS clone for the 2nd+ topic) and update
  the ledger. The license printed in the PDF decides the folder.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import uuid
from collections import Counter
from pathlib import Path

import requests

import _pdf as C
from _common import (ACCESS_TYPES, PACER, access_rank, get_json, host_of, json_read, json_write_atomic, jsonl_append,
                     license_access, log, norm_license, now_iso, session, today)

# Hosts that answered plain scripted requests with a bot challenge. Open routes never touch them.
BLOCKED_SEED = {
    "onlinelibrary.wiley.com", "pubs.rsc.org", "pubs.acs.org", "www.sciencedirect.com", "sciencedirect.com",
    "linkinghub.elsevier.com", "www.cell.com", "www.mdpi.com", "susy.mdpi.com", "www.tandfonline.com",
    "pubs.aip.org", "aip.scitation.org", "academic.oup.com", "downloads.hindawi.com", "www.hindawi.com",
    "www.degruyter.com", "www.degruyterbrill.com", "chemrxiv.org", "www.science.org", "spj.science.org",
    "europepmc.org", "pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "ieeexplore.ieee.org", "dl.acm.org",
    "www.researchgate.net", "www.pnas.org", "www.annualreviews.org", "journals.sagepub.com", "www.jstor.org",
    "papers.ssrn.com", "www.ssrn.com", "doaj.org",
}
BLOCKED_SUFFIX = (".onlinelibrary.wiley.com", ".sciencedirect.com", ".elsevier.com", ".mdpi.com", ".science.org")
# Official APIs on those domains: made for scripts (with a key), unlike the publishers' web pages.
API_HOSTS = {"api.elsevier.com"}

# DOI prefix -> publisher key (one EZproxy pacing/cap bucket per key). Elsevier (10.1016/10.1006) is absent on
# purpose: its pages show a CAPTCHA even through EZproxy, and CAPTCHAs are never solved.
EZ_PREFIX = {
    "10.1002": "wiley", "10.1111": "wiley", "10.1155": "wiley", "10.1021": "acs", "10.1039": "rsc",
    "10.1007": "springer", "10.1023": "springer", "10.1134": "springer", "10.1557": "springer", "10.1140": "springer",
    "10.1038": "nature", "10.1088": "iop", "10.1149": "iop", "10.1063": "aip", "10.1116": "aip", "10.1080": "tandf",
    "10.1093": "oup", "10.1246": "oup", "10.1126": "science", "10.1073": "pnas", "10.1017": "cambridge",
    "10.1515": "degruyter", "10.1177": "sage", "10.1146": "annualreviews",
}
NOT_PROXYABLE = {"10.1016": "Elsevier (CAPTCHA wall even through EZproxy; never bypassed)",
                 "10.1006": "Elsevier (CAPTCHA wall even through EZproxy; never bypassed)"}

CHALLENGE_RX = re.compile(r"(just a moment|checking your browser|cf-chl|attention required|verifying you are human|"
                          r"access denied|errors\.edgesuite\.net|enable javascript and cookies|request unsuccessful|"
                          r"incapsula|captcha|are you a robot|preparing to download)", re.I)

_lock = threading.Lock()
_blocked = set(BLOCKED_SEED)
_challenges = Counter()
_blocked_file = {"path": None}


def ez_publisher(doi):
    return EZ_PREFIX.get((doi or "").split("/")[0])


def load_blocked(proj):
    _blocked_file["path"] = proj.scr / "blocked_hosts.json"
    _blocked.update((json_read(_blocked_file["path"], {}) or {}).get("blocked", []))


def mark_challenge(host):
    with _lock:
        _challenges[host] += 1
        if _challenges[host] >= 2 and host not in _blocked:
            _blocked.add(host)
            log(f"host {host} now treated as bot-walled for open routes")
            if _blocked_file["path"]:                # keep what other runs listed meanwhile
                _blocked.update((json_read(_blocked_file["path"], {}) or {}).get("blocked", []))
                json_write_atomic(_blocked_file["path"], {"blocked": sorted(_blocked), "updated_at": now_iso()})


def is_blocked(host):
    return host not in API_HOSTS and (host in _blocked or host.endswith(BLOCKED_SUFFIX))


def publisher_pdf_patterns(doi):
    pre, suf = doi.split("/", 1)
    if pre == "10.1038":
        return [f"https://www.nature.com/articles/{suf}.pdf"]
    if pre in ("10.1007", "10.1186", "10.1557", "10.1140", "10.1023"):
        return [f"https://link.springer.com/content/pdf/{doi}.pdf"]
    if pre in ("10.1088", "10.1149"):
        return [f"https://iopscience.iop.org/article/{doi}/pdf"]
    if pre == "10.3389":
        return [f"https://www.frontiersin.org/articles/{doi}/pdf"]
    if pre == "10.48550":
        return [f"https://export.arxiv.org/pdf/{suf.split('arxiv.', 1)[-1]}"]
    return []


def arxiv_pdf(url):
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:\.pdf)?$", url or "")
    return f"https://export.arxiv.org/pdf/{m.group(1)}" if m else url


def fetch(proj, url, accept="application/pdf,*/*;q=0.8", timeout=(15, 90), max_bytes=300 * 1024 * 1024,
          headers=None):
    """-> dict(kind=pdf|html|challenge|http_error|network_error|redirect_blocked, ...). `headers` (an API key) go to
    the URL's own host only, never to another host a redirect leads to, and are never logged."""
    host = host_of(url)
    PACER.wait(host)
    s = session()
    cur = url
    try:
        for _ in range(10):
            extra = (headers or {}) if host_of(cur) == host else {}
            r = s.get(cur, headers={"Accept": accept, **extra}, timeout=timeout, stream=True, allow_redirects=False)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                nxt = urllib.parse.urljoin(cur, r.headers["location"])
                r.close()
                if is_blocked(host_of(nxt)):
                    return {"kind": "redirect_blocked", "final_url": nxt, "status": r.status_code}
                if host_of(nxt) != host_of(cur):
                    PACER.wait(host_of(nxt))
                cur = nxt
                continue
            break
    except requests.RequestException as e:
        return {"kind": "network_error", "error": repr(e)[:200]}
    try:
        it = r.iter_content(65536)
        first = b""
        for chunk in it:
            first += chunk
            if len(first) >= 8:
                break
        if r.status_code == 200 and first[:4] == b"%PDF":
            tmp = proj.tmp / f"{uuid.uuid4().hex}.part"
            n = len(first)
            with open(tmp, "wb") as fh:
                fh.write(first)
                for chunk in it:
                    fh.write(chunk)
                    n += len(chunk)
                    if n > max_bytes:
                        break
            return {"kind": "pdf", "path": tmp, "bytes": n, "final_url": cur, "status": 200}
        body = first
        for chunk in it:
            body += chunk
            if len(body) > 4 * 1024 * 1024:
                break
        text = body.decode("utf-8", "ignore")
        server = (r.headers.get("server") or "").lower()
        chal = (r.status_code in (403, 429, 503, 202) and ("cloudflare" in server or "akamai" in server
                                                             or CHALLENGE_RX.search(text[:20000]) or r.headers.get("cf-mitigated"))) \
            or (r.status_code == 200 and len(text) < 30000 and CHALLENGE_RX.search(text[:20000]) and "citation_title" not in text)
        if chal:
            mark_challenge(host_of(cur))
            return {"kind": "challenge", "status": r.status_code, "final_url": cur}
        if r.status_code != 200:
            return {"kind": "http_error", "status": r.status_code, "final_url": cur}
        return {"kind": "html", "status": 200, "text": text, "final_url": cur}
    except requests.RequestException as e:
        return {"kind": "network_error", "error": repr(e)[:200]}
    finally:
        r.close()


def pdf_links_from_html(html, base):
    links = []
    for pat in (r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
                r'<meta[^>]+name=["\']eprints\.document_url["\'][^>]+content=["\']([^"\']+\.pdf)',
                r'<meta[^>]+name=["\']bepress_citation_pdf_url["\'][^>]+content=["\']([^"\']+)'):
        links += [m.group(1) for m in re.finditer(pat, html, re.I)]
    if not links:  # repository download anchors (DSpace / EPrints / Pure / Figshare ...)
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.{0,200}?)</a>', html, re.I | re.S):
            href, txt = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2)).lower()
            if (href.lower().split("?")[0].endswith(".pdf") or "/bitstream/" in href or "/download" in href.lower()) and \
                    ("pdf" in txt or "download" in txt or "full text" in txt or href.lower().split("?")[0].endswith(".pdf")):
                links.append(href)
    out, seen = [], set()
    for l in links:
        l = urllib.parse.urljoin(base, l.replace("&amp;", "&").strip())
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out[:4]


def attempt(proj, source_id, doi, **kw):
    jsonl_append(proj.logs / "download_attempts.jsonl", {"id": source_id, "doi": doi, "ts": now_iso(), **kw})


# ---------------------------------------------------------------- filing a PDF
def decide_access(entry, first, last):
    """-> (access, license, evidence, snippet). Strongest evidence first: license statement printed in the PDF >
    PMC license code > the copy's license metadata > how it was obtained."""
    strong, s_snip = C.article_license(first, last)
    if strong and license_access(strong):
        return license_access(strong), strong, "pdf_article_license_statement", s_snip
    pmc = entry.get("pmc_license") if entry.get("src") == "pmc_aws" else None
    if license_access(pmc):
        return license_access(pmc), pmc, "pmc_license_code", ""
    expected = entry.get("access") or "Free-to-read"
    if expected == "Paywalled":
        return "Paywalled", "all-rights-reserved", "subscription_copy_no_open_license_in_pdf", ""
    weak, w_snip, _, arr = C.license_from_text(first, last)
    meta = norm_license(entry.get("license"))
    macc = license_access(meta)
    if macc:
        if arr and entry.get("version") == "publishedVersion":
            return "Free-to-read", meta, "metadata_contradicted_by_pdf_all_rights_reserved", ""
        wacc = license_access(weak)
        if wacc and access_rank(wacc) > access_rank(macc):
            return wacc, weak, "pdf_license_mention_more_restrictive_than_metadata", w_snip
        return macc, meta, "copy_license_metadata", ""
    if license_access(weak):
        return license_access(weak), weak, "pdf_license_mention", w_snip
    return "Free-to-read", meta if meta in ("publisher-specific", "other-oa") else "other-oa", "oa_copy_without_reuse_license", ""


_CC_URL = re.compile(r"https?://creativecommons\.org/(?:licenses|publicdomain)/[a-z\-]+/\d\.\d[^\s)\]>\"']*", re.I)


def pdf_license_fields(paper, entry, access, lic, evidence, snip, method):
    """Exact license label (with version), URL and source after the PDF check."""
    from _common import license_detail
    if evidence == "patent_office":
        return "Patent document (public record)", None, "Patent office"
    if access == "Paywalled":
        return "Subscription (no open license)", None, "How obtained (institutional access)"
    m = _CC_URL.search(snip or "")
    if evidence in ("pdf_article_license_statement", "pdf_license_mention", "pdf_license_mention_more_restrictive_than_metadata"):
        label, _ = license_detail(snip, lic)
        return label, (m.group(0).rstrip(".,;") if m else None), "PDF (printed license statement)"
    raw = entry.get("license_raw") or entry.get("license")
    if evidence == "pmc_license_code":
        label, url = license_detail(raw if norm_license(raw) == lic else None, lic)
        return label, url, "PubMed Central"
    if evidence == "metadata_contradicted_by_pdf_all_rights_reserved":
        return "Free to read (PDF says all rights reserved)", None, "PDF"
    if evidence == "copy_license_metadata":
        label, url = license_detail(raw, lic)
        return label, url, (paper.get("license_source") or C2_SOURCE.get(entry.get("src"), entry.get("src")))
    label, url = license_detail(raw if norm_license(raw) == lic else None, lic)
    return (label or "Free to read (no license)"), url, (paper.get("license_source") or "Metadata")


C2_SOURCE = {"unpaywall": "Unpaywall", "openalex": "OpenAlex", "openaire": "OpenAIRE", "pmc_aws": "PubMed Central",
             "europepmc": "Europe PMC", "s2": "Semantic Scholar", "preprint": "Preprint server", "arxiv": "arXiv (DataCite)",
             "mdpi_cdn": "Crossref", "publisher_pattern": "Crossref"}


def clone_or_copy(src, dst):
    """APFS clone (no extra disk) when possible, else hard link, else a plain copy."""
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    if Path(dst).exists():
        return
    try:
        if subprocess.run(["cp", "-c", str(src), str(dst)], capture_output=True).returncode == 0:
            return
    except OSError:
        pass
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


_sha_lock = threading.Lock()


def file_pdf(proj, led, paper, entry, tmp, method, final_url=None):
    """Validate + same-paper check + license decision; file into every wanting topic; update the ledger.
    Returns (outcome, detail): valid_pdf | invalid_pdf | wrong_paper | duplicate."""
    ok, reason, pages = C.validate(tmp)
    if not ok:
        Path(tmp).unlink(missing_ok=True)
        return "invalid_pdf", reason
    first, last = C.extract_text(tmp)
    rej = proj.scr / "rejected" / "wrong_paper"
    rej.mkdir(parents=True, exist_ok=True)
    if paper.get("doc_type") == "patent":   # patent office scans: no title check, no license statement to read
        return _file_checked(proj, led, paper, entry, tmp, pages, final_url, method,
                             ("Free-to-read", "other-oa", "patent_office", ""))
    if C.looks_like_si_document(first):
        Path(tmp).replace(rej / f"si_{paper['id']}_{uuid.uuid4().hex[:8]}.pdf")
        return "wrong_paper", "file is a supporting-information document, not the article"
    tm = C.title_match(paper.get("title"), first)
    thr = 0.5 if entry.get("version") in ("submittedVersion", "acceptedVersion") else 0.55
    if tm is not None and tm < thr:
        alt = C.poppler_text(tmp)                 # a second reader: some fonts defeat the first one
        tm = max(tm, C.title_match(paper.get("title"), alt) or 0.0)
        first = f"{first}\n{alt}"
        # the source's own DOI printed in it also proves it (3+ pages: a short correction notice prints it too)
        if tm < thr and not (pages >= 3 and C.doi_printed(paper.get("doi"), first)):
            dst = rej / f"{paper['id']}_{uuid.uuid4().hex[:8]}.pdf"
            Path(tmp).replace(dst)
            why = f"title_match={tm:.2f}" if first.strip() else "no text layer (pages are images): title not checked"
            return "wrong_paper", f"{why} kept at {proj.rel(dst)}"
    return _file_checked(proj, led, paper, entry, tmp, pages, final_url, method, decide_access(entry, first, last))


def _file_checked(proj, led, paper, entry, tmp, pages, final_url, method, decision):
    access, lic, evidence, snip = decision
    digest = C.sha1(tmp)
    with _sha_lock:
        dup = led.q("SELECT id FROM sources WHERE sha1=? AND id<>?", (digest, paper["id"]))
        if dup:
            Path(tmp).unlink(missing_ok=True)
            led.set(paper["id"], dl_status="duplicate", dl_note=f"Same PDF as ID {dup[0][0]}")
            return "duplicate", f"same file as source {dup[0][0]}"
        topics = [t for t in led.topics_of(paper["id"]) if t.get("in_scope") != 0]
        if not topics:
            topics = led.topics_of(paper["id"])[:1]
        paths = {}
        firstp = None
        for t in topics:
            d = proj.pdf_dir(t["topic"], access)
            d.mkdir(parents=True, exist_ok=True)
            dst = d / f"{paper['id']}.pdf"
            if firstp is None:
                Path(tmp).replace(dst)
                firstp = dst
            else:
                clone_or_copy(firstp, dst)
            paths[t["topic"]] = proj.rel(dst)
        meta_access = paper.get("access_type")
        basis = "pdf" if evidence in ("pdf_article_license_statement", "pmc_license_code") else "metadata"
        if meta_access and meta_access != access and meta_access != "Paywalled":
            basis = "pdf_differs"
        label, lurl, lsrc = pdf_license_fields(paper, entry, access, lic, evidence, snip, method)
        led.set(paper["id"], downloaded=1, access_type=access, license=lic, license_evidence=evidence,
                access_basis=basis, version=entry.get("version"), download_source=entry.get("src"),
                download_url=(final_url or entry.get("url") or "")[:500], download_date=today(), sha1=digest,
                page_count=pages, dl_status=None, dl_note=None, license_label=label, license_url=lurl,
                license_source=lsrc, last_checked=today())
        for topic, rel in paths.items():
            led.set_topic(paper["id"], topic, path=rel)
    return "valid_pdf", f"id={paper['id']} access={access} folders={len(paths)}"


def link_existing(proj, led, topic):
    """Sources of `topic` that another topic already downloaded: clone the PDF (and SI) into this topic's folders
    instead of downloading again. Returns the number of sources linked."""
    rows = led.topic_rows(topic, "AND p.downloaded = 1 AND t.path IS NULL AND COALESCE(t.in_scope, 1) = 1")
    n = 0
    for p in rows:
        others = [t for t in led.topics_of(p["id"]) if t.get("path") and t["topic"] != topic]
        src = next((proj.root / t["path"] for t in others if (proj.root / t["path"]).exists()), None)
        if not src:
            continue
        acc = p.get("access_type") or "Free-to-read"
        dst = proj.pdf_dir(topic, acc) / f"{p['id']}.pdf"
        clone_or_copy(src, dst)
        si_rels = []
        o = next(t for t in others if (proj.root / t["path"]).exists())
        for sp in json.loads(o.get("si_paths") or "[]"):
            s = proj.root / sp
            if s.exists():
                d = proj.si_dir(topic, acc) / s.name
                clone_or_copy(s, d)
                si_rels.append(proj.rel(d))
        led.set_topic(p["id"], topic, path=proj.rel(dst), si_paths=si_rels)
        n += 1
    return n


# ------------------------------------------------------------------ SI links on a landing page (find_si, fetch_si)
SI_URL = re.compile(r"(suppl|supplement|support[-_]?info|supporting|MediaObjects|MOESM|_ESM\b|/esm/|mmc\d|suppdata|"
                    r"additional[-_]?file|ancillary|Data[_-]?Sheet|DataSheet|Presentation[_-]\d|Video[_-]\d|"
                    r"Table[_-]\d+\.(xlsx?|docx?|pdf|csv)|type=supplementary|downloadSupplement|_si_\d|[_-]si[_.-]|"
                    r"/suppl_file/|supp\d)", re.I)
EXT = re.compile(r"\.(pdf|docx?|xlsx?|csv|txt|zip|gz|tgz|rar|7z|cif|xyz|mp4|avi|mov|mpg|wmv|json|dat|xml|pptx?|tif|mat|h5)(\?|$|#)", re.I)
IMG = re.compile(r"\.(jpe?g|png|gif|svg|webp)(\?|$)", re.I)


def extract_si_links(html, base):
    urls = []
    for m in re.finditer(r'(?:href|src|data-url|data-href)=["\']([^"\']+)["\']', html, re.I):
        u = urllib.parse.urljoin(base, m.group(1).replace("&amp;", "&"))
        du = urllib.parse.unquote(u)
        if IMG.search(du.split("?")[0]) or not du.startswith("http"):
            continue
        if SI_URL.search(du) and (EXT.search(du) or "downloadSupplement" in du or "type=supplementary" in du):
            if u not in urls:
                urls.append(u)
    return urls[:40]


def landing_url_for(doi):
    pre, suf = doi.split("/", 1)
    if pre == "10.1038":
        return f"https://www.nature.com/articles/{suf}"
    if pre in ("10.1007", "10.1557", "10.1140", "10.1023"):
        return f"https://link.springer.com/article/{doi}"
    if pre in ("10.1088", "10.1149"):
        return f"https://iopscience.iop.org/article/{doi}/data"
    if pre == "10.3389":
        return f"https://www.frontiersin.org/articles/{doi}/full"
    try:  # doi.org handle API -> target URL without touching the publisher
        d = get_json(f"https://doi.org/api/handles/{urllib.parse.quote(doi, safe='/')}", tries=3)
        for v in d.get("values") or []:
            if v.get("type") == "URL":
                return (v.get("data") or {}).get("value")
    except Exception:
        return None
    return None


def route_landing(proj, doi):
    url = landing_url_for(doi)
    if not url or is_blocked(host_of(url)):
        return []
    res = fetch(proj, url, accept="text/html,application/xhtml+xml,*/*;q=0.8")
    if res["kind"] != "html" or is_blocked(host_of(res.get("final_url", ""))):
        return []
    return [("landing", u) for u in extract_si_links(res["text"], res["final_url"])]
