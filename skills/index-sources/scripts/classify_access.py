"""Step 4 — decide each paper's Access type (OA / OA+ND / Free-to-read / Paywalled) and list its known copies.

Any topic size, as fast as the services allow: papers are taken 20,000 at a time (a block — the topic is never loaded
whole) and four blocks are looked up at once, every service at the pace it allows: OpenAlex 30 requests/s with a key
(100 DOIs each), Crossref 3 requests at a time (~200 DOIs each), Europe PMC and Semantic Scholar 500 DOIs per request.
Each block is decided and saved as soon as its answers are in, so an interrupted run loses nothing and a re-run goes
on where it stopped.

Sources: Crossref (publisher-deposited licenses with their version), OpenAlex (every copy with its license and
version; goes on while the free daily budget or prepaid credit lasts, minus a small reserve), Unpaywall (only DOIs
OpenAlex does not know and Crossref does — Unpaywall knows only Crossref DOIs; one call per DOI, at most 90,000 per
UTC day on this machine, because Unpaywall asks API users to stay under 100,000), Europe PMC, the PMC open-data mirror,
DataCite (arXiv licenses) and Semantic Scholar. Answers are cached in .scripts/enrich/<api>.sqlite (shared by all
topics). A paper whose OpenAlex / Unpaywall answer is still pending keeps an empty access type and is decided when the
script is re-run (after 00:00 UTC when a daily budget stopped it). Access type = the most open copy found anywhere:
  OA            a copy under CC BY / BY-SA / BY-NC / BY-NC-SA / CC0 / public domain
  OA+ND         best copy is CC BY-ND / BY-NC-ND
  Free-to-read  an open copy exists but carries no reuse license (bronze, publisher terms, unlicensed manuscript)
  Paywalled     no open copy anywhere
This is the metadata verdict. download_open.py / download_paywalled.py re-check the license printed in the PDF
and may move a paper to another folder (the PDF wins). The exact license (with version, e.g. CC BY-NC 4.0), its URL
and where it came from are stored too. Abstracts and keywords missing from the search records are filled from
Semantic Scholar / Europe PMC / OpenAlex / Crossref when they have them. Patents are Free-to-read public documents;
datasets and DOI-less records are judged from the license their repository states.

usage:
  python3 -I classify_access.py --topic <slug>                       # papers without an access type
  python3 -I classify_access.py --topic <slug> --recheck-older-than 30   # update mode: re-query papers checked > 30
                                                                     # days ago (embargoes end, OA copies appear,
                                                                     # retractions, preprints get published)
  python3 -I classify_access.py --topic <slug> --abstracts-only     # only fill missing abstracts / keywords
                                                                     # (OpenAlex, Semantic Scholar, Europe PMC,
                                                                     # Crossref); no access decision, no Unpaywall
  options: --refresh (re-decide every paper from cached answers),
           --skip s2,openalex,unpaywall,europepmc,pmcaws,datacite,
           --no-export (leave the index CSVs and papers.db for one export.py at the end of a chain of steps — on a
           topic of millions each export takes minutes)
"""
import argparse
import datetime as _dt
import json
import re
import sys
import threading
import time
import urllib.parse
from array import array
from bisect import bisect_right
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (ACCESS_TYPES, PACER, HTTPFail, ND_LICENSES, OPEN_LICENSES, SOURCE_LABEL, Project, access_rank,
                     add_project_arg, clean_text, file_lock, get_json, host_of, http_get, license_access,
                     license_detail, load_config, load_keys, log, norm_doi, norm_license, normalize_abstract, now_iso,
                     polite_email, retraction_of, today, update_state)
from _cache import Cache
from _ledger import Ledger
from build_list import is_preprint_doi, is_repository_doi
from _sources import OALEX_SELECT, openalex_budget_ok, openalex_record
from _topics import Vocab, apply_vocab

VERSION_RANK = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2, None: 3}
# Unpaywall asks API users to stay under 100,000 calls per day. 90,000 leaves room for anything else that uses the
# same polite email; the count is shared by every project and process on this machine and resets at 00:00 UTC.
UNPAYWALL_DAILY_CAP = 90_000
UNPAYWALL_USAGE = Path.home() / ".paper-acquisition" / "unpaywall_usage.json"
OPENALEX_OR_MAX = 100   # OpenAlex OR-filters take up to 100 values; per_page 100 returns them all in one page
OPENALEX_THREADS = 8    # OpenAlex allows 30 requests/s with a key (10 without): see set_paces()
CROSSREF_URL_MAX = 6500  # Crossref answers 414 above ~8,000 URL characters (percent-encoded): ~170 DOIs per lookup
CROSSREF_SLOTS = threading.BoundedSemaphore(3)   # Crossref polite pool: 3 list requests at a time (x-concurrency-limit)
EPMC_BATCH = 500        # DOIs per Europe PMC search (POST, ~2 s)
EPMC_SLOTS = threading.BoundedSemaphore(3)
S2_BATCH = 500          # the Semantic Scholar batch endpoint's maximum
S2_KEYLESS_MAX = 20000  # without a key Semantic Scholar shares one small pool with everyone (mostly HTTP 429): only
                        # topics up to this size wait for it; a larger one is classified without it (--abstracts-only
                        # can add its abstracts later; a free `s2:` key in keys.txt makes it part of every run)
CHUNK = 20000           # papers per block: looked up together, decided and saved in one transaction
IN_FLIGHT = 4           # blocks looked up at the same time (every service keeps its own pace and limits)
SLICE = 5000            # papers whose API answers are held in memory at once while a block is decided
VERBOSE = True          # one line per service lookup; a topic of several blocks logs one line per block instead
S2_STOPPED = threading.Event()        # Semantic Scholar failed for good: the rest of the run goes without it
UP_CAP_LOGGED = threading.Event()


def vlog(msg):
    if VERBOSE:
        log(msg)


def set_paces(keys):
    """Run each service as fast as it allows: OpenAlex 30 req/s with a key (10 without), Crossref 3 list req/s,
    Semantic Scholar 1 req/s with a key (shared pool without), DataCite 10 req/s, the PMC mirror on S3."""
    PACER.set("api.openalex.org", 0.04 if keys.get("openalex") else 0.11)
    PACER.set("api.crossref.org", 0.34)
    PACER.set("api.unpaywall.org", 0.05)
    PACER.set("api.semanticscholar.org", 1.05 if keys.get("s2") else 3.0)
    PACER.set("api.datacite.org", 0.12)
    PACER.set("pmc-oa-opendata.s3.amazonaws.com", 0.01)


def run_parallel(jobs):
    """{name: (fn, *args)} -> {name: result}: different services looked up at the same time."""
    if not jobs:
        return {}
    with ThreadPoolExecutor(len(jobs)) as ex:
        futs = {name: ex.submit(job[0], *job[1:]) for name, job in jobs.items()}
        return {name: f.result() for name, f in futs.items()}


def norm_pmcid(p):
    return "PMC" + str(p).rsplit("/", 1)[-1].upper().replace("PMC", "")


class DailyCap:
    """Machine-wide count of calls to one API per UTC day (file-locked, shared by every project and process)."""

    def __init__(self, path, limit):
        self.path, self.limit = Path(path), limit

    @staticmethod
    def _today():
        return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

    def _read(self):
        try:
            st = json.loads(self.path.read_text())
        except (OSError, ValueError):
            st = {}
        return st if st.get("date") == self._today() else {"date": self._today(), "calls": 0}

    def take(self):
        """Count one call; False once today's limit is reached."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.path):
            st = self._read()
            if st["calls"] >= self.limit:
                return False
            st["calls"] += 1
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(st))
            tmp.replace(self.path)
            return True

    def used(self):
        return self._read()["calls"]


class Hints:
    """The search records' hints per paper (candidates.jsonl: copies, licenses, preprint DOIs ...), read by byte offset —
    the file reaches gigabytes on a large topic and is never loaded whole."""
    ID_RX = re.compile(rb'\{"paper_id": (\d+)')

    def __init__(self, path):
        self.path, self.lock, self.fh = Path(path), threading.Lock(), None
        ids, offs, ordered, pos = array("q"), array("q"), True, 0
        if self.path.exists():
            with open(self.path, "rb") as fh:
                for line in fh:
                    m = self.ID_RX.match(line)
                    pid = int(m.group(1)) if m else self._pid(line)
                    if pid is not None:
                        ordered = ordered and (not ids or pid > ids[-1])
                        ids.append(pid)
                        offs.append(pos)
                    pos += len(line)
        if not ordered:       # stable sort: of two lines of one paper the later one is found (it wins, as before)
            order = sorted(range(len(ids)), key=ids.__getitem__)
            ids, offs = array("q", (ids[i] for i in order)), array("q", (offs[i] for i in order))
        self.ids, self.offs = ids, offs
        if len(ids):
            self.fh = open(self.path, "rb")

    @staticmethod
    def _pid(line):
        try:
            return int(json.loads(line).get("paper_id"))
        except (ValueError, TypeError, AttributeError):
            return None

    def get_many(self, pids):
        want = []
        for pid in pids:
            i = bisect_right(self.ids, pid) - 1
            if i >= 0 and self.ids[i] == pid:
                want.append((self.offs[i], pid))
        out = {}
        with self.lock:
            for off, pid in sorted(want):
                self.fh.seek(off)
                try:
                    out[pid] = json.loads(self.fh.readline())
                except ValueError:
                    continue
        return out


def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


# ---------------------------------------------------------------- lookups (each caches its answers)
def do_unpaywall(cache, dois, cap):
    """One GET per DOI (Unpaywall has no batch endpoint), paced by PACER, stopped at the machine-wide daily cap.
    Returns the DOIs still without an answer, or None when Unpaywall cannot be used at all (no polite email)."""
    if not polite_email():
        log("unpaywall: skipped (needs polite_email in config)")
        return None
    miss = set(cache.missing(dois))
    todo = [d for d in dict.fromkeys(dois) if d in miss]       # the caller's order: the most useful DOIs first
    if todo:
        vlog(f"unpaywall: {len(todo)} DOIs to look up (daily cap {cap.limit:,}; {cap.used():,} used today)")
    lock, buf, capped = threading.Lock(), [], threading.Event()

    def one(doi):
        if capped.is_set() or not cap.take():
            capped.set()
            return
        url = "https://api.unpaywall.org/v2/" + urllib.parse.quote(doi, safe="/()<>;:@")
        try:
            d = get_json(url, params={"email": polite_email()}, tries=4, timeout=(15, 60))
            rec = {"doi": doi, "found": True, "is_oa": d.get("is_oa"), "oa_status": d.get("oa_status"),
                   "genre": d.get("genre"), "publisher": d.get("publisher"), "journal_name": d.get("journal_name"),
                   "oa_locations": [{k: l.get(k) for k in ("url", "url_for_pdf", "url_for_landing_page", "license",
                                                             "version", "host_type", "is_best")}
                                    for l in (d.get("oa_locations") or [])]}
        except HTTPFail as e:
            if str(e.status) not in ("404", "422"):
                return  # transient: retried on the next run
            rec = {"doi": doi, "found": False}
        except ValueError:
            return
        with lock:
            buf.append(rec)
            if len(buf) >= 200:
                cache.add(list(buf))
                buf.clear()

    with ThreadPoolExecutor(10) as ex:
        for part in chunks(todo, 2000):
            list(ex.map(one, part))
            if capped.is_set():
                break
    cache.add(buf)
    left = cache.missing(todo)
    if capped.is_set() and left and not UP_CAP_LOGGED.is_set():
        UP_CAP_LOGGED.set()
        log("unpaywall: daily cap reached; the DOIs it was still needed for wait for the next UTC day (re-run after "
            "00:00 UTC)")
    return left


def do_crossref(cache, dois):
    todo = [d for d in cache.missing(dois) if "," not in d]
    if not todo:
        return
    vlog(f"crossref: {len(todo)} DOIs to look up")
    sel = ("DOI,license,link,relation,alternative-id,update-to,type,volume,issue,article-number,page,container-title,"
           "abstract")

    def batch(ds):
        params = {"filter": ",".join("doi:" + d for d in ds), "rows": len(ds), "select": sel}
        if polite_email():
            params["mailto"] = polite_email()
        try:
            with CROSSREF_SLOTS:
                d = get_json("https://api.crossref.org/works", params=params, tries=5, timeout=(20, 120))
            items = d["message"].get("items") or []
        except HTTPFail as e:
            if str(e.status) == "414" and len(ds) > 1:      # URL too long after all: halve the batch
                batch(ds[:len(ds) // 2])
                batch(ds[len(ds) // 2:])
            else:
                log(f"crossref batch failed ({str(e)[:120]}); retried on the next pass")
            return
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            log(f"crossref batch failed ({str(e)[:120]}); retried on the next pass")
            return
        got = {}
        for it in items:
            doi = norm_doi(it.get("DOI"))
            got[doi] = {"doi": doi, "found": True, "type": it.get("type"),
                        "licenses": [{"url": l.get("URL"), "version": l.get("content-version")} for l in it.get("license") or []],
                        "links": [{"url": l.get("URL"), "type": l.get("content-type"), "version": l.get("content-version")}
                                  for l in it.get("link") or []],
                        "relation": it.get("relation"), "alternative_id": it.get("alternative-id"),
                        "update_to": it.get("update-to"), "volume": it.get("volume"), "issue": it.get("issue"),
                        "article_number": it.get("article-number"), "page": it.get("page"),
                        "journal": (it.get("container-title") or [None])[0] if it.get("container-title") else None,
                        "abstract": clean_text(it.get("abstract"))[:6000] or None}
        cache.add([got.get(x) or {"doi": x, "found": False} for x in ds])

    groups, cur, size = [], [], 0
    for d in todo:                      # as many DOIs as the URL takes (~170): each lookup takes ~3 s whatever its size
        n = len(urllib.parse.quote(d, safe="")) + 9          # 'doi%3A' + the DOI + '%2C', as sent
        if cur and size + n > CROSSREF_URL_MAX:
            groups.append(cur)
            cur, size = [], 0
        cur.append(d)
        size += n
    if cur:
        groups.append(cur)
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(batch, groups))


def do_openalex(cache, dois, keys, stop=None):
    """100 DOIs per call. `stop` (shared by the blocks of a run) is set when the budget reserve is reached or the key
    is refused; the DOIs left are returned (looked up after the reset)."""
    stop = stop or threading.Event()
    todo = [d for d in cache.missing(dois) if "|" not in d and "," not in d]
    if not todo or stop.is_set():
        return todo
    vlog(f"openalex: {len(todo)} DOIs to look up")
    base = {"select": OALEX_SELECT, "per_page": 100}
    if polite_email():
        base["mailto"] = polite_email()
    if keys.get("openalex"):
        base["api_key"] = keys["openalex"]

    def batch(ds):
        if stop.is_set():
            return
        try:
            r = http_get("https://api.openalex.org/works", params=dict(base, filter="doi:" + "|".join(ds)), tries=5,
                         timeout=(20, 120))
            results = r.json().get("results") or []
        except HTTPFail as e:
            st = str(e.status)
            if st == "400" and len(ds) > 1:          # a DOI the filter cannot take: find it, keep the others
                batch(ds[:len(ds) // 2])
                batch(ds[len(ds) // 2:])
            elif st == "400":
                cache.add([{"doi": ds[0], "found": False}])
            elif st.startswith("429") or st in ("401", "403"):
                if not stop.is_set():
                    log(f"openalex lookup stopped ({e}); re-run later to continue")
                stop.set()
            else:
                log(f"openalex batch failed ({str(e)[:120]}); retried on the next run")
            return
        except ValueError as e:
            log(f"openalex batch failed ({str(e)[:120]}); retried on the next run")
            return
        got = {}
        for w in results:
            rec = openalex_record(w)
            d = norm_doi(rec.get("doi"))
            if d:
                rec.update({"doi": d, "found": True})
                got[d] = rec
        cache.add([got.get(x) or {"doi": x, "found": False} for x in ds])
        ok, rem = openalex_budget_ok(r, reserve=0.002)
        if not ok and not stop.is_set():
            log(f"openalex: budget reserve reached (usd_left={rem}, free daily budget + prepaid credit); re-run after "
                "the 00:00 UTC reset to continue")
            stop.set()

    with ThreadPoolExecutor(OPENALEX_THREADS) as ex:
        list(ex.map(batch, list(chunks(todo, OPENALEX_OR_MAX))))
    return cache.missing(todo)


def do_europepmc(cache, dois):
    todo = [d for d in cache.missing(dois) if '"' not in d]
    if not todo:
        return
    vlog(f"europepmc: {len(todo)} DOIs to look up")

    def batch(ds):
        q = " OR ".join(f'DOI:"{d}"' for d in ds)
        try:
            with EPMC_SLOTS:
                r = http_get("https://www.ebi.ac.uk/europepmc/webservices/rest/searchPOST", method="POST",
                             data={"query": q, "format": "json", "pageSize": 1000, "resultType": "core"}, tries=5,
                             timeout=(20, 180))
            d = r.json()
        except HTTPFail as e:
            if str(e.status) == "400" and len(ds) > 1:   # a DOI the query parser rejects: find it, keep the others
                batch(ds[:len(ds) // 2])
                batch(ds[len(ds) // 2:])
            elif str(e.status) == "400":
                cache.add([{"doi": ds[0], "found": False}])
            else:
                log(f"europepmc batch failed ({str(e)[:120]})")
            return
        except ValueError as e:
            log(f"europepmc batch failed ({str(e)[:120]})")
            return
        res = (d.get("resultList") or {}).get("result") or []
        if int(d.get("hitCount") or 0) > len(res) and len(ds) > 1:     # more records than one page: halve the batch
            batch(ds[:len(ds) // 2])
            batch(ds[len(ds) // 2:])
            return
        got = {}
        for r in res:
            doi = norm_doi(r.get("doi"))
            if not doi:
                continue
            rec = {"doi": doi, "found": True, "pmcid": r.get("pmcid"), "license": r.get("license"),
                   "is_oa": r.get("isOpenAccess") == "Y", "abstract": clean_text(r.get("abstractText"))[:6000] or None,
                   "keywords": ((r.get("keywordList") or {}).get("keyword") or [])[:20],
                   "fulltext": [{"url": u.get("url"), "style": u.get("documentStyle"), "availability": u.get("availability")}
                                for u in ((r.get("fullTextUrlList") or {}).get("fullTextUrl") or [])]}
            if doi not in got or (rec["pmcid"] and not got[doi].get("pmcid")):
                got[doi] = rec
        cache.add([got.get(x) or {"doi": x, "found": False} for x in ds])

    with ThreadPoolExecutor(3) as ex:
        list(ex.map(batch, list(chunks(todo, EPMC_BATCH))))


def pmcaws_lookup(pmcid):
    n = pmcid.upper().replace("PMC", "")
    r = http_get("https://pmc-oa-opendata.s3.amazonaws.com/", params={"list-type": "2", "prefix": f"PMC{n}.",
                                                                      "max-keys": "1000"}, tries=4, timeout=(15, 60))
    keys = re.findall(r"<Key>([^<]+)</Key>", r.text)
    if not keys:
        return {"pmcid": f"PMC{n}", "found": False}
    vers = sorted({k.split("/")[0] for k in keys}, key=lambda x: int(x.split(".")[-1]))
    v = vers[-1]
    files = [k for k in keys if k.startswith(v + "/")]
    meta = get_json(f"https://pmc-oa-opendata.s3.amazonaws.com/{v}/{v}.json", tries=4)
    return {"pmcid": f"PMC{n}", "found": True, "folder": v, "files": files, "license_code": meta.get("license_code"),
            "is_pmc_openaccess": meta.get("is_pmc_openaccess"), "is_manuscript": meta.get("is_manuscript"),
            "is_retracted": meta.get("is_retracted"), "doi": norm_doi(meta.get("doi"))}


def do_pmcaws(cache, pmcids):
    todo = cache.missing(pmcids)
    if not todo:
        return
    vlog(f"pmc open-data mirror: {len(todo)} PMCIDs to look up")
    lock, buf = threading.Lock(), []

    def one(p):
        try:
            rec = pmcaws_lookup(p)
        except HTTPFail as e:
            rec = {"pmcid": p, "found": False, "error": str(e)[:120]}
        except ValueError:
            return
        with lock:
            buf.append(rec)
            if len(buf) >= 200:
                cache.add(list(buf))
                buf.clear()

    with ThreadPoolExecutor(16) as ex:
        list(ex.map(one, todo))
    cache.add(buf)


def do_datacite(cache, arxiv_ids):
    todo = cache.missing(arxiv_ids)
    if not todo:
        return
    vlog(f"datacite (arXiv licenses): {len(todo)} ids to look up")
    lock, buf = threading.Lock(), []

    def one(aid):
        doi = f"10.48550/arxiv.{aid}".lower()
        try:
            d = get_json(f"https://api.datacite.org/dois/{doi}", tries=4)
            a = (d.get("data") or {}).get("attributes") or {}
            rec = {"arxiv": aid, "found": True,
                   "licenses": [x.get("rightsUri") or x.get("rights") for x in a.get("rightsList") or []]}
        except HTTPFail as e:
            rec = {"arxiv": aid, "found": False, "error": str(e)[:120]}
        except ValueError:
            return
        with lock:
            buf.append(rec)

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, todo))
    cache.add(buf)


def do_s2(cache, dois, keys):
    todo = cache.missing(dois)
    if not todo or S2_STOPPED.is_set():
        return
    vlog(f"semantic scholar: {len(todo)} DOIs to look up")
    headers = {"x-api-key": keys["s2"]} if keys.get("s2") else None
    fields = "externalIds,abstract,openAccessPdf,isOpenAccess,citationCount,influentialCitationCount"
    for ds in chunks(todo, S2_BATCH):
        if S2_STOPPED.is_set():
            return
        try:
            # without a key the shared pool often refuses everything: give up after one wait instead of eight
            r = http_get("https://api.semanticscholar.org/graph/v1/paper/batch", method="POST", params={"fields": fields},
                         json_body={"ids": ["DOI:" + d for d in ds]}, headers=headers, tries=8 if headers else 2,
                         timeout=(20, 180))
            arr = r.json()
        except HTTPFail as e:
            if str(e.status) == "400":  # S2 answers 400 when none of the ids in the batch is known to it
                cache.add([{"doi": d, "found": False} for d in ds])
                continue
            if not S2_STOPPED.is_set():
                log(f"semantic scholar stopped ({str(e)[:80]}); the run goes on without it (--abstracts-only later, or a "
                    "free `s2:` key)")
            S2_STOPPED.set()
            return
        except ValueError as e:
            log(f"semantic scholar batch failed ({str(e)[:120]})")
            continue
        recs = []
        for d, p in zip(ds, arr):
            if not p:
                recs.append({"doi": d, "found": False})
                continue
            oa = p.get("openAccessPdf") or {}
            ex = p.get("externalIds") or {}
            recs.append({"doi": d, "found": True, "abstract": p.get("abstract"), "is_oa": p.get("isOpenAccess"),
                         "oa_url": oa.get("url"), "oa_license": oa.get("license"), "cited_by": p.get("citationCount"),
                         "influential": p.get("influentialCitationCount"), "arxiv": ex.get("ArXiv"),
                         "pmcid": ex.get("PubMedCentral")})
        cache.add(recs)


# ---------------------------------------------------------------- license decision (per paper)
def crossref_vor_license(cr):
    if not cr or not cr.get("found"):
        return None
    toks = [((l.get("version") or "").lower(), norm_license(l.get("url"))) for l in cr.get("licenses") or []]
    vor = [t for v, t in toks if v in ("vor", "unspecified", "")]
    cc = [t for t in vor if t and (t.startswith("cc") or t in ("cc0", "public-domain"))]
    if cc:
        nd = [t for t in cc if t in ND_LICENSES]
        return nd[0] if nd else cc[0]
    return "publisher-specific" if vor else None


def crossref_vor_url(cr):
    if not cr or not cr.get("found"):
        return None
    urls = [(l.get("version") or "").lower() for l in cr.get("licenses") or []]
    for want in ("vor", "unspecified", ""):
        for l in cr.get("licenses") or []:
            if (l.get("version") or "").lower() == want and l.get("url"):
                return l["url"]
    return None


def versions_for(h, up, oa, ep, pmc, s2, crv, dc_by, up_cache, cr_cache, oa_cache=None):
    vers, known = [], set()

    def add(src, url, pdf_url, lic, version, host_type=None, extra=None):
        if not (url or pdf_url):
            return
        key = pdf_url or url
        if key in known:
            return
        known.add(key)
        vers.append({"src": src, "url": url, "pdf_url": pdf_url, "license": norm_license(lic), "license_raw": lic,
                     "version": version, "host_type": host_type, "host": host_of(pdf_url or url), **(extra or {})})

    for l in (up or {}).get("oa_locations") or []:
        add("unpaywall", l.get("url_for_landing_page") or l.get("url"), l.get("url_for_pdf"), l.get("license"),
            l.get("version"), l.get("host_type"))
    for l in ((oa or {}).get("locations") or []) + [l for l in h.get("locations") or [] if l.get("source") == "openalex"]:
        if l.get("is_oa"):
            add("openalex", l.get("url"), l.get("pdf_url"), l.get("license"), l.get("version"), l.get("host_type"))
    for l in h.get("locations") or []:
        if l.get("source") == "openaire" and l.get("is_oa"):
            u = l.get("url") or ""
            add("openaire", u, u if u.lower().endswith(".pdf") else None, l.get("license"), None, l.get("type"))
    for u in h.get("oa_urls") or []:
        add(u.get("source"), None, u.get("url"), u.get("license"), u.get("version"))
    if pmc and pmc.get("found") and pmc.get("is_pmc_openaccess") and not pmc.get("is_retracted"):
        pdf = next((f for f in pmc.get("files") or [] if f.endswith(".pdf") and f.split("/")[-1].startswith("PMC")), None)
        add("pmc_aws", f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc['pmcid']}/",
            f"https://pmc-oa-opendata.s3.amazonaws.com/{pdf}" if pdf else None, pmc.get("license_code"),
            "acceptedVersion" if pmc.get("is_manuscript") else "publishedVersion", "repository",
            {"pmcid": pmc["pmcid"], "pmc_license": norm_license(pmc.get("license_code"))})
    if ep and ep.get("found") and ep.get("is_oa"):
        for u in ep.get("fulltext") or []:
            if (u.get("availability") or "").lower().startswith("open") and u.get("style") == "pdf":
                add("europepmc", None, u.get("url"), ep.get("license"), "publishedVersion", "repository")
    if s2 and s2.get("found") and s2.get("oa_url"):
        add("s2", None, s2["oa_url"], s2.get("oa_license"), None)
    # publisher copies without their own license metadata inherit the license deposited in Crossref for the VoR
    if crv:
        for v in vers:
            if v.get("host_type") in ("publisher", "journal") and v.get("license") in (None, "other-oa"):
                v["license"], v["license_inherited"] = crv, "crossref_vor"
                v["license_raw"] = crossref_vor_url(cr_cache.get(h.get("doi"))) or v.get("license_raw")
    # licensed preprint copies merged into this paper (ChemRxiv / Research Square / arXiv ...)
    for pd in h.get("preprint_dois") or []:
        u, c = up_cache.get(pd), cr_cache.get(pd)
        lic_cr = next((t for t in (norm_license(l.get("url")) for l in (c or {}).get("licenses") or [])
                       if t and (t.startswith("cc") or t in ("cc0", "public-domain"))), None)
        for l in (u or {}).get("oa_locations") or []:
            add("preprint", l.get("url_for_landing_page") or l.get("url"), l.get("url_for_pdf"),
                l.get("license") or lic_cr, l.get("version") or "submittedVersion", "repository", {"preprint_doi": pd})
        for l in ((oa_cache.get(pd) if oa_cache else None) or {}).get("locations") or []:
            if not u and l.get("is_oa"):
                add("preprint", l.get("url"), l.get("pdf_url"), l.get("license") or lic_cr,
                    l.get("version") or "submittedVersion", "repository", {"preprint_doi": pd})
        if not u and lic_cr:
            add("preprint", f"https://doi.org/{pd}", None, lic_cr, "submittedVersion", "repository", {"preprint_doi": pd})
    aid = (h.get("external_ids") or {}).get("arxiv")
    if aid:
        aid = re.sub(r"v\d+$", "", str(aid))
        dc = dc_by.get(aid)
        lic = None
        for x in (dc or {}).get("licenses") or []:
            lic = norm_license(x) or lic
        add("arxiv", f"https://arxiv.org/abs/{aid}", f"https://export.arxiv.org/pdf/{aid}",
            lic if lic != "other-oa" else None, "submittedVersion", "repository")
    return vers


def decide(h, vers, crv, up, oa):
    for v in vers:
        acc = license_access(v.get("license"))
        if v.get("host_type") in ("publisher", "journal") and crv and acc == "OA" and crv not in OPEN_LICENSES:
            v["license_conflict"] = f"crossref_vor={crv}"
            acc = license_access(crv)
        v["access"] = acc or "Free-to-read"
    oa_any = bool(vers) or bool((up or {}).get("is_oa")) or bool((oa or {}).get("is_oa")) or bool(h.get("is_oa_any"))
    best = min((v["access"] for v in vers), key=access_rank) if vers else ("Free-to-read" if oa_any else "Paywalled")
    if license_access(crv) and access_rank(license_access(crv)) < access_rank(best):
        best = license_access(crv)  # Crossref says CC but no aggregator lists a location yet
    vers.sort(key=lambda v: (access_rank(v["access"]), VERSION_RANK.get(v.get("version"), 3), 0 if v.get("pdf_url") else 1))
    src = next((v for v in vers if v["access"] == best and v.get("license")), None) or \
        next((v for v in vers if v["access"] == best), None)
    lic = src.get("license") if src else None
    if best == "OA+ND" or best == "OA":
        lic = lic or crv
    elif best == "Free-to-read":
        lic = lic if lic in ("publisher-specific", "other-oa") else "other-oa"
    else:
        lic = None
    return best, lic, src


LICENSE_SOURCE = {"unpaywall": "Unpaywall", "openalex": "OpenAlex", "openaire": "OpenAIRE", "pmc_aws": "PubMed Central",
                  "europepmc": "Europe PMC", "s2": "Semantic Scholar", "preprint": "Preprint server",
                  "arxiv": "arXiv (DataCite)", "crossref_vor": "Crossref"}


def license_fields(best, lic, src, crv, cr, h):
    """-> license_label (exact, with version), license_url, license_source for the deciding copy."""
    if best == "Paywalled":
        url = crossref_vor_url(cr)
        return ("Subscription (no open license)" if not url else
                f"Subscription — {license_detail(url)[0]}"), url, ("Crossref" if url else "No open copy in Unpaywall, "
                                                                                       "OpenAlex, Crossref or PMC")
    raw, srcname = None, None
    if src:
        raw = src.get("license_raw")
        srcname = LICENSE_SOURCE.get(src.get("license_inherited") or "", None) or \
            LICENSE_SOURCE.get(src.get("src"), SOURCE_LABEL.get(src.get("src"), src.get("src")))
    if lic and lic == crv and (not raw or norm_license(raw) != lic):
        raw, srcname = crossref_vor_url(cr) or raw, "Crossref"
    # a versioned URL/string seen anywhere for the same license token beats a bare token ('cc-by')
    if lic and (not raw or not re.search(r"\d\.\d", str(raw))):
        cands = [l.get("raw") or l.get("license") for l in h.get("licenses_seen") or []]
        cands += [crossref_vor_url(cr)] if crv == lic else []
        better = next((c for c in cands if c and norm_license(c) == lic and re.search(r"\d\.\d", str(c))), None)
        if better:
            raw = better
    label, url = license_detail(raw, lic) if (raw or lic) else (None, None)
    if best == "Free-to-read" and lic == "other-oa":
        label = "Free to read (no license)"
    return label, url, srcname


# ---------------------------------------------------------------- blocks (any topic size)
OA_DROP = ("$.authors_detail", "$.authors")     # the parts of OpenAlex answers a decision never reads


def count_rows(led, topic, cond, args):
    return led.q("SELECT COUNT(*) FROM papers p JOIN paper_topics t ON t.paper_id = p.id WHERE t.topic=? " + cond,
                 (topic, *args))[0][0]


def blocks(led, topic, cond, args):
    """The topic's papers matching `cond`, CHUNK at a time in id order (never the whole topic in memory)."""
    return led.iter_topic(topic, cond, args, CHUNK)


def run_blocks(fn, gen, total, label, proj=None, topic=None):
    """fn(rows) -> papers done, for every block; IN_FLIGHT blocks at a time (at most that many in memory)."""
    t0, done, k, futs = time.time(), 0, 0, deque()
    nblocks = max(1, -(-total // CHUNK))

    def finish(f):
        nonlocal done, k
        done += f.result()
        k += 1
        if nblocks > 1:
            el = time.time() - t0
            eta = el / max(done, 1) * max(total - done, 0)
            log(f"{label}: block {k}/{nblocks} — {done:,}/{total:,} papers ({el / 60:.1f} min, ~{eta / 60:.0f} min left)")
            if proj and topic:
                update_state(proj, topic, lambda st: st.__setitem__(label + "_progress", {
                    "papers_done": done, "papers_total": total, "blocks_done": k, "blocks_total": nblocks,
                    "minutes": round(el / 60, 1), "minutes_left": round(eta / 60), "updated_at": now_iso()}))

    with ThreadPoolExecutor(IN_FLIGHT) as ex:
        for rows in gen:
            futs.append(ex.submit(fn, rows))
            while len(futs) >= IN_FLIGHT:
                finish(futs.popleft())
        while futs:
            finish(futs.popleft())
    return done


class Classifier:
    """Looks up one block of papers (every service at once, then the lookups that need their answers) and decides it.
    Several blocks are looked up at the same time; decisions are written one block at a time."""

    def __init__(self, proj, led, topic, keys, skip, age, hints):
        self.proj, self.led, self.topic, self.keys, self.skip, self.hints = proj, led, topic, keys, set(skip), hints
        self.up, self.cr = Cache(proj, "unpaywall", max_age_days=age), Cache(proj, "crossref", max_age_days=age)
        self.oa, self.ep = Cache(proj, "openalex", max_age_days=age), Cache(proj, "europepmc", max_age_days=age)
        self.s2 = Cache(proj, "s2", max_age_days=age)
        self.pmc, self.dc = Cache(proj, "pmcaws", key="pmcid", max_age_days=age), Cache(proj, "datacite", key="arxiv")
        self.cap = DailyCap(UNPAYWALL_USAGE, UNPAYWALL_DAILY_CAP)
        self.up_on = "unpaywall" not in skip and bool(polite_email())
        if "unpaywall" not in skip and not polite_email():
            log("unpaywall: skipped (needs polite_email in config)")
        self.oa_stop = threading.Event()
        self.lock = threading.Lock()
        self.vocab = Vocab(proj)
        self.cnt, self.n, self.examples = Counter(), Counter(), []

    # ------------------------------------------------------------ lookups
    def lookup(self, rows):
        led, skip = self.led, self.skip
        ids = [r["id"] for r in rows]
        hints = self.hints.get_many(ids)
        alias = defaultdict(list)
        for i in range(0, len(ids), 900):
            part = ids[i:i + 900]
            for pid, d in led.q(f"SELECT paper_id, doi FROM dois WHERE paper_id IN ({','.join('?' * len(part))})",
                                tuple(part)):
                alias[pid].append(d)
        dois, all_dois, pmcids, arx, no_abs, oa_any = [], set(), set(), set(), set(), set()
        for r in rows:
            h = hints.get(r["id"], {})
            # preprint / repository copies merged into this paper later (dedup.py) are copies of it too — but never a
            # publisher's SI deposit on Figshare, whose license is not the article's
            extra = [d for d in alias.get(r["id"], ()) if d != r.get("doi") and d.startswith("10.")
                     and (is_preprint_doi(d) or is_repository_doi(d)) and not d.startswith(("10.6084/", "10.25384/"))]
            if extra:
                h = dict(h, preprint_dois=list(dict.fromkeys(list(h.get("preprint_dois") or []) + extra)))
                hints[r["id"]] = h
            if r.get("doi"):
                dois.append(r["doi"])
                all_dois.add(r["doi"])
                if len(r.get("abstract") or "") < 80:
                    no_abs.add(r["doi"])
                if h.get("is_oa_any"):
                    oa_any.add(r["doi"])
            all_dois.update(h.get("preprint_dois") or [])
            p = (r.get("external_ids") or {}).get("pmcid") or (h.get("external_ids") or {}).get("pmcid")
            if p:
                pmcids.add(norm_pmcid(p))
            aid = (h.get("external_ids") or {}).get("arxiv")
            if aid:
                arx.add(re.sub(r"v\d+$", "", str(aid)))
            for d in h.get("dois_all") or []:
                if d.startswith("10.48550/arxiv."):
                    arx.add(d.split("arxiv.", 1)[1])
        all_dois = sorted(all_dois)
        # 1. the services that need nothing else, all at once
        jobs = {"crossref": (do_crossref, self.cr, all_dois)}
        if "openalex" not in skip:
            jobs["openalex"] = (do_openalex, self.oa, all_dois, self.keys, self.oa_stop)
        if "s2" not in skip:
            jobs["s2"] = (do_s2, self.s2, dois, self.keys)
        res = run_parallel(jobs)
        do_crossref(self.cr, all_dois)          # second pass for a batch that failed (usually nothing is left)
        oa_left = res.get("openalex") or []
        # 2. Unpaywall only for DOIs OpenAlex lacks (it knows only Crossref DOIs: none that Crossref and OpenAlex both
        #    do not know); Europe PMC for papers likely open or without an abstract
        O = self.oa.summary(all_dois, ("$.found", "$.is_oa", "$.ids.pmcid"))
        C = self.cr.summary(all_dois, ("$.found",))
        need = [d for d in all_dois if not (O.get(d) or (None,))[0] and not (d in O and (C.get(d) or (None,))[0] == 0)]
        need.sort(key=lambda d: d not in O)     # DOIs OpenAlex does not know first, then the ones it was not asked
        epmc = [d for d in dois if (O.get(d) or (None, None))[1] or d in oa_any or d in no_abs]
        jobs = {}
        if self.up_on:
            jobs["unpaywall"] = (do_unpaywall, self.up, need, self.cap)
        if "europepmc" not in skip:
            jobs["europepmc"] = (do_europepmc, self.ep, epmc)
        res = run_parallel(jobs)
        up_left = res.get("unpaywall") or []
        if "europepmc" not in skip:             # papers Unpaywall has found open
            asked, U = set(epmc), self.up.summary(dois, ("$.is_oa",))
            do_europepmc(self.ep, [d for d in dois if d not in asked and (U.get(d) or (None,))[0]])
        # 3. the PMC copies and arXiv licenses of the ids found so far
        E, S = self.ep.summary(dois, ("$.pmcid",)), self.s2.summary(dois, ("$.pmcid", "$.arxiv"))
        for d in dois:
            for v in ((E.get(d) or (None,))[0], (S.get(d) or (None, None))[0], (O.get(d) or (None, None, None))[2]):
                if v:
                    pmcids.add(norm_pmcid(v))
            a_ = (S.get(d) or (None, None))[1]
            if a_:
                arx.add(re.sub(r"v\d+$", "", str(a_)))
        jobs = {}
        if "pmcaws" not in skip:
            jobs["pmcaws"] = (do_pmcaws, self.pmc, sorted(pmcids))
        if "datacite" not in skip:
            jobs["datacite"] = (do_datacite, self.dc, sorted(arx))
        run_parallel(jobs)
        return hints, len(oa_left), len(up_left)

    def answered(self, doi, O, U, C):
        """True when OpenAlex or Unpaywall has answered for this DOI, or neither can (switched off / no email), or
        neither OpenAlex nor Crossref knows it (Unpaywall knows only Crossref DOIs)."""
        o_ = O.get(doi)
        if o_ is None and ("|" in doi or "," in doi):
            o_ = {}                         # OpenAlex cannot be asked for this DOI: count it as "not found"
        if (o_ or {}).get("found") or U.get(doi) is not None:
            return True
        if o_ is not None and (C.get(doi) or {}).get("found") is False:
            return True
        if not self.up_on:                  # Unpaywall unavailable: OpenAlex's answer (even "not found") decides
            return o_ is not None or "openalex" in self.skip
        return False

    # ------------------------------------------------------------ decisions
    def process(self, rows):
        hints, oa_left, up_left = self.lookup(rows)
        with self.lock:                     # one block at a time: one ledger transaction each
            filled = []
            with self.led.tx():
                for i in range(0, len(rows), SLICE):
                    filled += self.decide_rows(rows[i:i + SLICE], hints)
            for i in range(0, len(filled), 900):   # new abstracts: vocabulary topics again (Claude/API/manual kept)
                part = filled[i:i + 900]
                apply_vocab(self.led, self.vocab,
                            self.led.topic_rows(self.topic, f"AND p.id IN ({','.join('?' * len(part))})", tuple(part)))
            self.n["filled"] += len(filled)
            self.n["oa_left"] += oa_left
            self.n["up_left"] += up_left
        return len(rows)

    def decide_rows(self, rows, hints):
        led = self.led
        dois = [r["doi"] for r in rows if r.get("doi")]
        all_d = set(dois)
        for r in rows:
            all_d.update(hints.get(r["id"], {}).get("preprint_dois") or [])
        U, C, O = self.up.get_many(all_d), self.cr.get_many(all_d), self.oa.get_many(all_d, drop=OA_DROP)
        E, S = self.ep.get_many(dois), self.s2.get_many(dois)
        pmc_of, aids = {}, set()
        for r in rows:
            d = r.get("doi")
            e, s, o = E.get(d), S.get(d), O.get(d)
            p = (r.get("external_ids") or {}).get("pmcid") or (e or {}).get("pmcid") or (s or {}).get("pmcid") \
                or ((o or {}).get("ids") or {}).get("pmcid")
            if p:
                pmc_of[r["id"]] = norm_pmcid(p)
            aid = (hints.get(r["id"], {"external_ids": r.get("external_ids") or {}}).get("external_ids") or {}).get("arxiv")
            if aid:
                aids.add(re.sub(r"v\d+$", "", str(aid)))
        P, D = self.pmc.get_many(pmc_of.values()), self.dc.get_many(aids)
        filled, notices = [], []
        for r in rows:
            h = hints.get(r["id"], {"external_ids": r.get("external_ids") or {}})
            d = r.get("doi")
            u, o, c, e, s = U.get(d), O.get(d), C.get(d), E.get(d), S.get(d)
            pid_pmc = pmc_of.get(r["id"])
            pm = P.get(pid_pmc) if pid_pmc else None
            upd = {"last_checked": today()}
            if r.get("doc_type") == "patent":
                upd.update(access_type="Free-to-read", license="other-oa", license_label="Patent document (public record)",
                           license_url=None, license_source="Patent office", access_basis="metadata", versions=[])
                led.set(r["id"], **upd)
                self.cnt["Free-to-read"] += 1
                continue
            if d and not self.answered(d, O, U, C):
                self.n["pending"] += 1      # decided on a later run, never guessed as Paywalled from missing data
                continue
            crv = crossref_vor_license(c)
            vers = versions_for(dict(h, doi=d), u, o, e, pm, s, crv, D, U, C, O)
            for l in h.get("licenses_seen") or []:   # licenses stated by DOI-less sources (repositories, datasets)
                if not vers and l.get("license") and h.get("landing_urls"):
                    vers.append({"src": l.get("source"), "url": h["landing_urls"][0].get("url"), "pdf_url": None,
                                 "license": norm_license(l["license"]), "license_raw": l.get("raw") or l["license"],
                                 "version": "publishedVersion", "host_type": "repository",
                                 "host": host_of(h["landing_urls"][0].get("url"))})
            best, lic, src = decide(h, vers, crv, u, o)
            label, lurl, lsrc = license_fields(best, lic, src, crv, c, h)
            upd.update({"access_type": best, "license": lic, "versions": vers[:25], "access_basis": "metadata",
                        "oa_status": (u or {}).get("oa_status") or (o or {}).get("oa_status") or h.get("oa_status"),
                        "license_label": label,
                        "license_url": lurl, "license_source": lsrc})
            if r.get("downloaded") and r.get("access_basis") in ("pdf", "pdf_differs"):
                for k in ("access_type", "license", "license_label", "license_url", "license_source", "access_basis"):
                    upd.pop(k, None)          # the license printed in the downloaded PDF stays authoritative
            final = upd.get("access_type", r.get("access_type"))
            old_acc = r.get("access_type")
            if old_acc and final and final != old_acc:
                self.n["more_open" if access_rank(final) < access_rank(old_acc) else "less_open"] += 1
                if len(self.examples) < 20:
                    self.examples.append({"id": r["id"], "doi": d, "from": old_acc, "to": final})
                if not r.get("downloaded") and r.get("dl_status") in ("not_selected", "no_route", "failed"):
                    upd.update(dl_status=None, dl_note=None)   # the old reason no longer applies; the next download decides
            ext = dict(r.get("external_ids") or {})
            if pid_pmc and not ext.get("pmcid"):
                ext["pmcid"] = pid_pmc
                upd["external_ids"] = ext
            if s and s.get("found") and r.get("cited_by") is None and s.get("cited_by") is not None:
                upd["cited_by"] = s["cited_by"]
            if o and o.get("found") and o.get("cited_by_count") is not None:
                upd["cited_by"] = o["cited_by_count"]
            # abstract / keywords the search records lacked
            if len(r.get("abstract") or "") < 80 and r.get("abstract_source") != "pdf":
                for name, src_rec in (("Semantic Scholar", s), ("Europe PMC", e), ("OpenAlex", o), ("Crossref", c)):
                    ab = clean_text((src_rec or {}).get("abstract") or "")
                    if len(ab) >= 80:
                        upd["abstract"], upd["abstract_source"] = ab[:6000], name
                        filled.append(r["id"])
                        break
            kw = list(r.get("keywords") or [])
            for k in ((o or {}).get("keywords") or []) + ((e or {}).get("keywords") or []):
                if k and k.lower() not in {x.lower() for x in kw}:
                    kw.append(k)
            if kw != (r.get("keywords") or []):
                upd["keywords"] = kw[:25]
            itself, retracts = retraction_of((c or {}).get("update_to"), d)
            if retracts:                       # a retraction notice: the papers it names are the retracted ones
                notices.append((r["id"], retracts))
            elif itself or ((o or {}).get("retracted") and not (r.get("external_ids") or {}).get("retraction_of")):
                upd["retracted"] = 1
                self.n["retracted"] += not r.get("retracted")
            # a preprint that has since been published: record the published DOI (dedup.py merges both records)
            if r.get("is_preprint") and c and c.get("found"):
                for x in ((c.get("relation") or {}).get("is-preprint-of") or []):
                    vor = norm_doi(x.get("id")) if x.get("id-type") == "doi" else None
                    if vor and not led.find_id(doi=vor):
                        led.add_dois(r["id"], [vor])
                        upd.update(doi=vor, is_preprint=0, doc_type="article")
                        self.n["upgraded"] += 1
                        break
            led.set(r["id"], **upd)
            self.cnt[final or best] += 1
        for nid, retracts in notices:          # after the slice: a retracted paper's own update above cannot undo it
            self.n["retracted"] += led.record_retraction(nid, retracts)
            self.n["notices"] += 1
        return filled


def fill_abstracts(proj, led, topic, keys, skip, export=True):
    """Papers without an abstract (< 80 characters, not read from a PDF): look their DOIs up in OpenAlex (100 per
    call, daily budget), Semantic Scholar, Europe PMC and Crossref — all at once, block by block — and keep the first
    real abstract. Re-run after 00:00 UTC when OpenAlex's budget stopped it (lookups_left)."""
    global VERBOSE
    cond = ("AND p.is_erratum = 0 AND LENGTH(COALESCE(p.abstract, '')) < 80 "
            "AND COALESCE(p.abstract_source, '') NOT LIKE 'pdf%'")
    total = count_rows(led, topic, cond, ())
    VERBOSE = total <= CHUNK
    log(f"{total:,} papers without an abstract")
    cr, oa = Cache(proj, "crossref"), Cache(proj, "openalex")
    ep, s2 = Cache(proj, "europepmc"), Cache(proj, "s2")
    stop, lock, vocab = threading.Event(), threading.Lock(), Vocab(proj)
    by, n = Counter(), Counter()

    def block(rows):
        dois = sorted({r["doi"] for r in rows if r.get("doi")})
        jobs = {"crossref": (do_crossref, cr, dois)}
        if "openalex" not in skip:
            jobs["openalex"] = (do_openalex, oa, dois, keys, stop)
        if "s2" not in skip:
            jobs["s2"] = (do_s2, s2, dois, keys)
        if "europepmc" not in skip:
            jobs["europepmc"] = (do_europepmc, ep, dois)
        res = run_parallel(jobs)
        with lock:
            filled = []
            with led.tx():
                for i in range(0, len(rows), SLICE):
                    part = rows[i:i + SLICE]
                    ds = [r["doi"] for r in part if r.get("doi")]
                    S, E = s2.get_many(ds), ep.get_many(ds)
                    O, C = oa.get_many(ds, drop=OA_DROP), cr.get_many(ds)
                    for r in part:
                        d = r.get("doi")
                        if not d:
                            continue
                        upd = {}
                        for name, rec in (("Semantic Scholar", S.get(d)), ("Europe PMC", E.get(d)),
                                          ("OpenAlex", O.get(d)), ("Crossref", C.get(d))):
                            ab = normalize_abstract((rec or {}).get("abstract") or "")
                            if len(ab) >= 80:
                                upd.update(abstract=ab, abstract_source=name)
                                by[name] += 1
                                break
                        kw = list(r.get("keywords") or [])
                        for k in ((O.get(d) or {}).get("keywords") or []) + ((E.get(d) or {}).get("keywords") or []):
                            if k and k.lower() not in {x.lower() for x in kw}:
                                kw.append(k)
                        if kw != (r.get("keywords") or []):
                            upd["keywords"] = kw[:25]
                        if upd:
                            led.set(r["id"], **upd)
                            if "abstract" in upd:
                                filled.append(r["id"])
            for i in range(0, len(filled), 900):   # new abstracts: vocabulary topics again (Claude/API/manual kept)
                part = filled[i:i + 900]
                apply_vocab(led, vocab, led.topic_rows(topic, f"AND p.id IN ({','.join('?' * len(part))})", tuple(part)))
            n["with_doi"] += len(dois)
            n["filled"] += len(filled)
            n["oa_left"] += len(res.get("openalex") or [])
        return len(rows)

    run_blocks(block, blocks(led, topic, cond, ()), total, "abstracts_only", proj, topic)
    if export:
        led.export(topics=[topic])
    stats = {"without_abstract": total, "with_doi": n["with_doi"], "abstracts_filled": n["filled"],
             "by_source": dict(by), "lookups_left": {"openalex": n["oa_left"]}, "finished_at": now_iso()}
    if n["oa_left"]:
        stats["next"] = "OpenAlex's budget stopped the lookups; re-run with --abstracts-only after 00:00 UTC"
    def fn(st):
        st.setdefault("abstracts_only", {}).update(stats)
        st.pop("abstracts_only_progress", None)
    update_state(proj, topic, fn)
    print(json.dumps(stats))


def main():
    global VERBOSE
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--refresh", action="store_true", help="re-decide papers that already have an access type")
    ap.add_argument("--skip", default="", help="comma list of lookups to skip: s2,openalex,unpaywall,europepmc,pmcaws,"
                                               "datacite (Crossref is always used)")
    ap.add_argument("--abstracts-only", action="store_true",
                    help="only fill missing abstracts and keywords from metadata (no access decision, no Unpaywall)")
    ap.add_argument("--recheck-older-than", type=int, default=None, metavar="DAYS",
                    help="re-query and re-decide papers last checked DAYS or more days ago (update mode); 0 = every paper, "
                         "with fresh lookups — use it when the user asks to re-check everything")
    ap.add_argument("--no-export", action="store_true",
                    help="do not refresh the index CSVs and papers.db (run export.py once after the last step)")
    a = ap.parse_args()
    proj = Project(a.project)
    load_config(proj, a.topic)
    keys = load_keys(proj)
    set_paces(keys)
    skip = set(x for x in a.skip.split(",") if x)
    led = Ledger(proj)
    if a.abstracts_only:
        return fill_abstracts(proj, led, a.topic, keys, skip, export=not a.no_export)
    age = a.recheck_older_than
    if age is not None:
        cutoff = (_dt.date.today() - _dt.timedelta(days=age)).isoformat()
        cond, args = "AND (p.access_type IS NULL OR p.last_checked IS NULL OR p.last_checked <= ?)", (cutoff,)
    else:
        cond, args = ("" if a.refresh else "AND p.access_type IS NULL"), ()
    total = count_rows(led, a.topic, cond, args)
    log(f"{total:,} papers to classify" + (f" in {-(-total // CHUNK)} blocks of {CHUNK:,}" if total > CHUNK else ""))
    if not total:
        print(json.dumps({"classified": 0}))
        return
    VERBOSE = total <= CHUNK
    t0 = time.time()
    if "s2" not in skip and not keys.get("s2") and total > S2_KEYLESS_MAX:
        skip.add("s2")
        log(f"semantic scholar: not used for {total:,} papers without a key (its shared keyless pool refuses most "
            "requests); abstracts it could add: --abstracts-only later, or add a free `s2:` key to keys.txt")
    cl = Classifier(proj, led, a.topic, keys, skip, age, Hints(proj.topic_dir(a.topic) / "candidates.jsonl"))
    run_blocks(cl.process, blocks(led, a.topic, cond, args), total, "classify_access", proj, a.topic)
    if not a.no_export:
        led.export(topics=[a.topic])
    cnt, n, pending = cl.cnt, cl.n, cl.n["pending"]
    stats = {"classified": sum(cnt.values()), "by_access_type": {k: cnt.get(k, 0) for k in ACCESS_TYPES},
             "abstracts_filled": n["filled"], "newly_retracted": n["retracted"], "retraction_notices": n["notices"],
             "preprints_now_published": n["upgraded"],
             "access_changes": {"more_open": n["more_open"], "less_open": n["less_open"], "examples": cl.examples},
             "recheck_older_than_days": age, "pending": pending,
             "lookups_left": {"openalex": n["oa_left"], "unpaywall": n["up_left"]},
             "unpaywall_calls_today": cl.cap.used(), "complete": pending == 0,
             "skipped_lookups": sorted(skip), "minutes": round((time.time() - t0) / 60, 1),
             "exported": not a.no_export, "finished_at": now_iso()}
    if pending:
        stats["next"] = (f"{pending} papers wait for OpenAlex's budget or Unpaywall's daily cap; re-run "
                         f"classify_access.py --topic {a.topic} after 00:00 UTC (they keep an empty access type)")

    def fn(st):
        st["classify_access"] = stats
        st.pop("classify_access_progress", None)
        if "classify_access" not in st.setdefault("steps_done", []):
            st["steps_done"].append("classify_access")
    update_state(proj, a.topic, fn)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
