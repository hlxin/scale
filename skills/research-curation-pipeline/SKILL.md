---
name: research-curation-pipeline
description: Front door for the papers-to-knowledge-graph pipeline. Runs the whole chain for a topic — index every paper, preprint, patent and dataset into publications/papers.db and the topic's index files, download the chosen access types, then extract a knowledge graph with the schema the user gives — or just the stage the request needs, asking 1-3 questions only when intent is genuinely ambiguous. PREFER this as the default entry point whenever the user wants to build a dataset or knowledge graph FROM academic papers and has NOT scoped the task to a single stage, e.g. "build a knowledge graph of X from the literature", "collect papers and extract data", "here is my schema, curate the CO2RR papers", "I don't know where to start", or a topic plus a schema with no instructions. Defer to paper-acquisition (only find, index, update or download papers) or data-curation (only extract from papers already downloaded, schema in hand) when the user clearly scopes the task to that stage. (Xin's Research Group, Virginia Tech.)
---

# Research Curation Pipeline — the front door

The user sees ONE pipeline: topic → index → papers → knowledge graph. Internally you hand off to `paper-acquisition`
(index, download, update) and `data-curation` (extraction + knowledge graph with a given schema) and step out of the
way.

## Standing rules

- **English only** with the user, in every message.
- **Never name the sub-skills, "routing" or internal state checks** in user-facing text. The user's model is: "I
  asked the pipeline for X, it asked 1-2 questions, then it produced the result." File paths the user needs (the keys
  file `~/.paper-acquisition/keys.txt`, output folders) are fine to show.
- **Every decision question uses `AskUserQuestion`**; plain text only for free-form input and status lines.
- **At most 3 questions**, then ONE consolidated confirmation. Decide silently when one reading clearly dominates.
- **The schema comes from the user.** Never draft one from a topic. If the user describes the fields they want in
  words or a table, that IS their schema: convert it faithfully with data-curation's rules (its
  `references/schema_format.md`; validate with its `scripts/check_schema.py`), keep their original wording beside the
  draft (`.scripts/<slug>/kg/schema_source.txt`), and get approval in the confirmation. A missing unit or an ambiguous
  field is asked there too — never guessed. No schema and extraction wanted → ask for one, or offer to index and
  download now and extract once they have it.
- **API keys never go through the chat** — they belong in `~/.paper-acquisition/keys.txt` (the collection stage
  explains which ones help).
- You write no corpus files. A schema you converted goes to `.scripts/<slug>/kg/schema_draft.json`; every agent file
  lives under `.scripts/`; `publications/` holds `papers.db`, the topic folders and exports.

## Step 1 — banner (first message, before any tool call)

```
┃ CURATION PIPELINE · Xin's Research Group, Virginia Tech
┃ topic → index → papers → knowledge graph
```

## Step 2 — what already exists (silent unless something matters)

- Indexed topics: `.scripts/*/config.json` (folder name = topic slug) and `publications/<slug>/index/`; graphs:
  `publications/<slug>/kg/*/schema.json`; an unfinished graph: `.scripts/<slug>/kg/<name>/state.json` with
  `phase != "done"`.
- A named topic that exists → likely intents: download what is missing, update with newer papers, build a graph from
  it, or continue an unfinished graph — ask only if the request does not say. Its saved settings
  (`.scripts/<slug>/config.json`: `download.access_types`, `screening`) answer the collection questions unless the
  user changes them; show them in the plan instead of asking again.
- Nothing relevant exists → say nothing about it and continue.

## Step 3 — read the input and infer the intent (no opening question when the message has content)

| Input | Intent |
|---|---|
| topic only, "find / index / list papers" | index (collection, no download unless asked) |
| topic + "download / get the PDFs" | index + download |
| existing topic + "new / recent / latest papers" | update |
| topic + schema (file path, pasted JSON, a table or a field list) | full chain: index → download → graph |
| existing downloaded topic + schema | graph only |
| "ask / what does the literature say about ..." about a built graph | ask (data-curation ask mode) |
| unclear | ask |

Slug: an existing topic folder, or a short hyphenated form of the topic (`MXene HER electrocatalysts` → `mxene-her`).

## Step 4 — the questions (only the missing ones, one `AskUserQuestion` call)

Read the user's words first: "open access" = OA + OA+ND; "free / anything I can read" adds Free-to-read;
"everything / including paywalled" = all four. Ask only what the words leave open:
1. **Access types to download** (`multiSelect: true`; every paper is indexed regardless): OA · OA+ND · Free-to-read ·
   Paywalled (library EZproxy; campus or VPN; slow — about 120 papers per publisher per day). Remembered preference
   (auto-memory) = "(Recommended)"; otherwise recommend OA and OA+ND. Skip it for an index-only request: it is asked
   when the user later downloads (then omit `access=` from the hand-off; the collection stage keeps its own default).
2. **How to decide relevance and topics**: Claude reads every title + abstract (Recommended) · an OpenAI-compatible
   API you host (base URL + model) · a keyword list · no screening.
3. For a graph: **which papers and options** — all downloaded in-scope research papers (Recommended) or a subset
   (relevance ≥ 4, some topics, a year range); options: figure crops, independent reviewer, copy missing abstracts from
   the PDFs (all Recommended). Or one genuinely open item (which topic, update vs download-missing).

Bad questions: batch sizes, parallelism, retries, file layout, which internal stage to use. Still unclear after 3
questions → state your best reading in one sentence and ask yes / no / different.

## Step 5 — ONE consolidated confirmation

One `AskUserQuestion` with the plan in its description and options **Proceed · Change something · Cancel**:

```
Topic: <topic>  →  publications/<slug>/  (index + papers; index only: publications/<slug>/index/) and publications/papers.db
Now:   <existing topic: N papers, M in scope, K downloaded, last update <date>>          (existing topics only)
Index: every paper, preprint, patent and dataset from the automated sources; dedup; access + exact license;
       relevance + Topic A/B/C with <method>; every paper's SI listed before any download
  or Update: everything new since <last run − 30 days> on every source + citation chasing; re-check access,
       retractions and preprints of the older papers
Download: <access types> — you see the numbers before anything is downloaded   (or: no download now)
Graph: schema <name> v<version> (<n> node types, <m> edge types) on <selection>; pilot of 5 papers first
       → publications/<slug>/kg/<name>/ (graph.json, tables, views)                (only when a graph is requested)
       (no schema given → "a graph needs your schema; I can build it later")
Time: index ~minutes-hours; open downloads hours; paywalled days; graph ~2 subagent calls per paper
```

For an update, also say how many in-scope papers of the chosen access types are still not downloaded and offer them
as part of the plan; if the user takes them, hand off a separate `mode=download` call after the update reports.

## Step 6 — hand off, then step out

Index, download or update (one call per stage; the collection stage still shows its download numbers and asks
before downloading — pass `auto_download=true` only if the user explicitly said to download without stopping):

```
Skill(skill="paper-acquisition",
      args='topic="<topic>" slug=<slug> mode=<index|download|update> access=<OA,OA+ND,...> \
            screening=<claude|api|keywords|none> [base_url=<url> model=<name>] [fill_abstracts=true] wrapper_confirmed=true')
```

Full chain: `mode=index`, then (after it reports) `mode=download` — with `fill_abstracts=true` when the user kept the
graph option "copy missing abstracts" or asked for abstracts — then the graph. Graph:

```
Skill(skill="data-curation",
      args="topic=<slug> schema=<path to the user's schema.json> name=<schema name> wrapper_confirmed=true \
            [min_relevance=<n>] [subject=<labels>] [figures=false] [reviewer=false] [fill_abstracts=false]")
```

data-curation still shows its 5-paper pilot so the user can judge whether their schema fits — a new decision. When it
releases the graph, the collection stage's `export.py --topic <slug>` refreshes the index (Extracted column, copied
abstracts); make sure it ran. Once you have handed off, do not narrate, wrap or repeat the sub-skill's output.

## Smart behaviors

- Combine intents naturally ("index the CO2RR literature and build the graph with this schema" is one plan).
- Honor explicit overrides ("just index, I'll extract later" → index only even if a schema is present).
- Several topics → one plan listing each; one folder per topic, one database row per paper (shared papers are
  downloaded once).
- A graph requested on a topic whose papers are not downloaded → the plan includes the download stage first.
- Never overwrite a schema the user already saved; a changed schema becomes a new graph name unless they say replace.

## Anti-patterns

- Opening with "How would you like to begin?" when the message already says what to do.
- Drafting a schema the user did not give; naming internal skills; narrating after the hand-off.
- Asking the collection choices again after Step 4 answered them; more than 3 questions; plain-text decision questions.
