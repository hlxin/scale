# CO2 reduction driven by electricity: paper database

A SQLite database of **23,631 papers on CO2 reduction driven by electricity**, taken from a whole-field catalysis
index (2,313,134 records on 2026-10-20) built on 2026-10-13/14 with the [`paper-acquisition`](../skills/paper-acquisition/)
skill and updated in place since.
It is an index of records, not a corpus. This folder holds its documentation and a query tool; the database itself
is shared outside git.

## Where the database is

The file is not in this repository, for two reasons. Every new version of it would stay in the history of every
clone (about 37 MB each). And its abstracts keep their papers' own licences, some of them non-commercial or
no-derivatives (CC BY-NC-ND), which a licence rule in `REUSE.toml` cannot state for the file as a whole.

| File | Size | Use |
|---|---|---|
| `co2-reduction-electricity.db.gz` | 37 MB | shared outside git; `gunzip -k co2-reduction-electricity.db.gz` gives `co2-reduction-electricity.db` (123 MB, SQLite), the version described here (built 2026-10-22) |

Put the unpacked file in this folder (or name it in `CATALYSIS_PAPERS_DB`) and [`consult.py`](consult.py) finds it.

## Keeping it current

The CO2 database is a saved filter of the catalysis database (`papers.db`), which evolves: every paper-acquisition
step updates it in place and records what changed. The filter's definition is
[`co2-reduction-electricity.filter.json`](co2-reduction-electricity.filter.json): concept CO2 reduction × driver
(electrochemical, plasma, electrified heating), strict and broad, with errata, notices and retracted papers left
out. Stored in `papers.db`, it re-runs after every update, and the CO2 file is exported from it:

```bash
S=skills/paper-acquisition/scripts
python3 -I $S/filters.py define --name co2-reduction-electricity --file catalysis-index/co2-reduction-electricity.filter.json
python3 -I $S/filters.py export --name co2-reduction-electricity --out co2-reduction-electricity.db --public
```

`define` is needed once per database; `export --public` keeps abstracts only for OA and OA+ND papers, as in the shared
file.

## What is in it

Papers on the reduction of CO2 (electrochemical, plasma, electrified heating) found in 24 open databases (OpenAlex,
Crossref, Semantic Scholar, Europe PMC, OpenAIRE, PubMed Central, arXiv, OSTI, DOAJ, HAL, Zenodo, DataCite, J-STAGE,
CiNii and others), deduplicated (same DOI, preprint ↔ published version, patent families). Errata, notices and
retracted papers are left out.

| Driver of the CO2 reduction | Strict | Broad only | Total |
|---|---|---|---|
| Electrochemical (electrocatalysis, electrolysis, metal-CO2 batteries, bioelectrocatalysis) | 17,526 | 4,392 | **21,918** |
| Non-thermal plasma (electric discharge) | 1,636 | 130 | 1,766 |
| Electrified heating (Joule, induction, microwave) | 73 | 82 | 155 |

*Strict:* CO2 reduction and the driver appear in the title or among the paper's main topics (Topic A/B/C). *Broad
only:* they appear only in the abstract or keywords. A paper can have two drivers. Table `co2_selection`
(`paper_id`, `driver`, `level`) records each match, so any of these sets can be selected.

Electrochemical, strict: 17,368 papers (14,800 articles, 1,507 reviews, 463 preprints, 275 conference papers, 130
theses, 113 book chapters …; plus 146 datasets). 14,035 papers have CO2RR as Topic A, B or C. Access type of the
21,918 electrochemical records: OA 4,737 · OA+ND 1,286 · Free-to-read 3,483 · Paywalled 12,412.

**Abstracts** are included only where the paper's licence allows redistribution (Access type OA or OA+ND: 6,436
papers). The `License` and `License URL` columns give each paper's licence, and an abstract stays under it.

**Preprints:** a preprint and its journal article are one row, under the journal article (`url`); `preprint_url`
keeps the preprint's link. 711 journal articles have one, and the 471 records that are preprints link themselves.
Retracted papers are left out of this database (`is_retracted` marks them in the full one).

**Supporting information** was looked up for every paper before anything is downloaded (`find_si.py`): **12,440 SI
files and deposits for 8,182 papers** (OA 2,178 · OA+ND 758 · Free-to-read 1,058 · Paywalled 4,188), listed in table
`supplements` (DOI or file URL, title, and the route that found it: Elsevier SI CDN 3,418 · ACS/PLOS `.s001`
components 3,326 · PubMed Central 2,955 · data deposits such as CCDC structures and Dryad 1,451 · publisher pages
993 · MDPI CDN 140 · Figshare/DataCite/other 157) and in the `si` column ("Available (n deposits)"). SI that only sits
on walled publisher sites (Wiley, RSC, ACS and IOP pages) is not listed; it is found when a paper is downloaded.

## Tables

Same layout as the paper-acquisition `papers.db` (column definitions in the `about` table and in
[`references/database.md`](../skills/paper-acquisition/references/database.md)):

| Table | Contents |
|---|---|
| `papers` | one row per paper: DOI, title, authors, year, venue, publisher, doc type, abstract, keywords, Topic A/B/C, access type, exact licence, citations, notes; `url` (the journal version) and `preprint_url` (its preprints, merged into its row), `is_retracted` |
| `co2_selection` | why the paper is in this database: driver and level |
| `authors`, `paper_authors` | authors in order, with ORCID, institutions and countries |
| `identifiers` | every identifier of a paper (DOI aliases, PMID, PMCID, arXiv, OSTI, patent numbers; a retracted paper's notice, `retraction_notice`) |
| `paper_subjects`, `subjects` | Topic A/B/C and related topics from a 125-term catalysis vocabulary |
| `paper_sources`, `sources` | which databases found each paper |
| `supplements` | each paper's supporting information, found before download (DOI or file URL, title, route) |
| `papers_fts` | full-text index on title, abstract and keywords |

```sql
-- electrochemical CO2 reduction, strict, newest first
SELECT p.year, p.title, p.doi, p.venue FROM co2_selection s JOIN papers p ON p.id = s.paper_id
WHERE s.driver = 'electro' AND s.level = 'strict' ORDER BY p.year DESC, p.citations DESC;
-- open-access copper papers among them
SELECT p.title, p.doi, p.license FROM papers_fts f JOIN papers p ON p.id = f.rowid
JOIN co2_selection s ON s.paper_id = p.id AND s.driver = 'electro'
WHERE papers_fts MATCH 'copper' AND p.access_type IN ('OA', 'OA+ND');
```

[`consult.py`](consult.py) answers questions in one command, for example
`python3 -I consult.py count --concept co2-reduction --driver electro` ([`CONSULT.md`](CONSULT.md) explains the
concepts and drivers). The membership of this database is `co2_selection`, decided on the full database with every
abstract; consult.py's text matching on this copy sees abstracts only for OA papers, so it finds slightly fewer
(17,355 strict and 21,025 broad electrochemical records).

`papers.downloaded` and `files` record which papers had their PDF (and their SI, where found) in the local corpus
when the file was built. The PDFs are not shared.

## Limits

- The full catalysis database (2,313,134 records, 12.9 GB) is not shared here either.
- Keyed databases were not searched (Scopus, Web of Science, CORE, Lens, EPO, Springer Nature, IEEE Xplore, NASA
  ADS).
- The selection uses deterministic text and vocabulary rules: the strict level is precise, the broad level adds
  related work (e.g. reviews of electrocatalysis that cover CO2 reduction).
- Access types are the metadata verdict; a downloaded PDF's printed licence can still change one.
