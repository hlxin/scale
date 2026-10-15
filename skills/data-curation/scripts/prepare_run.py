"""Phase 1 — set up a curation run: check the GIVEN schema, freeze a copy, and pick the topic's papers from the index
that paper-acquisition built (publications/papers.db, or publications/<topic>/index/merged.csv).

  python3 -I prepare_run.py --topic co2rr --schema my_schema.json [--name co2rr-catalysts] \
          [--min-relevance 3] [--subject "CO2RR,Copper catalysts"] [--doc-types article,preprint] \
          [--access OA,OA+ND,Free-to-read,Paywalled] [--year 2015-2026] [--ids 12,57] [--max 200] \
          [--no-figures] [--no-reviewer] [--no-abstracts] [--replace-schema]
  python3 -I prepare_run.py --topic co2rr --name co2rr-catalysts --status
  python3 -I prepare_run.py --list-topics       # indexed topics (papers, in scope, downloaded) and existing graphs

Default paper selection: in scope (or not screened) for the topic, downloaded (a PDF on disk), document type
article / preprint / conference-paper / thesis / report (reviews hold other papers' values; add them with
--doc-types when the schema wants them). Writes .scripts/<topic>/kg/<name>/worklist.jsonl and state.json, and
publications/<topic>/kg/<name>/schema.json. Papers already extracted are kept (the run resumes).
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _kgcommon import Run, add_root_arg, now_iso, read_json, slug, topic_papers, write_json
from check_schema import check

DEFAULT_DOC_TYPES = ["article", "preprint", "conference-paper", "thesis", "report", "letter"]


def summary(run, papers=None):
    papers = papers if papers is not None else run.papers()
    st = run.statuses()
    c = {"selected": len(papers), "with_pdf": sum(1 for p in papers.values() if p.get("pdf")),
         "fragments": len(list(run.frag.glob("paper_*.json"))), "reviews": len(list(run.reviews.glob("paper_*.json")))}
    for k in ("extracted", "rejected", "failed", "no_data"):
        c[k] = sum(1 for p in st.values() if p.get("status") == k and int(p["paper_id"]) in papers)
    c["remaining"] = sum(1 for pid, p in papers.items() if p.get("pdf") and pid not in st)
    return c


def main():
    ap = add_root_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic")
    ap.add_argument("--list-topics", action="store_true")
    ap.add_argument("--schema", type=Path)
    ap.add_argument("--name")
    ap.add_argument("--min-relevance", type=int, default=None)
    ap.add_argument("--subject", default=None, help="Topic A/B/C labels (comma = any)")
    ap.add_argument("--doc-types", default=",".join(DEFAULT_DOC_TYPES))
    ap.add_argument("--access", default=None)
    ap.add_argument("--year", default=None)
    ap.add_argument("--ids", default=None)
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--no-reviewer", action="store_true")
    ap.add_argument("--no-abstracts", action="store_true")
    ap.add_argument("--replace-schema", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.list_topics:
        import sqlite3
        root = Path(a.project or ".").resolve()
        db = root / "publications" / "papers.db"
        out = []
        if db.exists():
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for slug_, topic, n, ins, dl in con.execute("SELECT slug, topic, papers, in_scope, downloaded FROM collections"):
                graphs = sorted(p.parent.name for p in (root / "publications" / slug_ / "kg").glob("*/schema.json"))
                out.append({"topic": slug_, "description": topic, "papers": n, "in_scope": ins, "downloaded": dl,
                            "graphs": graphs})
        print(json.dumps({"topics": out, "index": str(db) if db.exists() else None}, indent=1))
        return 0
    if not a.topic:
        print(json.dumps({"error": "give --topic (or --list-topics)"}))
        return 2

    if a.status:
        if not a.name:
            print(json.dumps({"error": "--status needs --name"}))
            return 2
        run = Run(a.project, a.topic, a.name)
        st = run.state()
        print(json.dumps({"topic": a.topic, "name": a.name, "phase": st.get("phase"), "counts": summary(run),
                          "next": st.get("next"), "deliverables": run.rel(run.out)}, indent=1))
        return 0
    if not a.schema or not a.schema.exists():
        print(json.dumps({"error": "give --schema <path to the user's schema.json>"}))
        return 2
    schema = json.loads(a.schema.read_text(encoding="utf-8-sig"))
    errs, warns, summ = check(schema)
    if errs:
        print(json.dumps({"ok": False, "schema_errors": errs, "warnings": warns}, indent=1))
        return 1
    name = slug(a.name or schema.get("name") or a.schema.stem)
    run = Run(a.project, a.topic, name).ensure()
    version = str(schema.get("version") or "1")
    digest = hashlib.sha1(json.dumps(schema, sort_keys=True).encode()).hexdigest()[:10]
    old = read_json(run.schema)
    if old is not None and json.dumps(old, sort_keys=True) != json.dumps(schema, sort_keys=True):
        if not a.replace_schema:
            print(json.dumps({"ok": False, "error": f"{run.rel(run.schema)} holds a different schema. A changed schema "
                              "makes earlier fragments inconsistent: use a new --name (new graph) or --replace-schema "
                              "(then re-extract with next_batch.py --role extract --all)."}))
            return 1
        shutil.copy2(run.schema, run.work / f"schema.replaced.{digest}.json")
    schema.setdefault("name", name)
    write_json(run.schema, schema)

    rows, origin = topic_papers(run.root, a.topic)
    if not rows:
        print(json.dumps({"ok": False, "error": f"no index for topic {a.topic!r}: run paper-acquisition (Index, then "
                          "Download) first — publications/papers.db or publications/<topic>/index/merged.csv"}))
        return 1
    dts = {x.strip() for x in (a.doc_types or "").split(",") if x.strip()}
    acc = {x.strip() for x in (a.access or "").split(",") if x.strip()}
    subj = {x.strip().lower() for x in (a.subject or "").split(",") if x.strip()}
    ids = {int(x) for x in (a.ids or "").split(",") if x.strip().isdigit()}
    ylo, yhi = 0, 9999
    if a.year:
        m = re.match(r"^(\d{4})(?:-(\d{4})?)?$", a.year)
        ylo, yhi = int(m.group(1)), int(m.group(2) or (m.group(1) if "-" not in a.year else 9999))
    picked, skipped = [], {"out_of_scope": 0, "doc_type": 0, "access": 0, "relevance": 0, "subject": 0, "year": 0}
    for r in rows:
        if ids and r["id"] not in ids:
            continue
        if not ids:
            if r.get("in_scope") == 0 or r.get("is_non_paper") or r.get("is_retracted"):
                skipped["out_of_scope"] += 1
                continue
            if dts and (r.get("doc_type") or "article") not in dts:
                skipped["doc_type"] += 1
                continue
            if acc and r.get("access_type") not in acc:
                skipped["access"] += 1
                continue
            if a.min_relevance is not None and r.get("relevance") is not None and r["relevance"] < a.min_relevance:
                skipped["relevance"] += 1
                continue
            if subj and not subj & {str(r.get(k) or "").lower() for k in ("topic_a", "topic_b", "topic_c")}:
                skipped["subject"] += 1
                continue
            if not (ylo <= (r.get("year") or 0) <= yhi) and a.year:
                skipped["year"] += 1
                continue
        pdf = run.root / r["pdf_path"] if r.get("pdf_path") else None
        si = [str(run.root / s) for s in (r.get("si") or []) if (run.root / s).exists()]
        picked.append({"paper_id": r["id"], "doi": r.get("doi"), "identifier": r.get("identifier"), "title": r.get("title"),
                       "year": r.get("year"), "venue": r.get("venue"), "doc_type": r.get("doc_type"),
                       "access_type": r.get("access_type"), "license": r.get("license"), "relevance": r.get("relevance"),
                       "pages": r.get("pages"), "pdf": str(pdf) if pdf and pdf.exists() else None, "si": si,
                       "has_abstract": len(r.get("abstract") or "") >= 80, "authors": r.get("authors"),
                       "topics": [t for t in (r.get("topic_a"), r.get("topic_b"), r.get("topic_c")) if t]})
    picked.sort(key=lambda p: (0 if p["pdf"] else 1, -(p.get("relevance") if p.get("relevance") is not None else 3),
                               -(p.get("year") or 0)))
    if a.max:
        with_pdf = [p for p in picked if p["pdf"]][:a.max]
        picked = with_pdf + [p for p in picked if not p["pdf"]]
    tmp = run.worklist.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in picked), encoding="utf-8")
    tmp.replace(run.worklist)
    papers = {p["paper_id"]: p for p in picked}
    counts = summary(run, papers)
    st = run.update_state(topic=a.topic, name=name, schema_version=version, schema_digest=digest,
                          phase=run.state().get("phase") if run.state().get("phase") not in (None, "prepared", "done") else "prepared",
                          created_at=run.state().get("created_at") or now_iso(), index_source=origin,
                          options={"figures": not a.no_figures, "reviewer": not a.no_reviewer,
                                   "fill_abstracts": not a.no_abstracts},
                          selection={"min_relevance": a.min_relevance, "subject": a.subject, "doc_types": sorted(dts),
                                     "access": sorted(acc), "year": a.year, "ids": sorted(ids), "max": a.max},
                          counts=counts, next="pilot: next_batch.py --role extract --n 5")
    no_pdf = [p["paper_id"] for p in picked if not p["pdf"]]
    print(json.dumps({"ok": True, "name": name, "schema_version": version, "warnings": warns, "index": origin,
                      "selected": len(picked), "with_pdf": counts["with_pdf"], "without_pdf": len(no_pdf),
                      "without_pdf_ids": no_pdf[:30], "skipped": skipped, "already_done": counts["extracted"],
                      "missing_abstracts": sum(1 for p in picked if p["pdf"] and not p["has_abstract"]),
                      "deliverables": run.rel(run.out), "working": run.rel(run.work)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
