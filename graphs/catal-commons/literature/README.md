# Catal commons: the literature

What catalysis brings to SCALE's general skills, kept with the commons rather than in the skills:

| File | What it is |
|---|---|
| [`vocabulary.json`](vocabulary.json) | the catalysis topic vocabulary (125 terms in four facets) that [`index-sources`](../../../skills/index-sources/SKILL.md) assigns Topic A/B/C from, when it runs from this repository ([topics.md](../../../skills/index-sources/references/topics.md)) |
| [`co2-reduction-electricity.filter.json`](co2-reduction-electricity.filter.json) | the saved filter that selects the CO2 reduction database below from the catalysis index |
| [`consult.py`](consult.py), [`CONSULT.md`](CONSULT.md) | a read-only query tool for the catalysis index and its CO2 subset, and its guide |

The index files themselves are never committed (`*.db` and `*.db.gz` here are git-ignored).

## CO2 reduction driven by electricity: source index

A SQLite file of **23,631 sources on CO2 reduction driven by electricity**, taken from a whole-field catalysis
index (2,313,134 records on 2026-10-20) built on 2026-10-13/14 with the [`index-sources`](../../../skills/index-sources/)
skill (then named paper-acquisition) and updated in place since.
It is an index of records, not a corpus. This folder holds its documentation and a query tool; the database itself
is shared outside git.

### Where the file is

The file is not in this repository, for two reasons. Every new version of it would stay in the history of every
clone (about 37 MB each). And its abstracts keep their sources' own licences, some of them non-commercial or
no-derivatives (CC BY-NC-ND), which a licence rule in `REUSE.toml` cannot state for the file as a whole.

| File | Size | Use |
|---|---|---|
| `co2-reduction-electricity.db.gz` | 37 MB | shared outside git; `gunzip -k co2-reduction-electricity.db.gz` gives `co2-reduction-electricity.db` (123 MB, SQLite), the version described here (built 2026-10-22) |

Put the unpacked file in this folder (or name it in `CATALYSIS_SOURCES_DB`) and [`consult.py`](consult.py) finds it.

A copy built before the sources were so named (tables `papers`, `paper_id`; the files shared on 2026-10-22 and
earlier) is upgraded once, where it can be written: `python3 -I skills/index-sources/scripts/upgrade.py --db <file>`
renames its tables and columns in place (seconds) and rebuilds its full-text index; consult.py says so when it meets
one. A project folder upgrades itself the first time an index-sources script opens it.

### Keeping it current

The CO2 index is a saved filter of the catalysis index (`index.db`), which evolves: every index-sources
step updates it in place and records what changed. The filter's definition is
[`co2-reduction-electricity.filter.json`](co2-reduction-electricity.filter.json): concept CO2 reduction × driver
(electrochemical, plasma, electrified heating), strict and broad, with errata, notices and retracted sources left
out. Stored in `index.db`, it re-runs after every update, and the CO2 file is exported from it:

```bash
S=skills/index-sources/scripts
python3 -I $S/filters.py define --name co2-reduction-electricity --file graphs/catal-commons/literature/co2-reduction-electricity.filter.json
python3 -I $S/filters.py export --name co2-reduction-electricity --out co2-reduction-electricity.db --public
```

`define` is needed once per index; `export --public` keeps abstracts only for OA and OA+ND sources, as in the shared
file.

### What is in it

Sources on the reduction of CO2 (electrochemical, plasma, electrified heating) found in 24 open databases (OpenAlex,
Crossref, Semantic Scholar, Europe PMC, OpenAIRE, PubMed Central, arXiv, OSTI, DOAJ, HAL, Zenodo, DataCite, J-STAGE,
CiNii and others), deduplicated (same DOI, preprint ↔ published version, patent families). Errata, notices and
retracted sources are left out.

| Driver of the CO2 reduction | Strict | Broad only | Total |
|---|---|---|---|
| Electrochemical (electrocatalysis, electrolysis, metal-CO2 batteries, bioelectrocatalysis) | 17,526 | 4,392 | **21,918** |
| Non-thermal plasma (electric discharge) | 1,636 | 130 | 1,766 |
| Electrified heating (Joule, induction, microwave) | 73 | 82 | 155 |

*Strict:* CO2 reduction and the driver appear in the title or among the source's main topics (Topic A/B/C). *Broad
only:* they appear only in the abstract or keywords. A source can have two drivers. Table `co2_selection`
(`source_id`, `driver`, `level`) records each match, so any of these sets can be selected.

Electrochemical, strict: 17,368 papers (14,800 articles, 1,507 reviews, 463 preprints, 275 conference papers, 130
theses, 113 book chapters …; plus 146 datasets). 14,035 sources have CO2RR as Topic A, B or C. Access type of the
21,918 electrochemical records: OA 4,737 · OA+ND 1,286 · Free-to-read 3,483 · Paywalled 12,412.

**Abstracts** are included only where the source's licence allows redistribution (Access type OA or OA+ND: 6,436
sources). The `License` and `License URL` columns give each source's licence, and an abstract stays under it.

**Preprints:** a preprint and its journal article are one row, under the journal article (`url`); `preprint_url`
keeps the preprint's link. 711 journal articles have one, and the 471 records that are preprints link themselves.
Retracted sources are left out of this index (`is_retracted` marks them in the full one).

**Supporting information** was looked up for every source before anything is downloaded (`find_si.py`): **12,440 SI
files and deposits for 8,182 sources** (OA 2,178 · OA+ND 758 · Free-to-read 1,058 · Paywalled 4,188), listed in table
`supplements` (DOI or file URL, title, and the route that found it: Elsevier SI CDN 3,418 · ACS/PLOS `.s001`
components 3,326 · PubMed Central 2,955 · data deposits such as CCDC structures and Dryad 1,451 · publisher pages
993 · MDPI CDN 140 · Figshare/DataCite/other 157) and in the `si` column ("Available (n deposits)"). SI that only sits
on walled publisher sites (Wiley, RSC, ACS and IOP pages) is not listed; it is found when a source is downloaded.

### Tables

Same layout as the index-sources `index.db` (column definitions in the `about` table and in
[`references/database.md`](../../../skills/index-sources/references/database.md)):

| Table | Contents |
|---|---|
| `sources` | one row per source: DOI, title, authors, year, venue, publisher, doc type, abstract, keywords, Topic A/B/C, access type, exact licence, citations, notes; `url` (the journal version) and `preprint_url` (its preprints, merged into its row), `is_retracted` |
| `co2_selection` | why the source is in this index: driver and level |
| `authors`, `source_authors` | authors in order, with ORCID, institutions and countries |
| `identifiers` | every identifier of a source (DOI aliases, PMID, PMCID, arXiv, OSTI, patent numbers; a retracted source's notice, `retraction_notice`) |
| `source_subjects`, `subjects` | Topic A/B/C and related topics from a 125-term catalysis vocabulary |
| `source_databases`, `databases` | which databases found each source |
| `supplements` | each source's supporting information, found before download (DOI or file URL, title, route) |
| `sources_fts` | full-text index on title, abstract and keywords |

```sql
-- electrochemical CO2 reduction, strict, newest first
SELECT p.year, p.title, p.doi, p.venue FROM co2_selection s JOIN sources p ON p.id = s.source_id
WHERE s.driver = 'electro' AND s.level = 'strict' ORDER BY p.year DESC, p.citations DESC;
-- open-access copper sources among them
SELECT p.title, p.doi, p.licence FROM sources_fts f JOIN sources p ON p.id = f.rowid
JOIN co2_selection s ON s.source_id = p.id AND s.driver = 'electro'
WHERE sources_fts MATCH 'copper' AND p.access_type IN ('OA', 'OA+ND');
```

[`consult.py`](consult.py) answers questions in one command, for example
`python3 -I consult.py count --concept co2-reduction --driver electro` ([`CONSULT.md`](CONSULT.md) explains the
concepts and drivers). The membership of this index is `co2_selection`, decided on the full index with every
abstract; consult.py's text matching on this copy sees abstracts only for OA sources, so it finds slightly fewer
(17,355 strict and 21,025 broad electrochemical records).

`sources.downloaded` and `files` record which sources had their PDF (and their SI, where found) in the local corpus
when the file was built. The PDFs are not shared.

### Limits

- The full catalysis index (2,313,134 records, 12.9 GB) is not shared here either.
- Keyed databases were not searched (Scopus, Web of Science, CORE, Lens, EPO, Springer Nature, IEEE Xplore, NASA
  ADS).
- The selection uses deterministic text and vocabulary rules: the strict level is precise, the broad level adds
  related work (e.g. reviews of electrocatalysis that cover CO2 reduction).
- Access types are the metadata verdict; a downloaded PDF's printed licence can still change one.
