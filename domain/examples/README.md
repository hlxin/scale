# Catalysis examples

The examples of the catalysis domain. The science kernel's own examples are in
[`core/examples/`](../../core/examples/).

| directory | kind | use |
|---|---|---|
| `scale-catal/` | worked examples of the catalysis **scale-catal** schema (`domain/graph/scale-catal.yaml`), all **synthetic** (invented values and sources) and public, all following the one catalysis checklist: `example.json` (a thermocatalytic test with its catalyst sample, feed, reaction and evidence), one document per driving force and combination of forces (`driving-force-examples/`), on which the domain's competency questions run, a source's lifecycle (`source-lifecycle/`), and current densities that a scientific comparison keeps apart (`comparison-examples/`, competency question CQ-06) | `scale graph validate`; `scale domains cq catalysis`; `tools/tests/test_pgraph.py`, `domain/tests/test_driving_force_domains.py`, `domain/tests/test_graph_layers.py` |

Source-grounded records and synthetic test cases are kept apart on purpose. `data_status:
synthetic_example` requires every record's origin to be `synthetic`, and SCALE rejects a synthetic
record inside a `research_data` document.

Every committed document is public (`scale evidence access` checks it in `scale check`). Curated project data that
is not cleared for publication is never committed: it stays with its project. A source-grounded example added here
quotes its sources only within the copyright cap (`rights.yaml` beside it; [docs/curation.md](../../docs/curation.md)).
Local material of an example (source texts, OCR output, scratch: `work/`, `scratchpad/`, `curation/ocr/`) is
ignored by git and never bundled. A directory holding a `.scale-verbatim` marker (a sealed kg-bundle, for
example) is kept as-is and is not reformatted.
