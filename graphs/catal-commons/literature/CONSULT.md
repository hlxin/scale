# Consulting the catalysis catalog

This folder holds an index of the catalysis literature: **about 2.3 million records** (journal articles,
reviews, preprints, conference papers, theses, reports, patents and datasets) found in 24 open databases
(OpenAlex, Crossref, Semantic Scholar, Europe PMC, OpenAIRE, arXiv, OSTI, DOAJ, HAL, Zenodo, DataCite ...), merged
into one row per work, with title, abstract, authors (ORCID, institutions), venue, year, DOI and other identifiers,
citations and topics. Nothing in it is downloaded. Everything lives in one SQLite file, `index.db` (12.9 GB).

> **In the hlxin/scale repository** this folder holds this guide and `consult.py`, not the data. The CO2 subset of
> `index.db`, `co2-reduction-electricity.db` (23,631 sources on CO2 reduction driven by electricity,
> [README.md](README.md)), is shared outside git: put it in this folder (or name it in `CATALYSIS_SOURCES_DB`) and
> `consult.py` uses it by default. The counts quoted in this guide refer to the full catalog (2.3 million records,
> also outside the repository; pass `--db /path/to/index.db`); on the subset, questions outside CO2 reduction
> return only the sources that overlap with it.

You can ask it questions in two ways:

1. **`consult.py`** (this folder), which handles concepts ("CO2 reduction"), drivers ("electricity as the main
   driver"), topics, years, document types and authors, and answers in JSON. Start here.
2. **SQL** on `index.db`, for anything else (schema and recipes below).

Both are read-only. Never edit `index.db` by hand: the index-sources pipeline rebuilds it.

---

## 1. Quick start

Run from this folder with Python 3.10+ (standard library only):

```bash
python3 -I consult.py count --concept co2-reduction --driver electro      # add --db /path/to/index.db if needed
```

**"How many sources are about CO2 reduction with electricity as the main driver?"** Answer as of 2026-10-14
(`db_built_at` 2026-10-14T17:38Z: after deduplication and topic re-assignment):

**a) Vocabulary first** (the index-sources skill's recipe; `terms` command, section 3). Each term is counted
as Topic A/B/C, and the neighbours are listed separately so the asker decides what to include:

```bash
python3 -I consult.py terms co2rr,pec,pulsed,electrolyzer,metal-air,bioelectro --with-co2
```

| term (Topic A/B/C) | sources | of which mention CO2 |
|---|---|---|
| CO2RR (CO2 electroreduction) | **14,335** | 14,264 |
| PEC (light + bias) | 12,399 | 1,234 |
| Electrolyzer engineering | 7,298 | 1,968 |
| Metal-air & metal-CO2 batteries | 7,568 | 609 |
| Bioelectrocatalysis | 4,793 | 497 |
| Pulsed electrolysis | 203 | 71 |
| all six terms, without double counting | 44,856 | **17,068** |

Plus plasma catalysis of CO2 (another electricity-driven route): `count --topic plasma --concept co2-reduction` →
1,468. Plus the full-text count for wording the vocabulary lacks:
`count --text '("co2 reduction" OR co2rr OR "carbon dioxide reduction") AND (electrochemical OR electrocatalytic OR electroreduction)'`
→ 13,846.

**b) Concept + driver** (one number at two levels, also catching sources without topics):

```bash
python3 -I consult.py count --concept co2-reduction --driver electro
```

| level | records | papers (no patents/datasets) | of which articles | reviews | preprints |
|---|---|---|---|---|---|
| strict: CO2 reduction **and** the electric driver both in the title or Topic A/B/C | 17,135 | 16,977 | 14,668 | 1,484 | 482 |
| broad: also when they appear only in the abstract or keywords | 20,172 | 19,982 | 16,821 | 2,123 | 584 |

**Answer:** about **14,000 sources have CO2 electroreduction as a main topic, and 17,000–20,000 deal with
electricity-driven CO2 reduction** once sources framed as electrolyzers, PEC, batteries or bioelectrocatalysis are
counted. Plasma CO2 conversion adds about 1,500 more. Always say which terms or definitions were counted: the JSON
returns them.

How CO2 reduction splits by driver (`breakdown --concept co2-reduction --by driver`, strict): electro 17,135 ·
thermal 13,271 · photo 12,661 · bio 1,618 · plasma 1,507 · photoelectro 1,360 · electrified heating 70 ·
no driver detected 5,500. A source can have two drivers, so the rows don't add up to the total.

---

## 2. From a question to a command

| Question | Command |
|---|---|
| How many sources on X? | `count --concept X` · or `count --topic "Label"` · or `count --text 'fts query'` |
| … per vocabulary term and its neighbours, each separately | `terms co2rr,pec,pulsed,electrolyzer --with-co2` |
| … driven by electricity / light / heat / plasma / enzymes? | add `--driver electro` (`photo`, `photoelectro`, `thermal`, `plasma`, `bio`, `electrified-heat`, `mechano`) |
| … since 2020 / in 2024? | add `--year 2020-2026` / `--year 2024` |
| … only reviews / only patents / only articles? | add `--doc-type review` (`patent`, `article,review`, `preprint`, `dataset`, `thesis` …) |
| … in a journal? | add `--venue "ACS Catal"` (substring; comma = any) |
| … by an author? | add `--author "Sargent"` (substring of the author name) |
| How does X split by driver? | `breakdown --concept X --by driver` |
| How did X grow over time? | `breakdown --concept X --by year` |
| Which journals publish most on X? | `breakdown --concept X --by venue --limit 20` |
| What are the main sub-topics of X? | `breakdown --concept X --by topic_a` |
| The most cited sources on X | `list --concept X --sort citations --limit 20` |
| The newest sources on X | `list --concept X --sort year --limit 20` |
| A table of sources on X to open in Excel | `list --concept X --limit 0 --format csv > my_list.csv` |
| Everything about one source | `source 10.1021/acscatal.5b00737` · `source 17445` · `source "words of the title"` |
| Which concepts exist and what exactly do they match? | `concepts` · `concepts co2-reduction` · `drivers` |
| Which topics exist and how many sources carry each? | `topics` · `topics --like copper` |
| Anything else | `schema`, then `sql "SELECT …"` |

Filters combine with AND; inside one filter a comma means "any of" (`--concept co2-reduction,co-reduction`).
Errata, ChemInform digests, cover pages and retracted sources are excluded unless you add `--include-notices`.

More examples:

```bash
python3 -I consult.py count --concept nitrate-reduction --driver electro --year 2020-2026
python3 -I consult.py count --concept sac --driver electro                 # single-atom electrocatalysts
python3 -I consult.py count --topic "Copper catalysts" --text 'ethylene OR c2h4'
python3 -I consult.py breakdown --concept water-splitting --by driver
python3 -I consult.py breakdown --concept co2-reduction --driver photo --by year
python3 -I consult.py list --concept co2-reduction --driver electro --doc-type review --sort citations --limit 10
python3 -I consult.py list --concept plastics-upcycling --year 2023-2026 --limit 0 --format csv > plastics.csv
```

---

## 3. What the words mean

### Concepts (`--concept`)

`python3 -I consult.py concepts` prints each concept's exact definition. A concept combines:

- **vocabulary topics**: each source has up to three main topics (Topic A/B/C) from a 125-term catalysis
  vocabulary (`topics` lists them);
- **text phrases**, searched in the title (strict) or in title + abstract + keywords (broad).

Built-in concepts: `co2-reduction`, `co2-conversion`, `co-reduction`, `nitrogen-to-ammonia`, `nitrate-reduction`,
`ammonia`, `water-splitting`, `hydrogen-production`, `oxygen-reduction`, `methane-conversion`, `biomass-conversion`,
`plastics-upcycling`, `pollutant-degradation`, `organic-synthesis`. **Every vocabulary id is a concept too**: for
example `co2rr`, `photo-co2rr`, `sac` (single-atom catalysts), `mof`, `zeolite`, `copper`, `perovskite`, `dft`,
`ml` (machine learning), `operando`, `tea-lca`.

`co2-reduction` means reduction of CO2 by any route (electrochemical, photocatalytic, photoelectrochemical,
thermocatalytic hydrogenation / methanation / RWGS, plasma, enzymatic). It excludes non-reductive uses such as
cycloaddition, which are covered by `co2-conversion`.

### Drivers (`--driver`): what drives the reaction

| driver | meaning | detected by |
|---|---|---|
| `electro` | electricity drives the reaction: electrocatalysis, electrolysis, fuel cells, metal-air / metal-CO2 batteries | electro reaction topics (CO2RR, HER, OER, ORR, NRR, NO3RR …) or words such as electroreduction, electrocatalytic, electrolysis, Faradaic, overpotential, gas-diffusion electrode |
| `photo` | light: photocatalysis, photoredox, photothermal/plasmonic | photocatalytic topics or photocatal\*, photoreduc\*, visible light … |
| `photoelectro` | light + electricity: PEC cells, photoelectrodes | PEC topic or photoelectro\*, photocathode, photoanode |
| `thermal` | conventional heat (thermocatalysis; most heterogeneous and homogeneous catalysis) | thermocatalytic topics or hydrogenation, fixed bed, GHSV, RWGS, Fischer-Tropsch … |
| `plasma` | non-thermal plasma (electric discharge) | plasma topic or plasma catalysis, DBD, gliding arc … |
| `bio` | enzymes or cells | biocatalysis topics or enzymatic, whole-cell, biohybrid … |
| `electrified-heat` | electricity used as the heat source (Joule / induction / microwave) | electrified-thermocatalysis topic or those words |
| `mechano` | ball milling | mechanocatalysis |

**Main driver:** a driver does not count when a competing driver is in the **title** or among Topic A/B/C. For
example, a source titled "photoelectrochemical CO2 reduction" counts as `photoelectro`, not `electro`, and a
photocatalysis source whose abstract mentions "electrochemical impedance" stays `photo`. If the question says
"electricity" broadly, also report `plasma` and `electrified-heat`, which are electrically powered too.

### Strict and broad

- **strict**: the concept and the driver appear in the **title** or in **Topic A/B/C**. High precision; the
  conservative number.
- **broad**: they may appear anywhere in the **title, abstract or keywords**. More recall, some noise: a general
  electrocatalysis review that mentions CO2 reduction counts here.

Always report both. In a spot check of CO2 reduction + electro, 12–14 of 15 random strict hits were clearly on
target; the broad level adds about 17 % more, mostly related work (urea electrosynthesis from CO2, general
electrocatalysis reviews).

### Records and sources

`records` counts every matching row. `papers` leaves out patents, datasets and software. `by_doc_type` gives the
full split.

---

## 4. Writing your own text query (`--text`, `--title`)

The full-text index (SQLite FTS5) covers title, abstract and keywords. It is case-insensitive and has no stemming.

| you want | write |
|---|---|
| a word | `electrocatalyst` |
| a word and its endings | `electrocatal*` (electrocatalyst, electrocatalysis, electrocatalytic …) |
| an exact phrase | `"gas diffusion electrode"` (a hyphen or space both match: gas-diffusion electrode) |
| a phrase ending in a prefix | `"co2 reduc" *` (CO2 reduction, CO2-reducing …) |
| all of | `copper AND ethylene` |
| any of | `(ethylene OR c2h4 OR "c2+")` |
| but not | `"co2 reduction" NOT photocatal*` |
| words close together | `NEAR(copper ethylene, 10)` |

Formulas: `co2` also appears as `co₂` and `"co 2"` in some abstracts; `carbon dioxide` is a phrase. Short acronyms
that are also English words (HER = "her") cannot be searched as text: use `--topic HER` instead.

---

## 5. SQL on `index.db`

```bash
python3 -I consult.py schema                    # tables and columns
python3 -I consult.py sql "SELECT year, COUNT(*) FROM sources WHERE topic_a = 'CO2RR' GROUP BY year ORDER BY year"
```

or open the file with DB Browser for SQLite, `sqlite3`, pandas (`pd.read_sql`) or R.

| table | contents |
|---|---|
| `sources` | one row per work: `id, doi, identifier, title, authors, year, venue, publisher, doc_type, url, abstract, keywords, topic_a, topic_b, topic_c, related_topics, access_type, licence, citations, is_preprint, is_retracted, is_notice, databases, notes …` |
| `sources_fts` | full-text index on `title, abstract, keywords` (`rowid` = `sources.id`) |
| `authors`, `source_authors` | authors (name, ORCID) and their position, institutions and countries in each source |
| `identifiers` | every identifier of a work: `scheme` = doi, pmid, pmcid, arxiv, osti, patent, s2, openalex … |
| `source_subjects` | topics of each source: `term` (vocabulary id), `label`, `kind` = main (rank 1–3 = Topic A/B/C) or related |
| `subjects` | the vocabulary |
| `source_databases`, `databases` | which databases found each work |
| `source_topics`, `topics` | topic indexes ("catalysis" and its subtopics) with relevance and in-scope flags |
| `files`, `extractions`, SI-link table | downloaded PDFs / supplementary files and curation status (filled later) |
| `about` | column descriptions, example queries, `built_at` |

Recipes:

```sql
-- full-text search joined to sources
SELECT p.id, p.year, p.title FROM sources_fts f JOIN sources p ON p.id = f.rowid
WHERE sources_fts MATCH '"co2 reduc" * AND electrocatal*' AND COALESCE(p.is_notice,0) = 0 ORDER BY p.citations DESC LIMIT 20;

-- sources whose Topic A/B/C include a vocabulary term
SELECT COUNT(DISTINCT source_id) FROM source_subjects WHERE term = 'co2rr' AND kind = 'main';

-- a source by DOI (any alias)
SELECT p.* FROM identifiers i JOIN sources p ON p.id = i.source_id WHERE i.value = '10.1002/adma.202202952';

-- sources by an author with their ORCID (stored without the https://orcid.org/ prefix; some carry a leading space)
SELECT p.year, p.title FROM authors a JOIN source_authors pa ON pa.author_id = a.id JOIN sources p ON p.id = pa.source_id
WHERE TRIM(a.orcid) = '0000-0002-1825-0097';

-- top venues for a topic
SELECT venue, COUNT(*) n FROM sources WHERE topic_a = 'Photocatalytic CO2 reduction' GROUP BY venue ORDER BY n DESC LIMIT 15;
```

Leave out non-research rows with `COALESCE(is_notice,0) = 0 AND COALESCE(is_retracted,0) = 0`.
`related_topics` and `source_subjects.kind = 'related'` include vocabulary *neighbours* (an ORR source gets CO2RR as
related), so count with `kind = 'main'` unless you want that looser set.

---

## 6. For AI agents answering questions

1. Turn the question into a `consult.py` command (section 2). Use `concepts` / `drivers` to check that a definition
   fits; if none fits, use `--text` with an FTS query (section 4), or SQL.
2. Run it and read the JSON. For counts, give **strict and broad** numbers, `papers` vs `records` when the
   question says "papers", and the split by `by_doc_type` if useful.
3. State the definitions you relied on (from `definitions` in the JSON) and the database date (`db_built_at`).
4. For lists, use `list` (sorted by citations or year) and give titles, years and DOIs.
5. Don't modify the database. To save a list, redirect `list --format csv` to a file, or use the
   index-sources skill's `export.py` in the project that holds the database.
6. Mention the limits below when they affect the answer.

---

## 7. Limits (as of 2026-10-14)

- **Coverage:** 24 open databases. Scopus, Web of Science, CORE, Lens, EPO, Springer, IEEE and ADS were not
  searched (no keys), so some journal-only and patent records are missing. Records are deduplicated (same DOI,
  preprint ↔ published version, patent families); a few duplicates remain.
- **Relevance:** every record passed a "cataly…" text gate, then keyword screening (2026-10-14) scored it 0–5:
  5 = "cataly…" in the title, 4 = only in the abstract; metaphors such as "catalyst for change" are out of scope.
  In scope: 2,186,836; out of scope: 15,597 (in `excluded.csv` and `source_topics.in_scope = 0`).
- **Access type and licence:** every record was classified on 2026-10-14 (OpenAlex, Crossref, Unpaywall, Europe PMC,
  PMC). In scope: OA 380,167 · OA+ND 74,198 · Free-to-read 366,090 · Paywalled 1,366,381. This is the metadata
  verdict; a downloaded PDF's printed licence can still change it. Filter with `--access OA,OA+ND`.
- **Topics:** Topic A/B/C come from a deterministic match against a 125-term vocabulary (re-assigned on
  2026-10-14). Sources without a matching term have no Topic A; concepts add text matching, so they don't depend
  on topics alone.
- **Abstracts:** 419,256 in-scope records (19 %) still have no abstract (113,558 were filled on 2026-10-14);
  they can only match on title and keywords.
- **Historical methanol synthesis (added 2026-10-20):** SCALE's pre-1966 methanol-synthesis corpus
  (`graphs/methanol-synthesis-pre1966/sources.json`) is the topic `methanol-synthesis-pre1966`: 178 records, of
  which 128 were new to the catalog, among them 79 patents from 1923–1968 (42 from the 1920s) that the open patent
  sources do not reach. SCALE's statuses are its scope decisions (174 in scope, 4 off scope, with the reason in
  `relevance_note`); every in-scope record has Methanol synthesis among its Topic A/B/C, so `--concept co2-methanol
  --year 1920-1965` now finds 184 records (75 patents) at the strict level.
- The numbers change when the pipeline updates the index. Every answer carries `db_built_at`.

To extend `consult.py`, add an entry to `CONCEPTS` (topics + FTS phrases) or `DRIVERS` at the top of the file;
`concepts` shows the result.
