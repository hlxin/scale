"""Download step — download in-scope sources through OPEN routes (no institutional access needed).

Selects sources of the topic that are in scope (or unscreened), not yet downloaded, and whose Access type is one of
config['download']['access_types']. Tries every known open copy, most open first (repositories, PMC open-data
mirror, arXiv, publisher CDNs, landing-page citation_pdf_url), never touching hosts that block scripted clients.
Each PDF is validated, checked against the title, and filed by the license printed in it.

Sources it cannot get openly are marked: queued for EZproxy when paywalled access is set up and the publisher is
supported, otherwise left as "No" with the reason in Notes. Paywalled sources are never attempted here. Datasets and
software are indexed only (never downloaded); US patents come from the USPTO image server.

usage:
  python3 -I download_open.py --topic <slug> [--max N] [--workers 10] [--retry-failed] [--added-since YYYY-MM-DD]
Long runs: nohup python3 -I .../download_open.py --topic <slug> > .scripts/<slug>/download_open.log 2>&1 &
"""
import argparse
import json
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _core  # noqa: F401,E402  (index-sources' scripts: the shared core)
import _mdpi as MDPI
from _common import (ACCESS_TYPES, NOT_DOWNLOADED_TYPES, Project, access_rank, add_project_arg, host_of, json_read,
                     load_config, log, now_iso, update_state)
from _download import (NOT_PROXYABLE, arxiv_pdf, attempt, ez_publisher, fetch, file_pdf, is_blocked, link_existing,
                       load_blocked, pdf_links_from_html, publisher_pdf_patterns)
from _corpus import add_corpus_arg, scope
from _ledger import Ledger
from _vectors import after_step


def paywalled_ready(proj):
    ez = json_read(proj.ezg / "config.json", {}) or {}
    return bool(ez.get("enabled") and ez.get("host") and ez.get("verified_at"))


def routes(p, selected):
    """Ordered open URLs for one source: [(entry, url)]."""
    out, seen = [], set()
    doi = p.get("doi")

    def add(entry):
        url = entry.get("url")
        if not url:
            return
        if "arxiv.org" in url:
            url = arxiv_pdf(url)
            entry["url"] = url
        if url in seen or is_blocked(host_of(url)):
            return
        seen.add(url)
        out.append(entry)

    vers = p.get("versions") or []
    wanted = [v for v in vers if v.get("access") in selected] or vers
    for v in sorted(wanted, key=lambda v: access_rank(v.get("access"))):
        base = {"src": v.get("src"), "version": v.get("version"), "license": v.get("license"), "access": v.get("access"),
                "pmc_license": v.get("pmc_license"), "license_raw": v.get("license_raw")}
        if v.get("pdf_url"):
            add({**base, "url": v["pdf_url"], "kind": "pdf"})
    for v in wanted:
        if v.get("url") and v.get("src") != "pmc_aws":
            add({"src": f"{v.get('src')}.landing", "version": v.get("version"), "license": v.get("license"),
                 "access": v.get("access"), "url": v["url"], "kind": "landing", "license_raw": v.get("license_raw")})
    if p.get("doc_type") == "patent":
        for u in patent_pdf_urls(p):
            add({"src": "patent_office", "url": u, "kind": "pdf", "version": "publishedVersion", "license": "other-oa",
                 "access": "Free-to-read"})
        return out
    if doi and p.get("access_type") in selected and p.get("access_type") != "Paywalled":
        lic = p.get("license")
        if doi.startswith("10.3390/"):
            for u in MDPI.pdf_urls(doi, None, p.get("journal")):
                add({"src": "mdpi_cdn", "url": u, "kind": "pdf", "version": "publishedVersion", "license": lic,
                     "access": p.get("access_type")})
        for u in publisher_pdf_patterns(doi):
            add({"src": "publisher_pattern", "url": u, "kind": "pdf", "version": "publishedVersion", "license": lic,
                 "access": p.get("access_type")})
        add({"src": "doi.landing", "url": f"https://doi.org/{doi}", "kind": "landing", "version": "publishedVersion",
             "license": lic, "access": p.get("access_type")})
    return out


def patent_pdf_urls(p):
    """Full-text PDF of a US patent or US application from the USPTO image server (no key). Other offices: none —
    the source keeps its Espacenet / Lens link."""
    import re
    pn = str((p.get("external_ids") or {}).get("patent") or "").upper().replace("-", "")
    m = re.match(r"^US(\d{7,11})([A-Z]\d?)?$", pn)
    if not m:
        return []
    num = m.group(1)
    return [f"https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/{num}"]


def figshare_pdf(url):
    """figshare.com/articles/<type>/<slug>/<id> -> the article's PDF download URL via the public API."""
    import re
    from _common import get_json
    m = re.search(r"figshare\.com/articles/(?:[^/]+/)?(?:[^/]+/)?(\d{5,})", url or "")
    if not m:
        return None
    try:
        files = get_json(f"https://api.figshare.com/v2/articles/{m.group(1)}/files", tries=3)
    except Exception:
        return None
    pdfs = [f.get("download_url") for f in files or [] if (f.get("name") or "").lower().endswith(".pdf")]
    return pdfs[0] if pdfs else None


def try_entry(proj, led, p, e):
    url = e["url"]
    if "figshare.com/articles/" in url:
        url = figshare_pdf(url) or url
        e = {**e, "url": url, "kind": "pdf" if url.startswith("https://ndownloader") or "/files/" in url else e["kind"]}
    accept = "application/pdf,*/*;q=0.8" if e["kind"] == "pdf" else "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8"
    t0 = time.time()
    res = fetch(proj, url, accept=accept)
    if res["kind"] == "redirect_blocked" or (res["kind"] == "html" and is_blocked(host_of(res.get("final_url", "")))):
        attempt(proj, p["id"], p.get("doi"), step=e["src"], url=url, outcome="redirected_to_bot_walled_host")
        return "walled"
    if res["kind"] == "html":
        for l in pdf_links_from_html(res["text"], res["final_url"]):
            if is_blocked(host_of(l)):
                continue
            r2 = fetch(proj, l)
            if r2["kind"] == "pdf":
                out, why = file_pdf(proj, led, p, e, r2["path"], "open", r2.get("final_url"))
                attempt(proj, p["id"], p.get("doi"), step=e["src"] + ".pdflink", url=l, outcome=out, reason=why,
                        secs=round(time.time() - t0, 1))
                if out in ("valid_pdf", "duplicate"):
                    return out
        attempt(proj, p["id"], p.get("doi"), step=e["src"], url=url, outcome="no_pdf_link")
        return "fail"
    if res["kind"] == "pdf":
        out, why = file_pdf(proj, led, p, e, res["path"], "open", res.get("final_url"))
        attempt(proj, p["id"], p.get("doi"), step=e["src"], url=url, outcome=out, reason=why, secs=round(time.time() - t0, 1))
        return out if out in ("valid_pdf", "duplicate") else "fail"
    attempt(proj, p["id"], p.get("doi"), step=e["src"], url=url, outcome=res["kind"], http_status=res.get("status"))
    return "walled" if res["kind"] == "challenge" else "fail"


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    add_corpus_arg(ap, topic_required=True)
    ap.add_argument("--access", default=None, help="comma list of access types to fetch (default: the topic's config, download.access_types)")
    ap.add_argument("--max", type=int, default=None, help="download at most N sources this run (most relevant first)")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--retry-failed", action="store_true", help="also retry sources that failed before")
    ap.add_argument("--added-since", default=None, help="YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ: only sources that entered this "
                                                         "topic at/after that time (update mode: download just the new "
                                                         "sources; build_list.py prints the run's start time)")
    a = ap.parse_args()
    proj = Project(a.project)
    a.topic, ids = scope(a, topic_required=True)
    cfg = load_config(proj, a.topic)
    selected = ({x.strip() for x in a.access.split(",") if x.strip()} if a.access else
                set((cfg.get("download") or {}).get("access_types") or ["OA", "OA+ND", "Free-to-read"]))
    ez_ok = paywalled_ready(proj)                  # EZproxy is a route for walled open copies of any selected type
    pw = ez_ok and "Paywalled" in selected         # ... and the only route for Paywalled sources
    load_blocked(proj)
    led = Ledger(proj)
    linked = link_existing(proj, led, a.topic)
    if linked:
        log(f"{linked} sources were already downloaded for another topic — cloned into this topic's folders")
    cond = "AND p.downloaded = 0 AND p.is_erratum = 0 AND COALESCE(t.in_scope, 1) = 1"
    args = ()
    if a.added_since:
        cond += " AND t.date_added >= ?"
        args = (a.added_since,)
    todo, skipped = [], Counter()
    for rows in led.iter_topic(a.topic, cond, args):      # 20,000 at a time: a topic may hold millions
        with led.tx():
            for p in rows:
                if ids is not None and p["id"] not in ids:
                    continue                                  # not in the corpus
                acc = p.get("access_type")
                if (p.get("doc_type") or "") in NOT_DOWNLOADED_TYPES:
                    skipped["dataset_or_software"] += 1      # indexed only, never downloaded
                    continue
                if acc not in selected:
                    if p.get("dl_status") != "not_selected":
                        led.set(p["id"], dl_status="not_selected", dl_note=f"{acc or 'Unknown access'} — type not selected for download")
                    skipped["not_selected"] += 1
                    continue
                if acc == "Paywalled":
                    pre = (p.get("doi") or "").split("/")[0]
                    if pw and ez_publisher(p.get("doi")):
                        if p.get("dl_status") != "queued_paywalled":
                            led.set(p["id"], dl_status="queued_paywalled", dl_note="Queued for EZproxy download")
                        skipped["queued_paywalled"] += 1
                    elif pw and pre in NOT_PROXYABLE:
                        led.set(p["id"], dl_status="no_route", dl_note=f"Paywalled — {NOT_PROXYABLE[pre]}")
                        skipped["no_route"] += 1
                    else:
                        note = ("Paywalled — publisher not supported through EZproxy" if pw else
                                "Paywalled — institutional access not set up")
                        led.set(p["id"], dl_status="no_route", dl_note=note)
                        skipped["no_route"] += 1
                    continue
                if p.get("dl_status") in ("failed", "duplicate", "queued_paywalled") and not a.retry_failed:
                    skipped[p["dl_status"]] += 1
                    continue
                todo.append((-(p.get("t_relevance") if p.get("t_relevance") is not None else 3), -(p.get("cited_by") or 0),
                             p["t_rowid"], p["id"]))
    todo = [x[-1] for x in sorted(todo)]           # most relevant, then most cited first
    if a.max:
        todo = todo[:a.max]
    log(f"open download: {len(todo)} sources to try; skipped {dict(skipped)}; EZproxy route ready={ez_ok}")
    cnt, lock = Counter(), threading.Lock()

    def one(p):
        status, walled = "no_open_copy", False
        for e in routes(p, selected):
            o = try_entry(proj, led, p, e)
            if o in ("valid_pdf", "duplicate"):
                status = o
                break
            walled |= (o == "walled")
        if status not in ("valid_pdf", "duplicate"):
            if ez_ok and ez_publisher(p.get("doi")):
                led.set(p["id"], dl_status="queued_paywalled", dl_note="Open copy not reachable — queued for EZproxy")
                status = "queued_paywalled"
            else:
                note = ("Open copy only on a site that blocks scripted downloads" if walled else
                        "No downloadable open copy found")
                led.set(p["id"], dl_status="failed", dl_note=note)
                status = "failed"
        with lock:
            cnt[status] += 1
            n = sum(cnt.values())
            if n % 100 == 0:
                log(f"open download: {n}/{len(todo)} {dict(cnt)}")
                led.export_progress(topics=[a.topic])

    def load(ids):
        got = {}
        for i in range(0, len(ids), 900):
            part = ids[i:i + 900]
            got.update((r["id"], r) for r in led.topic_rows(a.topic, f"AND p.id IN ({','.join('?' * len(part))})",
                                                            tuple(part)))
        return [got[i] for i in ids if i in got]

    with ThreadPoolExecutor(a.workers) as ex:
        for i in range(0, len(todo), 2000):            # full rows read 2,000 at a time, in download order
            list(ex.map(one, load(todo[i:i + 2000])))
    led.export()
    res = {"tried": len(todo), "outcomes": dict(cnt), "skipped": dict(skipped), "linked_from_other_topics": linked,
           "vector_store": after_step(proj, led), "finished_at": now_iso()}
    update_state(proj, a.topic, lambda st: st.setdefault("download_open", {}).update(res))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
