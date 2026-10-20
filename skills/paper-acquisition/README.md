# paper-acquisition — README

A Claude Code skill that indexes the literature of a topic — papers, preprints,
patents and datasets — into a filterable database, and downloads the papers you choose. Ask Claude in plain words
("index the literature on MXene catalysts for nitrate reduction", "download the open-access papers of co2rr",
"update co2rr with newer papers", "export the 2020-2026 copper papers in ACS journals").

## Modes

| Mode | What happens | Downloads? |
|---|---|---|
| **Index** | searches every source, deduplicates, classifies access and license, screens relevance, lists every paper's SI, assigns Topic A/B/C | no |
| **Download** | downloads the selected access types (open routes; paywalled only through the library EZproxy) + SI | yes |
| **Update** | exhaustive refresh: every source and query since the last run, citation chasing, re-check of access, retractions and preprints | optional |

When a topic already exists, Claude asks whether to download, update or rebuild the index. Everything else is just a
request, no mode:

- **Questions and lists** ("how many 2024 papers are open access?", "give me a BibTeX of the 2023 ACS papers on
  copper") — answered from `publications/papers.db`; files go to `publications/exports/` (CSV, JSONL, BibTeX, RIS).
- **Adding papers** from a Web of Science export (Plain text, Tab-delimited, BibTeX, RIS), a Scopus export (CSV,
  BibTeX, RIS), a Zotero / EndNote file or a list of DOIs — the file's abstracts and keywords are kept.
- **Duplicates** are merged automatically after every index, update and download (preprint ↔ published version,
  repository copy ↔ journal article, same paper without/with DOI, byte-identical PDFs, one patented invention filed
  in several offices). Claude asks only about uncertain pairs (the same title under two DOIs); a pair you keep
  separate is never asked again.
- **SI**: every in-scope paper's supplementary information is listed in the index before anything is downloaded
  (`find_si.py`: ACS/PLOS `.s001` components, DataCite deposits, Crossref relations, PubMed Central files, and for
  topics up to 50,000 papers the Elsevier/MDPI CDNs and open publisher pages; index SI column "Available (n
  deposits)"). Download mode fetches the listed files first; SI on walled sites comes when the paper is downloaded.
- **Very large topics** (a whole field): index once as a catalog; access type, license and screening run on the whole
  catalog in hours (blocks of 20,000 papers, every source at its allowed pace — about 2 million papers in 2-3 h);
  downloads go per subtopic.

## What you get

```
publications/
  papers.db                         SQLite database of every topic, updated in place by every step, with its history
                                    (open with DB Browser for SQLite, pandas, R)
  <topic>/index/*.csv               on request: merged.csv (in scope or not screened), one CSV per access type,
                                    excluded.csv (screened out / not research articles / retracted, with the reason)
  <topic>/papers/<access>/<ID>.pdf  downloaded papers; SI in <topic>/papers/SI/<access>/
  <topic>/corpora/<name>/sources.json   a frozen corpus for curation: every paper with its status (freeze_corpus.py)
  exports/                          filtered lists you asked for
```

Index columns: ID, Title, Authors, Year, Venue, Publisher, Doc type, DOI/ID, URL, Abstract, Keywords, Topic A, Topic B,
Topic C, Related topics, Relevance, Relevance note, Access type, License (exact, e.g. CC BY-NC 4.0), License URL,
License source, Version, Database, Index, Citations, Downloaded, Path, SI, Extracted, Notes, Date added, Last checked.
Details: `references/database.md`. Agent working files live in `.scripts/` (never needed to use the results).

## API keys

Most sources need no key. Some add coverage only with a key; without it they are skipped (Claude tells you which).

**Where:** `~/.paper-acquisition/keys.txt` — one file for all your projects, outside any project folder so it is never
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
yourself and run `chmod 600 ~/.paper-acquisition/keys.txt`. Open it in any text editor, paste each key after its
`service:` and save. **Never paste keys into the chat** — the scripts read the file and never print a key (they show
only "set (…last 4)" or "missing").

**Check it:** `keys.py` lists every source and the key it waits for; `keys.py --test` makes one tiny request per key.

| service | How to get it | What it enables |
|---|---|---|
| `openalex` | free — openalex.org account → API key (help.openalex.org/api/authentication) | **needed for a complete index**: without it OpenAlex returns at most 10,000 results per query and shares one small daily budget with everyone on your network, so a run can stop halfway |
| `s2` | free — semanticscholar.org/product/api (request form) | Semantic Scholar abstracts and open copies on topics of any size (without a key its shared pool refuses most requests, so topics over 20,000 papers skip it) |
| `core` | free — core.ac.uk/services/api | CORE: ~300M open-access records from repositories |
| `lens` | free for non-commercial use — lens.org → API access (Scholarly and Patent API) | Lens scholarly works and Lens patents (100+ patent offices) |
| `epo_key` + `epo_secret` | free — developers.epo.org (create an app: consumer key + secret) | EPO Open Patent Services (EP, WO, worldwide patents) |
| `springer` | free — dev.springernature.com | Springer Nature metadata incl. Nature, BMC, SpringerOpen |
| `ieee` | free (limited) — developer.ieee.org | IEEE Xplore |
| `ads` | free — ui.adsabs.harvard.edu → Settings → API Token | NASA ADS |
| `scopus` (+ optional `scopus_insttoken`) | dev.elsevier.com; works with the library's Scopus subscription (campus network or VPN; the institutional token lets it work off campus) | Scopus |
| `wos` | developer.clarivate.com (Web of Science Starter API; institutional) | Web of Science |
| `zenodo`, `ncbi`, `cinii` | optional tokens for higher rate limits | Zenodo, PubMed Central, CiNii |
| `llm_api_key` | your institution's OpenAI-compatible LLM service | relevance screening through that API instead of Claude |

## Sources

34 automated sources: 25 keyless (OpenAlex, Crossref, Crossref preprint servers incl. ChemRxiv / Research Square /
SSRN / bioRxiv, Semantic Scholar, Europe PMC, PubMed Central, OpenAIRE, OSTI, NASA NTRS, arXiv, DOAJ, HAL, Zenodo,
Figshare, OSF, PLOS, DataCite, Harvard Dataverse, Dryad, Materials Cloud, J-STAGE, CiNii, Europe PMC patents, OpenAIRE
datasets, ERIC) and 9 with a key (CORE, Scopus, Web of Science, Springer Nature, IEEE, NASA ADS, Lens, Lens patents,
EPO). Another 35 are reached through those or deliberately skipped (Google Scholar, ResearchGate and pirate sites
never) — the full list with reasons is in `references/sources.md`.

## Paywalled papers

Only through your library's EZproxy from the campus network or VPN, by one rate-limited process per computer
(≤ 120 papers per publisher per day, ≤ 600 per day overall, long pauses, automatic stops on any block or login page).
The skill never logs in, never types credentials, never solves CAPTCHAs. Details: `references/paywalled.md`.

## Using the database

```sql
-- papers of a topic, newest first
SELECT id, title, year, venue FROM v_collection_papers WHERE collection = 'co2rr' AND in_scope = 1 ORDER BY year DESC;
-- by subject (Topic A/B/C or related)
SELECT p.title FROM papers p JOIN paper_subjects s ON s.paper_id = p.id WHERE s.label = 'Single-atom catalysts';
-- full-text search
SELECT p.title FROM papers_fts JOIN papers p ON p.id = papers_fts.rowid WHERE papers_fts MATCH 'copper AND ethylene';
```

`papers.db` evolves: every step updates, in place, only the papers it changed, and records the run (`runs`) and the
changes (`changes`: added, merged, access, licence, retraction, download, SI ...). It also carries the topics' queries
and settings, so whoever receives the file can keep updating it. A sync rewrites the rows of the papers it touches, so
change data through the skill rather than by editing the file. Saved filters (`filters.py`) keep a selection, such
as all CO2-reduction papers, up to date in the same file. Two people who updated separate copies bring them back
together with `merge_db.py` (nothing either found is lost; the same paper found by both is kept once).

## Requirements

Python 3.10+ with `requests`, `pymupdf` and `pypdf` (`pip install requests pymupdf pypdf`), macOS or Linux.
