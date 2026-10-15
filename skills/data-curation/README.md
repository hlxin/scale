# data-curation — README

A Claude Code skill (Xin's Research Group, Virginia Tech) that turns a topic's downloaded papers into a knowledge
graph, following a schema **you** provide. Ask Claude: "build the knowledge graph of co2rr with my schema
schemas/co2rr.json", "continue the co2rr-catalysts graph", "which Cu catalysts reach FE(C2H4) > 60 %?".

## What it needs

1. A topic indexed and downloaded by paper-acquisition (`publications/papers.db`, `publications/<topic>/papers/`).
2. Your schema: `schema.json` with node types (and their properties), edge types and optional scope, record view,
   never-merge rules and extra faithfulness rules — see `references/schema_format.md` and
   `examples/schema.catalysis.example.json`. A table or a list of fields works too: Claude converts it faithfully and
   shows it to you before using it. Claude never invents a schema.

## What happens

For every selected paper one subagent extracts nodes and edges with a verbatim quote and a page/table/figure anchor
for every assertion, a validator checks the fragment, and an independent reviewer audits it against the PDF (text and
figure crops). Wrong extractions get one corrective pass; papers outside the schema's scope are rejected. Fragments
are merged deterministically (same entity → one node), near-duplicate names are resolved with your approval, and the
graph is validated. A 5-paper pilot comes first so you can judge whether your schema fits.

## What you get — `publications/<topic>/kg/<name>/`

| File | Content |
|---|---|
| `graph.json` | the knowledge graph (NetworkX node-link JSON; every edge with `_evidence` and `_citation`) |
| `schema.json` | the schema used, frozen |
| `tables/` | one CSV per node type, `edges.csv`, `publications.csv`, `records.csv` (from the schema's record view) |
| `figures/` | figure crops linked from `Figure` nodes |
| `views/overview.html`, `views/schema.html` | interactive views (open in a browser, no internet needed) |
| `answers/` | reports written when you ask questions |
| `README.md` | what was built, counts and quality figures |

The paper index's **Extracted** column then shows `Yes — <name> (<date>)` or `Rejected — ...`, and abstracts the
extractor copied from PDFs fill papers that had none.

```python
import json, networkx as nx
G = nx.node_link_graph(json.load(open("publications/co2rr/kg/co2rr-catalysts/graph.json")), edges="links")
```

## Requirements

Python 3.10+ with `pypdf` and `pymupdf` (`pip install pypdf pymupdf`). Claude Code with subagents (Sonnet or better;
the reviewer must be able to read images).
