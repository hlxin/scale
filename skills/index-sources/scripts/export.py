"""Bring the paper database up to date, write a topic's index files, or export a filtered subset.

Every step already publishes the papers it changed into publications/papers.db, in place (_publish.py); run this
after manual changes, to write a topic's index CSVs (only on request), or to export a subset someone asked for.

  python3 -I export.py                                  # publish any pending change into publications/papers.db
  python3 -I export.py --topic co2rr --csv              # also write publications/co2rr/index/*.csv
  python3 -I export.py --rebuild                        # fallback: rebuild papers.db from the ledger (history kept)
  python3 -I export.py --name cu-2020s --topic co2rr --subject "Copper catalysts" --year 2020-2026 \\
          --access OA,OA+ND --format csv                # -> publications/exports/cu-2020s.csv
  python3 -I export.py --set-extracted 12,57 --topic co2rr --kg co2rr-kg --value extracted [--note "..."]
Filters (all optional, combined with AND): --topic (in scope or unscreened; never errata or retracted papers),
--subject (matches Topic A/B/C AND related topics; label or id; comma = any), --main-only (Topic A/B/C only), --venue (substring; comma = any), --year 2018-2026 / 2020, --access,
--doc-type (article,review,preprint,patent,dataset ...), --min-relevance N, --downloaded yes|no, --text "fts query",
--author (substring). Formats: csv (index columns), jsonl, bib (BibTeX), ris.
"""
import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Project, add_project_arg, die, slugify, today
from _ledger import INDEX_COLUMNS, Ledger
from _topics import Vocab


def query_ids(proj, a, vocab):
    con = sqlite3.connect(f"file:{proj.db}?mode=ro", uri=True)
    where, args = ["COALESCE(p.is_non_paper,0)=0 AND COALESCE(p.is_retracted,0)=0"], []   # never errata or retracted
    if a.topic:
        where.append("p.id IN (SELECT paper_id FROM paper_collections WHERE collection=? AND COALESCE(in_scope,1)=1"
                     + (" AND relevance>=?" if a.min_relevance is not None else "") + ")")
        args += [a.topic] + ([a.min_relevance] if a.min_relevance is not None else [])
    if a.subject:
        terms = [vocab.resolve(s) or s for s in a.subject.split(",") if s.strip()]
        where.append(f"p.id IN (SELECT paper_id FROM paper_subjects WHERE (term IN ({','.join('?' * len(terms))}) "
                     f"OR label IN ({','.join('?' * len(terms))}))" + (" AND kind='main'" if a.main_only else "") + ")")
        args += terms + [vocab.label(t) for t in terms]
    if a.venue:
        vs = [v.strip() for v in a.venue.split(",") if v.strip()]
        where.append("(" + " OR ".join("p.venue LIKE ?" for _ in vs) + ")")
        args += [f"%{v}%" for v in vs]
    if a.year:
        m = re.match(r"^(\d{4})(?:-(\d{4})?)?$", a.year)
        if not m:
            die("--year must look like 2020, 2018-2026 or 2020-")
        lo, hi = int(m.group(1)), int(m.group(2) or (m.group(1) if "-" not in a.year else 9999))
        where.append("p.year BETWEEN ? AND ?")
        args += [lo, hi]
    if a.access:
        acc = [x.strip() for x in a.access.split(",") if x.strip()]
        where.append(f"p.access_type IN ({','.join('?' * len(acc))})")
        args += acc
    if a.doc_type:
        dts = [x.strip() for x in a.doc_type.split(",") if x.strip()]
        where.append(f"p.doc_type IN ({','.join('?' * len(dts))})")
        args += dts
    if a.downloaded:
        where.append("p.downloaded = ?")
        args.append("Yes" if a.downloaded.lower().startswith("y") else "No")
    if a.author:
        where.append("p.authors LIKE ?")
        args.append(f"%{a.author}%")
    if a.text:
        where.append("p.id IN (SELECT rowid FROM papers_fts WHERE papers_fts MATCH ?)")
        args.append(a.text)
    sql = "SELECT p.id FROM papers p WHERE " + " AND ".join(where) + " ORDER BY p.year DESC, p.id"
    return [r[0] for r in con.execute(sql, args)]


def bib_key(p):
    first = (p.get("authors") or ["anon"])[0]
    sur = re.sub(r"[^A-Za-z]", "", first.split(",")[0] if "," in first else first.split()[-1] if first.split() else "anon")
    return f"{sur or 'anon'}{p.get('year') or ''}_{p['id']}"


def write_subset(proj, led, ids, a, vocab):
    from _ledger import render_row
    proj.exports.mkdir(parents=True, exist_ok=True)
    name = slugify(a.name or "export")
    path = proj.exports / f"{name}.{a.format}"
    subj = led._subject_map()
    ext = led._extraction_map()
    tp = {}
    for r in led.q("SELECT paper_id, topic FROM paper_topics ORDER BY topic"):
        tp.setdefault(r[0], []).append(r[1])
    rows = []
    for pid in ids:
        p = led.get(pid)
        if not p:
            continue
        p["_aliases"] = led.aliases(pid)          # its preprint DOIs give the Preprint link column
        t = next((x for x in led.topics_of(pid) if x["topic"] == a.topic), None) if a.topic else None
        if t:
            p.update({"t_relevance": t.get("relevance"), "t_relevance_note": t.get("relevance_note"),
                      "t_in_scope": t.get("in_scope"), "t_path": t.get("path"), "t_date_added": t.get("date_added")})
        rows.append((p, render_row(p, a.topic, subj.get(pid), ext.get(pid), tp.get(pid, []), vocab)))
    if a.format == "csv":
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=INDEX_COLUMNS)
            w.writeheader()
            w.writerows(r for _, r in rows)
    elif a.format == "jsonl":
        with open(path, "w", encoding="utf-8") as fh:
            for _, r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    elif a.format == "bib":
        with open(path, "w", encoding="utf-8") as fh:
            for p, r in rows:
                kind = {"article": "article", "review": "article", "conference-paper": "inproceedings",
                        "book-chapter": "incollection", "book": "book", "thesis": "phdthesis", "report": "techreport",
                        "patent": "misc", "dataset": "misc", "preprint": "misc"}.get(r["Doc type"], "misc")
                fields = {"title": r["Title"], "author": " and ".join(p.get("authors") or []), "year": r["Year"],
                          "journal": r["Venue"], "doi": p.get("doi") or "", "url": r["URL"], "abstract": r["Abstract"],
                          "keywords": r["Keywords"], "note": r["Access type"] + (f"; {r['License']}" if r["License"] else "")}
                body = ",\n".join(f"  {k} = {{{str(v).replace('{', '(').replace('}', ')')}}}" for k, v in fields.items() if v)
                fh.write(f"@{kind}{{{bib_key(p)},\n{body}\n}}\n\n")
    else:
        with open(path, "w", encoding="utf-8") as fh:
            for p, r in rows:
                ty = {"article": "JOUR", "review": "JOUR", "conference-paper": "CPAPER", "book-chapter": "CHAP",
                      "book": "BOOK", "thesis": "THES", "report": "RPRT", "patent": "PAT", "dataset": "DATA"}.get(r["Doc type"], "GEN")
                pairs = [("TY", ty), ("TI", r["Title"])] + [("AU", x) for x in p.get("authors") or []]
                pairs += [("PY", r["Year"]), ("JO", r["Venue"]), ("DO", p.get("doi") or ""), ("UR", r["URL"]),
                          ("AB", r["Abstract"])] + [("KW", k) for k in (p.get("keywords") or [])]
                fh.write("".join(f"{t}  - {v}\n" for t, v in pairs if str(v).strip()) + "ER  - \n\n")
    return path, len(rows)


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic")
    ap.add_argument("--name", help="export name -> publications/exports/<name>.<format>; omit to just refresh")
    ap.add_argument("--subject")
    ap.add_argument("--main-only", action="store_true")
    ap.add_argument("--venue")
    ap.add_argument("--year")
    ap.add_argument("--access")
    ap.add_argument("--doc-type")
    ap.add_argument("--min-relevance", type=int)
    ap.add_argument("--downloaded")
    ap.add_argument("--author")
    ap.add_argument("--text")
    ap.add_argument("--format", choices=["csv", "jsonl", "bib", "ris"], default="csv")
    ap.add_argument("--set-extracted", help="comma list of paper IDs (records a curation result by hand)")
    ap.add_argument("--kg", help="knowledge-graph / schema name for --set-extracted")
    ap.add_argument("--value", help="extracted | rejected | failed | no_data | none (removes the record)")
    ap.add_argument("--note")
    ap.add_argument("--csv", action="store_true", help="write the index CSVs of --topic (or of every topic)")
    ap.add_argument("--rebuild", action="store_true", help="rebuild papers.db from the ledger, keeping its history")
    a = ap.parse_args()
    proj = Project(a.project)
    led = Ledger(proj)
    vocab = Vocab(proj)
    if a.set_extracted:
        if not (a.topic and a.kg and a.value):
            die("--set-extracted needs --topic, --kg and --value")
        ids = [int(x) for x in a.set_extracted.split(",") if x.strip().isdigit()]
        with led.tx():
            for i in ids:
                if a.value == "none":
                    led.x("DELETE FROM extractions WHERE paper_id=? AND topic=? AND kg=?", (i, a.topic, a.kg))
                else:
                    led.set_extraction(i, a.topic, a.kg, a.value, date=today(), note=a.note)
        led.export(topics=[a.topic])
        print(json.dumps({"extracted_set": len(ids), "topic": a.topic, "kg": a.kg, "value": a.value}))
        return
    if not a.name:
        topics = [a.topic] if a.topic else None
        led.export(topics=topics, rebuild=a.rebuild)
        out = {"database": proj.rel(proj.db), **(led.last_publish or {})}
        if a.csv:
            out["index_rows"] = led.export(topics=topics, db=False, csv=True)
            out["index"] = [proj.rel(proj.index_dir(t)) for t in (topics or led.all_topics())]
        print(json.dumps(out))
        return
    if not proj.db.exists():
        led.export()
    ids = query_ids(proj, a, vocab)
    path, n = write_subset(proj, led, ids, a, vocab)
    print(json.dumps({"export": proj.rel(path), "papers": n}))


if __name__ == "__main__":
    main()
