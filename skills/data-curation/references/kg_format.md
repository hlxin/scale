# Canonical KG format — graph.json (NetworkX node-link JSON)

The single source of truth is `graph.json` (`publications/<topic>/kg/<name>/graph.json`), built
from the per-paper fragments in `.scripts/<topic>/kg/<name>/fragments/`. It is **plain JSON**  AND the native
**NetworkX node-link** shape, so it loads in one line and interoperates with the scientific-Python /
web-viz ecosystem without any bespoke format.

```python
import json, networkx as nx
G = nx.node_link_graph(json.load(open("graph.json")))   # -> MultiDiGraph
```
(We WRITE it with stdlib `json` so building/validating needs no networkx dependency; `networkx` is only
needed if you want graph algorithms or GraphML/GEXF export — load on demand.)

## Shape
```json
{
  "directed": true, "multigraph": true,
  "graph": {"topic": "...", "n_papers": 4, "schema": "schema.json"},
  "nodes": [ {"id": "Catalyst:co-zsm-5", "label": "Catalyst", "props": { ... }} ],
  "links": [ {"type": "ACHIEVES", "source": "...", "target": "...", "props": { ... }} ]
}
```
It is a **property graph**: properties live on nodes AND edges. (Some networkx versions name the edge
array `edges` instead of `links`; the scripts accept both.)

## Naming conventions (load-bearing — consistency is what lets the merge resolve entities)
ONE convention is used everywhere. The user's schema should already conform (`check_schema.py` warns
otherwise), and `validate_kg.py` **warns** on any drift in fragments so it is caught early:

| Element | Convention | Examples |
|---|---|---|
| Node **label** (type) | `PascalCase` | `Catalyst`, `ActiveSite`, `CharacterizationMethod` |
| **Edge type** (relationship) | `UPPER_SNAKE_CASE`, verb-ish | `HAS_METRIC`, `CATALYZES`, `TRANSFORMS_INTO` |
| Node **id** | `<Label>:<slug>` — slug **lowercased**, non-alphanumerics → single hyphen, ASCII | `Catalyst:cu-nc`, `ActiveSite:fe-n4` |
| **Property key** | `snake_case`; unit/chemistry tokens kept as a verbatim suffix | `metric_type`, `binding_energy_eV`, `pH` |
| **Provenance keys** | underscore-prefixed | `_evidence`, `_citation` |

Slugs are lowercased on purpose: the same entity named `Cu-N4` in one paper and `cu-n4` in another must
collapse to ONE node, not fork. The builtin labels/edges (below) are the only names exempt from these rules.
A visualization should surface the label (type) and the edge type, not just the name — `build_view.py`
encodes node type by COLOUR (uniform circles) and colours each edge by its real edge type, showing the
relationship type on hover / zoom / selection, with node-type + relationship legends and live type/access filters.

## Node id scheme (drives entity resolution)
- **Domain entity:** `"<Label>:<slug>"`, slug = lowercase name with non-alphanumerics collapsed to single
  hyphens (e.g. `Catalyst:co-zsm-5`, `Support:zsm-5`). GLOBAL — the same entity from different papers
  uses the same id, so `merge_graph.py` unifies them automatically and accumulates `source_paper_ids`.
- **Figure:** `"Figure:<paper_id>:<short-label>"` (per-paper; never merged across papers).
- **Publication:** `"Publication:<doi>"` — **the DOI is the canonical paper id** (normalized: lowercased, no
  `https://doi.org/` prefix). Synthesized by the merge from each fragment's `paper` block; a paper with no DOI
  falls back to `Publication:nodoi-<internal_id>`. The run-time numeric id is preserved as `props.internal_id`
  (figure FILES are named by it, so they stay filesystem-safe). `source_paper_ids` on every node/edge are DOIs.

## Edges are assertions with provenance
A domain edge encodes a triplet (subject—predicate—object) AND its receipt:
```json
{"type": "ACHIEVES", "source": "Catalyst:co-zsm-5", "target": "PerformanceMetric:c5plus-72",
 "props": {"_evidence": "C5+ selectivity of 72%", "_citation": "(p.5, Table 2)", "source_paper_ids": ["1"]}}
```
- `_evidence` — short verbatim quote (the assertion's grounding).
- `_citation` — anchor: `(p.5)`, `(Table 2)`, `(Fig. 3)`, `(Table S3)`.
- `source_paper_ids` — accumulated by the merge; lists every paper that asserted this edge.
Underscore-prefixed props are provenance/metadata and are always allowed by the validator;
`source_paper_ids`, `name`, `name_variants`, `evidence_count` are also whitelisted.

## Builtins (always allowed, never put in schema.json)
- Node labels: **`Publication`** (paper metadata from `publications/papers.db`: doi, title, year, journal/venue,
  authors, **`access`** = `OA` / `OA+ND` / `Free-to-read` / `Paywalled`, `license`, **`record_type`** = the document
  type (`article`, `preprint`, `review` …), `topics` = Topic A/B/C, `citations`, `url`), **`Figure`**
  (multimodal — `props.path` relative to KG root + `caption` + `source_figure`).
- Edge types: **`REPORTED_IN`** (entity→its Publication — every entity is one hop from its paper, so
  citing is trivial), **`DEPICTS`** (Figure→entity), **`MENTIONS`**, **`CITES`** (Publication→Publication,
  added when a fragment's `cites_dois` matches another in-corpus paper's DOI).

## Multimodality
Figures are first-class `Figure` nodes referenced by **relative path** (`figures/<paper>_<n>.png`) — the
canonical store stays portable (share the folder). For sharing a single file, `build_view.py` base64-embeds
the figures it renders (see `ask_and_visualize.md`). Extraction uses `extract_figures.py` (pypdf per-image,
pymupdf whole-page fallback for vector charts).

## No embeddings (by design)
The typed graph + provenance quotes are the retrieval substrate (see `ask_and_visualize.md`), so there is
no embedding model dependency and no float arrays bloating `graph.json`. If semantic search is ever needed
at very large scale, add embeddings as a **sidecar** (`embeddings.npy`/parquet keyed by node id) — never
inside `graph.json`.

## Derived artifacts (regenerable, not the source of truth)
- `manifest.json` — counts (nodes by label, edges by type, n_papers).
- `index.sqlite` — FTS5 + structural retrieval index (`kg_search.py index`; lives in `.scripts/<topic>/kg/<name>/`).
- `views/*.html` — self-contained interactive visualizations.
- `alias_candidates.json`, `hubs.json` — near-duplicate clusters and hub nodes for the alias pass (working files).
- `tables/*.csv` — flat views for spreadsheets (`export_tables.py`).
