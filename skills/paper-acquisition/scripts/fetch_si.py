"""Step 8 — supplementary information (SI) for downloaded papers of a topic.

Routes, by DOI (independent of where the main PDF came from):
  1 PMC open-data mirror media files     2 SI deposits the search already linked to the paper (Figshare / Zenodo DOIs)
  3 publisher landing page on hosts that serve scripted clients     4 ACS SI mirrored on Figshare
  5 MDPI CDN (-s001...)      6 Elsevier SI CDN (mmcN by PII)
  7 Crossref has-supplementary-material / Zenodo / Figshare / Dryad (title-affinity checked)
Files go to publications/<topic>/papers/SI/<ACCESS>/<ID>_SI.<ext> (one file) or <ID>_SI_1.<ext>, <ID>_SI_2.<ext> ...,
ACCESS = the paper's own folder. SI that only lives on a walled publisher site is queued for the EZproxy runner
when paywalled access is set up.

usage: python3 -I fetch_si.py --topic <slug> [--workers 8] [--retry]
"""
import argparse
import json
import re
import sys
import threading
import urllib.parse
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _mdpi as MDPI
import _pdf as C
from _common import (PACER, HTTPFail, Project, add_project_arg, get_json, host_of, http_get, json_read, jsonl_iter,
                     load_config, log, norm_title, now_iso, session, update_state)
from _download import attempt, clone_or_copy, ez_publisher, fetch, is_blocked, load_blocked
from _ledger import Ledger

SI_URL = re.compile(r"(suppl|supplement|support[-_]?info|supporting|MediaObjects|MOESM|_ESM\b|/esm/|mmc\d|suppdata|"
                    r"additional[-_]?file|ancillary|Data[_-]?Sheet|DataSheet|Presentation[_-]\d|Video[_-]\d|"
                    r"Table[_-]\d+\.(xlsx?|docx?|pdf|csv)|type=supplementary|downloadSupplement|_si_\d|[_-]si[_.-]|"
                    r"/suppl_file/|supp\d)", re.I)
EXT = re.compile(r"\.(pdf|docx?|xlsx?|csv|txt|zip|gz|tgz|rar|7z|cif|xyz|mp4|avi|mov|mpg|wmv|json|dat|xml|pptx?|tif|mat|h5)(\?|$|#)", re.I)
IMG = re.compile(r"\.(jpe?g|png|gif|svg|webp)(\?|$)", re.I)
MAX_SI_BYTES = 250 * 1024 * 1024  # larger SI archives are skipped (videos / raw data dumps)
for _h, _iv in {"api.figshare.com": 1.1, "ars.els-cdn.com": 0.5, "media.springernature.com": 0.5,
                "static-content.springer.com": 0.5, "datadryad.org": 1.0, "mdpi-res.com": 1.0}.items():
    PACER.set(_h, _iv)


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


def ext_of(url, ctype=""):
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    m = re.search(r"\.([A-Za-z0-9]{1,5})$", path)
    if m and m.group(1).lower() not in ("html", "htm", "php", "aspx", "jsp"):
        e = m.group(1).lower()
        return "tar.gz" if e == "gz" and path.lower().endswith(".tar.gz") else e
    ct = (ctype or "").lower()
    for k, e in (("pdf", "pdf"), ("zip", "zip"), ("word", "docx"), ("spreadsheet", "xlsx"), ("excel", "xls"),
                 ("msword", "doc"), ("csv", "csv"), ("plain", "txt"), ("mp4", "mp4"), ("xml", "xml")):
        if k in ct:
            return e
    return "bin"


def download_file(proj, url):
    """Download one non-HTML SI file to tmp -> (path, bytes, ext, final_url) or None."""
    h = host_of(url)
    if is_blocked(h):
        return None
    PACER.wait(h)
    try:
        r = session().get(url, timeout=(15, 180), stream=True, allow_redirects=True, headers={"Accept": "*/*"})
    except Exception:
        return None
    try:
        if r.status_code != 200:
            return None
        ctype = r.headers.get("content-type", "")
        it = r.iter_content(65536)
        first = b""
        for chunk in it:
            first += chunk
            if len(first) >= 512:
                break
        low = first[:512].lower()
        if ("text/html" in ctype.lower() or b"<html" in low or b"<!doctype html" in low) and not url.lower().endswith((".html", ".htm")):
            return None
        tmp = proj.tmp / f"si_{uuid.uuid4().hex}.part"
        n = len(first)
        with open(tmp, "wb") as fh:
            fh.write(first)
            for chunk in it:
                fh.write(chunk)
                n += len(chunk)
                if n > MAX_SI_BYTES:
                    break
        if n > MAX_SI_BYTES or n < 200:
            tmp.unlink(missing_ok=True)
            return None
        e = ext_of(r.url, ctype)
        if e == "pdf" and first[:4] != b"%PDF":
            tmp.unlink(missing_ok=True)
            return None
        return tmp, n, e, r.url
    except Exception:
        return None
    finally:
        r.close()


def affinity_ok(paper_title, rec_title, rec_desc=""):
    stop = {"data", "supporting", "supplementary", "information", "with", "from", "that", "this", "their", "using",
            "based", "study", "towards", "toward", "into", "through"}
    a = {w for w in norm_title(paper_title).split() if len(w) >= 4 and w not in stop}
    b = {w for w in norm_title((rec_title or "") + " " + (rec_desc or "")[:500]).split() if len(w) >= 4 and w not in stop}
    return len(a & b) >= max(1, min(3, len(a) // 3))


# ---------------------------------------------------------------- routes
def route_pmc(pmc):
    out = []
    for k in (pmc or {}).get("files") or []:
        name = k.split("/")[-1]
        if name.startswith(pmc["folder"]) and name.split(".")[-1] in ("pdf", "xml", "txt", "json"):
            continue  # the article itself
        if IMG.search(name) or re.search(r"-(g|e|i|f|fig|tab|t)\d+[a-z]?\.(jpg|gif|png|tif)$", name, re.I):
            continue
        out.append(("pmc_aws", f"https://pmc-oa-opendata.s3.amazonaws.com/{k}"))
    return out


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


def route_acs_figshare(doi):
    try:
        items = http_get("https://api.figshare.com/v2/articles/search", method="POST",
                         json_body={"resource_doi": doi, "page_size": 50}, tries=4).json() or []
    except HTTPFail:
        return []
    out = []
    for it in items:
        if not (it.get("doi") or "").lower().startswith(doi.lower() + ".s"):
            continue
        try:
            files = get_json(f"https://api.figshare.com/v2/articles/{it['id']}/files", tries=4)
        except HTTPFail:
            continue
        out += [("acs_figshare", f["download_url"]) for f in files or [] if f.get("download_url")]
    return out


def route_known(links):
    """SI deposits linked to the paper at index time (si_links): their files, straight from Figshare or Zenodo."""
    out = []
    for l in links:
        d = (l.get("si_doi") or "").lower()
        try:
            if d.startswith(("10.6084/", "10.25384/")):
                for it in http_get("https://api.figshare.com/v2/articles/search", method="POST",
                                   json_body={"doi": l["si_doi"], "page_size": 3}, tries=3).json() or []:
                    if (it.get("doi") or "").lower() == d:
                        files = get_json(f"https://api.figshare.com/v2/articles/{it['id']}/files", tries=3)
                        out += [("known_deposit", f["download_url"]) for f in files or [] if f.get("download_url")]
            elif d.startswith("10.5281/zenodo."):
                rec = get_json(f"https://zenodo.org/api/records/{d.rsplit('.', 1)[-1]}", tries=3)
                out += [("known_deposit", f["links"]["self"]) for f in rec.get("files") or []
                        if (f.get("links") or {}).get("self")]
        except Exception:
            continue
    return out


def _head_ok(url):
    try:
        PACER.wait(host_of(url))
        rr = session().head(url, timeout=(10, 30), allow_redirects=True)
        return rr.status_code == 200 and "text/html" not in rr.headers.get("content-type", "")
    except Exception:
        return False


def route_elsevier(cr):
    pii = None
    for a in (cr or {}).get("alternative_id") or []:
        x = a.replace("-", "").replace("(", "").replace(")", "").upper()
        if re.match(r"^S[0-9X]{16}$", x):
            pii = x
            break
    if not pii:
        return []
    out = []
    for n in range(1, 8):
        hit = next((u for e in ("pdf", "docx", "doc", "xlsx", "zip", "mp4", "xls", "txt")
                    for u in [f"https://ars.els-cdn.com/content/image/1-s2.0-{pii}-mmc{n}.{e}"] if _head_ok(u)), None)
        if not hit:
            break
        out.append(("elsevier_cdn", hit))
    return out


def route_mdpi(proj, p, cr):
    try:
        first, last = C.extract_text(proj.root / p["_path"], first=2, last=6)
    except Exception:
        first, last = "", ""
    if not re.search(r"supplementary material", first + " " + last, re.I):
        return []
    base = p.get("download_url") if "mdpi-res.com" in (p.get("download_url") or "") else (MDPI.pdf_urls(p["doi"], cr, p.get("journal")) or [None])[0]
    pre = MDPI.si_base(base) if base else None
    if not pre:
        return []
    out = []
    exts = ["zip", "pdf", "docx", "xlsx", "doc", "xls", "mp4", "csv", "txt", "cif", "avi", "mov"]
    for n in range(1, 10):
        hit = next((u for e in (exts if n == 1 else exts[:7]) for u in [f"{pre}{n:03d}.{e}"] if _head_ok(u)), None)
        if not hit:
            break
        out.append(("mdpi_cdn", hit))
    return out


def route_repos(p, cr):
    doi, title = p["doi"], p.get("title") or ""
    out = []
    for x in ((cr or {}).get("relation") or {}).get("has-supplementary-material") or []:
        if x.get("id-type") == "doi":
            out.append(("crossref_relation", f"https://doi.org/{x.get('id')}"))
        elif x.get("id-type") == "uri":
            out.append(("crossref_relation", x.get("id")))
    try:
        d = get_json("https://zenodo.org/api/records", params={"q": f'related.identifier:"{doi}"', "size": 10}, tries=3)
        for h in (d.get("hits") or {}).get("hits") or []:
            md = h.get("metadata") or {}
            if affinity_ok(title, md.get("title"), md.get("description")):
                out += [("zenodo", f["links"]["self"]) for f in h.get("files") or [] if (f.get("links") or {}).get("self")]
    except Exception:
        pass
    if not doi.startswith("10.1021/"):
        try:
            for it in http_get("https://api.figshare.com/v2/articles/search", method="POST",
                               json_body={"resource_doi": doi, "page_size": 20}, tries=3).json() or []:
                if affinity_ok(title, it.get("title")):
                    files = get_json(f"https://api.figshare.com/v2/articles/{it['id']}/files", tries=3)
                    out += [("figshare", f["download_url"]) for f in files or [] if f.get("download_url")]
        except Exception:
            pass
    try:
        d = get_json("https://datadryad.org/api/v2/search", params={"q": doi, "per_page": 5}, tries=2)
        for ds in ((d.get("_embedded") or {}).get("stash:datasets") or []):
            if doi.lower() in json.dumps(ds.get("relatedWorks") or []).lower() and affinity_ok(title, ds.get("title"), ds.get("abstract")):
                did = urllib.parse.quote(ds.get("identifier", ""), safe="")
                out.append(("dryad", f"https://datadryad.org/api/v2/datasets/{did}/download"))
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- driver
def process(proj, led, p, pmc_by, cr_by, ez_ready):
    doi = p.get("doi") or ""
    cands, tried = [], []
    pmcid = (p.get("external_ids") or {}).get("pmcid")
    if pmcid:
        pmcid = "PMC" + str(pmcid).rsplit("/", 1)[-1].upper().replace("PMC", "")
    pmc = pmc_by.get(pmcid) if pmcid else None
    if pmc:
        tried.append("pmc_aws")
        cands += route_pmc(pmc)
    if not cands:
        known = led.si_links_of(p["id"])
        if known:
            tried.append("known_deposits")
            cands += route_known(known)
    if doi and not cands:
        tried.append("landing")
        cands += route_landing(proj, doi)
    if doi.startswith("10.1021/") and not cands:
        tried.append("acs_figshare")
        cands += route_acs_figshare(doi)
    if doi.startswith("10.3390/") and not cands:
        tried.append("mdpi_cdn")
        cands += route_mdpi(proj, p, cr_by.get(doi))
    if doi.startswith(("10.1016/", "10.1006/")) and not cands:
        tried.append("elsevier_cdn")
        cands += route_elsevier(cr_by.get(doi))
    if doi and not cands:
        tried.append("repositories")
        cands += route_repos(p, cr_by.get(doi))
    files, seen_u, seen_sha = [], set(), set()
    for src, u in cands:
        if u in seen_u:
            continue
        seen_u.add(u)
        got = download_file(proj, u)
        if not got:
            attempt(proj, p["id"], doi, kind="si", step=src, url=u[:500], outcome="fail")
            continue
        tmp, n, e, final = got
        digest = C.sha1(tmp)
        if digest in seen_sha:
            tmp.unlink(missing_ok=True)
            continue
        seen_sha.add(digest)
        files.append((tmp, e, src))
    topics = [t for t in led.topics_of(p["id"]) if t.get("path")]
    acc = p.get("access_type") or "Free-to-read"
    names = []
    for i, (tmp, e, src) in enumerate(files, 1):
        names.append(f"{p['id']}_SI.{e}" if len(files) == 1 else f"{p['id']}_SI_{i}.{e}")
    first_paths = {}
    for t in topics:
        d = proj.si_dir(t["topic"], acc)
        d.mkdir(parents=True, exist_ok=True)
        rels = []
        for k, (tmp, e, src) in enumerate(files):
            dst = d / names[k]
            if k not in first_paths:
                Path(tmp).replace(dst)
                first_paths[k] = dst
            else:
                clone_or_copy(first_paths[k], dst)
            rels.append(proj.rel(dst))
        led.set_topic(p["id"], t["topic"], si_paths=rels)
    if files:
        led.set(p["id"], si_status="found", si_files=names)
        return "found"
    if ez_ready and ez_publisher(doi) and not doi.startswith("10.1021/"):
        led.set(p["id"], si_status="queued_paywalled")
        return "queued_paywalled"
    led.set(p["id"], si_status="not_found")
    return "not_found"


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--retry", action="store_true", help="also retry papers whose SI was not found before")
    a = ap.parse_args()
    proj = Project(a.project)
    load_config(proj, a.topic)
    load_blocked(proj)
    led = Ledger(proj)
    cond = "AND p.downloaded = 1 AND t.path IS NOT NULL AND " + \
           ("(p.si_status IS NULL OR p.si_status IN ('not_found','queued_paywalled'))" if a.retry else "p.si_status IS NULL")
    papers = led.topic_rows(a.topic, cond)
    for p in papers:
        p["_path"] = p["t_path"]
    from _cache import Cache

    class _Found:          # the PMC mirror answers for papers it actually holds
        def __init__(self, c):
            self.c = c

        def get(self, k):
            r = self.c.get(k)
            return r if r and r.get("found") else None
    pmc_by, cr_by = _Found(Cache(proj, "pmcaws", key="pmcid")), Cache(proj, "crossref")
    ez = json_read(proj.ezg / "config.json", {}) or {}
    ez_ready = bool(ez.get("enabled") and ez.get("verified_at"))
    log(f"SI: {len(papers)} papers to process")
    cnt, lock = Counter(), threading.Lock()

    def one(p):
        try:
            s = process(proj, led, p, pmc_by, cr_by, ez_ready)
        except Exception as e:
            s = "error"
            log(f"SI error for ID {p['id']}: {e!r}"[:300])
        with lock:
            cnt[s] += 1
            if sum(cnt.values()) % 100 == 0:
                log(f"SI: {sum(cnt.values())}/{len(papers)} {dict(cnt)}")

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, papers))
    led.export()
    res = {"papers": len(papers), "outcomes": dict(cnt), "finished_at": now_iso()}
    update_state(proj, a.topic, lambda st: st.setdefault("fetch_si", {}).update(res))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
