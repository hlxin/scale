"""Release — finish a run: tidy the figures folder, write the deliverable README, mark the run done.

  python3 -I release.py --topic co2rr --name co2rr-catalysts

Figure candidates no Figure node points to move to .scripts/<topic>/kg/<name>/figures_unused/ (never deleted).
publications/<topic>/kg/<name>/README.md records the schema, counts, papers, validation and how to load the graph.
Then refresh paper-acquisition's index so its Extracted column and papers.db show this run (the command is printed).
"""
import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _kgcommon import Run, add_root_arg, now_iso, read_json, read_jsonl


def main():
    ap = add_root_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    run = Run(a.project, a.topic, a.name)
    g, schema, man = read_json(run.graph), read_json(run.schema), read_json(run.out / "manifest.json", {})
    if not g or not schema:
        print(json.dumps({"error": "graph.json or schema.json missing — run merge_graph.py first"}))
        return 2
    used = {Path(n["props"].get("path", "")).name for n in g["nodes"] if n["label"] == "Figure"}
    unused_dir = run.work / "figures_unused"
    moved = 0
    for f in sorted(run.figures.glob("*.png")):
        if f.name not in used:
            unused_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(unused_dir / f.name))
            moved += 1
    st = run.statuses()
    c = Counter(r.get("status") for r in st.values())
    links = g.get("links") or []
    domain = [e for e in links if e["type"] not in ("REPORTED_IN", "DEPICTS", "MENTIONS", "CITES")]
    prov = sum(1 for e in domain if (e.get("props") or {}).get("_evidence") and (e.get("props") or {}).get("_citation"))
    v = read_jsonl(run.vreport)
    lines = [
        f"# Knowledge graph — {schema.get('name') or run.name}", "",
        f"Topic: {schema.get('topic') or run.topic}  ", f"Schema version: {schema.get('version') or '1'} (schema.json, given by the user)  ",
        f"Built: {now_iso()} from the `{run.topic}` index (publications/papers.db)", "",
        "## Contents", "",
        f"- `graph.json` — {man.get('n_nodes', len(g['nodes']))} nodes, {man.get('n_edges', len(links))} edges from "
        f"{man.get('n_papers', '?')} papers (NetworkX node-link JSON)",
        f"- `tables/` — one CSV per node type, `edges.csv`, `publications.csv`" + (", `records.csv`" if schema.get("record_view") else ""),
        "- `figures/` — figure crops referenced by `Figure` nodes", "- `views/` — interactive HTML views (open in a browser)",
        "- `answers/` — reports written in ask mode", "",
        "## Papers", "",
        f"extracted {c.get('extracted', 0)} · no data for the schema {c.get('no_data', 0)} · rejected by the reviewer "
        f"{c.get('rejected', 0)} · failed {c.get('failed', 0)}", "",
        "## Quality", "",
        f"- every domain edge with a verbatim quote and an anchor: {prov}/{len(domain)}",
        f"- fragments validated: {len(v)} checks logged (.scripts/{run.topic}/kg/{run.name}/validation_report.jsonl)",
        "- each fragment was audited by an independent reviewer against its PDF (text and figure crops)" if
        (run.state().get("options") or {}).get("reviewer", True) else "- reviewer pass was switched off for this run",
        "", "## Nodes by type", ""] + [f"- {k}: {v_}" for k, v_ in (man.get("nodes_by_label") or {}).items()] + [
        "", "## Edges by type", ""] + [f"- {k}: {v_}" for k, v_ in (man.get("edges_by_type") or {}).items()] + [
        "", "## Load it", "", "```python", "import json, networkx as nx",
        "G = nx.node_link_graph(json.load(open('graph.json')), edges='links')", "```", "",
        "Every domain edge carries `_evidence` (verbatim quote) and `_citation` (page / table / figure); "
        "`source_paper_ids` are DOIs. Publication nodes hold the paper's bibliographic data, access type and license."]
    (run.out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    run.update_state(phase="done", released_at=now_iso(), next=None, awaiting_user=None)
    print(json.dumps({"released": run.rel(run.out), "figures_moved_unused": moved, "status_counts": dict(c),
                      "provenance_coverage": f"{prov}/{len(domain)}",
                      "refresh_index": "run paper-acquisition's export.py (python3 -I <paper-acquisition>/scripts/export.py "
                                       f"--topic {run.topic}) so the Extracted column and papers.db show this run"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
