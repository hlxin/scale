# Catalysis literature index

An index of the catalysis literature, the whole field (heterogeneous, homogeneous, electro-, photo-, bio-/enzymatic,
organo- and plasma catalysis), built on 2026-10-13/14 with the `paper-acquisition` skill (v3.3, in
[`skills/paper-acquisition/`](../skills/paper-acquisition/)). It is an index of records, not a corpus: no PDF was
downloaded.

| | |
|---|---|
| Searched | 24 open databases (OpenAlex, Crossref, Semantic Scholar, Europe PMC, OpenAIRE papers and datasets, PubMed Central, arXiv, OSTI, DOAJ, HAL, Zenodo, DataCite, J-STAGE, CiNii, PLOS, NASA NTRS, Figshare, OSF, Dataverse, Dryad, Materials Cloud, Crossref preprint servers, Europe PMC patents) |
| Raw hits | 11,369,538, kept when the title or abstract carries "cataly…" |
| Records | **2,313,014** after deduplication (same DOI, preprint ↔ published version, patent families, repository copies) |
| In scope | **2,186,836** after keyword screening (Relevance 5 = "cataly…" in the title, 4 = only in the abstract) |
| Access type and license | every record, from OpenAlex, Crossref, Unpaywall, Europe PMC and PubMed Central |

## Files

The index is split by access type into gzipped CSV parts of at most 45 MB (GitHub's file limit). Every part has the
header row, so each one can be read on its own.

| Files | Rows | What |
|---|---|---|
| `index/OA-01…07.csv.gz` | 380,167 | open access with a licence allowing derivatives (CC BY, BY-SA, BY-NC, BY-NC-SA, CC0, public domain) |
| `index/OA+ND-01…02.csv.gz` | 74,198 | open access, no derivatives (CC BY-ND, BY-NC-ND) |
| `index/Free-to-read-01…02.csv.gz` | 366,090 | an open copy exists but carries no reuse licence (bronze, publisher terms); patents |
| `index/Paywalled-01…06.csv.gz` | 1,366,381 | no open copy found |
| `index/excluded-01.csv.gz` | 126,178 | out of scope after screening, non-papers (errata, corrections, ChemInform abstract digests, cover pages) and retracted papers, with the reason in `Notes` |

The four access files together are the in-scope index (the skill's `merged.csv`). Document types in scope: 1,899,305
articles, 120,252 reviews, 58,310 patents (one row per invention), 32,618 conference papers, 31,982 preprints,
16,099 reports, 14,269 datasets, 6,479 theses and 7,522 others.

**Abstracts** are included only where the paper's licence allows redistribution: rows whose `Access type` is OA or
OA+ND (their licence and its URL are in `License` and `License URL`). In Free-to-read and Paywalled rows the
`Abstract` column is left empty. The full database (`papers.db`) keeps every abstract; it is not in this repository
(10.9 GB).

## Columns (32)

`ID` (stable record number) · `Title` · `Authors` (first 10) · `Year` · `Venue` · `Publisher` · `Doc type` · `DOI/ID`
· `URL` · `Abstract` · `Keywords` · `Topic A`, `Topic B`, `Topic C` (main topics from a 125-term catalysis
vocabulary, `skills/paper-acquisition/vocab/catalysis.json`) · `Related topics` · `Relevance` (0-5) ·
`Relevance note` · `Access type` · `License` (exact, with version) · `License URL` · `License source` · `Version` ·
`Database` (every source that found the record) · `Index` · `Citations` · `Downloaded` · `Path` · `SI` · `Extracted` ·
`Notes` · `Date added` · `Last checked`. Full definitions: `skills/paper-acquisition/references/database.md`.

## Reading it

```python
import glob
import pandas as pd

oa = pd.concat(pd.read_csv(f, dtype=str) for f in sorted(glob.glob("catalysis-index/index/OA-*.csv.gz")))
in_scope = pd.concat(pd.read_csv(f, dtype=str) for f in sorted(glob.glob("catalysis-index/index/*.csv.gz"))
                     if "excluded" not in f)
```

One CSV from the parts, in a shell (the header is a single line; abstracts may contain line breaks):

```bash
{ gzip -dc catalysis-index/index/OA-01.csv.gz | head -1; for f in catalysis-index/index/OA-*.csv.gz; do gzip -dc "$f" | tail -n +2; done; } > OA.csv
```

[`CONSULT.md`](CONSULT.md) and [`consult.py`](consult.py) answer questions such as "how many papers are about CO2
reduction with electricity as the main driver?" from `papers.db` (pass `--db /path/to/papers.db`). The
paper-acquisition skill can also import these CSVs into a new project (`import_list.py` reads its own index files).

## Limits

- Keyed databases were not searched (Scopus, Web of Science, CORE, Lens, EPO, Springer Nature, IEEE Xplore, NASA
  ADS), so some journal-only records and many patents are missing.
- Relevance comes from a deterministic keyword rule; Topic A/B/C from a vocabulary match (83.7 % of in-scope records
  have a Topic A).
- 27,899 pairs with the same or nearly the same title (conference abstract and article, dataset and paper,
  corrections, Part I/II) were reviewed as a group and kept as separate records.
- 419,256 in-scope records have no abstract in any source the skill reads.
- Access types are the metadata verdict; a downloaded PDF's printed licence can still change one.
- The bibliographic metadata comes from the open databases above. An abstract stays under its paper's licence
  (`License` column); this folder's licence entry in `REUSE.toml` is for the maintainers to set.
