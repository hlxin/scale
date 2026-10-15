"""Index step — find every paper's supplementary information (SI) BEFORE anything is downloaded.

Each SI deposit or file found becomes an SI link of its paper (ledger si_links -> papers.db `supplements`, index SI
column "Available (n deposits)"); fetch_si.py later downloads the files listed here first. Nothing is downloaded.

Routes for every paper (batched or read from caches, so a topic of millions of papers takes a few hours):
  1 Crossref components '<DOI>.s001', '.s002' ... (ACS, PLOS ...): existence checked 170 DOIs per request
  2 DataCite deposits that declare IsSupplementTo the paper (publisher SI on Figshare, Zenodo, Dryad, Mendeley Data,
    institutional repositories): 100 DOIs per query
  3 Crossref relations is-supplemented-by / has-supplementary-material (read from classify_access's Crossref answers)
  4 the PubMed Central open-access mirror: the article's supplementary files (from classify_access's PMC answers)
Routes that cost one request (or a few) per paper — on by default for topics up to 50,000 papers, `--deep` forces them,
`--no-deep` skips them; each host keeps the skill's polite pace:
  5 Elsevier SI CDN (mmcN files by PII)     6 MDPI CDN (-s001 files)
  7 publisher pages that serve scripted clients (Nature, Springer, BMC, Frontiers)
SI on walled publisher sites (Wiley, RSC, ACS pages, IOP ...) without a deposit of its own is found by fetch_si.py when
the paper is downloaded. Run after classify_access.py (routes 3-6 use its Crossref and PMC answers). Answers are cached
in .scripts/enrich/si_*.sqlite: a re-run (or an update) only asks for papers not asked before.

usage: python3 -I find_si.py --topic <slug> [--deep | --no-deep] [--ids FILE] [--no-export]
  --ids FILE   only these paper IDs (one per line), e.g. a subset of a catalog that should get the deep routes
"""
import argparse
import json
import re
import sys
import threading
import time
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _mdpi as MDPI
from _cache import Cache
from _common import (PACER, HTTPFail, Project, add_project_arg, get_json, host_of, load_config, log, norm_doi, now_iso,
                     session, update_state)
from _download import load_blocked
from _ledger import Ledger

CHUNK = 20000            # papers per block
CR_BATCH = 170           # DOIs per Crossref filter request
DC_BATCH = 100           # DOIs per DataCite query
DEEP_MAX = 50000         # topics up to this size get the per-paper routes by default
MAX_COMPONENTS = 30      # '.s001' ... at most '.s030'
SKIP_TYPES = ("patent", "dataset", "software")
LANDING_PREFIXES = ("10.1038/", "10.1007/", "10.1557/", "10.1140/", "10.1023/", "10.1186/", "10.3389/")
ELS_EXT_FIRST = ("docx", "pdf", "doc", "xlsx", "zip", "mp4")
ELS_EXT_NEXT = ("docx", "pdf", "xlsx", "zip")
MDPI_EXT = ("pdf", "zip", "docx", "xlsx")
DATA_TYPES = {"dataset", "software", "model", "workflow"}
ARTICLE_TYPES = {"journalarticle", "preprint", "conferencepaper", "book", "bookchapter", "dissertation", "report",
                 "peerreview"}
for _h, _iv in {"ars.els-cdn.com": 0.5, "api.datacite.org": 0.25}.items():
    PACER.set(_h, _iv)


def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def link(parent, si_doi, url, title, source):
    return {"parent_doi": parent, "si_doi": si_doi, "url": url, "title": (title or "")[:300], "source": source}


# ---------------------------------------------------------------- 1 Crossref components (.s001 ...)
def crossref_components(dois, cache):
    """Ask Crossref which '<doi>.sNNN' exist, NNN = 1, 2 ... until a paper has no next one. Caches per paper DOI:
    {"doi", "components": [[si_doi, title], ...]}."""
    todo = [d for d in cache.missing(dois) if "," not in d]
    if not todo:
        return
    found = {d: [] for d in todo}
    level, current = 1, list(todo)
    while current and level <= MAX_COMPONENTS:
        hits = set()

        def ask(part):
            cand = {f"{d}.s{level:03d}": d for d in part}
            params = {"filter": ",".join("doi:" + c for c in cand), "rows": len(cand), "select": "DOI,title,type"}
            try:
                items = get_json("https://api.crossref.org/works", params=params, tries=5, timeout=(20, 120))["message"]["items"]
            except HTTPFail as e:
                if str(getattr(e, "status", "")) in ("400", "414", "431") and len(part) > 1:   # a DOI Crossref cannot parse, or a request line too long
                    halves = [ask(part[:len(part) // 2]), ask(part[len(part) // 2:])]
                    return None if None in halves else halves[0] + halves[1]
                if str(getattr(e, "status", "")) in ("400", "414", "431"):
                    return []
                log(f"find_si: crossref components batch failed ({e}); retried on the next run")
                return None
            except (KeyError, ValueError) as e:
                log(f"find_si: crossref components batch failed ({e}); retried on the next run")
                return None
            out = []
            for it in items:
                sd = norm_doi(it.get("DOI"))
                if sd in cand:
                    out.append((cand[sd], sd, (it.get("title") or [""])[0] if it.get("title") else ""))
            return out

        with ThreadPoolExecutor(3) as ex:
            results = list(ex.map(ask, list(chunks(current, CR_BATCH))))
        if any(r is None for r in results):    # incomplete answers are not cached: the next run asks again
            failed = {d for part, r in zip(chunks(current, CR_BATCH), results) if r is None for d in part}
            for d in failed:
                found.pop(d, None)
        for r in results or []:
            for parent, sd, title in r or []:
                if parent in found:
                    found[parent].append([sd, title])
                    hits.add(parent)
        current, level = [d for d in current if d in hits], level + 1
    cache.add([{"doi": d, "components": v} for d, v in found.items()])


# ---------------------------------------------------------------- 2 DataCite IsSupplementTo
def datacite_deposits(dois, cache):
    """DataCite records whose relatedIdentifiers say IsSupplementTo one of `dois` (checked pair by pair: the query
    matches the two fields separately). Caches per paper DOI: {"doi", "deposits": [[doi, url, title, type], ...]}."""
    todo = [d for d in cache.missing(dois) if '"' not in d and "\\" not in d]
    if not todo:
        return

    def ask(part):
        want = {d.lower(): d for d in part}
        q = ("relatedIdentifiers.relationType:IsSupplementTo AND relatedIdentifiers.relatedIdentifier:("
             + " OR ".join(f'"{d}"' for d in part) + ")")
        got, url = {d: [] for d in part}, "https://api.datacite.org/dois"
        params = {"query": q, "page[size]": 1000, "page[cursor]": 1,
                  "fields[dois]": "doi,url,titles,types,relatedIdentifiers"}
        try:
            while url:
                d = get_json(url, params=params, tries=5, timeout=(20, 120))
                for it in d.get("data") or []:
                    a = it.get("attributes") or {}
                    rtype = re.sub(r"[^a-z]", "", str((a.get("types") or {}).get("resourceTypeGeneral") or "").lower())
                    if rtype in ARTICLE_TYPES:
                        continue
                    for r in a.get("relatedIdentifiers") or []:
                        target = norm_doi(r.get("relatedIdentifier") or "") or ""
                        if r.get("relationType") == "IsSupplementTo" and target.lower() in want:
                            title = ((a.get("titles") or [{}])[0] or {}).get("title") or ""
                            got[want[target.lower()]].append([a.get("doi"), a.get("url") or f"https://doi.org/{a.get('doi')}",
                                                              title, rtype])
                url, params = (d.get("links") or {}).get("next"), None
        except HTTPFail as e:
            if str(getattr(e, "status", "")) in ("400", "414", "431") and len(part) > 1:
                return ask(part[:len(part) // 2]) + ask(part[len(part) // 2:])
            if str(getattr(e, "status", "")) in ("400", "414", "431"):
                return [{"doi": part[0], "deposits": []}]
            log(f"find_si: datacite batch failed ({e}); retried on the next run")
            return []
        except ValueError as e:
            log(f"find_si: datacite batch failed ({e}); retried on the next run")
            return []
        return [{"doi": k, "deposits": v} for k, v in got.items()]

    with ThreadPoolExecutor(4) as ex:
        for recs in ex.map(ask, list(chunks(todo, DC_BATCH))):
            cache.add(recs)


# ---------------------------------------------------------------- 4 PMC open-access mirror (cached file lists)
PMC_FIG = re.compile(r"[-_.](g|e|i|f|fig|figure|tab|t)\d+[a-z]?\.(jpe?g|gif|png|tiff?|eps)$|[-_.](f|fig|figure|g)\d+[a-z]?\.pdf$", re.I)
PMC_IMG = re.compile(r"\.(jpe?g|png|gif|svg|webp|tiff?)$", re.I)


def pmc_files(pmc):
    out = []
    for k in (pmc or {}).get("files") or []:
        name = k.split("/")[-1]
        if name.startswith(pmc.get("folder") or "\0") and name.split(".")[-1] in ("pdf", "xml", "txt", "json"):
            continue                                   # the article itself
        if PMC_IMG.search(name) or PMC_FIG.search(name):
            continue                                   # figures
        out.append((name, f"https://pmc-oa-opendata.s3.amazonaws.com/{k}"))
    return out


# ---------------------------------------------------------------- 5-7 per-paper routes
def head_ok(url):
    try:
        PACER.wait(host_of(url))
        r = session().head(url, timeout=(10, 30), allow_redirects=True)
        return r.status_code == 200 and "text/html" not in r.headers.get("content-type", "")
    except Exception:
        return False


def elsevier_files(cr):
    pii = None
    for a in (cr or {}).get("alternative_id") or []:
        x = a.replace("-", "").replace("(", "").replace(")", "").upper()
        if re.match(r"^S[0-9X]{16}$", x):
            pii = x
            break
    if not pii:
        return []
    out = []
    for n in range(1, 13):
        exts = ELS_EXT_FIRST if n == 1 else ELS_EXT_NEXT
        hit = next((u for e in exts for u in [f"https://ars.els-cdn.com/content/image/1-s2.0-{pii}-mmc{n}.{e}"]
                    if head_ok(u)), None)
        if not hit:
            break
        out.append(hit)
    return out


def mdpi_files(doi, cr, journal):
    base = (MDPI.pdf_urls(doi, cr, journal) or [None])[0]
    pre = MDPI.si_base(base) if base else None
    if not pre:
        return []
    out = []
    for n in range(1, 10):
        hit = next((u for e in MDPI_EXT for u in [f"{pre}{n:03d}.{e}"] if head_ok(u)), None)
        if not hit:
            break
        out.append(hit)
    return out


def landing_files(proj, doi):
    import fetch_si as FS                       # its landing-page reader (pages of hosts that serve scripted clients)
    return [u for _, u in FS.route_landing(proj, doi)]


def deep_one(proj, p, cr):
    doi, routes, files = p["doi"], [], []
    try:
        if doi.startswith(("10.1016/", "10.1006/")):
            routes.append("elsevier_cdn")
            files += [("elsevier_cdn", u) for u in elsevier_files(cr)]
        elif doi.startswith("10.3390/"):
            routes.append("mdpi_cdn")
            files += [("mdpi_cdn", u) for u in mdpi_files(doi, cr, p.get("journal"))]
        elif doi.startswith(LANDING_PREFIXES):
            routes.append("landing")
            files += [("landing", u) for u in landing_files(proj, doi)]
    except Exception as e:                      # one paper's failure never stops the run; not cached, so retried
        log(f"find_si: deep routes failed for {doi}: {e!r}"[:200])
        return None
    return {"doi": doi, "routes": routes, "files": [[s, u] for s, u in files]}


def deep_eligible(doi):
    return bool(doi) and doi.startswith(("10.1016/", "10.1006/", "10.3390/") + LANDING_PREFIXES)


# ---------------------------------------------------------------- driver
def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--deep", action="store_true", help="per-paper routes for any topic size")
    g.add_argument("--no-deep", action="store_true", help="only the batched and cached routes")
    ap.add_argument("--ids", help="file with paper IDs (one per line): only these papers")
    ap.add_argument("--no-export", action="store_true", help="do not refresh the index CSVs and papers.db at the end")
    a = ap.parse_args()
    proj = Project(a.project)
    load_config(proj, a.topic)
    load_blocked(proj)
    led = Ledger(proj)
    only = None
    if a.ids:
        only = {int(x) for x in Path(a.ids).read_text().split() if x.strip().isdigit()}
    cond = ("AND p.is_erratum = 0 AND COALESCE(p.retracted, 0) = 0 AND COALESCE(t.in_scope, 1) = 1 "
            f"AND COALESCE(p.doc_type, '') NOT IN ({','.join('?' * len(SKIP_TYPES))})")
    total = len(only) if only is not None else led.q(
        "SELECT COUNT(*) FROM papers p JOIN paper_topics t ON t.paper_id = p.id WHERE t.topic=? " + cond,
        (a.topic, *SKIP_TYPES))[0][0]
    deep = a.deep or (not a.no_deep and total <= DEEP_MAX)
    comp, dc = Cache(proj, "si_crossref_components"), Cache(proj, "si_datacite")
    deep_c, cr_c, pmc_c = Cache(proj, "si_deep"), Cache(proj, "crossref"), Cache(proj, "pmcaws", key="pmcid")
    log(f"find_si: {total:,} papers; routes: crossref components, datacite, crossref relations, pmc mirror"
        + (", elsevier cdn, mdpi cdn, publisher pages" if deep else " (per-paper routes off: --deep to add them)"))
    cnt, by_route, papers_with = Counter(), Counter(), 0
    t0, done, k = time.time(), 0, 0
    nblocks = max(1, -(-led.q("SELECT COUNT(*) FROM paper_topics WHERE topic=?", (a.topic,))[0][0] // CHUNK))
    for rows in led.iter_topic(a.topic, cond, SKIP_TYPES, CHUNK):
        k += 1
        if only is not None:
            rows = [r for r in rows if r["id"] in only]
        if not rows:
            continue
        dois = [r["doi"] for r in rows if r.get("doi")]
        jobs = [threading.Thread(target=crossref_components, args=(dois, comp)),
                threading.Thread(target=datacite_deposits, args=(dois, dc))]
        deep_todo = [r for r in rows if deep and deep_eligible(r.get("doi"))]
        if deep_todo:
            need = set(deep_c.missing([x["doi"] for x in deep_todo]))
            deep_todo = [r for r in deep_todo if r["doi"] in need]
        crs = cr_c.get_many(dois, drop=("$.abstract",))

        def run_deep():
            groups = {}
            for r in deep_todo:
                d = r["doi"]
                key = ("elsevier" if d.startswith(("10.1016/", "10.1006/")) else "mdpi" if d.startswith("10.3390/")
                       else "nature" if d.startswith("10.1038/") else "bmc" if d.startswith("10.1186/")
                       else "frontiers" if d.startswith("10.3389/") else "springer")
                groups.setdefault(key, []).append(r)

            def run_group(rs):
                buf = []
                for r in rs:
                    rec = deep_one(proj, r, crs.get(r["doi"]))
                    if rec:
                        buf.append(rec)
                    if len(buf) >= 50:
                        deep_c.add(buf)
                        buf = []
                deep_c.add(buf)
            with ThreadPoolExecutor(max(1, len(groups))) as ex:
                list(ex.map(run_group, groups.values()))
        if deep_todo:
            jobs.append(threading.Thread(target=run_deep))
        for j in jobs:
            j.start()
        for j in jobs:
            j.join()
        C, D, X = comp.get_many(dois), dc.get_many(dois), deep_c.get_many([r["doi"] for r in rows if r.get("doi")])
        pmcids = {}
        for r in rows:
            p = (r.get("external_ids") or {}).get("pmcid")
            if p:
                pmcids[r["id"]] = "PMC" + str(p).rsplit("/", 1)[-1].upper().replace("PMC", "")
        P = pmc_c.get_many(list(pmcids.values()))
        links = []
        for r in rows:
            d, mine = r.get("doi"), []
            parent = d
            if not parent:
                continue
            for sd, title in (C.get(d) or {}).get("components") or []:
                mine.append(link(parent, sd, f"https://doi.org/{sd}", title, "crossref_component"))
            for sd, url, title, rtype in (D.get(d) or {}).get("deposits") or []:
                mine.append(link(parent, sd, url, title, "datacite" if rtype not in DATA_TYPES else "datacite_data"))
            for rel in ("is-supplemented-by", "has-supplementary-material"):
                for x in ((crs.get(d) or {}).get("relation") or {}).get(rel) or []:
                    sid = x.get("id")
                    if sid:
                        sid = norm_doi(sid) if x.get("id-type") == "doi" else sid
                        mine.append(link(parent, sid, f"https://doi.org/{sid}" if x.get("id-type") == "doi" else sid,
                                         None, "crossref_relation"))
            pm = P.get(pmcids.get(r["id"]))
            if pm and pm.get("found"):
                for name, url in pmc_files(pm):
                    mine.append(link(parent, url, url, name, "pmc_oa"))
            for src, url in (X.get(d) or {}).get("files") or []:
                mine.append(link(parent, url, url, urllib.parse.unquote(url.rsplit("/", 1)[-1]), src))
            seen, names, kept = set(), set(), []
            for m in mine:                     # one link per deposit; a file listed by two routes counts once
                sid = m["si_doi"]
                if not sid or sid == parent or sid in seen:
                    continue
                if sid.startswith("http"):
                    base = urllib.parse.unquote(sid.split("?")[0].rsplit("/", 1)[-1]).lower()
                    if base in names:
                        continue
                    names.add(base)
                seen.add(sid)
                kept.append(m)
            mine = kept
            if mine:
                papers_with += 1
                for m in mine:
                    by_route[m["source"]] += 1
            links += mine
        with led.tx():
            cnt["links_added"] += led.add_si_links(links)
        done += len(rows)
        el = time.time() - t0
        log(f"find_si: block {k}/{nblocks} — {done:,}/{total:,} papers, {papers_with:,} with SI so far "
            f"({el / 60:.1f} min, ~{el / max(done, 1) * max(total - done, 0) / 60:.0f} min left)")
        update_state(proj, a.topic, lambda st: st.__setitem__("find_si_progress", {
            "papers_done": done, "papers_total": total, "minutes": round(el / 60, 1), "updated_at": now_iso()}))
    n_csv = None if a.no_export else led.export(topics=[a.topic])
    res = {"papers": done, "papers_with_si": papers_with, "si_links_found": sum(by_route.values()),
           "si_links_added": cnt["links_added"], "by_route": dict(by_route), "deep_routes": deep,
           "index_rows": n_csv, "complete": True, "finished_at": now_iso()}
    if a.no_export:
        res["next"] = f"export.py --topic {a.topic} (index CSVs and papers.db were not refreshed)"
    update_state(proj, a.topic, lambda st: st.__setitem__("find_si", res))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
