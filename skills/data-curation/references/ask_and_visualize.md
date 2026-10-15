# Ask mode (DeepAsk by default) + Visualize mode

## Why ask-mode is DeepAsk
The recurring worry is "the index returns the wrong slice and the answer is built on a thin/empty set."
Ask mode now defaults to **DeepAsk**: multi-pass retrieval, Reciprocal Rank Fusion (RRF), graph expansion,
evidence-aware reranking, and explicit coverage reporting. Low recall should be visible rather than silent.
`kg_search.py query` is the engine; you (orchestrator) plan the query and read the coverage; Claude writes
the answer.

### The DeepAsk retrieval stack (`kg_search.py query`)
1. **Lexical node pass:** FTS5 over each node's searchable text = name + string props + the evidence quotes
   of its incident edges. Terms are tokenized and OR'd with prefix matching for high recall. Falls back to
   LIKE if the SQLite build lacks FTS5 (recorded in `notes`).
2. **Lexical edge-evidence pass:** FTS5 over edge type + edge evidence, then both edge endpoints become
   candidates. This catches evidence-bearing assertions even when the entity node itself has sparse text.
3. **Structural/numeric pass:** `--metric/--min-value/--max-value` scans typed node props directly. `--labels`
   are used as evidence/ranking boosts; when no terms or metric are present, labels can retrieve a label-only
   structural slice.
4. **Automatic broadening:** if the initial seed set is thin, token-level LIKE passes over node props and edge
   evidence are added automatically. `--broaden` forces the broadening pass.
5. **RRF fusion:** every pass contributes a ranked node list, fused with Reciprocal Rank Fusion:
   `score += 1 / (60 + rank_in_pass)`.
6. **Graph expansion:** fused seeds are expanded to their `--hops` k-hop neighborhood so connected context
   (the catalyst behind a metric, its support, conditions, source paper, figure) comes along even when a node
   did not match the query text directly.
7. **Evidence-aware reranking:** the expanded candidates are reranked using retrieval score plus evidence
   signals: `_evidence`, `_citation`, `Publication` links, figure links, numeric properties, label match, and
   multiple source papers.

Output remains render-ready: `{subgraph: {nodes, links}}` is still the same shape as `graph.json`, and the
result also includes `algorithm`, `passes`, `ranking`, `evidence_summary`, `notes`, and a `coverage` block:
`seeds`, `subgraph_nodes/edges`, `graph_nodes_total`, `hops`, `truncated`, and `broadened`.

### Your job (orchestrator) for an ask
1. **Plan the query.** From the question derive search `--terms` (entities + synonyms you expand yourself:
   a term, its acronym, and the near-synonyms the corpus uses), candidate `--labels`, and numeric
   `--metric/--min-value` when the question is quantitative. Add **provenance filters** when the question scopes the evidence base:
   `--access OA,OA+ND` (open-access only), `--record-type article,preprint`,
   `--exclude-record-type review,editorial` (primary sources only — avoids review double-counting),
   `--year-min/--year-max`, `--journal`. These keep only entities whose source Publication matches (DOI-keyed).
2. **Run** `kg_search.py query --db .scripts/<topic>/kg/<name>/index.sqlite ... --out
   publications/<topic>/kg/<name>/answers/<slug>.json`. Read `coverage`, `passes`, `ranking`, and
   `evidence_summary`. If `seeds` is low or `truncated` is true, broaden the question: add synonyms, use
   `--broaden`, raise `--hops`, or raise `--limit`. Do not answer from a thin slice.
3. **Reason over the returned subgraph**: typed nodes/edges + provenance quotes + figures. Resolve each claim
   to its `Publication` node for the citation.
4. **Write a STANDALONE scientific report** — a domain-expert synthesis of the literature that never reveals
   it came from a graph (see "Presentation rule" below). Author-year inline citations + figures shown as
   reproduced from their source paper. Separate strong evidence, weak evidence, contradictions, and gaps.
5. **Assess coverage PRIVATELY** (passes, seeds, truncation, source-paper spread) to decide whether to
   broaden and to avoid overclaiming — internal QA that does NOT appear in the report. Never imply
   completeness you did not retrieve; state any scope limit in plain scientific terms, not as retrieval/graph
   statistics.
6. Optionally render the supporting subgraph:
   `build_view.py --subgraph publications/<topic>/kg/<name>/answers/<slug>.json --kg-root publications/<topic>/kg/<name>
   --out publications/<topic>/kg/<name>/answers/<slug>.html`.

SQLite = "find fast and wide"; DeepAsk = "fuse and rerank"; the graph = "reason over"; Claude = "write".
The index is a regenerable cache, never the source of truth.

### Presentation rule — the report is a standalone brief; the graph is the engine, never the subject
Write the report as a domain expert synthesizing the literature. A reader must not be able to tell it was
produced from a graph. The report must NOT mention or allude to: the knowledge graph / "KG" / "graph",
DeepAsk / retrieval / index / search, nodes / edges / subgraph / triples / "provenance", how figures were
obtained ("auto-cropped", "from the PDFs"), node/edge/paper counts, coverage / seeds / truncation /
broadening, or "interim". Figures appear as figures reproduced from their source paper (caption + citation).
Inline author-year citations + an APA `References` section ARE expected (scholarship, not plumbing). Only the
separate subgraph-visualization HTML may look graph-like.

### Report quality — write like a scientist, for scientists
- **Claim ↔ evidence consistency.** Every quantitative claim must match what the report shows. A top-N table is
  "leading / representative examples", framed as such — do not headline an aggregate count you don't substantiate
  or fully trust (raw counts are inflated by unmerged aliases and adjacent reactions). A defensible qualitative
  statement beats a precise but shaky number.
- **Explain the science.** Ground the "why" in retrieved mechanism / intermediate / property / finding
  content — the operative pathway, the competing processes it must beat, and the structural or electronic
  effects behind the result — with trends and contrasts across the families present in the corpus. A short
  mini-review, not a list, even for closed questions.
- **Gather ALL relevant evidence; cite ALL of it — synthesis included.** Retrieve broadly enough to cover
  every claim (each motif, each trend), then cite everything — the overview/synthesis paragraphs to the SAME
  standard as the per-example body. An uncited generalization is a defect; back each with the papers (usually
  several) that support it.
- **Enumeration / comparison questions → count + grouped table.** For "which / how many X meet a threshold"
  (or "compare X"), give the corpus-wide count and a grouped comparison table (leading entries per group +
  metric + citation each) with a representative figure per group — not a few exemplars. Attribute each metric
  from the entity's OWN evidence and cite its OWN paper, so the count is defensible rather than inflated.
- **Meaningful figures only.** Choose figures that carry scientific signal for a claim: quantitative result
  plots (efficiency / yield / rate / selectivity / polarization curves), mechanism or energy diagrams, and
  characterization that reveals the active structure. Exclude review/overview/TOC/"scope-of-this-review"/
  roadmap/generic schematics and figures from review papers. Omit rather than pad. (Score candidate figures
  by caption keywords; when crops are imperfect, still prefer the most scientifically relevant caption.)
- **Natural formatting.** "Figure 1." / "Figure 2." with a real caption + citation, placed near the supporting
  text; no meta headings, no "auto-cropped", no pipeline "Notes/confirm-before-citing" box. Litmus test per
  sentence: would it appear in a real journal article?
- **Dual delivery.** The answer is delivered BOTH in chat (full brief + key figures shown inline) AND as the
  self-contained HTML twin; figures appear in both.

### Report citation format
Ask-mode reports should read like scientific prose:
- Put citations inline using author-year form from the linked `Publication` nodes: narrative
  `Fulano et al. (2024)` or parenthetical `(Fulano et al., 2024)`.
- Example: `The XYZ reaction behaves as XYZ under WCV medium (Fulano et al., 2024).`
- End with a `References` section containing APA-style entries:
  `Fulano, A., Mengano, B., & Zutano, C. (2024). Article title. Journal Name, 12(3), 45-67. https://doi.org/...`
- If author/year metadata is incomplete, do not fabricate it. Use the best available inline fallback
  (title + DOI/year) and include the available metadata in `References`.
- Keep `_citation` anchors such as `(p.5, Table 2)` as provenance near the claim when useful, but do not
  substitute them for the scholarly inline citation.

### Pitfalls
- **Single-term, no-synonym queries** still under-recall. Always expand terms.
- **Trusting a truncated subgraph** is unsafe. If `truncated`, either raise `--limit` or narrow with a
  label/metric filter so the cap keeps the right nodes.
- **Answering an empty result** is unsafe. `seeds: 0` means broaden or reformulate, not "the KG has nothing".
- **Letting label-only retrieval flood the result** is noisy. With terms or metrics present, labels should
  usually be ranking evidence rather than a standalone flood pass.

## Visualize mode (`build_view.py`)
Renders a focused subgraph into ONE self-contained interactive HTML (Cytoscape.js inlined from
`assets/cytoscape.min.js`, figures base64-embedded) -> share the single file, no internet, no folder.
- Selection: `--focus-node <id> --neighbors k`, `--focus-label <Label>`, `--query <text>`, or
  `--subgraph <ask-output.json>` to render exactly what DeepAsk retrieved.
- **Type is legible:** node TYPE = COLOUR (uniform circles — no shape zoo), with a node-type legend; on
  zoom-in the node label shows the entity NAME. **Relationships are legible:** edges are COLOURED by their
  ACTUAL edge type (from the schema — nothing hardcoded, no invented "families"), with a relationship legend
  (top types + "＋N more"); the edge type also appears on hover, on the highlighted neighbourhood (click a
  node), and on deep zoom. Click a node → its neighbourhood highlights (rest fades) with full props/figure
  in the side panel; click an edge → its provenance.
- **Live in-page filters:** a checkbox panel filters the rendered graph by `access` (OA / OA+ND / Free-to-read / Paywalled),
  `record_type`, and node type — right in the HTML, no re-running the CLI. Per-node access/type come from the
  Publications (augmented from the full `graph.json` when rendering a subgraph, so filters work on small subgraphs too).
- **Layout fills the canvas:** a spread force layout (high repulsion, low gravity) plus an explicit fit, so a
  dense subgraph opens into a readable web instead of collapsing into a ball.
- **`--schema`** renders the SCHEMA meta-overview: one node per type (sized by instance count), edges
  aggregated per type-pair (width by frequency; hover shows the relationship-type breakdown) — the whole
  graph's structure on a few dozen nodes. Use it for "how does everything relate" / a full-graph view.
- Whole-graph *instance* views are capped (`--max-nodes`, highest-degree kept, truncation noted); for big
  graphs prefer `--schema` or a focused subgraph over dumping every node.
- `--no-embed-figures` makes a smaller file that references `figures/` by relative path (needs the folder).
