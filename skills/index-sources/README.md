# index-sources — README

A Claude Code skill that indexes the sources of a topic — papers, preprints, patents, theses and reports, and the
datasets found with them — into a filterable index, and freezes the corpus a question needs. Ask Claude in plain words ("index the literature
on MXene catalysts for nitrate reduction", "update co2rr with newer sources", "export the 2020-2026 copper sources in
ACS journals", "freeze the open-access CO2-to-ethylene sources since 2020 for curation"). Fetching a corpus's files
(PDFs, SI) is the [fetch-corpus](../fetch-corpus/README.md) skill's; curating them is curate-corpus's.

## Modes

| Mode | What happens |
|---|---|
| **Index** | searches every database, deduplicates, classifies access and licence, screens relevance, lists every source's SI, assigns Topic A/B/C |
| **Update** | exhaustive refresh: every database and query since the last run, citation chasing, re-check of access, retractions and preprints |

Neither downloads a source's files. When a topic already exists, Claude asks whether to freeze a corpus from it,
update it or rebuild the index. Everything else is just a request, no mode:

- **Questions and lists** ("how many 2024 sources are open access?", "give me a BibTeX of the 2023 ACS sources on
  copper") — answered from `sources/index.db`; files go to `sources/exports/` (CSV, JSONL, BibTeX, RIS).
- **Adding sources** from a Web of Science export (Plain text, Tab-delimited, BibTeX, RIS), a Scopus export (CSV,
  BibTeX, RIS), a Zotero / EndNote file or a list of DOIs — the file's abstracts and keywords are kept.
- **Duplicates** are merged automatically after every index and update (preprint ↔ published version, whose
  row keeps the preprint's link in the Preprint link column,
  repository copy ↔ journal article, same source without/with DOI, byte-identical PDFs, one patented invention filed
  in several offices). Claude asks only about uncertain pairs (the same title under two DOIs); a pair you keep
  separate is never asked again.
- **SI**: every in-scope source's supplementary information is listed in the index before anything is downloaded
  (`find_si.py`: ACS/PLOS `.s001` components, DataCite deposits, Crossref relations, PubMed Central files, and for
  topics up to 50,000 sources the Elsevier/MDPI CDNs and open publisher pages; index SI column "Available (n
  deposits)"). fetch-corpus fetches the listed files first; SI on walled sites comes when the source is fetched.
- **Only English**, if you want it: the topic gate's `english_only` keeps records in other languages out of every later
  search; `remove_sources.py --non-english` takes those already indexed out (each logged in full, its files kept under
  `.scripts/removed/`). Sources leave the index only when you ask.
- **A corpus** is the selection a question needs, frozen by a rule (relevance, Topic A/B/C, document types, years,
  access types, or a list of IDs): `freeze_corpus.py` writes `sources/<topic>/corpora/<name>/sources.json`, which
  fetch-corpus fetches and curate-corpus curates.
- **Very large topics** (a whole field): index once as a catalog; access type, licence and screening run on the whole
  catalog in hours (blocks of 20,000 sources, every database at its allowed pace — about 2 million sources in 2-3 h);
  each question then freezes its own corpus from the catalog.
- **An index made before the sources were so named** (`publications/papers.db`) is upgraded in place the first time a
  script opens the project; `upgrade.py --db <file>` upgrades an index file that came alone.

## What you get

```
sources/
  index.db                         SQLite database of every topic, updated in place by every step, with its history
                                    (open with DB Browser for SQLite, pandas, R)
  <topic>/index/*.csv               on request: merged.csv (in scope or not screened), one CSV per access type,
                                    excluded.csv (screened out / not research articles / retracted, with the reason)
  <topic>/corpora/<name>/sources.json   a frozen corpus: every source with its status (freeze_corpus.py)
  <topic>/files/<access>/<ID>.pdf  the files fetch-corpus fetched; SI in <topic>/files/SI/<access>/
  exports/                          filtered lists you asked for
```

Index columns: ID, Title, Authors, Year, Venue, Publisher, Doc type, Retracted (Yes / Retraction notice / No), DOI/ID,
URL (the journal version when there is one), Preprint link (the preprint of a journal article, merged into its row),
Abstract, Keywords, Topic A, Topic B, Topic C, Related topics, Relevance, Relevance note, Access type, Licence (exact,
e.g. CC BY-NC 4.0), Licence URL, Licence source, Version, Database, Index, Citations, Downloaded, Path, SI, Extracted,
Notes, Date added, Last checked.
Details: `references/database.md`. Agent working files live in `.scripts/` (never needed to use the results).

## API keys

Most databases need no key. Some add coverage only with a key; without it they are skipped (Claude tells you which).

**Where:** `~/.scale/sources/keys.txt` — one file for all your projects, outside any project folder so it is never
shared with a corpus. (A project can override it with `<project>/.claude/keys.txt`.)

**Format:** one `service: key` per line (`service = key` also works); `#` starts a comment; leave a service out (or
keep its `<...>` placeholder) if you do not use it.

```
openalex: 3fa8c9...
core: Zk1n...
lens: ab12...
epo_key: xYz...
epo_secret: 9Qw...
```

**Create it:** ask Claude to run `keys.py --init` (copies `keys.example.txt`, readable only by you), or copy that file
yourself and run `chmod 600 ~/.scale/sources/keys.txt`. Open it in any text editor, paste each key after its
`service:` and save. **Never paste keys into the chat** — the scripts read the file and never print a key (they show
only "set (…last 4)" or "missing").

**Check it:** `keys.py` lists every database and the key it waits for; `keys.py --test` makes one tiny request per key.

| service | How to get it | What it enables |
|---|---|---|
| `openalex` | free — openalex.org account → API key (help.openalex.org/api/authentication) | **needed for a complete index**: without it OpenAlex returns at most 10,000 results per query and shares one small daily budget with everyone on your network, so a run can stop halfway |
| `s2` | free — semanticscholar.org/product/api (request form) | Semantic Scholar abstracts and open copies on topics of any size (without a key its shared pool refuses most requests, so topics over 20,000 sources skip it) |
| `core` | free — core.ac.uk/services/api | CORE: ~300M open-access records from repositories |
| `lens` | free for non-commercial use — lens.org → API access (Scholarly and Patent API) | Lens scholarly works and Lens patents (100+ patent offices) |
| `epo_key` + `epo_secret` | free — developers.epo.org (create an app: consumer key + secret) | EPO Open Patent Services (EP, WO, worldwide patents) |
| `springer` | free — dev.springernature.com | Springer Nature metadata incl. Nature, BMC, SpringerOpen |
| `ieee` | free (limited) — developer.ieee.org | IEEE Xplore |
| `ads` | free — ui.adsabs.harvard.edu → Settings → API Token | NASA ADS |
| `scopus` (+ optional `scopus_insttoken`) | dev.elsevier.com; works with the library's Scopus subscription (campus network or VPN; the institutional token lets it work off campus) | Scopus; Elsevier's open-access full text for fetch-corpus's download_open.py (ScienceDirect blocks scripts) |
| `wos` | developer.clarivate.com (Web of Science Starter API; institutional) | Web of Science |
| `zenodo`, `ncbi`, `cinii` | optional tokens for higher rate limits | Zenodo, PubMed Central, CiNii |
| `llm_api_key` | your institution's OpenAI-compatible LLM service | relevance screening through that API instead of Claude |

## Databases

34 automated databases: 25 keyless (OpenAlex, Crossref, Crossref preprint servers incl. ChemRxiv / Research Square /
SSRN / bioRxiv, Semantic Scholar, Europe PMC, PubMed Central, OpenAIRE, OSTI, NASA NTRS, arXiv, DOAJ, HAL, Zenodo,
Figshare, OSF, PLOS, DataCite, Harvard Dataverse, Dryad, Materials Cloud, J-STAGE, CiNii, Europe PMC patents, OpenAIRE
datasets, ERIC) and 9 with a key (CORE, Scopus, Web of Science, Springer Nature, IEEE, NASA ADS, Lens, Lens patents,
EPO). Another 35 are reached through those or deliberately skipped (Google Scholar, ResearchGate and pirate sites
never) — the full list with reasons is in `references/databases.md`.

## Using the index

```sql
-- sources of a topic, newest first
SELECT id, title, year, venue FROM v_topic_sources WHERE topic = 'co2rr' AND in_scope = 1 ORDER BY year DESC;
-- by subject (Topic A/B/C or related)
SELECT p.title FROM sources p JOIN source_subjects s ON s.source_id = p.id WHERE s.label = 'Single-atom catalysts';
-- full-text search
SELECT p.title FROM sources_fts JOIN sources p ON p.id = sources_fts.rowid WHERE sources_fts MATCH 'copper AND ethylene';
```

`index.db` evolves: every step updates, in place, only the sources it changed, and records the run (`runs`) and the
changes (`changes`: added, merged, access, licence, retraction, download, SI ...). It also carries the topics' queries
and settings, so whoever receives the file can keep updating it. A sync rewrites the rows of the sources it touches, so
change data through the skill rather than by editing the file. Saved filters (`filters.py`) keep a selection, such
as all CO2-reduction sources, up to date in the same file. Two people who updated separate copies bring them back
together with `merge_db.py` (nothing either found is lost; the same source found by both is kept once).

## Vector store

`vectors.py` keeps `sources/vectors.db`: the fetched sources' text as passages (cut as SCALE cuts source
pages), with a vector for each, for search by meaning and by words (`vectors.py search "Cu/ZnO deactivation by
sintering"`). The index keeps the records; the store keeps only the passages and their vectors, and a search joins its
hits to the index. Each source is read once and each text embedded once; every fetch (fetch-corpus), merge and dedup
updates the store. The embedder is SCALE's deterministic `scale-hash-v1` (no download) or a local model
(`sentence-transformers:BAAI/bge-small-en-v1.5`, fetched once by `vectors.py init`). Like the PDFs, it stays local.

## Requirements

Python 3.10+ with `requests`, `pymupdf` and `pypdf` (`pip install requests pymupdf pypdf`), macOS or Linux. The
vector store also needs `numpy`, and a local neural embedder `sentence-transformers` (or `fastembed`).
