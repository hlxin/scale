---
name: curate-corpus
version: 0.2.0
description: Curate a frozen corpus of downloaded papers into scale-catal documents, one per source, by running the curate-source procedure on each (scale source start, check, finish) through subagents in small batches, with a second reading of every document, resumable state, and each source's result handed back to the paper index. Use when many papers (a topic's downloads from paper-acquisition, or any corpus manifest whose sources have PDFs) are to become scale-catal documents. It has no schema, format, validator or merge of its own.
scale_release: ">v0.2.0"
inputs:
  - A frozen corpus manifest that `scale corpus check` accepts, whose included sources have their PDF (and SI) on disk (paper-acquisition's freeze_corpus.py writes one per topic)
  - Which included sources to curate (all, a list, or the first N) and the schema version to pin (SCALE's head, or the version of the graph the documents will join)
  - Who curates (a stewardship registry id) and for which project
  - Which model curates each source (Opus, Sonnet, Fable or Haiku), and who reads each document a second time — another Claude model (recommended, a different one from the curator), a model behind an OpenAI-compatible API, or no one (skip, always advised against): asked before the run
  - SCALE's tools (the `scale` command, from a version after v0.2.0 for `scale source`; in a checkout of hlxin/scale, `uv run scale`)
allowed-tools:
  - Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*)
  - "scale corpus check <manifest>"                          # the frozen corpus, before the first source
  - "scale source start --doi <doi> --pdf <file> --out <dir>"   # one working folder per source (curate_run.py prepare)
  - "scale source check <dir> [--derive-links]"              # the document against its schema, its page texts and the cap
  - "scale source finish <dir> [--public] [--bundle]"        # the evidence index; a copy to share
  - "scale call skills '{\"name\": \"curate-source\"}'"      # the procedure every curator follows
  - "scale graph describe [labels] --domain catalysis"       # what the schema can express
  - "scale pages render | region | agree | check"            # figures and pages whose text loses values
  - "scale graph contribute <graph> --to <folder>"           # a dry run; --write only into the run's local graph, or after a person's review
  - "scale graph build <folder>"                             # the run's local graph, to query
  - "scale gap issue <gap.json> (dry run)"                   # missing concepts, for evolve-schema
  - read access to the corpus PDFs and SI; write access to the run folder only
outputs:
  - One SCALE working folder per source (`scale source start`), holding its scale-catal document pinned to the schema version, its rights.yaml and its check report
  - The curator's report and the second reading of every source, and the run's settled states (state.jsonl)
  - Each source's result in the paper index (extracted, no_data, rejected or failed), through paper-acquisition's hand-off file
  - The gaps the documents record, routed to evolve-schema as a dry run
validation:
  - "`scale corpus check <manifest>` reports ok before the first source"
  - "`scale source check <dir>` reports ok (zero errors, every quote found verbatim in the page texts, the cap respected) for every document settled as passed"
  - Every passed document had a second reading after its last change (another subagent, or the API model), and that reading passed it — unless the run was prepared with --reviewer skip, which run.json, state.jsonl and the paper index record
  - "`curate_run.py status` accounts for every source picked: settled (passed, rejected, failed) or still in a state with a next step"
human-review:
  - Before the run starts (the corpus, how many sources, the cost) and after the pilot (5 sources), on whether the checklist and the procedure fit the corpus
  - Always before a document is treated as reviewed, shared beyond the run folder, or contributed (`scale graph contribute --write`, then a pull request a person approves)
  - Whenever a gap of kind missing_concept is raised, and whenever entity resolution would merge records across sources
  - Whenever the second reading rejects a source, or a source fails after three fixes
---

# Curate a corpus into scale-catal documents

curate-source turns one source into a scale-catal document. This skill runs that procedure over a frozen corpus,
one subagent per source, and keeps the bookkeeping. Each document is checked by SCALE's own tools; this skill only
hands out the work and records what came back.

## Standing rules

- **One data format.** Every document is a scale-catal document. It is written in a working folder made by `scale
  source start`, following the curate-source skill, and checked by `scale source check`. This skill has no schema,
  graph format, validator, merge or viewer of its own, and its scripts never read or write a document's records.
- **SCALE's schema.** What a source reports that the schema cannot express goes in the record's `unmodeled` list
  and becomes a gap. Only `missing_concept` gaps go to schema evolution: the evolve-schema skill, where a person
  decides. Never draft, extend or change a schema here.
- **Rights.** Each source's `rights.yaml` follows the copy read. Quotes stay within the copyright cap, which `scale
  source check` reports, and claims are in the curator's own words. Supporting information belongs to its paper's
  Source: `prepare` appends its text to the paper's page texts as pages `[page S1]`, `[page S2]` and so on.
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

1. **Freeze the corpus** (curate-source, step 1). For a paper-acquisition topic, run `python3 -I
   ${CLAUDE_SKILL_DIR}/../paper-acquisition/scripts/freeze_corpus.py --topic <slug> --name <corpus> [rule]`; it writes
   `publications/<slug>/corpora/<corpus>/sources.json`. Every candidate of the topic
   gets a status there: `in_scope` for those to curate, or the reason it is left out. Any other manifest works too.
   `scale corpus check <manifest>` must report ok. Show the counts and the rule; a person confirms.
2. **Ask, then prepare.** One `AskUserQuestion` with two questions, before anything starts:
   - *Which model curates?* Opus (Recommended: the procedure is demanding) · Sonnet · Fable · Haiku (cheapest; short
     or simple papers).
   - *Who reads each document a second time?* A different Claude model (Recommended: Sonnet when Opus curates, Opus
     otherwise) · a model behind an OpenAI-compatible API (its base URL and model; the key goes in
     `~/.paper-acquisition/keys.txt` as `llm_api_key: …`, never through the chat) · Skip (not recommended: documents
     then pass on SCALE's checks alone, and the index says they were not read a second time).

   Then `curate_run.py prepare --corpus <manifest> --run <run folder> --curator <model> --reviewer <model |
   api:<model> | skip> [--api-base-url <url>] [--ids 12,57 | --ids-file F | --max N] [--version <v>] [--contributor
   <id>] [--project <id>]`; prepare refuses to start without both. To curate the papers a question finds, take their
   IDs from paper-acquisition's vector store: `vectors.py search "<question>" --by-paper --k 50 --ids-out ids.txt`,
   then `--ids-file ids.txt`. For a topic, the run folder is
   `publications/<slug>/curation/<run name>`. Prepare starts one working folder per included source whose PDF is on
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

   Batches: start at 5, go up to 10–15 after clean batches, and back to 5 after failures or for long papers. Claude
   Code runs at most 20 subagents at once by default (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`) and refuses more instead
   of queueing them, so a batch stays at 15 or fewer (15 in one message ran together on 2026-10-22). Each subagent starts with about 46,000 tokens of context
   before it reads anything, so a source costs at least three of those (curate, read, often a fix). A curator gets
   one source and the curate-source skill, on the model the user chose. Batching
   details and the states: [references/batches.md](references/batches.md). If you cannot launch subagents, follow
   each prompt yourself, one source at a time. Curate first; do the second reading later as a separate, skeptical
   pass over a document you no longer remember writing.
5. **Record** with `curate_run.py status --run <dir> --apply`. It appends the settled sources to `state.jsonl`. For a
   paper-acquisition topic, it also writes their results to
   `.scripts/<topic>/kg/<run name>/extraction_status.jsonl` and runs paper-acquisition's export, so the index shows
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

## Orchestrated mode (invoked by another skill)

Inline arguments, for example `corpus=<manifest> run=<dir> curator=opus reviewer=sonnet ids=12,57 version=0.5.0
wrapper_confirmed=true` (`reviewer=api:<model> api_base_url=<url>`, or `reviewer=skip` when the user chose it). With
`wrapper_confirmed=true` there is no intake question: prepare, run the pilot, and still show the pilot result (a new
decision), then continue to step 6. Without `curator` and `reviewer`, ask them (step 2) even when confirmed. Return a short summary: the sources settled per state, the gaps, the run folder,
and the sources without a PDF.
