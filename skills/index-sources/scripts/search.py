"""Index step 2 — federated search: run every query in .scripts/<topic>/queries.json on every chosen database and page
each one to the end. Resumable: cursors live in .scripts/<topic>/state.json, raw hits are appended to
.scripts/<topic>/raw/<label>/<database>.jsonl. Nothing is downloaded here.

usage:
  python3 -I search.py --topic <slug> --count-only          # first page of each query -> estimated field size
  python3 -I search.py --topic <slug>                       # full search (all databases in config, in parallel)
  python3 -I search.py --topic <slug> --since 2026-09-01    # update mode: only works newer than the date
  python3 -I search.py --topic <slug> --citing [--since D]  # citation chasing: works citing the topic's core sources
Databases that need a key (keys.txt) are skipped with a message when the key is missing. Lists of DOIs, BibTeX/RIS files
and web pages are added with import_list.py. Prints one JSON summary line at the end.
"""
import argparse
import json
import re
import sys
import threading
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (KEY_FILES_HELP, Gate, HTTPFail, Project, add_project_arg, clean_text, die, http_get, json_read,
                     jsonl_append, load_config, load_keys, load_state, log, norm_doi, now_iso, open_text, polite_email,
                     update_state)
from _databases import CATALOG, FETCHERS, OALEX_SELECT, iso_or_none, keys_needed, openalex_budget_ok, openalex_record

# Relevance-ranked databases stop a query when < 4% of a page passes the topic gate twice in a row (the rest is a tail
# of loose matches). Strict boolean/filter databases and year-walked J-STAGE always page to the end.
STRICT_SOURCES = {"openalex", "citations", "pmc", "arxiv", "jstage", "europepmc_patents", "epo", "lens_patents", "s2"}
TAIL_STOP = 0.04
DUP_PAGES = 25         # OpenAlex: pages in a row without a new DOI before a secondary query stops early


def load_queries(proj, slug, databases, path=None):
    qs = json_read(Path(path) if path else proj.topic_dir(slug) / "queries.json")
    if not qs:
        die(f"missing {path or f'.scripts/{slug}/queries.json'} — write the per-database queries first "
            "(references/queries.md)")
    bad = [s for s in qs if s not in FETCHERS]
    if bad:
        die(f"queries.json has unknown databases {bad}; valid: {sorted(FETCHERS)}")
    return {s: qs[s] for s in databases if qs.get(s)}


def usable_databases(databases, keys):
    """-> (usable, skipped{database: reason}). Key databases without their key are skipped, never queried."""
    ok, skipped = [], {}
    for s in databases:
        if s not in FETCHERS:
            skipped[s] = CATALOG.get(s, {}).get("reason") or "unknown database"
            continue
        missing = [k for k in keys_needed(s) if not keys.get(k)]
        if missing:
            skipped[s] = f"needs {', '.join(f'`{k}: <key>`' for k in missing)} in {KEY_FILES_HELP}"
            continue
        ok.append(s)
    return ok, skipped


class Runner:
    def __init__(self, proj, slug, cfg, label, since):
        self.proj, self.slug, self.cfg, self.label, self.since = proj, slug, cfg, label, since
        self.raw = proj.topic_dir(slug) / "raw" / label
        self.raw.mkdir(parents=True, exist_ok=True)
        self.gate = Gate(cfg.get("gate"))
        self.ctx = {"keys": load_keys(proj)}
        self.seen = None
        self.seen_lock = threading.Lock()
        self.stop_rules = dict({k: TAIL_STOP for k in FETCHERS if k not in STRICT_SOURCES},
                               **(cfg.get("search", {}).get("stop_rule") or {}))

    def cursor(self, src, qid):
        st = load_state(self.proj, self.slug)
        return (((st.get("search") or {}).get(self.label) or {}).get(src) or {}).get(qid) or {}

    def set_cursor(self, src, qid, **kw):
        def fn(st):
            c = st.setdefault("search", {}).setdefault(self.label, {}).setdefault(src, {}).setdefault(qid, {})
            c.update(kw)
        update_state(self.proj, self.slug, fn)

    def seen_dois(self):
        with self.seen_lock:
            if self.seen is None:
                self.seen = set()
                for f in [*self.raw.glob("*.jsonl"), *self.raw.glob("*.jsonl.gz")]:
                    for line in open_text(f):
                        m = re.search(r'"doi": "([^"]+)"', line)
                        if m:
                            self.seen.add(m.group(1))
            return self.seen

    def emit(self, src, qid, recs):
        out = []
        for r in recs:
            r["source"], r["qid"] = src, qid
            r["doi"] = norm_doi(r.get("doi"))
            r["title"] = clean_text(r.get("title"))
            r["abstract"] = clean_text(r.get("abstract"))[:6000]
            if r["title"] or r["doi"]:
                out.append(r)
        jsonl_append(self.raw / f"{src}.jsonl", out)
        passed = sum(1 for r in out if self.gate.passes(r["title"], r["abstract"], r.get("journal")))
        new = 0
        sd = self.seen_dois()
        with self.seen_lock:
            for r in out:
                if r["doi"] and r["doi"] not in sd:
                    sd.add(r["doi"])
                    new += 1
        return len(out), passed, new

    def run_query(self, src, qid, query, primary):
        c = self.cursor(src, qid)
        if c.get("done"):
            return
        cur, pages, hits, passed = c.get("cursor"), c.get("pages", 0), c.get("hits", 0), c.get("passed", 0)
        low = c.get("low_streak", 0)
        total = c.get("total")
        fetch = FETCHERS[src]
        while True:
            try:
                recs, nxt, tot = fetch(query, cur, self.since, self.ctx)
            except HTTPFail as e:
                log(f"{src} {qid}: {e} — stopped here, re-run to resume")
                self.set_cursor(src, qid, cursor=cur, pages=pages, hits=hits, passed=passed, error=str(e)[:300])
                return
            if tot is not None:
                total = tot
            n, p, new = self.emit(src, qid, recs) if recs else (0, 0, 0)
            pages, hits, passed = pages + 1, hits + n, passed + p
            done = (not recs) or (nxt is None)
            why = None
            thr = self.stop_rules.get(src)
            if thr and recs and not done and not self.gate.empty:
                low = low + 1 if p / max(1, n) < thr else 0
                if low >= 2:
                    done, why = True, f"relevance tail (gate pass rate < {thr:.0%} twice)"
            # results come by relevance, so the first pages repeat what earlier queries found: only a long run of pages
            # with nothing new ends a query early (one such page used to stop it at its first 100 results)
            dup = c.get("dup_streak", 0) if pages > 1 else 0
            dup = dup + 1 if (recs and new == 0) else 0
            c["dup_streak"] = dup
            if src == "openalex" and not primary and dup >= DUP_PAGES and not done:
                done, why = True, f"{DUP_PAGES} pages in a row with every DOI already found by an earlier query"
            self.set_cursor(src, qid, cursor=nxt, pages=pages, hits=hits, passed=passed, total=total, low_streak=low,
                            dup_streak=dup, done=done, stopped_because=why, error=None)
            if pages % 10 == 0 or done:
                log(f"{src} {qid}: pages={pages} hits={hits} gate_pass={passed} total={total}"
                    + (f" DONE ({why})" if why else (" DONE" if done else "")))
            if done:
                return
            cur = nxt

    def run_source(self, src, queries):
        try:
            for i, (qid, q) in enumerate(queries.items()):
                if self.ctx.get("openalex_stop") and src == "openalex":
                    log("openalex: daily budget reserve reached — remaining queries resume after the reset")
                    return
                self.run_query(src, qid, q, primary=(i == 0))
        except Exception:
            log(f"{src}: CRASH\n{traceback.format_exc()}")


def count_only(runner, queries, skipped=None):
    """First page of every query. Strict databases: on-topic estimate = total x first-page topic-gate pass rate.
    Relevance-ranked databases (Crossref, Zenodo, DataCite ...): the total counts any-word matches, so only the first
    page's on-topic hits are reported, as a lower bound."""
    rows = []
    for src, qs in queries.items():
        for qid, q in qs.items():
            try:
                recs, nxt, tot = FETCHERS[src](q, None, runner.since, runner.ctx)
                ok = sum(1 for r in recs if runner.gate.passes(clean_text(r.get("title")), clean_text(r.get("abstract")),
                                                         r.get("journal")))
                rate = ok / len(recs) if recs else 0
                loose = src not in STRICT_SOURCES
                est = ok if loose else round((tot or 0) * rate)
                rows.append({"database": src, "qid": qid, "total": tot, "first_page": len(recs), "first_page_on_topic": ok,
                             "estimated_on_topic": est, "loose": loose})
            except HTTPFail as e:
                rows.append({"database": src, "qid": qid, "total": None, "error": str(e)[:200], "estimated_on_topic": 0})
            log(f"{src} {qid}: total={rows[-1].get('total')} on-topic~{rows[-1].get('estimated_on_topic')}")
    by_src = Counter()
    for r in rows:
        by_src[r["database"]] += r.get("estimated_on_topic") or 0
    out = {"count_only": True, "estimated_on_topic_per_database": dict(by_src), "skipped_databases": skipped or {},
           "estimated_on_topic_sum": sum(by_src.values()), "queries": rows,
           "note": "before deduplication (databases overlap ~30-60%); relevance-ranked databases (loose) are lower "
                   "bounds from page 1"}
    update_state(runner.proj, runner.slug, lambda st: st.update({"count_estimate": out, "count_estimate_at": now_iso()}))
    print(json.dumps(out))


def openalex_ids(runner, rows):
    """OpenAlex work ids of ledger rows (stored when OpenAlex found the source; else looked up by DOI)."""
    ids, need = {}, []
    for r in rows:
        w = (r.get("external_ids") or {}).get("openalex")
        if w:
            ids[r["id"]] = str(w).rsplit("/", 1)[-1]
        elif r.get("doi") and "|" not in r["doi"] and "," not in r["doi"]:
            need.append(r)
    base = {"select": "id,doi", "per_page": 50}
    if polite_email():
        base["mailto"] = polite_email()
    if runner.ctx["keys"].get("openalex"):
        base["api_key"] = runner.ctx["keys"]["openalex"]
    for i in range(0, len(need), 50):
        chunk = need[i:i + 50]
        try:
            resp = http_get("https://api.openalex.org/works", params=dict(base, filter="doi:" + "|".join(r["doi"] for r in chunk)),
                            tries=4, timeout=(20, 120))
        except HTTPFail as e:
            log(f"citations: OpenAlex id lookup stopped ({e})")
            break
        by_doi = {norm_doi(w.get("doi")): w.get("id", "").rsplit("/", 1)[-1] for w in resp.json().get("results") or []}
        for r in chunk:
            if by_doi.get(r["doi"]):
                ids[r["id"]] = by_doi[r["doi"]]
    return ids


def run_citations(runner, proj, slug, min_relevance=4, max_seeds=3000):
    """Forward citation chasing: works that cite the topic's core sources (relevance >= 4, or every in-scope source when
    the topic is not screened), newer than --since when given. Finds sources that use other words for the topic."""
    from _ledger import Ledger
    led = Ledger(proj)
    # the most cited core sources, chosen by SQLite (a topic may hold millions)
    cond = ("AND COALESCE(t.in_scope, 1) = 1 AND p.is_erratum = 0 AND p.doc_type NOT IN ('dataset', 'software', 'patent') ")
    order = " ORDER BY COALESCE(p.cited_by, 0) DESC, t.rowid LIMIT ?"
    core = led.topic_rows(slug, cond + "AND COALESCE(t.relevance, 0) >= ?" + order, (min_relevance, max_seeds)) or \
        led.topic_rows(slug, cond + order, (max_seeds,))
    ids = list(dict.fromkeys(openalex_ids(runner, core).values()))
    log(f"citations: {len(core)} core sources, {len(ids)} with OpenAlex ids")
    queries = {}
    for i in range(0, len(ids), 50):
        queries[f"cites-{i // 50 + 1:04d}"] = {"filter": "cites:" + "|".join(ids[i:i + 50])}
    runner.run_source("citations", queries)
    return len(core), len(queries)


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--databases", "--sources", dest="databases", default=None, help="comma list (default: config['databases'])")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD: only works published/registered on or after")
    ap.add_argument("--count-only", action="store_true")
    ap.add_argument("--citing", action="store_true", help="citation chasing from the topic's core sources (OpenAlex)")
    ap.add_argument("--year-from", type=int, default=None, help="index limited to works from this year on (default: "
                                                              "config search.year_from); the run stays a full index")
    ap.add_argument("--queries", default=None, help="a queries file of its own (default: .scripts/<topic>/queries.json)")
    ap.add_argument("--label", default=None, help="name of this run (raw/<label>/, its own state; build_list --run "
                                                  "<label> reads just it); default full / since-<date> / citing")
    a = ap.parse_args()
    proj = Project(a.project)
    cfg = load_config(proj, a.topic)
    since = iso_or_none(a.since)
    label = a.label or ((f"citing-since-{since}" if since else "citing") if a.citing else
                        (f"since-{since}" if since else "full"))
    year_from = a.year_from or (cfg.get("search") or {}).get("year_from")
    if year_from and not since:      # a year-limited index: each database's date filter, but still the full index run
        since = f"{int(year_from)}-01-01"
    runner = Runner(proj, a.topic, cfg, label, since)
    if a.citing:
        update_state(proj, a.topic, lambda s_: s_.setdefault("search_runs", {}).setdefault(label, {}).update(
            {"started_at": s_.get("search_runs", {}).get(label, {}).get("started_at") or now_iso(), "since": since}))
        n_core, n_q = run_citations(runner, proj, a.topic)
        st = ((load_state(proj, a.topic).get("search") or {}).get(label) or {}).get("citations") or {}
        pending = [q for q, c in st.items() if not c.get("done")]
        update_state(proj, a.topic, lambda s_: s_["search_runs"][label].update(
            {"finished_at": now_iso() if not pending else None, "pending": pending,
             "hits": {"citations": sum(c.get("hits", 0) for c in st.values())}}))
        print(json.dumps({"label": label, "core_sources": n_core, "queries": n_q,
                          "hits": sum(c.get("hits", 0) for c in st.values()), "pending_queries": pending,
                          "complete": not pending}))
        return
    wanted = [s for s in (a.databases.split(",") if a.databases else cfg.get("databases") or cfg.get("sources") or []) if s]
    databases, skipped = usable_databases(wanted, runner.ctx["keys"])
    for s_, why in skipped.items():
        log(f"{s_}: skipped — {why}")
    queries = load_queries(proj, a.topic, databases, a.queries)
    if not queries:
        die("no queries for the chosen databases")
    if a.count_only:
        return count_only(runner, queries, skipped)
    update_state(proj, a.topic, lambda st: st.setdefault("search_runs", {}).setdefault(label, {}).update(
        {"started_at": st.get("search_runs", {}).get(label, {}).get("started_at") or now_iso(), "since": since}))
    threads = [threading.Thread(target=runner.run_source, args=(s, q), name=s) for s, q in queries.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    st = (load_state(proj, a.topic).get("search") or {}).get(label) or {}
    pending = [f"{s}:{q}" for s, qs in st.items() for q, c in qs.items() if not c.get("done")]
    errors = {f"{s}:{q}": c.get("error") for s, qs in st.items() for q, c in qs.items() if c.get("error")}
    hits = {s: sum(c.get("hits", 0) for c in qs.values()) for s, qs in st.items()}

    def fin(s):
        r = s.setdefault("search_runs", {}).setdefault(label, {})
        r.update({"finished_at": now_iso() if not pending else None, "pending": pending, "hits": hits,
                  "skipped_databases": skipped})
    update_state(proj, a.topic, fin)
    print(json.dumps({"label": label, "hits_per_source": hits, "pending_queries": pending, "errors": errors,
                      "skipped_databases": skipped, "complete": not pending}))


if __name__ == "__main__":
    main()
