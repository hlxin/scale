# Pipeline — phases, batches, resume

## Contents
- Phases and what the user decides
- Phase 2 loop (extract → validate → review → fix → settle)
- Adaptive batch size and model tiers
- Layer-2 checks after the merge
- state.json and resume

## Phases and what the user decides

| Phase | Scripts | User decides |
|---|---|---|
| 0 intake | — | topic, schema file, paper selection, options (figures, reviewer, abstracts) |
| 1 prepare | `check_schema.py`, `prepare_run.py` | approve the schema summary + selection counts |
| 2a pilot (5 papers) | `next_batch.py` + subagents, `review_status.py` | does the schema fit? (no changes by you) |
| 2b extraction | same loop over all papers | cost confirmation for large runs |
| 3 merge + aliases | `merge_graph.py`, `next_batch.py --role alias`, `merge_graph.py --alias-map` | approve the proposed merges |
| 4 figure QA (optional) | subagents per figure ([figure_qa.md](figure_qa.md)) | — |
| 5 validate | `validate_kg.py --strict`, Layer-2 checks | — |
| 6 release | `export_tables.py`, `build_view.py`, `kg_search.py index`, `release.py`, paper-acquisition `export.py` | — |
| ask | `kg_search.py query`, `build_view.py --subgraph` ([ask_and_visualize.md](ask_and_visualize.md)) | the question |

## Phase 2 loop

```
repeat until review_status.py says "all papers settled":
  next_batch.py --role extract --n <batch>   -> one Agent per line, ONE message, prompt "Read <prompt> and follow it exactly."
  (when they return) review_status.py         -> validates new fragments in its own process; lists to_review / invalid
  next_batch.py --role review --n <batch>    -> reviewer Agents (skip when the reviewer is off)
  review_status.py --apply                   -> settles approved / rejected / invalid; lists needs_fix
  next_batch.py --role fix --n <batch>       -> one corrective extraction per needs_fix paper (then review again)
```

- A subagent report must contain the validator's literal stdout (`--- summary:` line). A report claiming PASS
  without it, or a fragment `review_status.py` finds invalid, is not trusted: the fragment is re-extracted once
  (invalid twice → `failed`).
- `needs_fix` → exactly one corrective pass with the reviewer's issues inserted into the prompt; still `needs_fix`
  → `failed`. `rejected` (outside scope / unusable) → excluded and reported.
- Nothing is overwritten: superseded and rejected fragments move to `fragments/superseded/` and `fragments/rejected/`.

## Adaptive batch size and model tiers

Start with 5 papers per batch (the pilot), climb to 10-15 after clean batches, drop to 5 after failures or for long
PDFs (> 30 pages). Record the choice in your messages; scripts do not need it. Suggest models to the user once:
Sonnet for extraction and review (vision-capable reviewer is required for figure crops); Opus for dense, table-heavy
or high-stakes corpora; never a smaller tier for review. A full run costs roughly two subagent calls per paper.

## Layer-2 checks after the merge (you, inline, on graph.json)

- **Orphans** — domain nodes with no domain edge (only REPORTED_IN): fine for entity-only schemas, suspicious otherwise.
- **Suspicious hubs** — one node with an implausible degree (e.g. `Catalyst:catalyst`): an over-generic slug or a
  false alias merge; fix the alias map or re-extract the papers involved.
- **Provenance coverage** — domain edges with `_evidence` + `_citation` / all domain edges (release reports it; aim
  for > 95 %).
- **Pending vocabulary** — count `_pending_vocab_addition` values per property; report them to the user as evidence
  for a schema change (never change the schema yourself).

## state.json and resume

`.scripts/<topic>/kg/<name>/state.json`: `phase` (prepared → extraction → merge → alias → validate → release →
done), `counts`, `options`, `selection`, `next` (the next command), `awaiting_user`. On resume read
`prepare_run.py --status`; the files on disk always win (fragments, reviews, extraction_status.jsonl). The project's
Stop hook (`check_resume.py`) nudges Claude to continue a run active in the last 30 minutes unless
`awaiting_user` is set (`review_status.py --await-user "<question>"` before asking the user, `--resume` after).
