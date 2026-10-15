# Scaling — 1,000-5,000 papers per graph, sharding beyond

## What scales out of the box
- **Per-paper fragments + `extraction_status.jsonl`:** settled papers are never re-dispatched; resume hands out
  only papers without a fragment or a final status (`next_batch.py`).
- **Batched parallel extraction:** adaptive batch size (you decide per batch; recorded in `state.json`).
- **Deterministic, idempotent merge:** re-running over the same fragments (± the same `alias_map`)
  reproduces identical `graph.json`.
- **`validate_kg.py --jobs N`:** parallel structural validation (near-linear speedup minus IPC).
- **Blocked alias review:** the reviewer only ever sees small same-label/name-prefix clusters, never the
  full node set — so resolution stays tractable at tens of thousands of nodes.
- **SQLite FTS5 index:** ask-mode queries hit `index.sqlite` (milliseconds) instead of loading a large
  `graph.json` per question. The index is a regenerable cache.

## `/loop` for unattended multi-day builds
```
/loop /data-curation resume topic=<topic> name=<name>
```
`/loop` self-paces across token-exhaustion cycles; the skill resumes from `state.json` each time and exits the
loop when `phase == "done"`. The project's Stop hook (`scripts/check_resume.py`) also keeps a live run going.

## SQLite vs embeddings at scale (why no vectors in v1)
At 1000–3000+ papers the typed graph is a better index than embeddings for the questions a KG answers:
- **Structural questions** ("which catalysts give ≥ X selectivity, on which support, under what
  conditions") are exact label + numeric filters — SQLite answers them precisely and instantly.
- **Lexical recall** over names + provenance quotes (FTS5) covers term/synonym matching.
- Embeddings would add a model dependency, recomputation on every change, and large float arrays — the
  exact bloat we avoid by keeping `graph.json` clean JSON.
If a future need for fuzzy semantic recall appears, add embeddings as a **sidecar** (`embeddings.npy` /
parquet keyed by node id) consumed by an extra `kg_search` retrieval layer — never inside `graph.json`.

## Beyond ~5K papers — sharding
A single `graph.json` grows to tens of MB (still loadable, but heavy to load whole and impossible to
visualize entirely). Then:
1. **Shard the corpus** into sub-KGs of ≤ ~5K papers each (e.g. by sub-topic, journal, or year), each a
   normal `<shard>_kg/` with its own `graph.json` + `index.sqlite`.
2. **One shared `schema.json`** across shards (the same given schema) so node ids are comparable across shards
   and the same entity resolves consistently.
3. **Aggregate** at query time: run `kg_search.py query` per shard and union the subgraphs, or
   periodically concatenate the shard `graph.json`s and re-merge (deterministic) into a roll-up KG +
   roll-up index for cross-shard asks.
4. `index.sqlite` keeps ask-mode fast regardless of shard count; visualization is always a focused
   subgraph, never the whole roll-up.

Disk note: keep `fragments/` (the resume + re-merge unit) and `figures/`; `graph.json`, `manifest.json`,
`tables/`, `index.sqlite` and `views/` are all regenerable from fragments + `schema.json` + `alias_map.json`.
Select a shard with `prepare_run.py --subject / --year / --ids` and a distinct `--name`.
