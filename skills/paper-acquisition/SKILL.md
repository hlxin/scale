---
name: paper-acquisition
description: Builds and maintains a per-topic paper index and corpus. Index mode finds every matching paper, preprint, patent and dataset in 34 automated sources (OpenAlex, Crossref, Europe PMC, arXiv, OSTI, Zenodo; Scopus, Web of Science, Lens, EPO with keys) and keeps publications/papers.db up to date in place, holding every paper with abstract, exact license, supplementary information (SI) links, Topic A/B/C and related topics, and the history of every run and change (index CSVs per access type — OA, OA+ND, Free-to-read, Paywalled — on request); copies of the database updated apart merge back into one (merge_db.py). Download mode fetches PDFs and SI, paywalled papers only through the library EZproxy at safe rates. Update mode exhaustively adds newer papers (all sources, citation chasing, access and retraction recheck). Duplicates merge automatically. Also imports Web of Science, Scopus or Zotero exports with their abstracts, answers questions about the indexed papers and writes filtered lists (CSV, BibTeX, RIS). Use whenever the user wants to find, index, import, list or download papers on a topic, refresh a literature corpus, or query the paper database. Curating the papers into scale-catal documents belongs to curate-corpus (a corpus) and curate-source (one source).
allowed-tools:
  - Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*)
  - Bash(nohup python3 -I ${CLAUDE_SKILL_DIR}/scripts/*)
  - Bash(nohup zsh ${CLAUDE_SKILL_DIR}/scripts/run_paywalled.sh *)
  - "scale corpus check <manifest>"     # SCALE checks a frozen corpus (freeze_corpus.py)
version: 3.5.0
scale_release: ">=v0.2.0"
inputs:
  - A topic in the user's words, or a Web of Science, Scopus or Zotero export, a list of DOIs or a web page of them
  - The access types to download (OA, OA+ND, Free-to-read, Paywalled) and how relevance is screened (Claude, an API, keywords or none)
  - Optional API keys in ~/.paper-acquisition/keys.txt (never through the chat), a polite-pool contact address, and the library's EZproxy host for paywalled papers
outputs:
  - publications/papers.db, updated in place by every step (runs and changes record how it evolved; it carries its working state, so whoever receives it can update it), with every paper, preprint, patent and dataset found, deduplicated, with its access type, exact licence, SI and Topic A/B/C; the topic's index CSVs on request
  - The downloaded PDFs and SI, filed by access type
  - For curation, a frozen corpus manifest (publications/<slug>/corpora/<name>/sources.json) that `scale corpus check` accepts
validation:
  - "`status.py --topic <slug>` accounts for every paper: downloaded, queued, or the reason it was not (Notes)"
  - Every downloaded PDF passed the same-paper title check and carries its licence decision
  - "`scale corpus check <manifest>` reports ok for every frozen corpus"
  - No paywalled paper was fetched except through the library EZproxy within the limiter's caps; no login, CAPTCHA or pirate site was used
human-review:
  - Before anything is downloaded (the numbers per access type), and before paywalled downloads start
  - Whenever the EZproxy limiter records a hard stop (a person clears it after looking)
  - Before a corpus is frozen for curation (which papers are included, and why the others are left out)
---

# Paper Acquisition

Topic-agnostic: the research domain always comes from the user; the topic vocabulary is tuned for catalysis and
extensible. The papers it downloads, frozen as a corpus, are the sources that [curate-corpus](../curate-corpus/SKILL.md)
turns into scale-catal documents with [curate-source](../curate-source/SKILL.md), one source at a time.

## Standing rules (apply for the whole task)

- **English only** with the user, in every message.
- **Index first, download second.** Index mode never downloads. Download only after the topic is indexed,
  deduplicated, classified and screened, its SI is listed, and the user approved the download plan (Download mode
  gate).
- **SI is in the index before anything is downloaded.** Every in-scope paper's supplementary information is looked up
  at index time (`find_si.py`, Index step 7) and listed in the index (SI column "Available (n deposits)", table
  `supplements` in papers.db). Download mode fetches the files listed there first. Never start a download while a
  topic's SI step is missing or incomplete.
- **Scripts do the exact work; you do the judgment.** Searching, deduplication, license decisions, downloads, folder
  routing, the index CSVs and `papers.db` are produced by the scripts below. Never write index files or move PDFs by
  hand, never write replacement code — if a script fails, read its error, fix the input (config, queries) and re-run.
- **Every decision question uses `AskUserQuestion`** (clickable options + "Other"). Plain text only for free-form
  input (a topic, a URL) and status updates.
- **API keys never go through the chat.** Keys live in `~/.paper-acquisition/keys.txt` as `service: key` lines.
  When a useful source needs a key, tell the user which line to add (README.md in this skill folder explains how to
  get each key) and check with `keys.py`; never ask them to paste a key, never print one.
- **Polite-pool email** goes only to OpenAlex (`mailto`), Unpaywall (`email`) and Crossref (`mailto`) — never in
  headers, never to publishers or the library proxy.
- **Paywalled access is sanctioned access only:** campus network / VPN through the library's EZproxy. Never log in
  or type credentials, never solve or bypass a CAPTCHA, never use pirate sites (Sci-Hub, LibGen ...). Never start a
  second EZproxy process, never change the limits in `scripts/_ezlimit.py`, never clear a hard stop without the
  user — the institution's rate limits must never be exceeded.
- **Nothing is deleted.** Out-of-scope, wrong or duplicate files move under `.scripts/`. Every file the agent creates
  (logs, caches, batches, configs) lives in `.scripts/`; `publications/` holds only `papers.db`, the topic folders
  (`papers/`, `corpora/`, and `index/` when CSVs were asked for) and `exports/`.
- Run every command from the **project root** (the folder that holds or will hold `publications/` and `.scripts/`).
  A bare script name (`status.py ...`) means `python3 -I ${CLAUDE_SKILL_DIR}/scripts/status.py ...`. Scripts print
  one JSON line on stdout and progress on stderr; all of them resume where they stopped when re-run.

## Step 0 — banner (interactive invocations only)

Your first message is exactly this block, copied verbatim, before any tool call:

```
┃ PAPER ACQUISITION
┃ index everything → papers.db + topic index → download
┃ modes: index · download · update
```

Skip it when invoked by another skill or with inline `key=value` arguments (orchestrated mode, last section).

## Step 1 — what exists, which mode

`init_topic.py --list` shows the project's topics (papers, in scope, downloaded, last index, last update). If the user
named a topic, `init_topic.py --slug <slug> --probe` (changes nothing).

- **A question or a list** ("how many…", "which papers…", "a BibTeX of the 2023 ACS papers on X", "check for
  duplicates") is not a mode: answer it directly, no menu ([Questions and lists](#questions-and-lists-no-mode)).
- **A file or list of papers to add** (Web of Science / Scopus / Zotero export, DOIs, a web page) → [Adding a list or
  an export](#adding-a-list-or-an-export).
- **Topic exists** → `AskUserQuestion`: Download papers from its index · Update — find newer papers (exhaustive) ·
  New index — search again from scratch (results merge into the same list; nothing is lost). Its saved `config.json`
  settings are the defaults for everything below.
- **New topic** → Index mode; `init_topic.py` creates `publications/<slug>/`.
- Explicit wording wins: "find / index papers on" = Index; "download / get the PDFs" = Download; "new papers since /
  refresh" = Update.

## Step 2 — intake (at most two rounds; ask only what is missing)

One `AskUserQuestion` call with the missing items of:
1. **Access types to DOWNLOAD** (`multiSelect: true`; every paper is indexed regardless): OA (CC BY / BY-SA / BY-NC /
   BY-NC-SA / CC0) · OA+ND (CC BY-ND / BY-NC-ND) · Free-to-read (readable, no reuse license) · Paywalled (library
   EZproxy; campus/VPN; slow — about 120 papers per publisher per day). "Open access" = OA + OA+ND; "everything" = all.
   In Index mode the answer is only stored for later.
2. **How to decide relevance and topics** — always ask, never assume (also for every subtopic of a catalog): Claude
   reads every title + abstract and picks Topic A/B/C · an OpenAI-compatible API you host (base URL + model) · a
   keyword list I draft (deterministic, free, minutes even for millions of papers; topics from the vocabulary) · no
   screening (keep everything that matches; topics from the vocabulary). Put first, marked (Recommended): Claude for up
   to ~20,000 papers; the keyword list for a larger topic (Claude would need days of subagent batches).

Second round only if needed:
- **Keys.** Run `keys.py`. If OpenAlex has no key, say once what that costs: without a key OpenAlex returns at most
  10,000 results per query (also per citation-chasing batch) and shares a small daily budget with the whole network,
  so a large index or update stays incomplete; the key is free (README). Ask: I'll add a free OpenAlex key first
  (Recommended) · Continue without it. Also list other keyed sources that would add coverage (Scopus, Web of
  Science, CORE, Lens incl. patents, EPO patents, Springer, IEEE, ADS) — optional. Adding keys: `keys.py --init`
  creates the file from the template; the user edits it; `keys.py --test` checks it.
- **Paywalled selected** → "Are you on the campus network or connected to the VPN?" (Yes · No, skip paywalled ·
  Not sure, test it). The check runs in Download mode with one of the topic's own paywalled papers.
- **API selected** → base URL and model in plain text; the key goes into keys.txt as `llm_api_key: <key>`.
- **Polite-pool email**: from auto-memory (`polite_pool_email`); if absent, ask once and store it in memory.

## Step 3 — plan the index (you write it, the user approves it)

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/init_topic.py --topic "<topic as the user said it>" --slug <short-slug> \
  --email <polite email> --access <e.g. OA,OA+ND> --screening <claude|api|keywords|none>
```

Default sources = every keyless source in the catalog + keyed sources whose keys exist ([references/sources.md](references/sources.md)).
Then write, in `.scripts/<slug>/` ([references/queries.md](references/queries.md), [references/screening.md](references/screening.md)):
- `queries.json` — 15-25 distinct queries over the main sources plus 1-2 per other selected source (preprints,
  datasets, patents, regional), each in the source's own syntax. Every selected source needs at least one query.
- `config.json` → `gate` — anchor terms every on-topic paper carries (drops loose matches).
- `criteria.md` (Claude/API: topic definition, in-scope and out-of-scope lists) or `keywords.json` (keyword method).

A year limit ("from 2024 on") goes into the plan: `init_topic.py --slug <slug> --year-from 2024` (every source's date
filter, and `build_list.py` drops older works that loose sources let in; the run stays a full index).
Validate until `"ok": true`: `init_topic.py --slug <slug> --check`. Show a compact plan (queries per source, gate terms,
scope lists or keyword groups, sources waiting for keys) and ask: Approve and start · Edit (say what) · Cancel.

## Mode: Index — copy this checklist and tick it off

```
- [ ] 1 estimate the field         search.py --count-only
- [ ] 2 search every source        search.py  (background when large)
- [ ] 3 build the list             build_list.py   (gate, dedup, doc types, Topic A/B/C from the vocabulary)
- [ ] 4 citation chasing           search.py --citing  ->  build_list.py --run citing
- [ ] 5 access + license + abstracts   classify_access.py
- [ ] 6 screen relevance + topics  screen.py (claude / api / keywords / none)
- [ ] 7 supplementary information  find_si.py   (every in-scope paper's SI, listed before any download)
- [ ] 8 duplicates (automatic)     dedup.py --apply ; ask only about its to_review pairs
- [ ] 9 report                     status.py ; topics.py summary ; offer Download
```

**1 · Estimate.** `search.py --topic <slug> --count-only` → on-topic estimate per source (before deduplication;
sources overlap 30-60 %; loose sources are page-1 lower bounds). If the field may exceed ~20,000 papers, ask:
Index the whole field (Recommended) · Narrow the topic · Cancel. A whole field in the hundreds of thousands (e.g.
"all of catalysis") works best as a catalog: index it once, classify and screen it whole ("Very large topics"), then
download per subtopic (a new topic whose list is imported from the catalog's papers.db with `import_list.py`).

**2 · Search.** Large runs in the background (every query is paged to the end or to its relevance tail):

```bash
nohup python3 -I ${CLAUDE_SKILL_DIR}/scripts/search.py --topic <slug> > .scripts/<slug>/search.log 2>&1 &
```

Done when the log ends with a JSON line whose `complete` is true (re-run to resume `pending_queries`). The JSON's
`skipped_sources` lists keyed sources without a key — mention them once in the report.

**3 · Build.** `build_list.py --topic <slug>`. If it drops nearly everything (`off_topic_dropped_by_gate`) or keeps
obvious noise, fix the gate and re-run `build_list.py` (no new search needed). SI deposits found by the search are
not papers: they become SI links of their paper (index SI column "Available (n deposits)"). More than ~1 million raw
hits (the search JSON's total): `build_list.py --topic <slug> --batches N` with N ≈ raw hits / 1,000,000 — one
process, one batch at a time, the index written once at the end.

**4 · Citation chasing.** `search.py --topic <slug> --citing`, then `build_list.py --topic <slug> --run citing`.
OpenAlex lists every work citing the topic's core papers; the gate keeps the on-topic ones.

**5 · Classify.** `classify_access.py --topic <slug>` — access type, exact license with version, license source, and
missing abstracts/keywords from Semantic Scholar, Europe PMC, OpenAlex and Crossref. Patents are Free-to-read. Any
size: blocks of 20,000 papers, four looked up at once, every service at its own allowed pace (20,000 papers ≈ 1.5
min; 2 million ≈ 2-3 h, bounded by Crossref's 3 requests at a time); each block is saved when decided, so a re-run
continues where it stopped. OpenAlex runs while the free daily budget or prepaid credit lasts; Unpaywall is asked only
for DOIs OpenAlex lacks and Crossref knows, never more than 90,000 calls per UTC day on this machine (Unpaywall asks
for under 100,000). Without an `s2` key, Semantic Scholar (whose shared keyless pool refuses most requests) is used
only for topics up to 20,000 papers. When the JSON says `"complete": false`, the `pending` papers keep an empty access
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

**7 · SI.** `find_si.py --topic <slug>` lists every in-scope paper's supplementary information in the index before
anything is downloaded; nothing is fetched. For every paper, batched or read from the answers `classify_access.py`
cached: Crossref components (`<DOI>.s001`, `.s002` …: ACS, PLOS), DataCite deposits that declare IsSupplementTo the
paper (publisher SI on Figshare, Zenodo, Dryad, CCDC structures, repositories), Crossref `is-supplemented-by`
relations, and the PubMed Central open-access file lists. For topics up to 50,000 papers (or with `--deep`), also
the routes that cost a request per paper, at each host's polite pace: Elsevier's SI CDN (mmcN files), MDPI's CDN
(-s001 files) and the pages of publishers that serve scripted clients (Nature, Springer, BMC, Frontiers). SI that only
sits on walled sites (Wiley, RSC, ACS and IOP pages) without a deposit of its own is found by `fetch_si.py` when the
paper is downloaded. Answers are cached (`.scripts/enrich/si_*.sqlite`), so re-runs and updates only ask about new
papers. The JSON gives `papers_with_si` and `by_route`; the index SI column says "Available (n deposits)". A catalog
over 50,000 papers gets the batched routes; give a subset the per-paper ones with `find_si.py --topic <catalog> --ids
<file of paper IDs>` (or index the subset as its own topic).

**8 · Duplicates (automatic, no question).** `dedup.py --apply` merges the safe cases: preprint ↔ published version,
repository copy ↔ journal article, same paper without/with DOI, Angewandte twins, byte-identical PDFs, one patented
invention filed in several offices (WO, EP, US … and its HAL/OSTI copy: same title and inventors; one row keeps every
number), and SI deposits indexed as papers (they become SI links of their paper). A dataset is never merged into its
paper. Each merge is logged with the full merged row. Only its `to_review` pairs go to the user — the same title
under two DOIs, nearly the same title by the same first author, or two patents with the same title whose inventors
are unknown:
show them side by side (title, DOI, venue, year; all of them in `.scripts/dedup_review.csv`) and ask: Keep them
separate (Recommended) · Merge them all · Decide pair by pair. Then `dedup.py --keep-separate all` or
`dedup.py --merge <a>:<b>,...` (a pair kept separate is never listed again). `to_review` is 0 → no question.

**9 · Report.** `status.py --topic <slug>` and `topics.py summary --topic <slug>`. Tell the user in a few lines: papers
indexed (by access type and document type), in scope, papers with SI listed (find_si `papers_with_si`), duplicates
merged, the main Topic A values, papers without abstracts, sources skipped for want of a key, and where things are: `publications/papers.db` (the topic is the collection `<slug>`;
every later step updates it in place). The index CSVs are written only on request (`export.py --topic <slug> --csv`);
over 1,048,576 rows they no longer open in Excel, so point to papers.db (DB Browser for SQLite) or a filtered export. Nothing was downloaded; offer
Download mode.

## Mode: Download

```
- [ ] GATE: status.py --topic <slug>; ask what to download
- [ ] open routes                  download_open.py [--max N]
- [ ] paywalled (if selected)      check_paywalled_access.py -> run_paywalled.sh
- [ ] supplementary information    fetch_si.py   (the SI the index lists, then the paper page's)
- [ ] abstracts from PDFs (if chosen)   fill_abstracts.py
- [ ] duplicates (automatic)       dedup.py --apply (byte-identical PDFs) ; ask only about to_review, as Index step 8
- [ ] report                       status.py
```

**Gate.** Show the `status.py` table and estimate (in scope by access type; open hours and GB; paywalled days at the
limits). `AskUserQuestion` (`multiSelect` where noted): what to download — Everything selected (Recommended) · Only
the N most relevant (they type N) · Change access types; and "Fill missing abstracts from the downloaded PDFs?"
(Yes · No) when `status.py` reports in-scope papers without abstracts.

**Open routes** (background for more than a few hundred papers):

```bash
nohup python3 -I ${CLAUDE_SKILL_DIR}/scripts/download_open.py --topic <slug> [--max N] > .scripts/<slug>/download_open.log 2>&1 &
```

Datasets and software are never downloaded; US patents come from the USPTO image server.

**Paywalled** (only if selected; details [references/paywalled.md](references/paywalled.md)):
`check_paywalled_access.py --topic <slug> [--host <ezproxy host>]`. `"access": true` → re-run `download_open.py` once
(it queues paywalled papers and open papers that only sit on bot-protected sites), check `_ezlimit.py status` (a hard
stop needs the user's review — show it and stop), then start the single machine-wide runner if not running:

```bash
nohup zsh ${CLAUDE_SKILL_DIR}/scripts/run_paywalled.sh "$PWD" > /dev/null 2>&1 &
```

`"access": false` → tell the user the `reason` and `next` from the JSON and follow it. The runner works for days.
A publisher that keeps answering with a login page or a block while the others download is left out with
`run_paywalled.sh "$PWD" --skip-publishers <keys>` (its papers stay queued; tell the user which and why).

**SI.** `fetch_si.py --topic <slug>` after the open downloads: it downloads the SI the index lists (Index step 7)
first, then looks for more on the paper's own page. **Abstracts.** `fill_abstracts.py --topic <slug>` (only
if the user said yes; it reads the "Abstract" section of each PDF; `--heuristic` is unreliable — do not use it
without showing the user a dry-run sample). **Report.** `status.py`: downloaded per access type, queued for EZproxy
(days), where the PDFs are (`publications/<slug>/papers/<access>/<ID>.pdf`); the index `Notes` column says why a
paper was not downloaded.

Optional **full-text check** (Claude/API): `screen.py --topic <slug> prep --stage fulltext` → `next 5 --stage
fulltext` + subagents (or `api --stage fulltext`) → `merge --stage fulltext`; papers that fall below the threshold
move to `.scripts/<slug>/out_of_scope/`.

## Freeze a corpus for curation

Before papers are curated, freeze the corpus: `freeze_corpus.py --topic <slug> --name <corpus> [--min-relevance 4]
[--subject "<Topic A/B/C labels>"] [--doc-types article,review] [--years 2015-2026] [--access OA,OA+ND] [--ids FILE]`.
It writes `publications/<slug>/corpora/<corpus>/sources.json`, a corpus manifest in SCALE's format (SCALE's
curate-source skill asks for one before the first source, and its curate-corpus skill curates the included sources).
Every paper of the topic gets a status: `in_scope` (downloaded, in scope and kept by the rule: the sources to curate)
or the reason it is left out (`not_retrieved` with why, `off_scope`, `not_screened`, `retracted`, `excluded` with a
`status_reason`), and the counts add up. `scale corpus check <manifest>` checks it. Each entry carries the paper ID,
DOI, title, year, access type, licence, the version of the copy, and the paths of its PDF and SI. A corpus is frozen
once: a new rule gets a new name. Show the counts and the rule; the user confirms.

## Mode: Update — exhaustive, newer papers only

```
- [ ] since = last_update or last_full_index (init_topic.py --probe) minus 30 days
- [ ] keys.py: new keyed sources ready? add them to config sources (+ queries) before searching
- [ ] search.py --topic <slug> --since <D>                 (every query, every source)
- [ ] search.py --topic <slug> --citing --since <D>        (works citing the core papers)
- [ ] build_list.py --topic <slug> --run since-<D> --run citing-since-<D>
- [ ] classify_access.py --topic <slug> --recheck-older-than 30   (new papers + re-check older ones; 0 = re-check
        every paper with fresh lookups — use 0 when the user asks to re-check everything)
- [ ] screen.py (only unscreened papers are screened; keywords re-scores all)
- [ ] find_si.py --topic <slug>    (SI of the new papers; papers asked before are skipped)
- [ ] dedup.py --apply (automatic) ; ask only about its to_review pairs (Index step 8)
- [ ] status.py ; ask to download the new papers -> download_open.py --added-since <run_started of the first
        build_list.py of this update> (+ paywalled, fetch_si)
- [ ] report: NEW papers (build_list `new_ids`), access changes (classify_access `access_changes`: newly open /
        less open), retracted, preprints now published
```

The update is meant to be the most complete view of the field at that moment: every source with a key, every query,
citation chasing, and a re-check of access and retractions. The 30-day overlap catches papers indexed late.
`classify_access` reports `newly_retracted` and `preprints_now_published`; older leftovers can be retried separately
(`download_open.py --retry-failed`, `fetch_si.py --retry`).

## Very large topics (a whole field, millions of papers)

Index it once as a catalog (`--batches` in step 3), then classify and screen the WHOLE catalog before any download —
every step works in blocks, so size only changes the time. Chain the steps with `--no-export` in the background (each step
queues the papers it changed) and publish them all into papers.db once at the end:

```bash
S=${CLAUDE_SKILL_DIR}/scripts; nohup sh -c "python3 -I $S/classify_access.py --topic <slug> --no-export && \
  python3 -I $S/screen.py --topic <slug> keywords --no-export && python3 -I $S/find_si.py --topic <slug> --no-export && \
  python3 -I $S/dedup.py --apply --no-export && python3 -I $S/export.py --topic <slug>" > .scripts/<slug>/pipeline.log 2>&1 &
```

(`keywords` only when that is the method the user chose — ask, step 2.) Progress: the log, and
`classify_access_progress` / `find_si_progress` in `.scripts/<slug>/state.json`. The catalog gets the batched SI
routes; every subtopic gets the per-paper ones when its own `find_si.py` runs (up to 50,000 papers). Then answer
questions from papers.db, and download per subtopic: a subtopic is a new topic (`init_topic.py`, its own intake questions) whose list comes from the catalog —
`export.py --name <sub> --topic <catalog> --subject ... --format csv`, then `import_list.py --topic <sub> --file
publications/exports/<sub>.csv` and the import steps. A paper shared by both topics stays one row, with its access
type and license already known.

## After a skill upgrade (an index built by an older version)

Once, when nothing else is running on the project: `repair.py` (cleans stored abstracts, flags notices the new rules
recognize, recomputes the vocabulary topics of changed papers), `dedup.py --apply` (patent families, SI deposits that
older versions merged into papers or kept as papers), `build_list.py --topic <slug> --si-links-only` (SI deposits
older versions dropped), `topics.py assign --topic <slug>` (Topic A/B/C from the current vocabulary; Claude, API and
manual topics are kept), `find_si.py --topic <slug>` (the SI of every in-scope paper, for an index built before
find_si existed). Each prints what it changed; tell the user the numbers.

## Mode: New index (topic exists, search again)

Review `queries.json`, the gate and the scope lists with the user (improve them), then run the Index checklist; results
merge into the same ledger rows (same IDs, nothing lost). Use `search.py` without `--since`.

## Adding a list or an export

A Web of Science export (Plain text, Tab-delimited, BibTeX or RIS), a Scopus export (CSV, BibTeX, RIS), a Zotero /
EndNote / Mendeley file, a list of DOIs or a web page of DOIs: `import_list.py --topic <slug> --file <path>` (or
`--url`). It keeps the file's abstracts and author keywords and adds Web of Science / Scopus to the Database column;
Excel files are refused (ask for Plain text or Tab-delimited instead). Then the Index steps from 3 on, for the
imported run only: `build_list.py --topic <slug> --run manual` → `classify_access.py` → `screen.py` → `find_si.py`
→ `dedup.py --apply` → report (papers added, abstracts kept from the file, duplicates merged, imported papers the screening put
out of scope). A new topic gets `init_topic.py` first.

## Questions and lists (no mode)

Answer questions about the corpus directly — no menu, no plan, nothing searched or downloaded:
- Progress, counts per access type, what is left and how long it takes: `status.py --topic <slug>` (`--json`).
- Anything else ("how many 2024 papers on copper catalysts", "which venues publish most"): read-only SQL on
  `publications/papers.db` — tables, views and examples in [references/database.md](references/database.md). A
  question that names a subject in words ("CO2 reduction driven by electricity") → map it to vocabulary terms
  (`topics.py vocab`), count with `paper_subjects` (`kind='main'` = Topic A/B/C, the paper is mainly about it), add a
  full-text count (`papers_fts`) for wording the vocabulary lacks, and say which terms you counted and which neighbours
  you left out (e.g. PEC, plasma, bioelectrochemical) so the user can widen or narrow it.
- A list as a file → `publications/exports/<name>.<ext>`:

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/export.py --name <name> --topic <slug> [--subject "Copper catalysts"] \
  [--main-only] [--venue "ACS Catal,Nat. Catal"] [--year 2020-2026] [--access OA,OA+ND] [--doc-type article,review] \
  [--min-relevance 4] [--downloaded yes] [--text "copper AND ethylene"] [--format csv|jsonl|bib|ris]
```

  `--subject` matches Topic A/B/C and related topics; add `--main-only` when the user means papers mainly about it.
  Errata and retracted papers are never exported.
- "Check for duplicates" → `dedup.py --apply`, then as Index step 8.

## Utility scripts (`${CLAUDE_SKILL_DIR}/scripts/`, run with `python3 -I`; `--help` for details)

| Script | What it does |
|---|---|
| `init_topic.py` | `--list` / `--probe` topics; create/update a topic; `--check` validates the plan |
| `keys.py` | which sources are ready, which keys are missing; `--init` key file, `--test` keys |
| `search.py` | every query on every source; `--count-only`, `--since`, `--citing` |
| `import_list.py` | add a WoS / Scopus / Zotero export (abstracts kept), DOIs or a web page of DOIs to a topic |
| `build_list.py` | gate, dedup, doc types, SI links, merge into the ledger, vocabulary topics, refresh index; `--batches N`, `--no-export`, `--si-links-only` |
| `classify_access.py` | access type, exact license, abstracts/keywords (any size, blocks; OpenAlex first, Unpaywall capped); `--recheck-older-than DAYS`, `--abstracts-only`, `--no-export` |
| `screen.py` | relevance 0-5 + Topic A/B/C; `prep/next/merge`, `api`, `keywords`, `none`, `status`; `--no-export` |
| `find_si.py` | every in-scope paper's SI listed in the index before any download (Crossref components, DataCite, Crossref relations, PMC; Elsevier/MDPI CDNs and publisher pages up to 50,000 papers); `--deep`, `--no-deep`, `--ids`, `--no-export` |
| `topics.py` | `vocab`, `summary`, `assign` (`--no-export`), `proposed`, `set` (manual correction) |
| `status.py` | progress table + download estimate (Download gate, reports, "how far along") |
| `download_open.py` | open-route downloads, PDF license check, folder routing; `--added-since`, `--retry-failed` |
| `check_paywalled_access.py` / `run_paywalled.sh` | EZproxy check / the single rate-limited runner (all topics) |
| `fetch_si.py` | downloads the SI the index lists (then the paper page's) into `papers/SI/<access>/` |
| `fill_abstracts.py` | abstracts from downloaded PDFs (Download / curation option) |
| `dedup.py` | `--apply` merges the safe duplicates incl. patent families and SI deposits (automatic); `--merge` / `--keep-separate` for the uncertain pairs; `--no-export` |
| `repair.py` | once after a skill upgrade: re-apply the current abstract and non-paper rules to stored papers |
| `export.py` | publish pending changes into papers.db (in place); `--topic <slug> --csv` writes the topic's index CSVs; `--rebuild` (fallback; the history is kept); a filtered list as a file; `--set-extracted` |
| `merge_db.py` | merge another copy of papers.db into this one (`--from`; `--files` copies in its PDFs and SI; `--dry-run`); then `dedup.py --apply` |
| `filters.py` | saved filters kept in papers.db and re-run as it evolves: `define`, `list`, `show`, `refresh`, `export` (a filter's papers as their own database; `--public`: abstracts only for OA and OA+ND) |
| `freeze_corpus.py` | a frozen corpus manifest for curation (SCALE's format: every candidate with its status; `scale corpus check`) |
| `_ezlimit.py status` | EZproxy counters, cooldowns, hard stop (`clear-hard-stop` only after the user's review) |

Requires Python 3.10+ with `requests`, `pymupdf`, `pypdf` (`pip install requests pymupdf pypdf`).

## The database evolves

`publications/papers.db` is never rebuilt: the working ledger marks every paper a step changes, and the step ends by
publishing just those papers into papers.db, in place. Each publish adds a row to `runs` (when, which step, papers
added / updated / removed) and the papers' changes to `changes`: added; removed (merged into, or SI of, another
paper); access type, licence, version, retraction, download, SI, Topic A, DOI; a topic's scope. "What is new since
June" or "what became open access" is one query ([references/database.md](references/database.md)). The file also
holds the working state (`_paper_state`; the topics' config, queries and run state; the merge decisions): a project
received as papers.db alone is rebuilt from it by the first script that runs, and Update continues where the
database stopped (the receiver adds their own keys and contact address). Saved filters (`filters.py`) live in it
and re-run whenever papers are added or removed, or their text, topics or retraction change. `export.py --rebuild`
rebuilds the file from the ledger only as a fallback, keeping the history.

**Two copies.** When two people update separate copies of papers.db, one of them runs `merge_db.py --from <their
papers.db>` (`--files <their project folder>` also copies in their PDFs and SI; `--dry-run` only says what would
change), then `dedup.py --apply`, and shares the merged file: the copies converge. Papers are matched by identity
(DOI, patent number, title key, aliases), never by ID; nothing either copy found, checked, downloaded, screened or
curated is lost, and duplicates one copy merged are merged in the other. The rules per field are in merge_db.py's
docstring and [references/database.md](references/database.md). A merge that finds nothing new changes nothing.

## Where things are

- `publications/papers.db` — the paper database (all topics), updated in place by every step, with its history
  (`runs`, `changes`), saved filters and working state ("The database evolves" below).
  `publications/<slug>/index/{OA,OA+ND,Free-to-read,Paywalled,merged,excluded}.csv` — the topic index (32 columns),
  written on request (`export.py --csv`). Columns, tables, access and license rules, the
  Extracted column: [references/database.md](references/database.md).
- `publications/<slug>/corpora/<corpus>/sources.json` — a frozen corpus (freeze_corpus.py).
- `publications/<slug>/papers/<access>/<ID>.pdf`, SI in `papers/SI/<access>/`. A paper in two topics has one row and a
  copy (APFS clone, no extra disk) in each topic folder.
- Topic vocabulary and Topic A/B/C rules: [references/topics.md](references/topics.md). Sources, keys, what is skipped:
  [references/sources.md](references/sources.md). Errors and fixes: [references/troubleshooting.md](references/troubleshooting.md).
- `.scripts/` — working ledger, per-topic config/queries/raw hits/batches/logs. `~/.paper-acquisition/` — keys.txt and
  the machine-wide EZproxy config and limiter state.

## Orchestrated mode (invoked by another skill)

Inline arguments, e.g. `topic="..." slug=... mode=index access=OA,OA+ND screening=claude wrapper_confirmed=true`.
Also accepted: `mode=index|download|update` (default index), `sources=`, `threshold=`, `base_url=`, `model=`,
`import_file=` (import_list.py), `max_papers=` (download_open.py --max), `fill_abstracts=true|false`,
`auto_download=true`. No banner, no intake questions: use the arguments and the topic's saved config, defaults for
the rest (access OA,OA+ND,Free-to-read; screening claude); write the plan files yourself and skip the plan approval
when `wrapper_confirmed=true`. Safe duplicates are merged as usual; uncertain pairs are not asked about here — they
stay separate and the summary gives their number. `mode=index` stops after the Index report. `mode=download` still
stops at the Download gate unless `auto_download=true` — the real numbers are a new decision. Return a short
summary: index paths, counts, duplicates merged, uncertain pairs, papers downloaded, keyed sources skipped.
