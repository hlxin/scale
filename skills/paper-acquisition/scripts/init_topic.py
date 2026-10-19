"""Create (or update) a topic, look at the topics a project already has, or validate a topic's plan.

  python3 -I init_topic.py --list                         # every topic in this project with its counts and dates
  python3 -I init_topic.py --slug mxene-her --probe       # does the topic exist? what has been done? (changes nothing)
  python3 -I init_topic.py --topic "MXene catalysts for HER" --email you@uni.edu \
          --access OA,OA+ND,Free-to-read --screening claude [--slug mxene-her] [--sources openalex,crossref,...]
          [--base-url https://llm.example.edu/api/v1 --model gpt-oss-120b] [--threshold 3]
  python3 -I init_topic.py --slug mxene-her --check       # validate config.json, queries.json, gate, criteria/keywords

Creates publications/<slug>/index/ and publications/<slug>/papers/{OA,OA+ND,Free-to-read,Paywalled}/ (SI folders appear
when the first SI file is saved), and .scripts/<slug>/{raw,screen}/. Re-running with new flags updates the existing
config (nothing is deleted). Default sources: every keyless source in the catalog plus the key sources whose keys are in
keys.txt. The check prints {"ok": true} or every problem found with how to fix it.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (ACCESS_TYPES, KEY_FILES_HELP, Project, add_project_arg, json_read, load_keys, now_iso, save_config,
                     slugify)
from _sources import CATALOG, FETCHERS, default_sources, keys_needed
METHODS = ["claude", "api", "keywords", "none"]


def check(proj, slug):
    errs, warns = [], []
    td = proj.topic_dir(slug)
    cfg = json_read(td / "config.json")
    if not cfg:
        return [f"no .scripts/{slug}/config.json — run init_topic.py --topic ... first"], []
    if not cfg.get("topic"):
        errs.append("config.topic is empty")
    if not cfg.get("polite_email"):
        warns.append("config.polite_email missing: Unpaywall lookups are skipped and other APIs throttle harder")
    srcs = cfg.get("sources") or []
    bad = [s for s in srcs if s not in FETCHERS]
    if bad:
        errs.append(f"config.sources has unknown entries {bad}; valid: {sorted(FETCHERS)}")
    keys = load_keys(proj)
    nokey = [s for s in srcs if any(not keys.get(k) for k in keys_needed(s))]
    if nokey:
        warns.append(f"sources waiting for a key (skipped until it is added to {KEY_FILES_HELP}): {nokey}")
    missing_default = [s for s in default_sources(keys) if s not in srcs]
    if missing_default:
        warns.append(f"sources available but not in this topic's plan (add them with a query each for a more complete "
                     f"index): {missing_default}")
    if "openalex" in srcs and not keys.get("openalex"):
        warns.append("no OpenAlex key: OpenAlex then uses a small daily budget shared by everyone on your network and "
                     "can stop mid-run. A key is free (README.md, 'API keys')")
    acc = (cfg.get("download") or {}).get("access_types") or []
    if not acc or any(a not in ACCESS_TYPES for a in acc):
        errs.append(f"config.download.access_types must be a non-empty subset of {ACCESS_TYPES} (got {acc})")
    sc = cfg.get("screening") or {}
    if sc.get("method") not in METHODS:
        errs.append(f"config.screening.method must be one of {METHODS}")
    if sc.get("method") == "api" and not (sc.get("base_url") and sc.get("model")):
        errs.append("api screening needs config.screening.base_url and .model")
    if sc.get("method") in ("claude", "api") and not (td / "criteria.md").exists():
        errs.append(f"missing .scripts/{slug}/criteria.md (topic definition + in-scope / out-of-scope lists)")
    if sc.get("method") == "keywords":
        kw = json_read(td / "keywords.json")
        if not kw or not kw.get("include_groups"):
            errs.append(f"missing or empty .scripts/{slug}/keywords.json include_groups")
        else:
            for t in [t for g in kw["include_groups"] for t in g] + (kw.get("exclude") or []):
                if str(t).startswith("re:"):
                    try:
                        re.compile(t[3:])
                    except re.error as e:
                        errs.append(f"keywords.json bad regex {t!r}: {e}")
    g = cfg.get("gate") or {}
    if not (g.get("any") or g.get("all_groups")):
        warns.append("config.gate is empty: every search hit is kept (loose sources such as Crossref and OSTI then "
                     "flood the list with off-topic papers)")
    for t in (g.get("any") or []) + [t for grp in g.get("all_groups") or [] for t in grp] + (g.get("title_only") or []):
        if str(t).startswith("re:"):
            try:
                re.compile(t[3:])
            except re.error as e:
                errs.append(f"gate bad regex {t!r}: {e}")
    qs = json_read(td / "queries.json")
    if not qs:
        errs.append(f"missing .scripts/{slug}/queries.json (per-source queries; references/queries.md)")
    else:
        for s in qs:
            if s not in FETCHERS:
                errs.append(f"queries.json: unknown source {s!r}")
        for s in srcs:
            q = qs.get(s)
            if not q:
                warns.append(f"queries.json has no queries for source {s!r} (it will be skipped)")
                continue
            if not isinstance(q, dict):
                errs.append(f"queries.json[{s!r}] must be an object {{query_id: query}}")
                continue
            for qid, v in q.items():
                text = v.get("q") or v.get("filter") if isinstance(v, dict) else v
                if not text or not str(text).strip():
                    errs.append(f"queries.json[{s!r}][{qid!r}] is empty")
                elif s == "openalex" and ":" not in str(text):
                    errs.append(f"queries.json['openalex'][{qid!r}] must be a filter, e.g. "
                                f"title_and_abstract.search:\"your phrase\" (got {text!r})")
        n = sum(len(v) for v in qs.values() if isinstance(v, dict))
        if n < 8:
            warns.append(f"only {n} queries in total; 15-25 distinct queries find far more of the field")
    return errs, warns


def probe(proj, slug):
    """What exists for a topic — used to ask the user: download / update / new index / status."""
    from _publish import run_dates
    td = proj.topic_dir(slug)
    cfg = json_read(td / "config.json")
    if not cfg:
        return {"slug": slug, "exists": False}
    st = json_read(td / "state.json", {}) or {}
    li, lu = run_dates(st)
    out = {"slug": slug, "exists": True, "topic": cfg.get("topic"), "created_at": cfg.get("created_at"),
           "last_full_index": li, "last_update": lu, "screening": (cfg.get("screening") or {}).get("method"),
           "download_access_types": (cfg.get("download") or {}).get("access_types"),
           "database": proj.rel(proj.db), "papers_folder": proj.rel(proj.pub / slug / "papers"),
           "index_csv": proj.rel(proj.index_dir(slug)) if (proj.index_dir(slug) / "merged.csv").exists() else None}
    if proj.ledger_db.exists():
        import sqlite3
        con = sqlite3.connect(f"file:{proj.ledger_db}?mode=ro", uri=True)
        try:
            # same definitions as status.py: non-papers (errata, corrections) and retracted papers are never in scope
            r = con.execute("SELECT COUNT(*), SUM(t.in_scope=1 AND p.is_erratum=0 AND COALESCE(p.retracted,0)=0), "
                            "SUM(t.in_scope=0 AND p.is_erratum=0), SUM(t.in_scope IS NULL AND p.is_erratum=0), "
                            "SUM(t.path IS NOT NULL), SUM(p.is_erratum=1) FROM paper_topics t JOIN papers p ON p.id=t.paper_id "
                            "WHERE t.topic=?", (slug,)).fetchone()
            out.update({"papers": r[0], "in_scope": r[1] or 0, "out_of_scope": r[2] or 0, "unscreened": r[3] or 0,
                        "downloaded": r[4] or 0, "non_papers": r[5] or 0})
        except sqlite3.Error:
            pass
    return out


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", default=None, help="topic as the user said it")
    ap.add_argument("--slug", default=None)
    ap.add_argument("--email", default=None, help="polite-pool contact email for scholarly APIs")
    ap.add_argument("--access", default=None, help="comma list of access types to DOWNLOAD (all are always listed)")
    ap.add_argument("--screening", choices=METHODS, default=None)
    ap.add_argument("--threshold", type=int, default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--sources", default=None)
    ap.add_argument("--year-from", type=int, default=None, help="index only works published in or after this year")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--probe", action="store_true", help="report whether the topic exists and what was done (no changes)")
    ap.add_argument("--list", action="store_true", help="list this project's topics")
    a = ap.parse_args()
    proj = Project(a.project)
    if a.list:
        print(json.dumps({"topics": [probe(proj, t) for t in proj.topics()]}, indent=1))
        return 0
    slug = a.slug or (slugify(a.topic) if a.topic else None)
    if not slug:
        print(json.dumps({"error": "give --topic (new topic) or --slug (existing topic)"}))
        return 2
    if a.probe:
        print(json.dumps(probe(proj, slug), indent=1))
        return 0
    if a.check:
        errs, warns = check(proj, slug)
        print(json.dumps({"ok": not errs, "errors": errs, "warnings": warns}, indent=1))
        return 0 if not errs else 1
    td = proj.make_topic_folders(slug)
    cfg = json_read(td / "config.json", {}) or {}
    cfg.setdefault("created_at", now_iso())
    cfg["slug"] = slug
    if a.topic:
        cfg["topic"] = a.topic
    if a.email:
        cfg["polite_email"] = a.email
    cfg.setdefault("sources", default_sources(load_keys(proj)))
    if a.sources:
        cfg["sources"] = [s for s in a.sources.split(",") if s]
    cfg.setdefault("gate", {})
    sc = cfg.setdefault("screening", {"method": "claude", "threshold": 3})
    if a.screening:
        sc["method"] = a.screening
    if a.threshold is not None:
        sc["threshold"] = a.threshold
    if a.base_url:
        sc["base_url"] = a.base_url
    if a.model:
        sc["model"] = a.model
    if a.year_from:
        cfg.setdefault("search", {})["year_from"] = a.year_from
    dl = cfg.setdefault("download", {"access_types": ["OA", "OA+ND", "Free-to-read"]})
    if a.access:
        dl["access_types"] = [x.strip() for x in a.access.split(",") if x.strip()]
    save_config(proj, slug, cfg)
    need = ["queries.json"] + (["criteria.md"] if sc["method"] in ("claude", "api") else []) + \
        (["keywords.json"] if sc["method"] == "keywords" else [])
    print(json.dumps({"slug": slug, "config": proj.rel(td / "config.json"),
                      "publications": proj.rel(proj.pub / slug), "write_next": [proj.rel(td / f) for f in need],
                      "then_run": f"init_topic.py --slug {slug} --check"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
