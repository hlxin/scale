# CO2 reduction driven by electricity: paper database

A SQLite database of **23,641 papers on CO2 reduction driven by electricity**, taken from a whole-field catalysis
index (2,313,014 records) built on 2026-10-13/14 with the `paper-acquisition` skill (v3.3, in
[`skills/paper-acquisition/`](../skills/paper-acquisition/)). It is an index of records, not a corpus: no PDF was
downloaded.

| File | Size | Use |
|---|---|---|
| `co2-reduction-electricity.db.gz` | 34 MB | `gunzip -k co2-reduction-electricity.db.gz` gives `co2-reduction-electricity.db` (107 MB, SQLite) |

## What is in it

Papers on the reduction of CO2 (electrochemical, plasma, electrified heating) found in 24 open databases (OpenAlex,
Crossref, Semantic Scholar, Europe PMC, OpenAIRE, PubMed Central, arXiv, OSTI, DOAJ, HAL, Zenodo, DataCite, J-STAGE,
CiNii and others), deduplicated (same DOI, preprint ↔ published version, patent families). Errata, notices and
retracted papers are left out.

| Driver of the CO2 reduction | Strict | Broad only | Total |
|---|---|---|---|
| Electrochemical (electrocatalysis, electrolysis, metal-CO2 batteries, bioelectrocatalysis) | 17,537 | 4,392 | **21,929** |
| Non-thermal plasma (electric discharge) | 1,636 | 129 | 1,765 |
| Electrified heating (Joule, induction, microwave) | 73 | 82 | 155 |

*Strict:* CO2 reduction and the driver appear in the title or among the paper's main topics (Topic A/B/C). *Broad
only:* they appear only in the abstract or keywords. A paper can have two drivers. Table `co2_selection`
(`paper_id`, `driver`, `level`) records each match, so any of these sets can be selected.

Electrochemical, strict: 17,379 papers (15,058 articles, 1,507 reviews, 452 preprints, 251 conference papers; plus
146 datasets and a few patents). 14,043 papers have CO2RR as Topic A, B or C. Access type of the 21,929
electrochemical records: OA 5,006 · OA+ND 1,106 · Free-to-read 3,397 · Paywalled 12,420.

**Abstracts** are included only where the paper's licence allows redistribution (Access type OA or OA+ND: 6,534
papers). The `License` and `License URL` columns give each paper's licence.

## Tables

Same layout as the paper-acquisition `papers.db` (column definitions in the `about` table and in
`skills/paper-acquisition/references/database.md`):

| Table | Contents |
|---|---|
| `papers` | one row per paper: DOI, title, authors, year, venue, publisher, doc type, abstract, keywords, Topic A/B/C, access type, exact licence, citations, notes |
| `co2_selection` | why the paper is in this database: driver and level |
| `authors`, `paper_authors` | authors in order, with ORCID, institutions and countries |
| `identifiers` | every identifier of a paper (DOI aliases, PMID, PMCID, arXiv, OSTI, patent numbers) |
| `paper_subjects`, `subjects` | Topic A/B/C and related topics from a 125-term catalysis vocabulary |
| `paper_sources`, `sources` | which databases found each paper |
| `supplements` | supporting-information deposits linked to their paper |
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

[`consult.py`](consult.py) answers questions in one command once the file is unpacked here, for example
`python3 -I consult.py count --concept co2-reduction --driver electro` ([`CONSULT.md`](CONSULT.md) explains the
concepts and drivers). The membership of this database is `co2_selection`, decided on the full database with every
abstract; consult.py's text matching on this copy sees abstracts only for OA papers, so it finds slightly fewer
(17,365 strict and 21,041 broad electrochemical records).

## Limits

- The full catalysis database (2,313,014 records, 10.9 GB) is not in this repository.
- Keyed databases were not searched (Scopus, Web of Science, CORE, Lens, EPO, Springer Nature, IEEE Xplore, NASA
  ADS).
- The selection uses deterministic text and vocabulary rules: the strict level is precise, the broad level adds
  related work (e.g. reviews of electrocatalysis that cover CO2 reduction).
- Access types are the metadata verdict; a downloaded PDF's printed licence can still change one.
- An abstract stays under its paper's licence (`License` column); this folder's licence entry in `REUSE.toml` is for
  the maintainers to set.
