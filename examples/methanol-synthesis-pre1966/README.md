# Example — methanol synthesis from CO/CO2 + H2, literature published before 1966

This example is the knowledge and data graph of the historical methanol-synthesis corpus of the
ARPA-E CATALYST project, **curated from the source texts** and scoped to **CO and CO2 hydrogenation** (CO + D2 included):
105 sources published from 1923 to 1965, 4,868 records and 16,586 links, 684 catalytic tests. It exercises the three tasks of the SCALE framework: the representation it
is curated under (and the gaps it raised), evidence-preserving curation, and evidence-linked queries. It is
public, research data (`data_status: research_data`, `access: public`), and the repository's checks and tests
run on it (`tools/tests/test_example_methanol.py`).

## What is here, and what is not

The project partners cleared the curated data for publication. This folder holds:

- `methanol-synthesis.graph.json`, the graph, **valid under scale-graph 0.1.0** of this repository (0 errors);
- `rights.yaml`, the rights of every source, and `stewardship.yaml`;
- `corpus/`: `sources.json`, the 105 sources on CO/CO2 + H2 that the benchmark uses, with each PDF's sha256 (the
  PDFs themselves are local, `corpus/pdfs/`, git-ignored; [corpus/README.md](corpus/README.md)), and
  `manifest.json`, the frozen corpus; `curation/GUIDE.md` and `curation/assembly-report.json`;
- `queries/scale-graph/*.yaml`, the manuscript's questions as query plans, and `tools/`.

**Quoted text is capped.** Most sources are in copyright, so the graph keeps the quoted text of each
source within the repository's cap (`scale evidence cap`: 300 characters a quote; 4,000 distinct
characters and 10 % of the text a source; `rights.yaml` gives each source's class). The rest is withheld
as `sha256` and length in the evidence `note`: 6,920 of the 25,230 evidence items carry a withheld quote.
Every withheld quote keeps its source, locator and passage, and anyone holding the source texts restores
it with `scale evidence rehydrate`. US patents and works published before 1931 are public domain (in the
US) and are not capped.

**Not here** (they reproduce source text beyond the cap, or are rebuilt locally): the curation fragments
and second readings, the page texts and OCR (`work/`, `curation/ocr/`), the GALAXY bundles and the full graph
(all 108 sources, tests of every reaction the sources report). They stay in the restricted copy (outside the repository, named only by the environment;
`scale.layout.restricted_path`), at this folder's path; the curation tools read and write them there. The evidence index is not committed either: build it with
`scale graph index methanol-synthesis.graph.json` (a few seconds).

**Schema version.** The fragments were curated under the scale-graph 0.1.0 of the consortium schema
repository, a different schema from this repository's 0.1.0 (the numbering restarted). The graph was moved
to that repository's 0.5.0 with its own tools (`scale kg update`: 17 record changes, 0 errors), which is the
content of this repository's 0.1.0, and re-pinned to 0.1.0, as decision record 0001 did for the other
example documents. The graph's title still says it was curated under scale-graph 0.1.0: that is the
consortium repository's version.

## The cutoff: published before 1 January 1966

The corpus is frozen with a publication-date cutoff (`corpus/manifest.json`, built by
`tools/freeze_corpus.py`):

- **Rule.** A source is in scope when it was published or publicly disclosed **before 1 January
  1966**. A journal article, thesis or report counts from its publication year; a patent from the
  grant date printed on it (checked against the USPTO table of the first patent number of each
  year), **not** its priority or filing date.
- **Why 1966.** ICI launched low-pressure methanol synthesis over Cu/ZnO/Al2O3 in 1966 (GB
  1,010,871, published 1966; US 3,326,956). The cutoff holds out that commercialization and what
  followed (10 held-out target documents, held out by role whatever their dates) and admits
  everything published before it, **ICI's own earlier publications included** (US 2,964,551,
  granted 1960). This is the corpus's original design (`historical/LEAKAGE_AUDIT.md`).
- **An earlier cutoff.** Every record carries its source year, so a query plan with
  `published_before: 1959-01-01` sees only the 86 sources published before 1959 (holding out Kume,
  Abe and Tanioka 1959: CO2 + H2 over Cu–Zn–Al).
- **What the cutoff does not remove.** Cu–Zn–Al compositions appear before 1966 in the in-scope
  sources, and the graph records them as their sources state them: query `q6-cu-zn-al-formulations`
  finds five catalysts in four sources (1928, 1936, 1951 and 1965), among them Example 10 of Larson's
  US 2,061,470 (DuPont, granted 1936), which the corpus leakage audit names. The records are project
  data (above). A rediscovery evaluation that must not see any Cu–Zn–Al composition has to hold these
  out as well.

| | sources |
|---|---:|
| in scope (curated) | **108**: 57 articles, 39 patents, 12 theses and reports; 1923–1965 |
| of which read from OCR (scanned patents, reports) | 40 |
| after the cutoff | 1 |
| held-out targets | 10 |
| not retrieved (no PDF) | 58 |
| off scope | 1 |

## How it was curated

1. **Freeze** (`tools/freeze_corpus.py CORPUS_DIR`): date every source, apply the cutoff, and write
   each PDF's page texts to `work/texts/` (local, not committed). A page without a text layer is
   read by Tesseract 5 (two-column patents column by column); each page records whether its text
   is the PDF's own or OCR.
2. **Curate** one source at a time (`curation/GUIDE.md`, the `curate-source` skill):
   `tools/curation.py brief <slug>` gives the page texts, the schema (`scale graph describe --domain
   catalysis`: the one catalysis checklist) and a checklist of what earlier extractions found (the curation kit's bundle and
   the pre-1965 data table — a checklist only, never evidence). The curator writes a fragment,
   `curation/fragments/<slug>.json`, and `tools/curation.py check` validates it against the schema
   and checks every quote verbatim against the page texts and its PDF page. All 108 fragments pass.
   The curators were agents; nothing from their own knowledge or from later literature is allowed.
   The 22 sources of 1959–1965 were curated by a multi-agent workflow: one agent per batch curated,
   and a second agent re-read each source and tried to refute every record before it counted.
3. **Assemble** (`tools/curation.py assemble`): merge the shared chemistry (species by formula,
   the canonical reactions), keep catalysts, samples and tests per source, add the Source, author
   and stewardship records, derive REPORTED_IN, place each quote in its source passage, validate,
   and build the evidence index. Report: `curation/assembly-report.json`.

## The graph

`methanol-synthesis.graph.json`: **4,868 nodes, 16,586 links**, valid under scale-graph 0.1.0 (0 errors);
25,230 evidence items, every quote verbatim in its source's page text (before the cap) and from a source
published before the cutoff. It is the curated graph scoped to CO and CO2 hydrogenation to methanol
(`scope_methanol_synthesis` in `tools/curation.py`): the tests of other reactions (methanol decomposition,
formaldehyde, formate, Fischer–Tropsch, catalyst glow, ...), the records only they use, the claims and hypotheses
resting only on them, and the reactions no kept test or claim is about are left out; 105 of the 108 curated
sources remain, the 105 of [`corpus/sources.json`](corpus/sources.json). The full curation keeps everything
(restricted copy).

| nodes | | links | |
|---|---:|---|---:|
| Claim | 1,409 | REPORTED_IN | 4,675 |
| CatalyticTest | 684 | ABOUT | 2,619 |
| Catalyst | 484 | HAS_COMPONENT | 1,626 |
| ChemicalSpecies | 430 | OF_REACTION | 884 |
| CatalystSample | 408 | SUPPORTS | 823 |
| Feed | 196 | FED_WITH | 690 |
| Hypothesis | 174 | PREPARED_FROM | 667 |
| Preparation | 159 | USES_CATALYST | 667 |
| Treatment | 139 | IN_REACTOR | 594 |
| Characterization | 132 | HAS_FORMULATION | 404 |
| Source | 105 | TREATED_BY | 383 |
| ProcessUnit | 99 | PREPARED_BY | 332 |
| Reactor 83, Analysis 81, Reaction 73, Material 72, Person 72, ... | 449 | CATALYZES 295, CONCLUDES 278, HAS_INPUT 210, CHARACTERIZES 188, ... | 2,222 |

The counts of conformance and gaps below are those of the full curation.

- **Roles on edges.** Supports, promoters and precursors are roles on `HAS_COMPONENT` and
  `PREPARED_FROM`; poisons are `INHIBITED_BY` (with `negated` where a source says something does
  *not* poison).
- **Values as printed.** Every condition and result is a value object in the printed unit, with
  the printed text in `as_reported`; ranges are `lower`/`upper`; nothing is converted.
- **Conformance.** Against the `thermocatalysis` checklist the graph is not conformant, and that is
  an answer about the sources: 44 % of the recommended fields are filled; the sources often give no
  conversion basis, space velocity, flow rate or time on stream.
- **Gaps.** The curators recorded 720 gaps: 327 `absent_source_information`, 198
  `extraction_error` (illegible OCR or garbled text layers; 83 answered by reading the page
  images), 148 `ambiguous_source_information` (a source contradicting itself) and 47
  `missing_concept` (below).
- **For human review.** Where a text layer is garbled and the page image was not re-read, curators
  read values from the rendered page and say so in the evidence note; the quote is the garbled
  text as it stands.
- **Sources whose relevance should be reviewed:** FIAT Final Report 426 (`hid-20089`) is mostly
  Fischer–Tropsch work, and the 1958 thesis `hid-20099` studies adsorption on zinc oxide; the
  corpus bibliography gives the thesis a wrong title and degree.

### What the schema could not say

The 47 `missing_concept` gaps are what the curators could not record in the schema they curated
under. 39 are answered by concepts of scale-graph 0.1.0 (`resolved_by: "scale-graph 0.1.0"`, each
with how the records now say it): measured equilibria as tests (and the checklist's exemption for
equilibrium tests), the approach to equilibrium, process units and staged beds linked by
`FEEDS_INTO`, planned plants, component amounts and relative bases, negated statements, isotopic
labels. Measures specific to one source, concepts that already existed and numbers without a printed
unit are answered by curation guidance (`curation/GUIDE.md` §5a). 8 stay open for a proposal:
a composition in mol% of Zn + Cr with no single reference component, links to results in other
sources, an electron-impact driving force (1928), and adsorption heat as a function of coverage.

## Releases

`releases/v<version>/` are immutable snapshots of the graph, to cite and to benchmark against:

| release | date | schema | graph | sources | records | links | tests |
|---|---|---|---|---:|---:|---:|---:|
| [v1.0.0](releases/v1.0.0/RELEASE.yaml) | 2026-10-09 | scale-graph 0.1.0 (spec `3c2fa720…02006`) | sha256 `0dfc8c1c…ed13f` | 105 | 4,868 | 16,586 | 684 |

Each holds the graph, the corpus list (`sources.json`), the rights file and the query plans as they were, with
`RELEASE.yaml` (the schema version and its spec digest, the graph's file and content digests, the counts, and each
plan's status and row count) and `SHA256SUMS`. Built only from a graph that validates with no error, keeps every
quote within the cap and is public; never edited afterwards (a changed graph is a new release):

```bash
python tools/release_graph.py build v1.1.0     # refuses an existing release
python tools/release_graph.py verify           # every file's digest and every plan's answer still hold
```

To pin an analysis, record the release and its graph digest; the schema is named by its spec digest
(`scale graph spec --expect <sha256>`).

## Search: evidence as vectors

Every quote is indexed (`scale graph index`): `methanol-synthesis.evidence.jsonl` (the items) and
`.i8` (a 512-dimension int8 vector per item, embedder `scale-hash-v1`: hashed words, word pairs
and character 4-grams, with chemistry aliases so that "Cu" finds "copper" and "sulphur"
"sulfur"). Search combines BM25 and cosine similarity; hits lead to the records that cite them.
Built from the public graph, the index holds the capped quotes, so a withheld quote is found only
through its record's other text. Each evidence item names its source passage in `evidence.passage`.

```bash
G=examples/methanol-synthesis-pre1966/methanol-synthesis.graph.json
scale graph index $G
scale graph search $G "sulphur poisons the copper catalyst" --published-before 1966 --format markdown
```

## Queries: the manuscript's questions before the cutoff

`queries/scale-graph/*.yaml` are the manuscript's methanol questions as query plans
(`scale graph query $G <plan> --format markdown`, after `scale graph index $G`). Every answer carries each row's evidence with
its source year and locator; all come from sources published before 1966 (a plan run with
`published_before: 1959-01-01` answers for the earlier cutoff). The counts of the evidence-search plans
depend on the index, here built from the capped quotes; `tools/tests/test_example_methanol.py` keeps the
others.

| plan | question | result |
|---|---|---|
| `q1-copper-lower-temperature` | evidence for retaining Cu at lower temperature | 236 methanol-synthesis tests with a Cu-containing catalyst, 1932–1965, lowest temperature first |
| `q2-feed-poisons` | when were feed poisons recognized, and what for Cu | 69 claims (evidence search), 1925–1960: sulfur, arsenic, phosphorus and volatile iron compounds to be kept from the gas |
| `q2b-inhibited-by` | catalysts reported as poisoned, and by what | 88 catalyst–poison pairs, 1927–1965 |
| `q3-feed-purification` | what changes when contaminants are removed upstream | 47 claims (evidence search), 1926–1962 (e.g. ZnO beds for H2S, activated carbon for carbonyls) |
| `q4-co2-feedstock` | was CO2 known to yield methanol | 135 tests with CO2 as a reactant, 1930–1959 (e.g. ZnO–Cr2O3 1930, Cu–Al2O3 1945, Kudo 1952, Kume 1959) |
| `q5-carbon-source` | which carbon oxide supplies methanol carbon | 62 claims and proposals (evidence search), 1926–1960; none settles it |
| `q6-cu-zn-al-formulations` | Cu–Zn–Al formulations before 1966 | 5 catalysts: 1928, 1936 (two), 1951, 1965 |

## Page images and OCR: two readers

Scanned sources lose digits, exponents and whole table bodies in their text layer. The 69 sources on CO and CO2
hydrogenation were therefore re-read from their page images (`curation/GUIDE.md`, section 4a):

```bash
python tools/curation.py pages <slug>                       # page images (work/pages/) and positioned OCR words (curation/ocr/)
python tools/curation.py region <slug> <page> x0 y0 x1 y1   # a 400 dpi crop and what OCR reads there
python tools/curation.py agree curation/fragments/<slug>.json      # each reading's agreement, and the OCR engines used
python tools/curation.py pending curation/fragments/<slug>.json    # crops (not readings) for a second reader
python tools/curation.py merge-second <slug>                # curation/second-readings/<slug>.json onto the evidence
```

A reading carries its page region and transcription. It stands when OCR reads the same numbers in that region
(each as often as printed, next to the same word) or when an independent second reader, who sees the crop but not
the first reading, gives them (figure points within 5 % or 0.3); otherwise the value is left out and listed as a
gap. Result: 2,259 readings (1,174 confirmed by OCR, 1,173 by a second reader); printed values on the tests
4,989 -> 6,398 and tests 743 -> 815 (`tools/value_census.py`); OCR misreadings corrected in the values' notes;
115 gaps resolved. The page images and OCR words reproduce whole pages of the sources, so they are
rebuilt locally from the corpus PDFs and not distributed; each fragment records the agreements and the OCR
engines they were computed with (`ocr_engines`), and a recomputed agreement from another engine is
reported as a warning. `tools/compare_reference.py WORKBOOK.xlsx` compares the tests with another group's workbook,
and `tools/export_curated_table.py TEMPLATE.xlsx OUT.xlsx` writes them in that group's layout, with derived
cells marked by their rule.

## The GALAXY bundle

The GALAXY knowledge-graph bundles (galaxy-kg-bundle 1.0.0; 1.0.0 and 1.1.0, scoped to CO and CO2 hydrogenation
to methanol) ship the full quotes and the US patent texts, so they stay in the restricted copy and are built there
(`python tools/curation.py bundle`). Any document gets the same lineage from the command line:
`scale graph export <document> --to galaxy --out DIR --version <later version> --previous <previous bundle>
[--replaced <merge map>] [--corpus corpus/manifest.json]`.

## Files

| file | content |
|---|---|
| `methanol-synthesis.graph.json` | The graph, pinned to scale-graph 0.1.0, quoted text capped. |
| `rights.yaml`, `stewardship.yaml` | The rights of every source (the cap reads them); the graph's default stewardship. |
| `corpus/manifest.json` | The frozen corpus: every source, its date and date basis, its status under the cutoff, its PDF digest and page-text origins. |
| `curation/GUIDE.md` | How one source is curated. |
| `curation/assembly-report.json` | Assembly: coverage per source, gaps, merge notes, validation, conformance, indexes. |
| `queries/scale-graph/*.yaml` | The manuscript's questions as query plans. |
| `releases/v<version>/` | Immutable, digested snapshots of the graph (`tools/release_graph.py build | verify`). |
| `tools/freeze_corpus.py`, `tools/curation.py` | Freeze, brief, check, assemble, bundle (with the restricted copy). |
| the other `tools/` | Value census, comparison with and export to another group's workbook layout, and the record-format conversion of an earlier curation (below). |

## Reproduce

```bash
CORPUS=.../ARPA-E-CATALYST/Corpus            # the corpus directory (PDFs, bibliography, curation kit)
RESTRICTED=...                                # the restricted copy (the folder its environment variable names)
cd examples/methanol-synthesis-pre1966              # with the restricted copy set: the fragments and work/ are there
python tools/freeze_corpus.py $CORPUS --texts-from galaxy/methanol-synthesis_v1.0.0   # manifest and page texts (pymupdf, tesseract)
SCALE_METHANOL_CORPUS=$CORPUS python tools/curation.py brief <slug>   # per source, for a curator
python tools/curation.py status               # every fragment checked
python tools/curation.py assemble             # graph, evidence index, passage index
python tools/curation.py scope                # the graph scoped to CO and CO2 hydrogenation to methanol
python tools/curation.py bundle
scale evidence cap $RESTRICTED/examples/methanol-synthesis-pre1966/methanol-synthesis.graph.json -o methanol-synthesis.graph.json
```

The last step publishes: it caps the assembled graph's quoted text into the public copy here.

`--texts-from` takes the US patents' page texts from the bundle, which ships the OCR the curation
was checked against: another Tesseract build of the same version (5.5.3) reads a few characters
differently, enough to break verbatim quotes. The other OCR-read sources are re-read; on
2026-09-28 five of them came out a few characters different, and every quote still matched.

`tools/tests/test_example_methanol.py` checks the cutoff, the graph (valid, public, within the cap, every
quote from an in-scope source), the curation's gaps and the query plans, on the public files alone.

## An earlier curation in the record format

An earlier curation of this corpus by another group (the bundle of the methanol-synthesis curation
kit, 60 sources up to 1965, and a pre-1965 data table) can be restated in the record format's
catalysis schema (legacy/v0.3.0) with `tools/galaxy_to_scale.py` and `tools/dataset_to_scale.py`.
The record format is retired (in the consortium schema repository): no current SCALE tool reads the restated
document, which only the record-format tools of the
earlier releases can check. It is not distributed here, since the data table is not ours to
redistribute; anyone holding the kit can rebuild it. It was used only as a checklist for the curation above,
never as evidence.
