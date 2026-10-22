# The paper database, the topic index and the folders

## Contents
- Folder layout
- Index CSV columns
- publications/papers.db (tables, example queries)
- Access type and license evidence
- IDs, several topics per paper, document types
- The Extracted column (papers curated into a graph)
- publications/vectors.db (the vector store)
- Internal files

## Folder layout

```
publications/
  papers.db                                   the paper database: every topic, normalized, with full-text search
  vectors.db                                  the vector store: the downloaded papers' passages and vectors (local)
  <topic>/index/OA.csv  OA+ND.csv  Free-to-read.csv  Paywalled.csv   (on request: export.py --topic <slug> --csv)
  <topic>/index/merged.csv                    every paper of the topic that is in scope (or not screened)
  <topic>/index/excluded.csv                  screened out, not research articles, retracted — with the reason
  <topic>/papers/OA/  OA+ND/  Free-to-read/  Paywalled/          <ID>.pdf
  <topic>/papers/SI/<access>/                 <ID>_SI.<ext>  or  <ID>_SI_1.<ext>, <ID>_SI_2.<ext> ...
  <topic>/corpora/<corpus>/sources.json      a frozen corpus for curation (freeze_corpus.py; scale corpus check)
  exports/                                    filtered subsets made on request (export.py --name ...)
.scripts/                                     everything the agent generates (never needed to read the corpus)
```

Every step publishes the papers it changed into `papers.db`, in place: the working ledger (`.scripts/ledger.sqlite`)
marks each paper a write touches (`publish_queue`), and the step's export rewrites just those papers' rows. The index
CSVs are written only on request (`export.py --topic <slug> --csv`). A sync rewrites the rows of the papers it
touches, so change data through the scripts (`topics.py set`, `export.py --set-extracted`, a dedup), not in the files. CSVs are UTF-8 with BOM so Excel shows accents.

## Index CSV columns (34)

| Column | Content |
|---|---|
| ID | stable number = file name stem; never reused |
| Title | clean title (HTML/LaTeX removed, chemical formulas rejoined: CO2, Fe2O3) |
| Authors | `First Last; ...` (first 10, then `et al.`; all authors with ORCID/affiliation are in papers.db) |
| Year | publication year |
| Venue | journal, conference, repository or patent office (`US patent`, `EP patent application`) |
| Publisher | publisher; for patents the applicants |
| Doc type | article, review, preprint, conference-paper, book-chapter, book, thesis, report, patent, dataset, software, editorial, letter, erratum, other |
| Retracted | `Yes` (the paper is retracted: OpenAlex / Retraction Watch, Crossref) · `Retraction notice` (this record retracts another paper; Notes links it) · `No` |
| DOI/ID | DOI, else patent number / `arXiv:` / `OSTI:` / other identifier |
| URL | the published (journal) version when there is one, `https://doi.org/<doi>`; else the preprint or landing page |
| Preprint link | the paper's preprint versions (`; `-separated): the preprint DOIs merged into it — a preprint and its journal article are one row — (ChemRxiv, SSRN, Research Square, bioRxiv, arXiv …) and its arXiv record; when none is known, its copies on preprint servers; a preprint's own link. Empty: no preprint known |
| Abstract | full abstract from metadata or an imported WoS / Scopus export; after download optionally from the PDF (`abstract_source` in papers.db) |
| Keywords | author keywords / subjects from the sources |
| Topic A, Topic B, Topic C | the paper's three main topics, most central first, from the topic vocabulary ([topics.md](topics.md)) |
| Related topics | other vocabulary topics it touches + neighbours of A/B/C (CO2RR → CORR, OER → ORR) |
| Relevance | 0-5 for this topic from screening; empty = not screened |
| Relevance note | why (short) |
| Access type | `OA` · `OA+ND` · `Free-to-read` · `Paywalled` |
| License | exact license with version when stated: `CC BY 4.0`, `CC BY-NC-ND 4.0`, `CC0 1.0`, `Elsevier TDM user license`, `Free to read (no license)`, `Subscription — Wiley terms and conditions`, `Patent document (public record)` |
| License URL | the license's URL when known |
| License source | where it came from: `PDF (printed license statement)`, `PubMed Central`, `Crossref`, `Unpaywall`, `OpenAlex`, `DataCite` ... |
| Version | `Published version` / `Accepted manuscript` / `Preprint` (downloaded copy, else the best open copy) |
| Database | every source that found it |
| Index | every topic (index) the paper belongs to |
| Citations | citation count (OpenAlex, else Semantic Scholar / Crossref) |
| Downloaded | `Yes` / `No` / `n/a` (datasets and software are indexed, never downloaded) |
| Path | `publications/<topic>/papers/<access>/<ID>.pdf` |
| SI | before download: `Available (n deposits)` when SI is listed for the paper (`find_si.py` at index time, and SI deposits the search found), else empty; after download: `Yes` / `No` / `Queued` |
| Extracted | `No`, or `Yes — <graph> (<date>)`, `Rejected — ...`, recorded when a paper is curated (below) |
| Notes | why: out of scope, not downloaded (reason), copy is the accepted manuscript, no abstract in the metadata, `RETRACTED (notice: <link>)`, `Retraction notice of <link>` ... |
| Date added | date the paper entered this topic (update runs: the run's date) |
| Last checked | last time access / license / retraction were checked |

Sort: relevance (unscreened counts as 3), then newest year, then most cited.

## publications/papers.db

Normalized SQLite, open with DB Browser for SQLite, `sqlite3`, pandas (`pd.read_sql`) or R. The `about` table holds
column descriptions and example queries. Tables: `papers` (one row per paper; `topic_a/b/c`, `related_topics`,
`license`, `access_type` ...), `authors` + `paper_authors` (ORCID, institutions, countries), `collections` (topics with
counts and last index/update dates) + `paper_collections` (relevance, scope, PDF path per topic), `subjects` (the
vocabulary) + `paper_subjects` (kind `main` rank 1-3 = Topic A/B/C, or `related`), `sources` + `paper_sources`,
`identifiers` (every DOI alias, PMCID, arXiv, every patent number of one invention ...), `files` (PDF/SI per topic),
`supplements` (the SI listed for a paper before download: doi or file URL, url, title, source — the route that
found it), `extractions` (curation
status), `papers_fts` (full-text index on title, abstract, keywords; kept in step by triggers). Views: `v_papers`,
`v_collection_papers`. In `papers`, `url` is the published version's link and `preprint_url` the preprint links (as
the index columns URL and Preprint link); `is_retracted` = 1 for a retracted paper, whose notice is in `identifiers`
(scheme `retraction_notice`); a retraction notice has `is_non_paper` = 1 and names the paper it retracts (scheme
`retraction_of`). Columns are only ever added: a database from an older version gains them, filled, at its next
update (a run of its own in `runs`).

History and state, in the same file:

| Table | Contents |
|---|---|
| `runs` | one row per publish that changed something: `at`, `step` (the script), `topics`, `added`, `updated`, `removed`, `papers` (in the database after it), `note` |
| `changes` | per paper and run: `change` = `added` (field: none; new: its topics) · `removed` (old: its DOI; new: `merged into <id>`, `supporting information of <id>`, `removed from every topic`) · `changed` (`field` = doi, access_type, license, version, is_preprint, is_retracted, downloaded, si, topic_a, preprint_url; `old`, `new`) · `collection` (field: the topic; old/new: in_scope, empty when it joined or left) |
| `filters`, `filter_members` | saved filters (`filters.py`): name, definition (JSON), last refresh, members; their papers with a `label` and `level` (strict / broad) |
| `_paper_state` | the ledger fields the tables above do not show (JSON per paper: key, author details, known copies, external ids, download state ...) |
| `project_files` | the topics' `config.json`, `queries.json`, `state.json`, `criteria.md`, `keywords.json`, and the project's `dedup_decisions.jsonl` and `vocab_custom.json` |
| `author_keys` | which ORCID, OpenAlex id or name each author id stands for, so ids stay the same across updates |
| `_si_links_unattached` | SI links whose parent DOI is no indexed paper (an issue DOI ...), kept so the ledger can be rebuilt whole |

With these, the file is self-contained: when `.scripts/ledger.sqlite` is missing, the first script that opens the
project rebuilds it (and the topic files) from papers.db, and every step carries on from there. `export.py --rebuild`
rebuilds papers.db from the ledger (a fallback; it keeps `runs`, `changes`, the filters and the author ids).

**Merging two copies** (`merge_db.py --from <their papers.db>`). Papers match by identity (key, DOI, any alias),
never by ID; a paper only the other copy has gets a new ID here; when one paper there matches two here, the other
copy merged them and they are merged here too. Bibliographic fields are kept and only filled where empty here;
citations take the larger count; a retraction or erratum flag from either copy holds; access and licence take a
verdict read from a PDF over metadata, else the more recently checked one; known copies, sources, identifiers,
aliases and SI links are united; downloads stay each copy's own (the other copy's download URL joins the known
copies, and `--files` copies the PDF and SI in under this copy's ID); topics are united, and in a topic both hold the
better screening method decides; Topic A/B/C come from the better method; curation results are united; the topics'
search runs, queries, merge decisions and project terms are united; the other copy's runs since the copies parted
(each run has a `uid`) are added with their changes, and the merge is a run of its own.

```sql
-- papers added since June, by run
SELECT r.at, r.step, p.title FROM changes c JOIN runs r ON r.id = c.run_id JOIN papers p ON p.id = c.paper_id
WHERE c.change = 'added' AND r.at >= '2026-06-01' ORDER BY r.at;
-- papers that became open access
SELECT p.title, c.old, c.new, r.at FROM changes c JOIN runs r ON r.id = c.run_id JOIN papers p ON p.id = c.paper_id
WHERE c.field = 'access_type' AND c.new IN ('OA', 'OA+ND');
```

```sql
SELECT id, title, year, venue FROM v_collection_papers WHERE collection = 'co2rr' AND in_scope = 1 ORDER BY year DESC;
SELECT title, year FROM papers WHERE venue LIKE '%ACS Catal%' AND year BETWEEN 2020 AND 2026;
SELECT p.title FROM papers p JOIN paper_subjects s ON s.paper_id = p.id WHERE s.label = 'Single-atom catalysts' AND s.kind = 'main';
SELECT p.id, p.title FROM papers_fts JOIN papers p ON p.id = papers_fts.rowid WHERE papers_fts MATCH 'copper AND ethylene';
```

A question that names a subject in words — "how many papers are about CO2 reduction driven by electricity?" — maps
to vocabulary terms (`topics.py vocab`; `subjects` lists them). Count the main term, then its neighbours separately so
the user decides what to include, and add a full-text count for wording the vocabulary lacks:

```sql
-- electrochemical CO2 reduction (CO2RR) as Topic A, B or C; never errata or retracted papers
SELECT COUNT(DISTINCT s.paper_id) FROM paper_subjects s JOIN papers p ON p.id = s.paper_id
WHERE s.term = 'co2rr' AND s.kind = 'main' AND COALESCE(p.is_non_paper, 0) = 0 AND COALESCE(p.is_retracted, 0) = 0;
-- neighbours: PEC (light + bias), pulsed electrolysis, electrolyzers, metal-CO2 batteries, bioelectrocatalysis
SELECT s.label, COUNT(DISTINCT s.paper_id) FROM paper_subjects s
WHERE s.kind = 'main' AND s.term IN ('co2rr', 'pec', 'pulsed', 'electrolyzer', 'metal-air', 'bioelectro') GROUP BY s.label;
-- electricity-driven CO2 conversion outside CO2RR, e.g. plasma catalysis of CO2
SELECT COUNT(DISTINCT a.paper_id) FROM paper_subjects a JOIN paper_subjects b ON b.paper_id = a.paper_id
WHERE a.term = 'plasma' AND a.kind = 'main' AND b.term IN ('co2-conversion', 'co2rr', 'co2-hydrogenation', 'ccu');
-- wording outside the vocabulary (title, abstract, keywords)
SELECT COUNT(*) FROM papers_fts JOIN papers p ON p.id = papers_fts.rowid
WHERE papers_fts MATCH '("CO2 reduction" OR co2rr OR "carbon dioxide reduction") AND (electrochemical OR electrocatalytic OR electroreduction)'
  AND COALESCE(p.is_non_paper, 0) = 0;
```

Per collection, join `paper_collections` (`collection = '<slug>' AND COALESCE(in_scope, 1) = 1`); by year, `GROUP BY p.year`.

The same filters, as files: `export.py --name <name> --topic <slug> --subject ... --venue ... --year 2020-2026
--access OA,OA+ND --doc-type article,review --format csv|jsonl|bib|ris` → `publications/exports/<name>.<ext>`.

## Access type and license evidence

| Value | Meaning | Reuse |
|---|---|---|
| OA | a copy under CC BY, BY-SA, BY-NC, BY-NC-SA, CC0 or public domain | derivatives allowed (respect NC/SA); attribution |
| OA+ND | best copy is CC BY-ND or BY-NC-ND | share unchanged; no derivatives |
| Free-to-read | an open copy exists but carries no reuse license (bronze, publisher terms, unlicensed manuscript); patents | read only |
| Paywalled | no open copy anywhere | institutional copy for internal research only |

Before download (`classify_access.py`) the value comes from metadata: the most open copy listed by Unpaywall,
OpenAlex, Crossref (publisher-deposited license of the version of record), Europe PMC, the PMC open-data mirror,
DataCite and Semantic Scholar; DOI-less records use the license their repository states. After download the PDF
decides, strongest evidence first: the license statement printed in the article (version and URL read from it) >
PMC license code > the copy's license metadata > how it was obtained. A paper can move folders (metadata said OA,
the PDF says ND → `OA+ND/`; Notes records the difference). Update mode re-checks papers whose `Last checked` is old:
embargoes end, open copies appear, retractions are flagged, preprints get their published DOI.

## IDs, several topics, document types

- IDs are assigned when a paper first enters the ledger and never change or get reused; merged duplicates keep the
  surviving ID. Files: `<ID>.pdf`, `<ID>_SI*.ext`.
- One row per paper. A paper found under two topics lists both in `Index`; when downloaded, the PDF (and SI) exists
  in each topic's folder as an APFS clone (no extra disk on macOS; hard link or copy elsewhere).
- Deduplication is automatic: `build_list.py` on every run, `dedup.py --apply` after every index, update and
  download: same DOI; same patent number (application and grant fall together); preprint ↔ published version (the
  journal article's row keeps the preprint's DOI, shown in the Preprint link column);
  repository copy ↔ journal article; Angewandte `ange.`/`anie.` twins; DOI-less records matched by title;
  byte-identical PDFs. A dataset is never merged into its paper. Uncertain pairs (the same title under two DOIs) wait
  for the user (`.scripts/dedup_review.csv`; `dedup.py --merge` / `--keep-separate`, remembered in
  `.scripts/dedup_decisions.jsonl`). Every merge is in `.scripts/logs/dedup_log.jsonl` with the full merged row.
- Patents: one row per invention. Records with the same number (application A1 and grant B1) fall together in
  `build_list.py`; family members filed in other offices (WO, EP, US, CN …) and HAL / OSTI copies are merged by
  `dedup.py` when the title and the inventors match. The row keeps every number (`identifiers` scheme `patent`, index
  Notes "Same invention also published as …"; the representative is the WO, else EP, else US number).
- SI is listed before anything is downloaded and is never a paper of its own: `si_links` in the ledger, `supplements`
  in papers.db, "Available (n deposits)" in the index SI column. `find_si.py` (Index step 7) finds it by route
  (`supplements.source`): `crossref_component` (ACS, PLOS `<DOI>.s001` …), `datacite` (publisher SI on Figshare,
  Zenodo …) and `datacite_data` (data deposits such as Dryad, CCDC structures, repository data that declare
  IsSupplementTo the paper), `crossref_relation` (is-supplemented-by), `pmc_oa` (PubMed Central open-access files),
  and for topics up to 50,000 papers `elsevier_cdn` (mmcN files), `mdpi_cdn` (-s001 files) and `landing` (publisher
  pages: Nature, Springer, BMC, Frontiers). A file found by two routes is listed once. `build_list.py` adds the SI
  deposits the search itself returned. Datasets found by the search also stay rows of type dataset, linked by
  `identifiers` scheme `supplement_to`. SI that only sits on walled publisher sites (Wiley, RSC, ACS and IOP pages)
  is found by `fetch_si.py` when the paper is downloaded; `fetch_si.py` downloads the listed SI first.
- Abstracts are cleaned on the way in: a leading "Abstract"/"Summary" heading (also glued to the text), ACS
  graphical-abstract debris, the trailing copyright line and placeholders are removed (`normalize_abstract`).
- Non-papers (errata, corrections, retraction notices such as "Retraction of …" / "Notice of retraction", withdrawn
  articles, expressions of concern, peer-review reports, cover art, ChemInform digests) and retracted papers go to
  `excluded.csv` and are never downloaded. A retraction is read from OpenAlex (Retraction Watch) and Crossref: a
  Crossref notice that names another DOI makes that paper retracted (Retracted `Yes`, Notes link the notice) and is
  itself a non-paper (Retracted `Retraction notice`), never a retracted paper. A record that only one source typed as an erratum, with nothing else
  marking it as a notice, is kept as an article.

## The Extracted column (papers curated into a graph)

A downloaded paper becomes a scale-catal document with [curate-source](../../curate-source/SKILL.md), a frozen
corpus of them with [curate-corpus](../../curate-corpus/SKILL.md)
(`scale source start --pdf publications/<slug>/papers/<access>/<ID>.pdf`). Record the result in the index by hand:
`export.py --set-extracted 12,57 --topic co2rr --kg <graph name> --value extracted` (or `rejected`, `failed`,
`no_data`; `none` removes the record). curate-corpus reports its results itself (`curate_run.py status --apply`), one
JSON object per paper in
`.scripts/<topic>/kg/<graph name>/extraction_status.jsonl`:
`{"paper_id": 12, "topic": "co2rr", "kg": "co2rr-catalysts", "status": "extracted|rejected|failed|no_data",
"schema_version": "0.5.0", "nodes": 18, "edges": 25, "date": "2026-10-12", "note": "...", "abstract": "..."}`.
Every export syncs these files into the ledger (`extractions` table) and fills a missing abstract with the one the
curator copied from the PDF.

## publications/vectors.db (the vector store)

The downloaded papers' text for search by meaning and by words (`vectors.py`). It holds only what a search needs; the
records stay in papers.db, joined by paper ID. Local, like the PDFs: it holds their text.

| Table | Contents |
|---|---|
| `papers` | one row per paper in the store: `signature` (what its passages were read from: the cutter, the PDF's sha1, each SI PDF's name and size), `pdf`, `si_files`, `pages`, `pages_without_text` (no text layer: scanned), `passages`, `chars`, `read_at`, `note` (why unreadable) |
| `passages` | `id` `<paper ID>/p<page>/<k>` (SI pages `S1`, `S2` … after the paper's), `paper_id`, `page`, `k`, `start` / `end` in the page's text, `text`, `text_sha1` |
| `vectors` | one int8 vector (L2-normalized, as SCALE quantizes) per passage text and `embedder`; a text is embedded once per embedder, whatever paper or page holds it |
| `passages_fts` | the passages' words (FTS5, BM25) |
| `about` | `embedders` (the ones kept up to date), `cutter`, `created_at`, `updated_at` |

Which papers: downloaded, in scope in a topic, not a non-paper or retracted, PDF on disk. Passages are cut as SCALE's
`tools/passages.py` cuts source pages (paragraphs joined up to 900 characters, a longer one cut at a sentence end;
spans under 25 characters are not stored, their numbers kept). Search (`vectors.py search`): `hybrid` (the mean of
BM25 scaled to its best and the cosine), `vector` or `keyword`, exact over every passage; `--topic`, `--year` and
`--ids` limit it by the index. Embedders keep SCALE's names (`scale-hash-v1`, `fastembed:<model>`) and add
`sentence-transformers:<model>`; a neural model is fetched only by `vectors.py init`, so updates and searches run offline.

```sql
-- the passages of paper 12 with its record (sqlite3 publications/vectors.db)
ATTACH 'publications/papers.db' AS idx;
SELECT v.id, v.page, substr(v.text, 1, 120), p.title FROM passages v JOIN idx.papers p ON p.id = v.paper_id
WHERE v.paper_id = 12 ORDER BY v.rowid;
```

## Internal files (`.scripts/`)

`ledger.sqlite` (the working ledger: also `si_links`, aliases such as `patent:WO2008004088` in `dois`, and
`publish_queue`, the papers changed since the last publish; rebuilt from papers.db when missing), `enrich/`
(`<api>.sqlite`: API answers shared by topics, each dated; an older `<api>.jsonl` is imported once and kept),
`dedup_decisions.jsonl`, `dedup_review.csv`, `logs/` (`download_attempts.jsonl`, `paywalled.log`, `dedup_log.jsonl`,
`repair_log.jsonl`, `ezproxy_evidence/`), `rejected/wrong_paper/`,
`duplicates/`, `tmp/`, `vocab_custom.json` (project topic terms), and per topic `<slug>/`: `config.json`,
`queries.json`, `criteria.md` or `keywords.json`, `state.json` (progress, search cursors, run dates),
`candidates.jsonl`, `raw/<run>/<source>.jsonl`, `screen/<stage>/{pending,out,done}/`, `out_of_scope/`, `kg/`
(curation status files, above).
