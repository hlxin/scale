# Batches, states and the run folder

## The run folder

| path | written by | content |
|---|---|---|
| `run.json` | prepare | the corpus manifest, the scale command, the schema version pinned, the models (`curator`, `reviewer`: a model, `api:<model>` with its endpoint, or `skip`), and each source picked (DOI, title, year, the copy's version and licence as the source index has them) |
| `sources/<id>/` | `scale source start` | SCALE's working folder: `<slug>.graph.json`, `source.json`, `rights.yaml`, `BRIEF.md`, `pdfs/` and `work/texts/` (local; git-ignored by its `.gitignore`) |
| `sources/<id>/work/si.json` | prepare | the SI files whose text was appended to the page texts (pages `[page S1]` …), and those left out, with why |
| `sources/<id>/work/curation.json` | the curator subagent | `result` (`curated` or `no_data`), `records`, `gaps`, `not_curated`, `note`, `attempt` |
| `sources/<id>/work/review.json` | the second reader (a subagent, or `review-api`) | `verdict` (`pass`, `needs_fix`, `reject`), `issues`, `coverage`, `note`; `reader` when an API model read it |
| `sources/<id>/work/gaps/GAP-*.json` | the curator | the gap reports it wrote (SCALE's gap format); `status` counts them by kind and lists the `missing_concept` ones |
| `sources/<id>/work/check.json` | status | the last `scale source check`, kept while the graph and `rights.yaml` are unchanged |
| `prompts/<role>/<id>.md` | next | the prompts handed out |
| `handouts.jsonl` | next | one line per prompt handed out (source, role, time) |
| `state.jsonl` | status --apply | one line per settled source; the last line of a source holds |
| `finish.json`, `contribute-dry-run.json` | finish, contribute | what `scale source finish` and the `scale graph contribute` dry run reported |
| `graph/` | assemble | a local graph kept as parts (`parts/`, `rights.yaml`, `stewardship.yaml`) with every passed document, and its build `graph.graph.json`, to query |

`<id>` is the source ID from the manifest (or the slug when there is none). The document's own slug comes from
`scale source start`: the DOI with `/` as `-`, else the PDF's name.

## States

| state | means | next |
|---|---|---|
| `not_started` | prepare has not made the folder (or `scale source start` failed: `run.json` keeps the error) | re-run prepare |
| `prepared` | the folder is ready, no curator's report yet | `next --role curate` |
| `curated` | the curator reported, the check passes, no second reading after the last change | `next --role review` (an API reader: `review-api`) |
| `check_failed` | the curator reported but `scale source check` fails | `next --role fix` (the prompt lists the errors) |
| `needs_fix` | the second reading asked for fixes | `next --role fix` (the prompt lists the issues) |
| `passed` | the check passes and the second reading after the last change passed it (`curated` or `no_data`); with `--reviewer skip`, the check alone | settled: `status --apply`, then finish |
| `rejected` | the second reading found the wrong source or an unreadable text | settled; a person looks |
| `failed` | three fixes reported and the check or the reading still fails | settled; a person looks |

A second reading counts only if it is newer than the graph, `rights.yaml` and the curator's report. A curator who
changes the document after it was read sends it back to `curated`. A prompt handed out is not handed out again for
three hours unless its report arrives first. A subagent that stopped without reporting gets its source back after that.

## Batches

- One subagent per source and per role. Launch a batch's subagents in one message, each with the prompt "Read
  <prompt> and follow it exactly." A curator needs no other context: the prompt names the folder, the procedure
  (`scale call skills '{"name": "curate-corpus"}'`), the commands and the report to write.
- Start at 5. Go up to 10–15 after clean batches, and back to 5 after failures, for long sources, or for sources with
  much SI. Never more than 15: Claude Code runs at most 20 subagents at once by default
  (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`), and a launch beyond that is refused, not queued.
- The curator and the second reader of a source are different subagents. The second reader never edits the document.
  Its pass is a second reading by an agent, not a review.
- Trust a subagent's reply only together with `status`: status runs `scale source check` itself and reads the reports
  from the folder.
- Each source costs about three to four subagent calls (curate, read, sometimes a fix and another reading), each
  starting with about 46,000 tokens of context. Say this before a large run. Every line `next` prints names the
  model to launch the subagent with (`--curator` for curate and fix, `--reviewer` for the reading).
- An API reader (`--reviewer api:<model>`): `review-api` sends each curated document, the curator's report and the
  page texts (the first 300,000 characters) to the endpoint with the reading's checklist, and writes the verdict to
  `work/review.json`. A failed call leaves the source `curated`, to be read again.

## The hand-off to the source index

For a manifest frozen in an index-sources project, `status --apply` appends one line per settled source to
`<project>/.scripts/<topic>/kg/<run name>/extraction_status.jsonl`:

```json
{"source_id": 12, "topic": "co2rr", "kg": "<run name>", "status": "extracted", "schema_version": "0.5.0",
 "nodes": 18, "edges": 25, "date": "2026-10-19", "note": "scale-catal document: <folder>"}
```

`status` is `extracted`, `no_data`, `rejected` or `failed`. index-sources' next export reads these lines into its
`extractions` table and the index's Extracted column.
