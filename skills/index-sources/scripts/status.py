"""Progress and the download plan for a topic (read-only). Use it at the index -> download gate and any time.

  python3 -I status.py --topic <slug>          # human-readable table
  python3 -I status.py --topic <slug> --json   # same numbers as JSON

Shows: sources identified, screening result, and a table of Access type x (in scope / downloaded / to download /
out of scope); document types, main topics (Topic A), missing abstracts, databases and years; databases skipped for want of
a key; and an estimate for what is left to download — open routes in hours and GB, paywalled sources in DAYS at the
EZproxy limits (<= 120 per publisher per day, <= 600 per day overall).
"""
import argparse
import datetime as _dt
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ACCESS_TYPES, DATABASE_LABEL, Project, add_project_arg, json_read, load_config, load_state
from _download import NOT_PROXYABLE, ez_publisher
from _ledger import Ledger
from _topics import Vocab

MB_PER_PDF = 3.5          # median article PDF ~2-4 MB; reviews and SI-heavy sources run larger
OPEN_PER_HOUR = 600       # open routes with 10 workers and per-host pacing (observed 400-900/h)
PER_PUB_DAY, GLOBAL_DAY = 120, 600  # EZproxy caps (see _ezlimit.py)
COLS = ("p.id, p.access_type, p.is_erratum, t.in_scope, t.relevance, p.doc_type, LENGTH(COALESCE(p.abstract, '')), "
        "p.downloaded, p.dl_status, p.doi, p.databases, p.year, p.retracted")


def scan(led, slug, chunk=50000):
    """The few columns status needs, 50,000 sources at a time (a topic may hold millions)."""
    last = 0
    while True:
        rows = led.q(f"SELECT {COLS} FROM source_topics t CROSS JOIN sources p ON p.id = t.source_id "
                     "WHERE +t.topic=? AND t.source_id > ? ORDER BY t.source_id LIMIT ?", (slug, last, chunk))
        if not rows:
            return
        last = rows[-1][0]
        yield from rows


def summarize(proj, slug):
    cfg = load_config(proj, slug)
    st = load_state(proj, slug)
    led = Ledger(proj)
    sel = set((cfg.get("download") or {}).get("access_types") or [])
    ez = json_read(proj.ezg / "config.json", {}) or {}
    tab = {a: Counter() for a in ACCESS_TYPES + ["Unclassified"]}
    pubs = Counter()
    src, yrs, dts = Counter(), Counter(), Counter()
    no_abs, n_rows, scr = 0, 0, Counter()
    for pid, acc, is_err, in_scope, relevance, doc_type, abs_len, downloaded, dl_status, doi, dbs, year, retracted \
            in scan(led, slug):
        n_rows += 1
        scr["screened"] += relevance is not None
        if is_err:
            scr["notices"] += 1
        elif in_scope == 1:
            scr["retracted" if retracted else "in_scope"] += 1
        elif in_scope == 0:
            scr["out_of_scope"] += 1
        elif in_scope is None:
            scr["unscreened"] += 1
        acc = acc or "Unclassified"
        c = tab[acc]
        c["identified"] += 1
        if is_err:
            c["errata"] += 1
            continue
        if in_scope == 0:
            c["out_of_scope"] += 1
            continue
        c["in_scope"] += 1
        dts[doc_type or "unknown"] += 1
        no_abs += (abs_len or 0) < 80
        if (doc_type or "") in ("dataset", "software"):
            c["index_only"] += 1
        elif downloaded:
            c["downloaded"] += 1
        elif acc not in sel:
            c["not_selected"] += 1
        elif dl_status in ("failed", "no_route", "duplicate"):
            c["no_copy_found"] += 1
        elif dl_status == "queued_paywalled":
            c["queued_ezproxy"] += 1
            pubs[ez_publisher(doi) or "unsupported"] += 1
        else:
            c["to_download"] += 1
            if acc == "Paywalled":
                pubs[ez_publisher(doi) or ("elsevier" if (doi or "").split("/")[0] in NOT_PROXYABLE
                                           else "unsupported")] += 1
        try:
            dbs = json.loads(dbs) if isinstance(dbs, str) else (dbs or [])
        except ValueError:
            dbs = []
        for d in dbs or []:
            src[d] += 1
        if year:
            yrs[int(year)] += 1
    open_left = sum(tab[a]["to_download"] for a in ("OA", "OA+ND", "Free-to-read") if a in sel)
    pw_ok = sum(v for k, v in pubs.items() if k not in ("elsevier", "unsupported"))
    pw_days = max([math.ceil(v / PER_PUB_DAY) for k, v in pubs.items() if k not in ("elsevier", "unsupported")]
                  + [math.ceil(pw_ok / GLOBAL_DAY)] + [0])
    vocab = Vocab(proj)
    topa = Counter()
    for term, n in led.q("SELECT s.term, COUNT(*) FROM source_subjects s JOIN source_topics t ON t.source_id = s.source_id "
                         "AND t.topic = ? JOIN sources p ON p.id = s.source_id WHERE s.kind = 'main' AND s.rank = 1 "
                         "AND (t.in_scope IS NULL OR t.in_scope != 0) AND NOT COALESCE(p.is_erratum, 0) "
                         "GROUP BY s.term ORDER BY 2 DESC, 1", (slug,)):
        topa[vocab.label(term)] += n
    last = max((v for k, v in (st.get("search_runs") or {}).items()), key=lambda v: v.get("started_at") or "", default={})
    out = {
        "topic": cfg.get("topic"), "slug": slug,
        "identified": n_rows,
        "searches": {k: sum((v.get("hits") or {}).values()) for k, v in (st.get("search_runs") or {}).items()},
        "search": {k: v for k, v in ((st.get("build_list_runs") or {}).get("all") or st.get("build_list") or {}).items() if k in (
            "raw_records", "off_topic_dropped_by_gate", "si_deposits_set_aside", "unique_sources", "new_in_ledger",
            "already_in_ledger", "preprint_links", "errata_or_corrections")},
        "screening": {"method": (cfg.get("screening") or {}).get("method"), "threshold": (cfg.get("screening") or {}).get("threshold", 3),
                      "screened": scr["screened"],
                      # a partition of the identified sources: in scope + retracted + out of scope + not screened + notices
                      "in_scope": scr["in_scope"], "retracted": scr["retracted"], "out_of_scope": scr["out_of_scope"],
                      "unscreened": scr["unscreened"], "notices": scr["notices"]},
        "selected_access_types": sorted(sel, key=lambda a: ACCESS_TYPES.index(a) if a in ACCESS_TYPES else 9),
        "table": {a: dict(c) for a, c in tab.items() if c},
        "estimate": {"open_sources_left": open_left, "open_hours": round(open_left / OPEN_PER_HOUR, 1),
                     "open_gb": round(open_left * MB_PER_PDF / 1024, 1),
                     "paywalled_sources_left": sum(pubs.values()), "paywalled_by_publisher": dict(pubs.most_common()),
                     "paywalled_days_at_limits": pw_days,
                     "paywalled_not_obtainable": pubs.get("elsevier", 0) + pubs.get("unsupported", 0),
                     "paywalled_access_verified": bool(ez.get("enabled") and ez.get("verified_at"))},
        "databases": {DATABASE_LABEL.get(k, k): v for k, v in src.most_common()},
        "doc_types": dict(dts.most_common()), "topic_a": dict(topa.most_common(10)),
        "missing_abstracts": no_abs, "skipped_databases_last_search": last.get("skipped_databases") or last.get("skipped_sources") or {},
        "years": {"min": min(yrs) if yrs else None, "max": max(yrs) if yrs else None,
                  "last_5_years": sum(v for y, v in yrs.items() if y >= _dt.date.today().year - 4)},
        "database": proj.rel(proj.db), "collection": slug,
        "index_csv": proj.rel(proj.index_dir(slug)) if (proj.index_dir(slug) / "merged.csv").exists() else
        f"on request: export.py --topic {slug} --csv",
    }
    return out


def show(s):
    print(f"Topic: {s['slug']} — {s['topic']}")
    b = s["search"]
    if s.get("searches"):
        print("Searches: " + ", ".join(f"{k} {v} raw hits" for k, v in s["searches"].items()))
    if b:
        print(f"Identified {s['identified']} sources  (last list build: {b.get('raw_records', '?')} raw hits, "
              f"{b.get('off_topic_dropped_by_gate', '?')} dropped by the topic filter, duplicates and preprint links merged)")
    sc = s["screening"]
    print(f"Screening ({sc['method']}, keep score >= {sc['threshold']}): in scope {sc['in_scope']}, "
          f"out of scope {sc['out_of_scope']}, not screened {sc['unscreened']}, notices {sc['notices']}"
          + (f", retracted {sc['retracted']}" if sc["retracted"] else ""))
    cols = ["identified", "errata", "out_of_scope", "in_scope", "downloaded", "to_download", "queued_ezproxy",
            "no_copy_found", "not_selected", "index_only"]
    heads = ["identified", "notices", "out of scope", "in scope", "downloaded", "to download", "EZproxy queue",
             "no copy found", "not selected", "index only"]
    print(f"\n{'Access type':15}" + "".join(f"{h:>14}" for h in heads))
    for a, c in s["table"].items():
        mark = " *" if a in s["selected_access_types"] else "  "
        print(f"{a + mark:15}" + "".join(f"{c.get(k, 0):>14}" for k in cols))
    print("(* = selected for download; identified = notices + out of scope + in scope; notices = errata, "
          "corrections, cover art; 'no copy found' = no reachable open copy — reason in the index Notes; "
          "'index only' = datasets/software)")
    e = s["estimate"]
    print(f"\nLeft to download: {e['open_sources_left']} open sources ≈ {e['open_gb']} GB, ~{e['open_hours']} h")
    if e["paywalled_sources_left"]:
        print(f"Paywalled: {e['paywalled_sources_left']} sources -> ≈ {e['paywalled_days_at_limits']} days at the EZproxy "
              f"limits; by publisher {e['paywalled_by_publisher']}; access verified: {e['paywalled_access_verified']}")
    print("Databases: " + ", ".join(f"{k} {v}" for k, v in list(s["databases"].items())[:12]))
    if s["skipped_databases_last_search"]:
        print("Skipped (no key): " + ", ".join(s["skipped_databases_last_search"]))
    print("Document types: " + ", ".join(f"{k} {v}" for k, v in s["doc_types"].items()))
    print("Topic A: " + ", ".join(f"{k} {v}" for k, v in s["topic_a"].items()))
    print(f"In-scope sources without an abstract: {s['missing_abstracts']}")
    y = s["years"]
    print(f"Years: {y['min']}–{y['max']} ({y['last_5_years']} in the last 5 years)")
    print(f"Database: {s['database']} (collection {s['collection']})  ·  Index CSVs: {s['index_csv']}")


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    s = summarize(Project(a.project), a.topic)
    print(json.dumps(s, indent=1)) if a.json else show(s)


if __name__ == "__main__":
    main()
