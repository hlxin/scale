# Many sources: a curation run

The procedure in [SKILL.md](../SKILL.md) turns one source into a scale-catal document. A run applies it to every
source of a frozen corpus, one subagent per source, and keeps the bookkeeping. Each document is checked by SCALE's own
tools; the run only hands out the work and records what came back.

## Standing rules

- **One data format.** Every document is a scale-catal document. It is written in a working folder made by `scale
  source start`, following the procedure in SKILL.md, and checked by `scale source check`. A run has no schema,
  graph format, validator, merge or viewer of its own, and its scripts never read or write a document's records.
- **SCALE's schema.** What a source reports that the schema cannot express goes in the record's `unmodeled` list
  and becomes a gap. Only `missing_concept` gaps go to schema evolution: the evolve-schema skill, where a person
  decides. Never draft, extend or change a schema here.
- **Rights.** Each source's `rights.yaml` follows the copy read. Quotes stay within the copyright cap, which `scale
  source check` reports, and claims are in the curator's own words. Supporting information belongs to its source's
  Source: `prepare` appends its text to the source's page texts as pages `[page S1]`, `[page S2]` and so on.
  Documents stay in the run folder. Only what a person clears is shared (`finish --public`) or contributed.
- **A second reading is not a review.** The reader is another agent. A model other than the curator's (or one behind
  an API) reads more independently than the curator's own model, but no agent is an independent reviewer: a person
  reviews a document before it counts as reviewed. Skipping the second reading is the user's choice, never yours, and
  always advised against.
- **Scripts keep the books; subagents read.** Never write a document, a curator's report, a second reading or a state
  line yourself, and never fix a subagent's document by hand. Hand it back with `next --role fix`.
- **Nothing is deleted.** Every report and prompt stays in the run folder.
- **People decide.** Agents never commit documents to hlxin/scale, push to `main`, approve or merge. A contribution is
  `scale graph contribute --write` on an `agent/…` branch, then a pull request that a person approves.
- A bare `curate_run.py` means `python3 -I ${CLAUDE_SKILL_DIR}/scripts/curate_run.py`. Each script prints JSON. The
  SCALE command is `scale` by default; give another with `--scale "<command>"` at `prepare`, for example `--scale
  "uv run --project <checkout of hlxin/scale> scale"`. The run remembers it.

## Procedure

1. **Freeze the corpus** (SKILL.md, step 1). For an index-sources topic, run `python3 -I
   ${CLAUDE_SKILL_DIR}/../index-sources/scripts/freeze_corpus.py --topic <slug> --name <corpus> [rule]`; it writes
   `sources/<slug>/corpora/<corpus>/sources.json`. Every candidate of the topic
   gets a status there: `in_scope` for those to curate, or the reason it is left out. Then fetch-corpus fetches the
   included sources' files and settles the manifest (`settle_corpus.py`: each source's PDF and SI, or
   `not_retrieved` with why). Any other manifest works too. `scale corpus check <manifest>` must report ok. Show the
   counts and the rule; a person confirms.
2. **Ask, then prepare.** One `AskUserQuestion` with two questions, before anything starts:
   - *Which model curates?* Opus (Recommended: the procedure is demanding) · Sonnet · Fable · Haiku (cheapest; short
     or simple sources).
   - *Who reads each document a second time?* A different Claude model (Recommended: Sonnet when Opus curates, Opus
     otherwise) · a model behind an OpenAI-compatible API (its base URL and model; the key goes in index-sources'
     key file, `~/.scale/sources/keys.txt`, as `llm_api_key: …`, never through the chat) · Skip (not recommended:
     documents then pass on SCALE's checks alone, and the index says they were not read a second time).

   Then `curate_run.py prepare --corpus <manifest> --run <run folder> --curator <model> --reviewer <model |
   api:<model> | skip> [--api-base-url <url>] [--ids 12,57 | --ids-file F | --max N] [--version <v>] [--contributor
   <id>] [--project <id>]`; prepare refuses to start without both. To curate the sources a question finds, take their
   IDs from index-sources' vector store: `vectors.py search "<question>" --by-source --k 50 --ids-out ids.txt`,
   then `--ids-file ids.txt`. For a topic, the run folder is
   `sources/<slug>/curation/<run name>`. Prepare starts one working folder per included source whose PDF is on
   disk, with `scale source start --doi --pdf`, and appends the SI pages. It paces Crossref at one lookup per second
   and starts a folder from the PDF alone when the DOI lookup fails; the curator then fills the Source's metadata. To
   contribute later to a graph that pins an older schema version (`graphs/catal-commons` pins 0.2.0), pin that version
   with `--version`. Re-running prepare resumes.
3. **Pilot: 5 sources.** Run the loop below with `--n 5` once. Show, for each source: the records added, one record
   with its evidence, the check (errors, conformance, the cap), the gaps and the second reading's verdict. Then ask:
   continue with every source (Recommended), stop, or change the selection. A source the checklist does not fit
   comes back `no_data` with the reason in its report.
4. **The loop**, until `status` reports every source settled:

   ```
   - [ ] curate_run.py next --run <dir> --role curate --n <batch>
           -> one subagent per printed line, all in ONE message, with the line's `model`: the prompt "Read <prompt>
              and follow it exactly."
   - [ ] curate_run.py status --run <dir>                 (runs scale source check on every folder that changed)
   - [ ] curate_run.py next --run <dir> --role review --n <batch>   -> second-reading subagents, same pattern
           (an API reader: curate_run.py review-api --run <dir> --n <batch> instead; skip: no reading step)
   - [ ] curate_run.py status --run <dir>
   - [ ] curate_run.py next --run <dir> --role fix --n <batch>      -> fixing subagents (check errors, reading issues)
   - [ ] repeat; status lists what each state waits for
   ```

   Batches: start at 5, go up to 10–15 after clean batches, and back to 5 after failures or for long sources. Claude
   Code runs at most 20 subagents at once by default (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`) and refuses more instead
   of queueing them, so a batch stays at 15 or fewer (15 in one message ran together on 2026-10-22). Each subagent
   starts with about 46,000 tokens of context
   before it reads anything, so a source costs at least three of those (curate, read, often a fix). A curator gets
   one source and this skill's procedure, on the model the user chose. Batching
   details and the states: [batches.md](batches.md). If you cannot launch subagents, follow
   each prompt yourself, one source at a time. Curate first; do the second reading later as a separate, skeptical
   pass over a document you no longer remember writing.
5. **Record** with `curate_run.py status --run <dir> --apply`. It appends the settled sources to `state.jsonl`. For an
   index-sources topic, it also writes their results to
   `.scripts/<topic>/kg/<run name>/extraction_status.jsonl` and runs index-sources' export, so the index shows
   them at once (its Extracted column; `index` in the JSON says what the export did).
6. **Finish:** `curate_run.py finish --run <dir> [--public] [--bundle]`. It runs `scale source finish` on every passed
   document that holds records: the evidence index, and with `--public` the copy with quoted text capped, the one to
   share.
7. **Gaps and questions.** `status` counts the gaps by kind: those on the documents' records and the gap reports
   in each folder's `work/gaps/`. It lists the `missing_concept` ones. Route each with `scale gap issue <gap.json>`
   (a dry run) to the evolve-schema skill; a person decides. To query the documents together,
   run `curate_run.py assemble --run <dir>`. It adds every passed document, with `scale graph contribute --write`, to
   a local graph kept as parts in `<run>/graph/` (never the repository), and builds it with `scale graph build`. Then
   follow query-graph for questions, map-coverage for a coverage map, scan-conflicts for sources that disagree, and
   export-graph for an export.
8. **Contribute**, only when a person asks: `curate_run.py contribute --run <dir> --to <checkout of
   hlxin/scale>/graphs/catal-commons`. This is a dry run of `scale graph contribute` for each passed document; it
   reports what would change, or why SCALE refuses (the same source already there, another schema version). Show the
   report. Writing (`--write`) happens on an `agent/…` branch after the person's review, and a pull request follows.
   graphs/ holds no quoted text of a source in copyright (its `rights.yaml` sets the limits to 0), and every record is
   public.

## Orchestrated mode (invoked by another skill or agent)

Inline arguments, for example `corpus=<manifest> run=<dir> curator=opus reviewer=sonnet ids=12,57 version=0.5.0
wrapper_confirmed=true` (`reviewer=api:<model> api_base_url=<url>`, or `reviewer=skip` when the user chose it). With
`wrapper_confirmed=true` there is no intake question: prepare, run the pilot, and still show the pilot result (a new
decision), then continue to step 6. Without `curator` and `reviewer`, ask them (step 2) even when confirmed. Return a short summary: the sources settled per state, the gaps, the run folder,
and the sources without a PDF.
