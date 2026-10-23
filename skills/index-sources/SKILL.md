---
name: index-sources
description: Builds and maintains a per-topic index of sources - papers, preprints, patents, theses, reports and datasets - and freezes corpora from it. Index mode finds every matching source in 34 automated databases (OpenAlex, Crossref, Europe PMC, arXiv, OSTI, Zenodo; Scopus, Web of Science, Lens, EPO with keys) and keeps sources/index.db up to date in place, holding every source with abstract, exact license, supplementary information (SI) links, Topic A/B/C and related topics, and the history of every run and change (index CSVs per access type — OA, OA+ND, Free-to-read, Paywalled — on request); copies of the database updated apart merge back into one (merge_db.py). Update mode exhaustively adds newer sources (all databases, citation chasing, access and retraction recheck). Duplicates merge automatically. Also imports Web of Science, Scopus or Zotero exports with their abstracts, answers questions about the indexed sources, writes filtered lists (CSV, BibTeX, RIS) and freezes a corpus (a selection by rule) for fetching and curation. Use whenever the user wants to find, index, import or list sources on a topic, refresh a literature index, query the source database, or choose the sources to curate. Fetching the corpus's files (PDFs, SI) belongs to fetch-corpus; curating them into scale-catal documents to curate-corpus.
allowed-tools:
  - Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*)
  - Bash(nohup python3 -I ${CLAUDE_SKILL_DIR}/scripts/*)
  - "scale corpus check <manifest>"     # SCALE checks a frozen corpus (freeze_corpus.py)
version: 4.0.0
scale_release: ">=v0.2.0"
inputs:
  - A topic in the user's words, or a Web of Science, Scopus or Zotero export, a list of DOIs or a web page of them
  - How relevance is screened (Claude, an API, keywords or none)
  - Optional API keys in ~/.scale/sources/keys.txt (never through the chat) and a polite-pool contact address
outputs:
  - sources/index.db, updated in place by every step (runs and changes record how it evolved; it carries its working state, so whoever receives it can update it), with every source, preprint, patent and dataset found, deduplicated, with its access type, exact licence, SI and Topic A/B/C; the topic's index CSVs on request
  - For fetching and curation, a frozen corpus manifest (sources/<slug>/corpora/<name>/sources.json) that `scale corpus check` accepts
  - sources/vectors.db (local, like the files, since it holds their text) — every fetched source's passages with their vectors, kept in step after every fetch (vectors.py)
validation:
  - "`status.py --topic <slug>` accounts for every source: in scope or why not, and its access type"
  - "`scale corpus check <manifest>` reports ok for every frozen corpus"
human-review:
  - Before the index plan runs (queries, gate, scope)
  - Before a corpus is frozen (which sources are included, and why the others are left out)
---

# Index sources

Topic-agnostic: the research domain always comes from the user, and so does the topic vocabulary (a domain's own file;
SCALE's catalysis vocabulary is [graphs/catal-commons/literature/vocabulary.json](../../graphs/catal-commons/literature/vocabulary.json),
[references/topics.md](references/topics.md)). A source here is anything the index holds: a paper, a preprint, a patent,
a thesis, a report or a dataset; the services that find them (OpenAlex, Crossref, Scopus …) are databases. The chain:

> **index-sources** (index a topic, freeze a corpus) → [fetch-corpus](../fetch-corpus/SKILL.md) (the corpus's files) →
> [curate-corpus](../curate-corpus/SKILL.md) (scale-catal documents, one source at a time)

This skill never downloads a source's files; it finds them, lists their supplementary information, and decides which
belong to a corpus.

## Standing rules (apply for the whole task)

- **English only** with the user, in every message.
- **Index first, fetch second.** This skill downloads no source's files. A corpus is frozen only after the topic is
  indexed, deduplicated, classified and screened and its SI is listed; fetch-corpus then fetches it.
- **SI is in the index before anything is fetched.** Every in-scope source's supplementary information is looked up
  at index time (`find_si.py`, Index step 7) and listed in the index (SI column "Available (n deposits)", table
  `supplements` in index.db); fetch-corpus fetches the files listed there first.
- **Scripts do the exact work; you do the judgment.** Searching, deduplication, license decisions, the index CSVs and
  `index.db` are produced by the scripts below. Never write index files by hand, never write replacement code — if a
  script fails, read its error, fix the input (config, queries) and re-run.
- **Every decision question uses `AskUserQuestion`** (clickable options + "Other"). Plain text only for free-form
  input (a topic, a URL) and status updates.
- **API keys never go through the chat.** Keys live in `~/.scale/sources/keys.txt` as `service: key` lines.
  When a useful database needs a key, tell the user which line to add (README.md in this skill folder explains how to
  get each key) and check with `keys.py`; never ask them to paste a key, never print one.
- **Polite-pool email** goes only to OpenAlex (`mailto`), Unpaywall (`email`) and Crossref (`mailto`) — never in
  headers, never to publishers or the library proxy.
- **Nothing is deleted.** Out-of-scope, wrong or duplicate files move under `.scripts/`. Every file the agent creates
  (logs, caches, batches, configs) lives in `.scripts/`; `sources/` holds only `index.db`, `vectors.db`, the topic
  folders (`corpora/`, `files/` once fetch-corpus fetched some, and `index/` when CSVs were asked for) and `exports/`.
  A project made before the sources were so named (`publications/papers.db`) is upgraded in place by the first script
  that opens it (`upgrade.py`).
- Run every command from the **project root** (the folder that holds or will hold `sources/` and `.scripts/`).
  A bare script name (`status.py ...`) means `python3 -I ${CLAUDE_SKILL_DIR}/scripts/status.py ...`. Scripts print
  one JSON line on stdout and progress on stderr; all of them resume where they stopped when re-run.

## Step 0 — banner (interactive invocations only)

Your first message is exactly this block, copied verbatim, before any tool call:

```
┃ INDEX SOURCES
┃ index everything → index.db → freeze a corpus → fetch-corpus
┃ modes: index · update
```

Skip it when invoked by another skill or with inline `key=value` arguments (orchestrated mode, last section).

## Step 1 — what exists, which mode

`init_topic.py --list` shows the project's topics (sources, in scope, fetched, last index, last update). If the user
named a topic, `init_topic.py --slug <slug> --probe` (changes nothing).

- **A question or a list** ("how many…", "which sources…", "a BibTeX of the 2023 ACS sources on X", "check for
  duplicates") is not a mode: answer it directly, no menu ([Questions and lists](#questions-and-lists-no-mode)).
- **A file or list of sources to add** (Web of Science / Scopus / Zotero export, DOIs, a web page) → [Adding a list or
  an export](#adding-a-list-or-an-export).
- **Topic exists** → `AskUserQuestion`: Freeze a corpus from its index (then fetch-corpus) · Update — find newer
  sources (exhaustive) · New index — search again from scratch (results merge into the same list; nothing is lost).
  Its saved `config.json` settings are the defaults for everything below.
- **New topic** → Index mode; `init_topic.py` creates `sources/<slug>/`.
- Explicit wording wins: "find / index sources on" = Index; "new sources since / refresh" = Update; "download / get
  the PDFs" = freeze a corpus (or take a frozen one), then fetch-corpus.

## Step 2 — intake (at most two rounds; ask only what is missing)

One `AskUserQuestion` call with the missing item:
- **How to decide relevance and topics** — always ask, never assume (also for every subtopic of a catalog): Claude
   reads every title + abstract and picks Topic A/B/C · an OpenAI-compatible API you host (base URL + model) · a
   keyword list I draft (deterministic, free, minutes even for millions of sources; topics from the vocabulary) · no
   screening (keep everything that matches; topics from the vocabulary). Put first, marked (Recommended): Claude for up
   to ~20,000 sources; the keyword list for a larger topic (Claude would need days of subagent batches).

Second round only if needed:
- **Keys.** Run `keys.py`. If OpenAlex has no key, say once what that costs: without a key OpenAlex returns at most
  10,000 results per query (also per citation-chasing batch) and shares a small daily budget with the whole network,
  so a large index or update stays incomplete; the key is free (README). Ask: I'll add a free OpenAlex key first
  (Recommended) · Continue without it. Also list other keyed databases that would add coverage (Scopus, Web of
  Science, CORE, Lens incl. patents, EPO patents, Springer, IEEE, ADS) — optional. Adding keys: `keys.py --init`
  creates the file from the template; the user edits it; `keys.py --test` checks it.
- **API selected** → base URL and model in plain text; the key goes into keys.txt as `llm_api_key: <key>`.
- **Polite-pool email**: from auto-memory (`polite_pool_email`); if absent, ask once and store it in memory.

## Step 3 — plan the index (you write it, the user approves it)

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/init_topic.py --topic "<topic as the user said it>" --slug <short-slug> \
  --email <polite email> --screening <claude|api|keywords|none>
```

Default databases = every keyless database in the catalog + keyed databases whose keys exist ([references/databases.md](references/databases.md)).
Then write, in `.scripts/<slug>/` ([references/queries.md](references/queries.md), [references/screening.md](references/screening.md)):
- `queries.json` — 15-25 distinct queries over the main databases plus 1-2 per other selected database (preprints,
  datasets, patents, regional), each in the database's own syntax. Every selected database needs at least one query.
- `config.json` → `gate` — anchor terms every on-topic source carries (drops loose matches).
- `criteria.md` (Claude/API: topic definition, in-scope and out-of-scope lists) or `keywords.json` (keyword method).

A year limit ("from 2024 on") goes into the plan: `init_topic.py --slug <slug> --year-from 2024` (every database's date
filter, and `build_list.py` drops older works that loose databases let in; the run stays a full index).
Validate until `"ok": true`: `init_topic.py --slug <slug> --check`. Show a compact plan (queries per database, gate terms,
scope lists or keyword groups, databases waiting for keys) and ask: Approve and start · Edit (say what) · Cancel.

## Mode: Index — copy this checklist and tick it off

```
- [ ] 1 estimate the field         search.py --count-only
- [ ] 2 search every database      search.py  (background when large)
- [ ] 3 build the list             build_list.py   (gate, dedup, doc types, Topic A/B/C from the vocabulary)
- [ ] 4 citation chasing           search.py --citing  ->  build_list.py --run citing
- [ ] 5 access + license + abstracts   classify_access.py
- [ ] 6 screen relevance + topics  screen.py (claude / api / keywords / none)
- [ ] 7 supplementary information  find_si.py   (every in-scope source's SI, listed before any fetch)
- [ ] 8 duplicates (automatic)     dedup.py --apply ; ask only about its to_review pairs
- [ ] 9 report                     status.py ; topics.py summary ; offer to freeze a corpus
```

**1 · Estimate.** `search.py --topic <slug> --count-only` → on-topic estimate per database (before deduplication;
databases overlap 30-60 %; loose databases are page-1 lower bounds). If the field may exceed ~20,000 sources, ask:
Index the whole field (Recommended) · Narrow the topic · Cancel. A whole field in the hundreds of thousands (e.g.
"all of catalysis") works best as a catalog: index it once, classify and screen it whole ("Very large topics"), then
freeze a corpus from it by rule for each question and fetch that.

**2 · Search.** Large runs in the background (every query is paged to the end or to its relevance tail):

```bash
nohup python3 -I ${CLAUDE_SKILL_DIR}/scripts/search.py --topic <slug> > .scripts/<slug>/search.log 2>&1 &
```

Done when the log ends with a JSON line whose `complete` is true (re-run to resume `pending_queries`). The JSON's
`skipped_databases` lists keyed databases without a key — mention them once in the report.

**3 · Build.** `build_list.py --topic <slug>`. If it drops nearly everything (`off_topic_dropped_by_gate`) or keeps
obvious noise, fix the gate and re-run `build_list.py` (no new search needed). SI deposits found by the search are
not sources: they become SI links of their source (index SI column "Available (n deposits)"). More than ~1 million raw
hits (the search JSON's total): `build_list.py --topic <slug> --batches N` with N ≈ raw hits / 1,000,000 — one
process, one batch at a time, the index written once at the end.

**4 · Citation chasing.** `search.py --topic <slug> --citing`, then `build_list.py --topic <slug> --run citing`.
OpenAlex lists every work citing the topic's core sources; the gate keeps the on-topic ones.

**5 · Classify.** `classify_access.py --topic <slug>` — access type, exact license with version, license source, and
missing abstracts/keywords from Semantic Scholar, Europe PMC, OpenAlex and Crossref. Patents are Free-to-read. Any
size: blocks of 20,000 sources, four looked up at once, every service at its own allowed pace (20,000 sources ≈ 1.5
min; 2 million ≈ 2-3 h, bounded by Crossref's 3 requests at a time); each block is saved when decided, so a re-run
continues where it stopped. OpenAlex runs while the free daily budget or prepaid credit lasts; Unpaywall is asked only
for DOIs OpenAlex lacks and Crossref knows, never more than 90,000 calls per UTC day on this machine (Unpaywall asks
for under 100,000). Without an `s2` key, Semantic Scholar (whose shared keyless pool refuses most requests) is used
only for topics up to 20,000 sources. When the JSON says `"complete": false`, the `pending` sources keep an empty access
type: tell the user, and re-run the same command after 00:00 UTC. Never work around the cap. `--abstracts-only` fills
missing abstracts without classifying.

**6 · Screen.** By method (details in [references/screening.md](references/screening.md)):
- `none`: `screen.py --topic <slug> none` · `keywords`: `screen.py --topic <slug> keywords`
- `api`: `screen.py --topic <slug> prep` → `screen.py --topic <slug> api` → `screen.py --topic <slug> merge`
- `claude`: `screen.py --topic <slug> prep`; then repeat until `next` prints nothing: `screen.py --topic <slug> next 5`
  → five lines `batch  batch_path  output_path`; launch five `Agent` calls in ONE message (`subagent_type:
  "general-purpose"`, `model: "sonnet"`), each with the prompt *"Read <instructions path printed by prep> and follow
  it exactly. Batch file: <batch_path>. Write your output to: <output_path>."*; when they return, `screen.py --topic
  <slug> merge`. Its `proposed_new_topics` are labels outside the vocabulary — if one recurs, offer to add it
  ([references/topics.md](references/topics.md)).

**7 · SI.** `find_si.py --topic <slug>` lists every in-scope source's supplementary information in the index before
anything is fetched; nothing is downloaded. For every source, batched or read from the answers `classify_access.py`
cached: Crossref components (`<DOI>.s001`, `.s002` …: ACS, PLOS), DataCite deposits that declare IsSupplementTo the
source (publisher SI on Figshare, Zenodo, Dryad, CCDC structures, repositories), Crossref `is-supplemented-by`
relations, and the PubMed Central open-access file lists. For topics up to 50,000 sources (or with `--deep`), also
the routes that cost a request per source, at each host's polite pace: Elsevier's SI CDN (mmcN files), MDPI's CDN
(-s001 files) and the pages of publishers that serve scripted clients (Nature, Springer, BMC, Frontiers). SI that only
sits on walled sites (Wiley, RSC, ACS and IOP pages) without a deposit of its own is found by fetch-corpus's
`fetch_si.py` when the source is fetched. Answers are cached (`.scripts/enrich/si_*.sqlite`), so re-runs and updates only ask about new
sources. The JSON gives `sources_with_si` and `by_route`; the index SI column says "Available (n deposits)". A catalog
over 50,000 sources gets the batched routes; give a corpus the per-source ones with `find_si.py --topic <catalog> --ids
<file of its source IDs>`.

**8 · Duplicates (automatic, no question).** `dedup.py --apply` merges the safe cases: preprint ↔ published version
(the journal article's row keeps the preprint's link: index column Preprint link, index.db `preprint_url`),
repository copy ↔ journal article, same source without/with DOI, Angewandte twins, byte-identical PDFs, one patented
invention filed in several offices (WO, EP, US … and its HAL/OSTI copy: same title and inventors; one row keeps every
number), and SI deposits indexed as sources (they become SI links of their source). A dataset is never merged into its
source, and two numbers of one office's series (US1625924 and US1625925, same title, same day) never into one row. Each merge is logged with the full merged row. Only its `to_review` pairs go to the user — the same title
under two DOIs, nearly the same title by the same first author, or two patents with the same title whose inventors
are unknown:
show them side by side (title, DOI, venue, year; all of them in `.scripts/dedup_review.csv`) and ask: Keep them
separate (Recommended) · Merge them all · Decide pair by pair. Then `dedup.py --keep-separate all` or
`dedup.py --merge <a>:<b>,...` (a pair kept separate is never listed again). `to_review` is 0 → no question.

**9 · Report.** `status.py --topic <slug>` and `topics.py summary --topic <slug>`. Tell the user in a few lines: sources
indexed (by access type and document type), in scope, sources with SI listed (find_si `sources_with_si`), duplicates
merged, the main Topic A values, sources without abstracts, databases skipped for want of a key, and where things are: `sources/index.db` (the topic is the collection `<slug>`;
every later step updates it in place). The index CSVs are written only on request (`export.py --topic <slug> --csv`);
over 1,048,576 rows they no longer open in Excel, so point to index.db (DB Browser for SQLite) or a filtered export. Nothing was downloaded; offer
to freeze a corpus (below) and fetch it with fetch-corpus.

## After a fetch: the full-text check (optional)

Once fetch-corpus has fetched a topic's files, an optional full-text check (Claude/API): `screen.py --topic <slug> prep --stage fulltext` → `next 5 --stage
fulltext` + subagents (or `api --stage fulltext`) → `merge --stage fulltext`; sources that fall below the threshold
move to `.scripts/<slug>/out_of_scope/`.

## Freeze a corpus (the sources to fetch and curate)

A corpus is the selection a question needs, frozen by a rule: `freeze_corpus.py --topic <slug> --name <corpus>
[--min-relevance 4] [--subject "<Topic A/B/C labels>"] [--doc-types article,review] [--years 2015-2026]
[--access OA,OA+ND] [--ids FILE]` (`vectors.py search --by-source --ids-out FILE` writes the IDs that answer a
question). It writes `sources/<slug>/corpora/<corpus>/sources.json`, a corpus manifest in SCALE's format. Every
source of the topic gets a status: `in_scope` (in scope and kept by the rule: the sources to fetch and curate) or the
reason it is left out (`off_scope`, `not_screened`, `retracted`, `excluded` with a `status_reason`), and the counts add
up. `scale corpus check <manifest>` checks it. Each entry carries the source ID, DOI, title, year, access type and
licence, and for a source whose file is already on disk its paths. A corpus is frozen once: a new rule gets a new
name. Show the counts and the rule; the user confirms. Then [fetch-corpus](../fetch-corpus/SKILL.md) fetches its
files and records in the manifest what it got (`not_retrieved` with why for the rest), and curate-corpus curates it.

## Mode: Update — exhaustive, newer sources only

```
- [ ] since = last_update or last_full_index (init_topic.py --probe) minus 30 days
- [ ] keys.py: new keyed databases ready? add them to config databases (+ queries) before searching
- [ ] search.py --topic <slug> --since <D>                 (every query, every database)
- [ ] search.py --topic <slug> --citing --since <D>        (works citing the core sources)
- [ ] build_list.py --topic <slug> --run since-<D> --run citing-since-<D>
- [ ] classify_access.py --topic <slug> --recheck-older-than 30   (new sources + re-check older ones; 0 = re-check
        every source with fresh lookups — use 0 when the user asks to re-check everything)
- [ ] screen.py (only unscreened sources are screened; keywords re-scores all)
- [ ] find_si.py --topic <slug>    (SI of the new sources; sources asked before are skipped)
- [ ] dedup.py --apply (automatic) ; ask only about its to_review pairs (Index step 8)
- [ ] status.py ; offer to fetch the new sources: fetch-corpus, download_open.py --topic <slug> --added-since
        <run_started of the first build_list.py of this update> (or freeze a corpus of them)
- [ ] report: NEW sources (build_list `new_ids`), access changes (classify_access `access_changes`: newly open /
        less open), retracted, preprints now published
```

The update is meant to be the most complete view of the field at that moment: every database with a key, every query,
citation chasing, and a re-check of access and retractions. The 30-day overlap catches sources indexed late.
`classify_access` reports `newly_retracted` and `preprints_now_published`.

## Very large topics (a whole field, millions of sources)

Index it once as a catalog (`--batches` in step 3), then classify and screen the WHOLE catalog before any fetch —
every step works in blocks, so size only changes the time. Chain the steps with `--no-export` in the background (each step
queues the sources it changed) and publish them all into index.db once at the end:

```bash
S=${CLAUDE_SKILL_DIR}/scripts; nohup sh -c "python3 -I $S/classify_access.py --topic <slug> --no-export && \
  python3 -I $S/screen.py --topic <slug> keywords --no-export && python3 -I $S/find_si.py --topic <slug> --no-export && \
  python3 -I $S/dedup.py --apply --no-export && python3 -I $S/export.py --topic <slug>" > .scripts/<slug>/pipeline.log 2>&1 &
```

(`keywords` only when that is the method the user chose — ask, step 2.) Progress: the log, and
`classify_access_progress` / `find_si_progress` in `.scripts/<slug>/state.json`. The catalog gets the batched SI
routes. Then answer questions from index.db, and for each question freeze a corpus from the catalog by its rule
(`freeze_corpus.py --topic <catalog> --subject ... --years ... --access ...`), give its sources the per-source SI
routes (`find_si.py --topic <catalog> --ids <its IDs>`) and fetch it with fetch-corpus: no new topic is needed.

## After a skill upgrade (an index built by an older version)

Once, when nothing else is running on the project: `repair.py` (cleans stored abstracts, flags notices the new rules
recognize, recomputes the vocabulary topics of changed sources, tells retraction notices from the sources they retract
using the cached Crossref answers; `--retractions-only` for that step alone), `dedup.py --apply` (patent families, SI deposits that
older versions merged into sources or kept as sources), `build_list.py --topic <slug> --si-links-only` (SI deposits
older versions dropped), `topics.py assign --topic <slug>` (Topic A/B/C from the current vocabulary; Claude, API and
manual topics are kept), `find_si.py --topic <slug>` (the SI of every in-scope source, for an index built before
find_si existed). Each prints what it changed; tell the user the numbers.

## Mode: New index (topic exists, search again)

Review `queries.json`, the gate and the scope lists with the user (improve them), then run the Index checklist; results
merge into the same ledger rows (same IDs, nothing lost). Use `search.py` without `--since`.

## Adding a list or an export

A Web of Science export (Plain text, Tab-delimited, BibTeX or RIS), a Scopus export (CSV, BibTeX, RIS), a Zotero /
EndNote / Mendeley file, a Google Patents CSV, a SCALE corpus list (a graph's `sources.json`), a list of DOIs or
patent numbers, or a web page of DOIs: `import_list.py --topic <slug> --file <path>` (or `--url`). It keeps the
file's abstracts and author keywords and adds Web of Science / Scopus to the Database column; a patent number
(US1558559A, US-1558559-A, US 1,558,559) becomes a patent row keyed by office and number, the row a patent search
finds. Excel files are refused (ask for Plain text or Tab-delimited instead). Who decides the scope: the screening
(default); `--scope file` the file's own decisions (a SCALE list's statuses: in_scope, not_retrieved,
held_out_target, after_cutoff in; off_scope, excluded, retracted out, with the reason); `--scope in` every source in
(a list someone chose by hand). Those two are manual decisions: later screening keeps them. Then the Index steps
from 3 on, for the imported run only: `build_list.py --topic <slug> --run manual` → `classify_access.py` →
`screen.py` → `find_si.py` → `dedup.py --apply` → report (sources added, abstracts kept from the file, duplicates
merged, imported sources the screening put out of scope). A new topic gets `init_topic.py` first; sources the whole
catalog should hold too go into it the same way (`--scope in`), and `topics.py set --ids ... --main <term> --add`
gives a list's sources the vocabulary term they are about, in front of their own Topic A/B/C.

## Questions and lists (no mode)

Answer questions about the corpus directly — no menu, no plan, nothing searched or downloaded:
- Progress, counts per access type, what is left and how long it takes: `status.py --topic <slug>` (`--json`).
- Anything else ("how many 2024 sources on copper catalysts", "which venues publish most"): read-only SQL on
  `sources/index.db` — tables, views and examples in [references/database.md](references/database.md). A
  question that names a subject in words ("CO2 reduction driven by electricity") → map it to vocabulary terms
  (`topics.py vocab`), count with `source_subjects` (`kind='main'` = Topic A/B/C, the source is mainly about it), add a
  full-text count (`sources_fts`) for wording the vocabulary lacks, and say which terms you counted and which neighbours
  you left out (e.g. PEC, plasma, bioelectrochemical) so the user can widen or narrow it.
- A list as a file → `sources/exports/<name>.<ext>`:

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/export.py --name <name> --topic <slug> [--subject "Copper catalysts"] \
  [--main-only] [--venue "ACS Catal,Nat. Catal"] [--year 2020-2026] [--access OA,OA+ND] [--doc-type article,review] \
  [--min-relevance 4] [--downloaded yes] [--text "copper AND ethylene"] [--format csv|jsonl|bib|ris]
```

  `--subject` matches Topic A/B/C and related topics; add `--main-only` when the user means sources mainly about it.
  Errata and retracted sources are never exported.
- "Check for duplicates" → `dedup.py --apply`, then as Index step 8.

## The vector store (the downloaded sources' text)

`vectors.py` keeps `sources/vectors.db`: every downloaded source's text (and its SI PDFs', as pages S1, S2 …) cut
into passages as SCALE cuts source pages, a vector per passage text and embedder, and a keyword index. The index
(index.db) keeps the records; the store keeps only each passage's text, page and position and its vectors, and
`vectors.py search "<question>"` joins its hits to the index (title, year, DOI); passages of reference lists, which
match almost any query on the titles they cite, are left out unless `--with-references`. `--ids` searches inside
given sources; `--by-source` ranks sources (by their best passages) and `--ids-out <file>` writes their IDs, the sources
to curate for a question (curate-corpus `--ids-file`); `vectors.py get <ID or DOI> [--text]` loads one source as the
store holds it, its record and its text page by page. Nothing is read or embedded twice: a
vector belongs to a passage's text and embedder, a source is read again only when its files change (then only new text
is embedded), a merged source's passages move to the ID it kept, and a source no longer downloaded (out of scope,
retracted) leaves. Every step that changes the files (fetch-corpus's download_open, download_paywalled, fetch_si; dedup,
merge_db) updates the store when the project has one; `vectors.py update` does it by hand, `status` says what is
left. Embedders: `scale-hash-v1` (SCALE's default: deterministic, lexical with chemistry aliases, no download),
`sentence-transformers:<model>` (a local model; `vectors.py init --embedder sentence-transformers:BAAI/bge-small-en-v1.5`
fetches it once, 133 MB — a download, so ask first), `fastembed:<model>`. A store keeps every embedder it was given;
`drop --embedder` removes one. The store holds the sources' text: share it no more than the PDFs.

## Utility scripts (`${CLAUDE_SKILL_DIR}/scripts/`, run with `python3 -I`; `--help` for details)

| Script | What it does |
|---|---|
| `init_topic.py` | `--list` / `--probe` topics; create/update a topic; `--check` validates the plan |
| `keys.py` | which databases are ready, which keys are missing; `--init` key file, `--test` keys |
| `search.py` | every query on every database; `--count-only`, `--since`, `--citing` |
| `import_list.py` | add a WoS / Scopus / Zotero export (abstracts kept), a Google Patents CSV, a SCALE corpus list, DOIs, patent numbers or a web page of DOIs to a topic; `--scope screen\|file\|in` |
| `build_list.py` | gate, dedup, doc types, SI links, merge into the ledger, vocabulary topics, refresh index; `--batches N`, `--no-export`, `--si-links-only` |
| `classify_access.py` | access type, exact license, abstracts/keywords (any size, blocks; OpenAlex first, Unpaywall capped); `--recheck-older-than DAYS`, `--abstracts-only`, `--no-export` |
| `screen.py` | relevance 0-5 + Topic A/B/C; `prep/next/merge`, `api`, `keywords`, `none`, `status`; `--no-export` |
| `find_si.py` | every in-scope source's SI listed in the index before any download (Crossref components, DataCite, Crossref relations, PMC; Elsevier/MDPI CDNs and publisher pages up to 50,000 sources); `--deep`, `--no-deep`, `--ids`, `--no-export` |
| `topics.py` | `vocab`, `summary`, `assign` (`--no-export`), `proposed`, `set` (manual correction; `--add` keeps the source's own topics after it) |
| `status.py` | progress table + what is left to fetch (reports, "how far along") |
| `fill_abstracts.py` | abstracts from fetched PDFs (after fetch-corpus, when the user wants them) |
| `dedup.py` | `--apply` merges the safe duplicates incl. patent families and SI deposits (automatic); `--merge` / `--keep-separate` for the uncertain pairs; `--no-export` |
| `repair.py` | once after a skill upgrade: re-apply the current abstract, notice and retraction rules to stored sources; `--retractions-only` |
| `export.py` | publish pending changes into index.db (in place); `--topic <slug> --csv` writes the topic's index CSVs; `--rebuild` (fallback; the history is kept); a filtered list as a file; `--set-extracted` |
| `merge_db.py` | merge another copy of index.db into this one (`--from`; `--files` copies in its PDFs and SI; `--dry-run`); then `dedup.py --apply` |
| `vectors.py` | the vector store of the downloaded sources (sources/vectors.db): `init [--embedder]`, `update` (new and changed sources only), `search "<question>"` (`--mode hybrid\|vector\|keyword`, `--topic`, `--year`, `--ids`, `--by-source`, `--ids-out`), `get <ID or DOI>` (one source's text), `status`, `drop --embedder` |
| `filters.py` | saved filters kept in index.db and re-run as it evolves: `define`, `list`, `show`, `refresh`, `export` (a filter's sources as their own database; `--public`: abstracts only for OA and OA+ND) |
| `freeze_corpus.py` | a frozen corpus by rule, for fetch-corpus and curate-corpus (SCALE's format: every candidate with its status; `scale corpus check`) |
| `upgrade.py` | upgrade a project, or one database file (`--db`), made before the sources were so named; every script does it for its own project |

Requires Python 3.10+ with `requests`, `pymupdf`, `pypdf` (`pip install requests pymupdf pypdf`).

## The database evolves

`sources/index.db` is never rebuilt: the working ledger marks every source a step changes, and the step ends by
publishing just those sources into index.db, in place. Each publish adds a row to `runs` (when, which step, sources
added / updated / removed) and the sources' changes to `changes`: added; removed (merged into, or SI of, another
source); access type, licence, version, retraction, download, SI, Topic A, DOI; a topic's scope. "What is new since
June" or "what became open access" is one query ([references/database.md](references/database.md)). The file also
holds the working state (`_source_state`; the topics' config, queries and run state; the merge decisions): a project
received as index.db alone is rebuilt from it by the first script that runs, and Update continues where the
database stopped (the receiver adds their own keys and contact address). Saved filters (`filters.py`) live in it
and re-run whenever sources are added or removed, or their text, topics or retraction change. `export.py --rebuild`
rebuilds the file from the ledger only as a fallback, keeping the history.

**Two copies.** When two people update separate copies of index.db, one of them runs `merge_db.py --from <their
index.db>` (`--files <their project folder>` also copies in their PDFs and SI; `--dry-run` only says what would
change), then `dedup.py --apply`, and shares the merged file: the copies converge. Sources are matched by identity
(DOI, patent number, title key, aliases), never by ID; nothing either copy found, checked, downloaded, screened or
curated is lost, and duplicates one copy merged are merged in the other. The rules per field are in merge_db.py's
docstring and [references/database.md](references/database.md). A merge that finds nothing new changes nothing.

## Where things are

- `sources/index.db` — the source database (all topics), updated in place by every step, with its history
  (`runs`, `changes`), saved filters and working state ("The database evolves" below).
  `sources/<slug>/index/{OA,OA+ND,Free-to-read,Paywalled,merged,excluded}.csv` — the topic index (34 columns),
  written on request (`export.py --csv`). Columns, tables, access and license rules, the
  Extracted column: [references/database.md](references/database.md).
- `sources/<slug>/corpora/<corpus>/sources.json` — a frozen corpus (freeze_corpus.py).
- `sources/vectors.db` — the vector store of the downloaded sources' text (vectors.py; local, never shared).
- `sources/<slug>/files/<access>/<ID>.pdf`, SI in `files/SI/<access>/`. A source in two topics has one row and a
  copy (APFS clone, no extra disk) in each topic folder.
- Topic vocabulary and Topic A/B/C rules: [references/topics.md](references/topics.md). Databases, keys, what is skipped:
  [references/databases.md](references/databases.md). Errors and fixes: [references/troubleshooting.md](references/troubleshooting.md).
- `.scripts/` — working ledger, per-topic config/queries/raw hits/batches/logs. `~/.scale/sources/` — keys.txt (and
  fetch-corpus's machine-wide EZproxy config and limiter state).

## Orchestrated mode (invoked by another skill)

Inline arguments, e.g. `topic="..." slug=... mode=index access=OA,OA+ND screening=claude wrapper_confirmed=true`.
Also accepted: `mode=index|update` (default index), `databases=`, `threshold=`, `base_url=`, `model=`,
`import_file=` (import_list.py). No banner, no intake questions: use the arguments and the topic's saved config,
defaults for the rest (screening claude); write the plan files yourself and skip the plan approval when
`wrapper_confirmed=true`. Safe duplicates are merged as usual; uncertain pairs are not asked about here — they stay
separate and the summary gives their number. Both modes stop after their report; fetching is fetch-corpus's. Return
a short summary: index paths, counts, duplicates merged, uncertain pairs, keyed databases skipped.
