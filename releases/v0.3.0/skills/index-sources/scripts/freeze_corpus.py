"""Freeze a topic's corpus for curation: a corpus manifest (sources.json) in which every candidate of the topic's
index has a status — included, or the reason it is left out — and the counts add up.

  python3 -I freeze_corpus.py --topic <slug> [--name <corpus name>] [--min-relevance 4] [--subject "CO2RR,MOFs"]
         [--doc-types article,review,preprint] [--years 2015-2026] [--access OA,OA+ND] [--ids FILE] [--out FILE]

The manifest is the one SCALE's curate-corpus skill asks for before the first source is curated (its step 1), and
`scale corpus check <manifest>` checks it; curate-corpus curates its included sources. The candidates are every source
of the topic (one row per work after deduplication). Statuses:

  in_scope        in scope and kept by the rule given here: the sources to fetch (fetch-corpus) and curate
  not_retrieved   set by fetch-corpus (settle_corpus.py), not here: included, but no file could be fetched (status_reason)
  off_scope       screened out of scope (status_reason: the screening note), or below --min-relevance
  not_screened    never screened
  retracted       a retraction is recorded for it
  excluded        status_reason says why: an erratum or notice, a dataset or software record (indexed, never
                  downloaded), or left out by the rule (--doc-types, --years, --access, --subject, --ids)

Each entry: slug (the DOI with / as -, lowercased, as `scale source start --doi` names the source; else the source
ID), status, status_reason, source_id, doi, title, year, doc_type, access_type, licence, licence_url, relevance, and
for a source whose file is on disk text_version (of the copy downloaded), pdf and si (paths relative to the manifest's
folder). Writes sources/<slug>/corpora/<name>/sources.json (default name: <slug>-<date>) and never overwrites a
manifest: a corpus is frozen once, so a new rule gets a new name. Which sources it holds never changes after; fetching
them (fetch-corpus) adds their files and marks those it could not get not_retrieved (settle_corpus.py).
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Project, add_project_arg, die, load_config, load_state, log, today  # noqa: E402
from _ledger import Ledger  # noqa: E402
from _publish import run_dates  # noqa: E402
from _topics import Vocab  # noqa: E402

INCLUDED = "in_scope"
NO_REASON = ("excluded", "out", "rejected")          # statuses that need a status_reason (as scale corpus check)
TEXT_VERSIONS = {"publishedVersion": "version_of_record", "acceptedVersion": "accepted_manuscript",
                 "submittedVersion": "submitted_manuscript"}
NOT_RETRIEVED = {"queued_paywalled": "queued for the library EZproxy", "failed": "no copy found",
                 "no_route": "no copy found (no open or proxied route)", "duplicate": "no copy found (duplicate file)"}


def slug_of(doi, pid):
    """The source's slug as `scale source start` makes it: the DOI lowercased with / as -; else the source ID."""
    return doi.strip().lower().replace("/", "-") if doi else str(pid)


def years(text):
    if not text:
        return None
    a, _, b = str(text).partition("-")
    return int(a), int(b or a)


def csv_set(text):
    return {x.strip() for x in (text or "").split(",") if x.strip()}


def rule_text(a):
    parts = ["in scope"]
    if a.min_relevance is not None:
        parts.append(f"relevance >= {a.min_relevance}")
    if a.subject:
        parts.append(f"Topic A/B/C among {a.subject}")
    if a.doc_types:
        parts.append(f"document types {a.doc_types}")
    if a.years:
        parts.append(f"published {a.years}")
    if a.access:
        parts.append(f"access types {a.access}")
    if a.ids:
        parts.append(f"source IDs listed in {Path(a.ids).name}")
    return ", ".join(parts)


def status_of(p, a, wanted, proj, subjects):
    """(status, status_reason) of one source of the topic."""
    doc_type = p.get("doc_type") or ""
    if p.get("is_erratum"):
        return "excluded", "an erratum, correction or other notice (indexed, never curated on its own)"
    if p.get("retracted"):
        return "retracted", "a retraction is recorded for it in the index"
    if p.get("t_in_scope") == 0:
        return "off_scope", p.get("t_relevance_note") or "screened out of scope"
    if p.get("t_in_scope") is None:
        return "not_screened", "never screened for relevance"
    if doc_type in ("dataset", "software"):
        return "excluded", f"a {doc_type} record: indexed, never downloaded (a data file is curated with curate-corpus, as a data file)"
    rel = p.get("t_relevance")
    if a.min_relevance is not None and (rel is None or rel < a.min_relevance):
        return "off_scope", f"relevance {rel if rel is not None else 'not scored'} below the rule's {a.min_relevance}"
    if wanted["doc_types"] and doc_type not in wanted["doc_types"]:
        return "excluded", f"left out by the rule: document type {doc_type or 'unknown'}"
    if wanted["years"] and not (p.get("year") and wanted["years"][0] <= int(p["year"]) <= wanted["years"][1]):
        return "excluded", f"left out by the rule: published {p.get('year') or 'year unknown'}"
    if wanted["access"] and (p.get("access_type") or "") not in wanted["access"]:
        return "excluded", f"left out by the rule: access type {p.get('access_type') or 'unclassified'}"
    if wanted["ids"] is not None and p["id"] not in wanted["ids"]:
        return "excluded", "left out by the rule: not in the ID list"
    if wanted["subjects"] and not (subjects(p["id"]) & wanted["subjects"]):
        return "excluded", "left out by the rule: none of the subjects among its Topic A/B/C"
    return INCLUDED, None


def check(manifest):
    """The rules of `scale corpus check`: every candidate named once with a status, a bare exclusion has its reason,
    the counts add up and at least one source is included."""
    problems, seen, counts = [], Counter(), Counter()
    for s in manifest["sources"]:
        seen[s["slug"]] += 1
        counts[s["status"]] += 1
        if s["status"] in NO_REASON and not s.get("status_reason"):
            problems.append(f"{s['slug']}: status {s['status']} gives no status_reason")
    problems += [f"{n}: listed {k} times" for n, k in seen.items() if k > 1]
    if dict(counts) != manifest["counts"]:
        problems.append("counts do not add up to the sources listed")
    if not counts.get(INCLUDED):
        problems.append("no source is included: loosen the rule")
    return problems


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True, help="topic slug")
    ap.add_argument("--name", help="corpus name (default: <slug>-<today>)")
    ap.add_argument("--min-relevance", type=int, default=None, help="keep sources scored at least this (1-5)")
    ap.add_argument("--subject", default=None, help="comma list of Topic A/B/C labels; keep sources with any of them")
    ap.add_argument("--doc-types", default=None, help="comma list, e.g. article,review,preprint")
    ap.add_argument("--years", default=None, help="e.g. 2015-2026")
    ap.add_argument("--access", default=None, help="comma list of access types, e.g. OA,OA+ND")
    ap.add_argument("--ids", default=None, help="a file with one source ID per line: only these are included")
    ap.add_argument("--out", default=None, help="manifest path (default: sources/<slug>/corpora/<name>/sources.json)")
    a = ap.parse_args()
    proj = Project(a.project)
    slug = a.topic
    cfg = load_config(proj, slug)
    name = a.name or f"{slug}-{today()}"
    out = Path(a.out) if a.out else proj.pub / slug / "corpora" / name / "sources.json"
    if out.exists():
        die(f"{proj.rel(out)} exists: a corpus is frozen once; give another --name")
    wanted = {"doc_types": csv_set(a.doc_types), "years": years(a.years), "access": csv_set(a.access),
              "subjects": {Vocab(proj).resolve(x) or x for x in csv_set(a.subject)},
              "ids": {int(x) for x in Path(a.ids).read_text().split() if x.strip().isdigit()} if a.ids else None}
    led = Ledger(proj)

    def subjects(pid):
        return {s["term"] for s in led.subjects_of(pid) if s.get("kind") == "main"}

    base = out.parent
    sources, counts = [], Counter()
    for block in led.iter_topic(slug):
        for p in block:
            status, reason = status_of(p, a, wanted, proj, subjects)
            e = {"slug": slug_of(p.get("doi"), p["id"]), "status": status, "source_id": p["id"], "doi": p.get("doi"),
                 "title": p.get("title"), "year": p.get("year"), "doc_type": p.get("doc_type"),
                 "access_type": p.get("access_type"), "licence": p.get("license"), "licence_url": p.get("license_url"),
                 "relevance": p.get("t_relevance")}
            if reason:
                e["status_reason"] = reason
            if p.get("downloaded") and p.get("t_path") and (proj.root / p["t_path"]).is_file():
                e["pdf"] = os.path.relpath(proj.root / p["t_path"], base)
                e["text_version"] = TEXT_VERSIONS.get(p.get("version") or "")
                si = p.get("t_si_paths") or []
                si = json.loads(si) if isinstance(si, str) else si
                e["si"] = [os.path.relpath(proj.root / s, base) for s in si if (proj.root / s).is_file()]
            sources.append({k: v for k, v in e.items() if v not in (None, "", [])})
            counts[status] += 1
    seen = Counter()
    for s in sources:                       # two works whose DOIs differ only in case: keep both, named apart
        seen[s["slug"]] += 1
        if seen[s["slug"]] > 1:
            s["slug"] = f"{s['slug']}-p{s['source_id']}"
    st = load_state(proj, slug)
    last_index, last_update = run_dates(st)
    built = sorted((r or {}).get("built_at") or "" for r in (st.get("build_list_runs") or {}).values())
    indexed = last_update or last_index or (built[-1] if built and built[-1] else None)   # an imported list: its build
    manifest = {
        "corpus": f"{cfg.get('topic') or slug} (index-sources topic {slug}): every paper, preprint, patent and "
                  f"dataset of the topic's index, one entry per work after deduplication; {len(sources)} candidates.",
        "cutoff": {"date": (indexed or today())[:10],
                   "rule": f"indexed by {(indexed or today())[:10]} from index-sources' sources; included: "
                           f"{rule_text(a)}"},
        "frozen_at": today(), "topic": slug, "included_status": INCLUDED,
        "built_by": "index-sources freeze_corpus.py", "counts": dict(sorted(counts.items())), "sources": sources}
    problems = check(manifest)
    if problems:
        die("the manifest would not pass scale corpus check: " + "; ".join(problems[:5]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    log(f"froze {proj.rel(out)}: {counts[INCLUDED]} of {len(sources)} candidates included")
    print(json.dumps({"manifest": proj.rel(out), "candidates": len(sources), "included": counts[INCLUDED],
                      "counts": dict(sorted(counts.items())),
                      "next": f"fetch-corpus: download_open.py --corpus {proj.rel(out)} (and fetch_si.py), then "
                              f"settle_corpus.py --corpus {proj.rel(out)}; then curate-corpus"}))


if __name__ == "__main__":
    main()
