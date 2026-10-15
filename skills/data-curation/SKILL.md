---
name: data-curation
description: Extracts structured knowledge from a topic's downloaded papers into a knowledge graph, following a schema the user provides (never generated). Reads the paper index built by paper-acquisition (publications/papers.db or the topic's index CSVs), runs one extraction subagent and one independent reviewer per paper with verbatim provenance on every assertion, validates every fragment with scripts, and merges deterministically into graph.json (NetworkX node-link JSON) with alias resolution, figure crops, flat CSV tables and interactive HTML views in publications/TOPIC/kg/NAME/. Writes each paper's Extracted status, and any abstract copied from the PDF, back to the index. Also answers questions over a built graph with cited scientific reports. Use when the user wants to extract data from papers, build a dataset or knowledge graph with a schema, curate a corpus, or ask questions of a curated corpus. Finding and downloading papers belongs to paper-acquisition; the end-to-end chain to research-curation-pipeline.
allowed-tools:
  - Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*)
---

# Data Curation — extraction + knowledge graph from a given schema

Xin's Research Group, Virginia Tech. Topic-agnostic: the domain comes from the user's topic and schema.

## Standing rules (apply for the whole task)

- **English only** with the user, in every message.
- **The schema is the user's.** Extract exactly its node types, properties and edge types. Never add, rename or
  "improve" a type, property or allowed value, and never induce a schema from papers. If the papers do not fit,
  show the user what is missing (with examples) and let them decide. Details: [references/schema_format.md](references/schema_format.md).
- **Faithfulness is non-negotiable** — source-only, verbatim provenance on every assertion, no cited-literature
  values, no vocabulary substitution, no fabricated required values ([references/faithfulness.md](references/faithfulness.md)).
- **Two roles per paper.** An extraction subagent writes the fragment; a separate reviewer subagent audits it against
  the PDF (text and figure crops). The reviewer may be switched off only when the user asks.
- **Scripts do the exact work; you do the judgment.** Paper selection, prompts, validation, settling, merging, tables
  and views come from the scripts below. Never write fragments, graph.json or tables yourself and never write
  replacement code — fix the input and re-run. Trust a subagent's PASS only together with its literal validator
  stdout; `review_status.py` re-validates every fragment in its own process anyway.
- **Every decision question uses `AskUserQuestion`** (clickable options + "Other"; at most 4 options per question).
  Once a run exists (after `prepare_run.py`), run `review_status.py --topic <t> --name <n> --await-user "<question>"`
  before asking and `--resume` after the answer, so the Stop hook does not push past the question.
- **Nothing is deleted.** Superseded, rejected and unused files move inside `.scripts/<topic>/kg/<name>/`. Agent files
  live in `.scripts/`; deliverables in `publications/<topic>/kg/<name>/`.
- Run every command from the **project root**. A bare script name (`prepare_run.py ...`) means
  `python3 -I ${CLAUDE_SKILL_DIR}/scripts/prepare_run.py ...`. Scripts print JSON on stdout.

## Step 0 — banner (interactive invocations only)

Your first message is exactly this block, copied verbatim, before any tool call:

```
┃ DATA CURATION · Xin's Research Group, Virginia Tech
┃ given schema + topic index → extraction → knowledge graph
┃ modes: build · resume · ask · visualize
```

Skip it when invoked by another skill or with inline `key=value` arguments (orchestrated mode, last section).

## Step 1 — intake

`prepare_run.py --list-topics` shows indexed topics (papers, in scope, downloaded) and existing graphs. Mode: a
graph for the topic exists and is unfinished → **resume** (`prepare_run.py --topic <t> --name <n> --status`);
a question about a built graph → **ask**; "show me the graph" → **visualize**; otherwise **build**.

For build, ask only what is missing, in ONE `AskUserQuestion` call:
1. **Topic** (from the list; a topic without an index or without downloads → offer paper-acquisition / the pipeline).
2. **Schema** — the path to their schema file (plain text). Not JSON (a table, field list, protocol, spreadsheet) →
   convert it faithfully ([references/schema_format.md](references/schema_format.md)), show the summary, get approval.
   No schema named → ask for one (point to `examples/schema.catalysis.example.json` for the format); a schema file you
   find in the project but the user did not name is only offered as an option ("use schemas/x.json?"), never used
   silently. Never draft one yourself.
3. **Which papers**: all downloaded in-scope research papers (Recommended) · only relevance ≥ 4 · a subset (Topic
   A/B/C subjects, years or IDs — they say which) · include reviews too. **Options** (`multiSelect`): Figure crops
   (Recommended) · Independent reviewer (Recommended) · Copy missing abstracts from the PDFs into the index
   (Recommended).

## Step 2 — prepare

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/check_schema.py <schema file>
python3 -I ${CLAUDE_SKILL_DIR}/scripts/prepare_run.py --topic <t> --schema <schema file> [--name <n>] \
  [--min-relevance 4] [--subject "CO2RR,Copper catalysts"] [--doc-types article,preprint,review] [--year 2015-2026] \
  [--no-figures] [--no-reviewer] [--no-abstracts]
```

Show the readable schema summary and the selection (selected, with PDF, without PDF, skipped by reason) and ask:
Start the 5-paper pilot (Recommended) · Change the selection · Stop — unless the user already said to go ahead (or
`wrapper_confirmed=true`). Papers without a PDF cannot be extracted: offer paper-acquisition's Download mode for
them, or continue with the downloaded ones. Large runs (> 200 papers): say the cost (about two Sonnet calls per paper).

## Step 3 — pilot (5 papers), then the full loop

Pilot = the loop below with `--n 5`, once. Then show: nodes/edges per paper, two sample nodes with their evidence,
validator results, reviewer verdicts, and `_pending_vocab_addition` values. Ask: Continue with all papers
(Recommended) · Stop — I will adjust the schema · Change the selection. You never edit the schema.

```
- [ ] next_batch.py --topic <t> --name <n> --role extract --n <batch>
        -> one Agent per printed line in ONE message: subagent_type "general-purpose", model "sonnet",
           prompt "Read <prompt> and follow it exactly."
- [ ] review_status.py --topic <t> --name <n>                    (validates the new fragments)
- [ ] next_batch.py ... --role review --n <batch>  -> reviewer Agents, same pattern (skip if reviewer off)
- [ ] review_status.py ... --apply                                (settles papers; lists needs_fix)
- [ ] next_batch.py ... --role fix --n <batch>     -> corrective extraction Agents, then review them
- [ ] repeat until review_status.py reports "all papers settled"
```

Batch size: start at 5, up to 10-15 after clean batches, back to 5 after failures or for long PDFs. Details, model
tiers and the rules for invalid / rejected / failed papers: [references/pipeline.md](references/pipeline.md).
If you cannot launch subagents (no Agent tool — e.g. you are yourself a subagent), carry out each printed prompt
yourself, one paper at a time, exactly as written (extraction first, then the review of a fragment as a separate,
skeptical pass), and keep the same files and scripts.

## Step 4 — merge and aliases

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/merge_graph.py --topic <t> --name <n>
python3 -I ${CLAUDE_SKILL_DIR}/scripts/next_batch.py --topic <t> --name <n> --role alias   # one reviewer Agent
```

The alias reviewer writes `alias_map.proposed.json` (lexical variants + semantic synonyms among hub nodes, respecting
the schema's `never_merge`). Show the merges and ask: Apply all (Recommended) · Apply some (say which) · None. Copy
the approved merges to `.scripts/<t>/kg/<n>/alias_map.json`, then re-merge:
`merge_graph.py --topic <t> --name <n> --alias-map`. Optional figure QA sweep: [references/figure_qa.md](references/figure_qa.md).

## Step 5 — validate

`validate_kg.py publications/<t>/kg/<n>/graph.json --strict` must pass; then the Layer-2 checks in
[references/pipeline.md](references/pipeline.md) (orphans, suspicious hubs, provenance coverage, pending vocabulary).
Fix by re-extracting the papers involved or correcting the alias map — never by editing graph.json.

## Step 6 — release

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/export_tables.py --topic <t> --name <n>
python3 -I ${CLAUDE_SKILL_DIR}/scripts/build_view.py publications/<t>/kg/<n>/graph.json --out publications/<t>/kg/<n>/views/overview.html --title "<n>"
python3 -I ${CLAUDE_SKILL_DIR}/scripts/build_view.py publications/<t>/kg/<n>/graph.json --schema --out publications/<t>/kg/<n>/views/schema.html
python3 -I ${CLAUDE_SKILL_DIR}/scripts/kg_search.py index publications/<t>/kg/<n>/graph.json --db .scripts/<t>/kg/<n>/index.sqlite
python3 -I ${CLAUDE_SKILL_DIR}/scripts/release.py --topic <t> --name <n>
```

Then refresh the paper index so its Extracted column shows the run: run paper-acquisition's
`export.py --topic <t>` (the release JSON prints the command; hand-off contract: [references/handoff.md](references/handoff.md)).
Report: papers extracted / no data / rejected / failed, nodes and edges by type, provenance coverage, and where things
are (`graph.json`, `tables/`, `views/overview.html`, `README.md`).

## Ask mode (questions over a built graph)

Plan terms + synonyms + labels (+ numeric filter, + provenance filters such as `--access OA,OA+ND`,
`--exclude-record-type review`), run
`kg_search.py query --db .scripts/<t>/kg/<n>/index.sqlite --terms "..." [--labels ...] --out publications/<t>/kg/<n>/answers/<slug>.json`,
check coverage (broaden when thin), then write a standalone scientific answer with author-year citations and an APA
reference list — in chat and as an HTML twin with `build_view.py --subgraph`. Full method and the presentation rule:
[references/ask_and_visualize.md](references/ask_and_visualize.md).

## Visualize mode

`build_view.py` on `graph.json` (`--schema` for the type-level overview, `--focus-node <id> --neighbors 2` or
`--query <text>` for a focused view). One self-contained HTML file, figures embedded.

## Utility scripts (`${CLAUDE_SKILL_DIR}/scripts/`, run with `python3 -I`)

| Script | What it does |
|---|---|
| `check_schema.py` | validate + summarize a given schema |
| `prepare_run.py` | `--list-topics`; select papers, freeze the schema, start/resume a run; `--status` |
| `next_batch.py` | prompts for the next papers: `--role extract / review / fix / alias` |
| `review_status.py` | per-paper state, re-validation, `--apply` settles; `--await-user` / `--resume`; `--phase` |
| `validate_kg.py` | structural validator (fragments or graph.json; `--strict` for release) |
| `merge_graph.py` | deterministic merge, papers.db enrichment, alias map, hubs |
| `extract_figures.py` | figure candidates from PDF pages (used by extraction subagents) |
| `si_text.py` | text of .docx / .xlsx / .pptx SI files that `Read` cannot open (used by subagents) |
| `export_tables.py` | graph → CSV tables (+ records.csv from the schema's record_view) |
| `build_view.py` | interactive HTML views |
| `kg_search.py` | `index` / `query` (DeepAsk retrieval for ask mode) |
| `release.py` | tidy figures, deliverable README, phase done |
| `check_resume.py` | the project's Stop hook (keeps a live run going) |

Graph format and id rules: [references/kg_format.md](references/kg_format.md). Large corpora and sharding:
[references/scaling.md](references/scaling.md). Requires Python 3.10+ with `pypdf` and `pymupdf`.

## Orchestrated mode (invoked by another skill)

Inline arguments, e.g. `topic=co2rr schema=path/to/schema.json name=co2rr-catalysts wrapper_confirmed=true`; also
`min_relevance=`, `subject=`, `doc_types=`, `year=`, `max_papers=`, `figures=false`, `reviewer=false`,
`fill_abstracts=false`, `mode=build|resume|ask`. No banner and no intake questions when `wrapper_confirmed=true`:
prepare, run the pilot and still show the pilot result for the schema-fit decision (it is a new decision), then
continue through release. Return a short summary: counts, deliverable paths, papers without PDF.
