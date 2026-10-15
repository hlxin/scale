"""Release — flatten graph.json into tables for spreadsheets, pandas or R (publications/<topic>/kg/<name>/tables/).

  python3 -I export_tables.py --topic co2rr --name co2rr-catalysts

Writes:
  <Label>.csv        one row per node of that type: id, name, every schema property, papers (DOIs), n_papers,
                     evidence (verbatim quotes, ' | '-joined) and citations
  edges.csv          type, source, source_label, target, target_label, evidence, citation, papers
  publications.csv   the papers in the graph (DOI, title, year, venue, access, license, document type, topics)
  records.csv        only when the schema has a record_view: one row per record node joined with its neighbours
                     (e.g. one row per performance value with its catalyst, product and conditions)
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _kgcommon import Run, add_root_arg, read_json

PROV = ("_evidence", "_citation")


def flat(v):
    if isinstance(v, list):
        return " | ".join(str(x) for x in v if x not in (None, ""))
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return "" if v is None else v


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = add_root_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    run = Run(a.project, a.topic, a.name)
    g, schema = read_json(run.graph), read_json(run.schema)
    if not g or not schema:
        print(json.dumps({"error": "graph.json or schema.json missing — run merge_graph.py first"}))
        return 2
    out = run.out / "tables"
    out.mkdir(parents=True, exist_ok=True)
    nodes = {n["id"]: n for n in g["nodes"]}
    links = g.get("links") or g.get("edges") or []
    by_label = defaultdict(list)
    for n in g["nodes"]:
        by_label[n["label"]].append(n)
    written = {}
    for label, ns in sorted(by_label.items()):
        if label == "Publication":
            hdr = ["id", "doi", "title", "year", "journal", "access", "license", "record_type", "topics", "url", "internal_id"]
            write_csv(out / "publications.csv", hdr, [{**{k: flat(n["props"].get(k)) for k in hdr}, "id": n["id"]} for n in ns])
            written["publications.csv"] = len(ns)
            continue
        props = list(((schema.get("node_types") or {}).get(label) or {}).get("properties", {}) or {})
        if label == "Figure":
            props = ["path", "caption", "source_figure"]
        extra = sorted({k for n in ns for k in n["props"] if not k.startswith("_") and k not in props
                        and k not in ("source_paper_ids", "name", "name_variants", "evidence_count")})
        hdr = ["id", "name"] + [p for p in props if p != "name"] + extra + ["papers", "n_papers", "evidence", "citation"]
        rows = []
        for n in ns:
            pr = n["props"]
            r = {"id": n["id"], "name": flat(pr.get("name")), "papers": flat(pr.get("source_paper_ids")),
                 "n_papers": len(pr.get("source_paper_ids") or []), "evidence": flat(pr.get("_evidence")),
                 "citation": flat(pr.get("_citation"))}
            for k in props + extra:
                if k != "name":
                    r[k] = flat(pr.get(k))
            rows.append(r)
        write_csv(out / f"{label}.csv", hdr, rows)
        written[f"{label}.csv"] = len(rows)
    erows = []
    for e in links:
        if e["type"] == "REPORTED_IN":
            continue
        s, t = nodes.get(e["source"], {}), nodes.get(e["target"], {})
        pr = e.get("props") or {}
        erows.append({"type": e["type"], "source": e["source"], "source_label": s.get("label"),
                      "source_name": flat((s.get("props") or {}).get("name")), "target": e["target"],
                      "target_label": t.get("label"), "target_name": flat((t.get("props") or {}).get("name")),
                      "evidence": flat(pr.get("_evidence")), "citation": flat(pr.get("_citation")),
                      "papers": flat(pr.get("source_paper_ids"))})
    write_csv(out / "edges.csv", ["type", "source", "source_label", "source_name", "target", "target_label",
                                  "target_name", "evidence", "citation", "papers"], erows)
    written["edges.csv"] = len(erows)
    rv = schema.get("record_view")
    if rv and rv.get("label") in by_label:
        out_e, in_e = defaultdict(list), defaultdict(list)
        for e in links:
            out_e[(e["source"], e["type"])].append(e["target"])
            in_e[(e["target"], e["type"])].append(e["source"])
        nt = schema.get("node_types") or {}
        rows, hdr = [], None
        for n in by_label[rv["label"]]:
            base_props = list((nt.get(rv["label"]) or {}).get("properties", {}) or {})
            r = {"record_id": n["id"], **{k: flat(n["props"].get(k)) for k in base_props},
                 "papers": flat(n["props"].get("source_paper_ids")), "evidence": flat(n["props"].get("_evidence")),
                 "citation": flat(n["props"].get("_citation"))}
            cols = ["record_id"] + base_props
            for j in rv.get("join") or []:
                ids = (out_e if j.get("direction", "out") == "out" else in_e).get((n["id"], j["edge"]), [])
                nb = [nodes[i] for i in ids if i in nodes]
                lab = nb[0]["label"] if nb else None
                pre = j.get("prefix") or (j["edge"].lower() + "_")
                nprops = ["name"] + [k for k in (nt.get(lab) or {}).get("properties", {}) or {} if k != "name"] if lab else ["name"]
                for k in nprops:
                    r[pre + k] = " ; ".join(str(flat(x["props"].get(k))) for x in nb if x["props"].get(k) not in (None, ""))
                cols += [pre + k for k in nprops]
            rows.append(r)
            hdr = hdr or cols + ["papers", "evidence", "citation"]
            for c in cols:
                if c not in hdr:
                    hdr.insert(len(hdr) - 3, c)
        write_csv(out / "records.csv", hdr or ["record_id"], rows)
        written["records.csv"] = len(rows)
    print(json.dumps({"tables": run.rel(out), "written": written}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
