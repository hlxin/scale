---
name: curate-topic
version: 0.1.0
description: Front door from a research topic to scale-catal documents. Runs the chain for a topic — index every paper, preprint, patent and dataset (paper-acquisition), download the chosen access types, freeze the corpus, curate it into scale-catal documents (curate-corpus, which runs SCALE's curate-source on each source) and answer questions over them (query-graph) — handing each stage to its skill. Use when the user names a topic and wants any part of that chain (find or download its papers, build its graph, resume a curation, or ask what the curated papers report). SCALE's one schema applies; there is no schema of the user's.
scale_release: ">v0.2.0"
inputs:
  - A topic in the user's words, and what they want from it (an index, the papers, scale-catal documents, an answer)
  - For downloads, the access types (OA, OA+ND, Free-to-read, Paywalled) and how relevance is screened
  - For curation, the rule that freezes the corpus (which downloaded papers), and who curates for which project
allowed-tools:
  - Bash(python3 -I ${CLAUDE_SKILL_DIR}/../paper-acquisition/scripts/freeze_corpus.py *)
  - Bash(python3 -I ${CLAUDE_SKILL_DIR}/../paper-acquisition/scripts/init_topic.py --list)
  - Bash(python3 -I ${CLAUDE_SKILL_DIR}/../curate-corpus/scripts/curate_run.py status *)
  - "scale corpus check <manifest>"                          # the frozen corpus
  - "scale call skills '{\"name\": \"<skill>\"}'"            # SCALE's procedures: query-graph, map-coverage, scan-conflicts, export-graph
  - "scale graph describe [labels] --domain catalysis"       # what the schema can record, for the user's fields
  - "scale graph query <graph> <plan.yaml>"                  # questions, by the query-graph procedure
outputs:
  - What each stage produces, in its own place - the paper index and the downloads (paper-acquisition), the frozen corpus manifest, the run folder with its scale-catal documents and their local graph (curate-corpus), answers with their query plans (query-graph)
  - One plan the user confirmed before anything ran, and a short summary after each stage
validation:
  - Each stage's own validation - paper-acquisition's status counts, `scale corpus check` on the manifest, `scale source check` on every document, the query-graph rules for every answer
  - Nothing is downloaded, curated or contributed beyond the plan the user confirmed
human-review:
  - The plan, before anything runs (the topic, the access types, the screening, the corpus rule, the curation pilot)
  - Every decision a stage asks for - the download numbers, paywalled access, the pilot of 5 sources, any contribution
  - Before an answer supports a publication, a decision or a new experiment
---

# Curate a topic: from the literature to scale-catal documents

The user sees one pipeline: topic → index → papers → frozen corpus → scale-catal documents → answers. Each stage
belongs to a skill, and this one hands off to each in turn, then steps out of the way:

- **paper-acquisition:** index, download and update, and freeze a corpus (its `freeze_corpus.py`).
- **curate-corpus:** turn the frozen corpus into scale-catal documents, one per source, through curate-source.
- **SCALE's own skills:** query-graph (answers), map-coverage (what is covered), scan-conflicts (sources that
  disagree), export-graph (handing a graph on) and evolve-schema (gaps in the schema, decided by a person).

## Standing rules

- **SCALE's one schema.** There is no schema of the user's. If the user lists fields they want, show what the
  catalysis schema records for them (`scale graph describe <Label> --domain catalysis`). A field it cannot express is
  kept in the record's `unmodeled` list and becomes a gap (`missing_concept`) for the evolve-schema skill, which a
  person decides. Never draft, extend or change a schema here.
- **Every decision question uses `AskUserQuestion`.** Ask at most 3 questions, then give ONE consolidated
  confirmation. Decide silently when one reading clearly dominates.
- **API keys never go through the chat.** They belong in `~/.paper-acquisition/keys.txt`; the index stage explains
  which ones help.
- **Where things go.** Agent files go under `.scripts/`. The index, papers and corpora go under `publications/<slug>/`.
  Curation runs go under `publications/<slug>/curation/<run>/`. Nothing is committed to hlxin/scale: a contribution
  is a dry run until a person approves it, and then a pull request on an `agent/…` branch. Agents never push to
  `main`, approve or merge.

## Step 1 — banner (first message, before any tool call)

```
┃ CURATE TOPIC
┃ topic → index → papers → corpus → scale-catal documents → answers
```

Skip it when invoked by another skill or with inline `key=value` arguments.

## Step 2 — what already exists (silent unless something matters)

- **Topics:** `python3 -I ${CLAUDE_SKILL_DIR}/../paper-acquisition/scripts/init_topic.py --list` (papers, in scope,
  downloaded, last index, last update).
- **Frozen corpora:** `publications/<slug>/corpora/*/sources.json`.
- **Curation runs:** `publications/<slug>/curation/*/run.json`. A run whose `curate_run.py status --run <dir>` still
  lists a next step is unfinished.
- A named topic that exists suggests the likely intents: download what is missing, update with newer papers, curate
  it, resume a run, or ask. Ask only when the request does not say. Its saved settings
  (`.scripts/<slug>/config.json`: `download.access_types`, `screening`) answer the collection questions unless the
  user changes them; show them in the plan instead of asking again.

## Step 3 — read the input and infer the intent (no opening question when the message has content)

| Input | Intent |
|---|---|
| topic only, "find / index / list papers" | index (no download unless asked) |
| topic + "download / get the PDFs" | index + download |
| existing topic + "new / recent / latest papers" | update |
| topic + "build the graph / curate / extract the data" | full chain: index → download → freeze → curate |
| existing downloaded topic + "curate" | freeze → curate |
| an unfinished run, or "continue" | resume the run (curate-corpus) |
| "what do the papers report about …", over curated documents | ask (query-graph) |
| "what is covered / where are the gaps" | map (map-coverage) |
| "do the sources disagree about …" | conflicts (scan-conflicts) |
| "export / share the graph" | export (export-graph); a contribution only when a person asks |
| unclear | ask |

The slug is an existing topic folder, or a short hyphenated form of the topic (`MXene HER electrocatalysts` →
`mxene-her`).

## Step 4 — the questions (only the missing ones, in one `AskUserQuestion` call)

Read the user's words first. "Open access" means OA and OA+ND. "Free" or "anything I can read" adds Free-to-read.
"Everything" or "including paywalled" means all four. Ask only what the words leave open:

1. **Access types to download** (`multiSelect: true`; every paper is indexed regardless): OA · OA+ND · Free-to-read ·
   Paywalled (through the library EZproxy, on campus or VPN; slow: at most 120 papers per publisher per day). A
   remembered preference is "(Recommended)"; otherwise recommend OA and OA+ND.
2. **How to decide relevance and topics:** Claude reads every title and abstract (Recommended) · an
   OpenAI-compatible API you host (base URL and model) · a keyword list · no screening.
3. **For curation, which papers and how:** every downloaded in-scope research paper (Recommended), or a rule
   (relevance ≥ 4, some Topic A/B/C subjects, a year range, some document or access types). The pilot of 5 sources
   always comes first.

Bad questions: batch sizes, parallelism, retries, file layout, which internal stage to use, and any schema question.
If it is still unclear after 3 questions, state your best reading in one sentence and ask yes / no / different.

## Step 5 — ONE consolidated confirmation

One `AskUserQuestion` with the plan in its description and the options **Proceed · Change something · Cancel**:

```
Topic:    <topic>  →  publications/<slug>/ (index + papers) and publications/papers.db
Now:      <existing topic: N papers, M in scope, K downloaded, last update <date>>       (existing topics only)
Index:    every paper, preprint, patent and dataset from the automated sources; dedup; access + exact licence;
          relevance + Topic A/B/C with <method>; every paper's SI listed before any download
  or Update: everything new since <last run − 30 days>, with citation chasing; access, retractions and preprints rechecked
Download: <access types>; you see the numbers before anything is downloaded   (or: no download now)
Corpus:   <rule>, frozen as publications/<slug>/corpora/<name>/sources.json (scale corpus check)
Curate:   scale-catal documents under SCALE's catalysis schema, one per source, by curate-source; a pilot of 5 first
          → publications/<slug>/curation/<run>/ (documents, reports, a local graph to query)
Time:     index minutes to hours; open downloads hours; paywalled days; curation about 3-4 subagent calls per source
```

## Step 6 — hand off, then step out

1. **Index, download or update:** one call per stage. The index stage still shows its download numbers and asks
   before downloading; pass `auto_download=true` only if the user explicitly said to download without stopping.

   ```
   Skill(skill="paper-acquisition",
         args='topic="<topic>" slug=<slug> mode=<index|download|update> access=<OA,OA+ND,...> \
               screening=<claude|api|keywords|none> [base_url=<url> model=<name>] wrapper_confirmed=true')
   ```

2. **Freeze the corpus** once the downloads the plan needs are done. Show the counts, then check the manifest with
   `scale corpus check publications/<slug>/corpora/<name>/sources.json`:

   ```
   python3 -I ${CLAUDE_SKILL_DIR}/../paper-acquisition/scripts/freeze_corpus.py --topic <slug> --name <name> \
     [--min-relevance 4] [--subject "<labels>"] [--years 2015-2026] [--doc-types article,review] [--access OA,OA+ND]
   ```

3. **Curate.** curate-corpus still shows its pilot of 5 sources so the user can judge whether the procedure fits the
   corpus; that is a new decision.

   ```
   Skill(skill="curate-corpus",
         args="corpus=publications/<slug>/corpora/<name>/sources.json run=publications/<slug>/curation/<run> \
               wrapper_confirmed=true [ids=<paper ids>] [version=<schema version>]")
   ```

   When it reports, run paper-acquisition's `export.py --topic <slug>` so the index's Extracted column shows the run.

4. **Ask, map, compare, export.** Follow SCALE's procedure for the request: `scale call skills '{"name":
   "query-graph"}'` (or `map-coverage`, `scan-conflicts`, `export-graph`). Run it over the run's local graph, which
   `curate_run.py assemble --run <dir>` builds from the passed documents. Every factual sentence of an answer comes
   from returned rows with their evidence, and absences are answers. Author interpretations are labelled as the
   authors', and extrapolations go in a separate, labelled paragraph.

Once a stage is handed off, do not narrate, wrap or repeat its output.

## Smart behaviors

- Combine intents naturally: "index the CO2RR literature and curate it" is one plan.
- Honor explicit overrides: "just index, I'll curate later" means index only.
- Several topics: one plan listing each, one folder per topic, one database row per paper (a paper shared by topics
  is downloaded once).
- Curation asked on a topic whose papers are not downloaded: the plan includes the download stage first.
- A corpus is frozen once. A new rule gets a new corpus name, and a new run a new run name. Never overwrite either.

## Anti-patterns

- Opening with "How would you like to begin?" when the message already says what to do.
- Drafting a schema, or promising fields the schema does not have, instead of routing them to gaps.
- Asking the collection choices again after Step 4 answered them; more than 3 questions; plain-text decision questions.
- Writing documents, reports or answers that a stage's skill writes, or narrating after a hand-off.
