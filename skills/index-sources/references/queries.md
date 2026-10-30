# Writing queries.json and the topic gate

## Contents
- How many queries, and how to vary them
- queries.json format
- Query syntax per database (with tested examples)
- Strict vs loose databases; date filters in update mode
- The topic gate (config.json → gate)
- Keys, citation chasing, imported lists

## How many queries, and how to vary them

Write **15-25 distinct queries for the main databases** (OpenAlex, Crossref, Europe PMC, Semantic Scholar, the keyed
indexes when available) plus **1-2 short queries for every other selected database** (preprints, repositories,
datasets, patents, regional) — every database in `config.json → databases` needs at least one query or it is skipped. One query per database finds a fraction of the
field: each database ranks and matches differently, and different wording surfaces different sources. Vary along:
- spelling / hyphenation (electroreduction, electro-reduction), singular/plural, British/US spelling
- abbreviations and full names (CO2RR / CO2 reduction reaction; Ti3C2Tx / MXene)
- synonyms of the core concept, and the main sub-classes (each material family, each product, each method)
- application or process framing ("for ammonia synthesis", "electrolyzer", "mechanism", "techno-economic")
- reverse word order ("nitrate reduction on MXene" vs "MXene for nitrate reduction")
Keep each query on-topic: precision comes from the gate, recall from the variety of queries.

## queries.json format

`.scripts/<slug>/queries.json` — one object per database, query ids are free text (`Q01`, ...). The FIRST query of
each database is its primary query (always paged to the end). A value is a string, or for Crossref/OpenAlex an object
with an extra filter.

```json
{
  "openalex": {
    "Q01": "title_and_abstract.search:MXene nitrate reduction",
    "Q02": "title_and_abstract.search:\"Ti3C2\" nitrate ammonia"
  },
  "crossref": {
    "Q01": "MXene electrocatalyst nitrate reduction ammonia",
    "Q02": {"q": "MXene nitrate electroreduction", "filter": "prefix:10.26434"}
  },
  "europepmc": {"Q01": "(TITLE_ABS:MXene OR TITLE_ABS:\"Ti3C2\") AND TITLE_ABS:nitrate AND TITLE_ABS:ammonia"},
  "s2": {"Q01": "(MXene | Ti3C2 | Ti3C2Tx) + nitrate + (ammonia | electroreduction)"},
  "arxiv": {"Q01": "abs:MXene AND abs:nitrate"}
}
```

## Query syntax per database

| Database (key) | Syntax | Example |
|---|---|---|
| OpenAlex (`openalex`) | a **filter**; the script adds `type:article\|review\|preprint`. `title_and_abstract.search:` matches all words (AND); quotes = phrase. Also `topics.id:T12345`. Keep ≤ 5 boolean operators per filter. | `title_and_abstract.search:"nitrate electroreduction" MXene` |
| Crossref (`crossref`) | free text, any-word relevance ranking (loose). Optional `filter`, e.g. `prefix:10.26434` (ChemRxiv), `prefix:10.21203` (Research Square), `prefix:10.2139` (SSRN), `prefix:10.31224` (EngrXiv) to reach preprint servers. Default filter: journal articles, posted content, proceedings. | `MXene electrocatalyst nitrate reduction ammonia` |
| Semantic Scholar (`s2`) | bulk search: `+` AND, `\|` OR, `-` NOT, quotes, parentheses | `(MXene \| Ti3C2) + nitrate + ammonia` |
| Europe PMC (`europepmc`) | fields `TITLE_ABS:`, `TITLE:`; `AND`/`OR`/`NOT`; quotes | `TITLE_ABS:"nitrate reduction" AND TITLE_ABS:MXene` |
| PubMed Central (`pmc`) | Entrez: `term[Title/Abstract]`, `AND`/`OR`, quotes | `MXene[Title/Abstract] AND nitrate[Title/Abstract]` |
| OpenAIRE (`openaire`) | keywords / quoted phrases (matches broadly) | `"nitrate electroreduction" MXene` |
| OSTI (`osti`) | keywords, quotes, `AND` (matches very broadly — the gate matters) | `"nitrate reduction" AND MXene` |
| arXiv (`arxiv`) | `abs:`, `ti:`, `AND`/`OR`; LaTeX in abstracts: CO$_2$ is indexed as `CO$2$` | `abs:MXene AND abs:nitrate` |
| DOAJ (`doaj`) | Elasticsearch query string; `bibjson.title:`, `bibjson.abstract:`; API caps at 1,000 hits per query | `bibjson.abstract:"nitrate reduction" AND MXene` |
| HAL (`hal`) | Solr: quotes, `AND`/`OR` | `"nitrate reduction" AND MXene` |
| Zenodo (`zenodo`) | Elasticsearch query string (publications only) | `"nitrate reduction" MXene` |
| Figshare (`figshare`) | free text (mostly datasets; low yield for papers) | `MXene nitrate` |
| OSF Preprints (`osf`) | words matched in the title | `MXene nitrate` |
| PLOS (`plos`) | Solr: `abstract:(...)`, `title:(...)` | `abstract:("nitrate reduction" AND MXene)` |
| Crossref preprints (`crossref_preprints`) | like Crossref (free text, loose), restricted to posted content: ChemRxiv, Research Square, SSRN, bioRxiv, TechRxiv ... | `MXene nitrate reduction` |
| DataCite (`datacite`) | Elasticsearch query string; optional `types` (`dataset`, `text`, `preprint`, `dissertation`, `report`) | `{"q": "MXene AND nitrate", "types": "dataset"}` |
| OpenAIRE datasets (`openaire_data`) | like OpenAIRE | `"nitrate electroreduction" MXene` |
| Harvard Dataverse (`dataverse`) | Solr keywords, quotes | `"nitrate reduction" MXene` |
| Dryad (`dryad`) | keywords (few hits; datasets behind papers) | `MXene nitrate` |
| Materials Cloud (`mcloud`) | Elasticsearch query string | `MXene AND nitrate` |
| Zenodo datasets (`zenodo`) | `{"q": "...", "type": "dataset"}`; use `AND` — a space is OR in Zenodo | `{"q": "MXene AND nitrate", "type": "dataset"}` |
| NASA NTRS (`ntrs`) | keywords | `CO2 electrolysis` |
| J-STAGE (`jstage`) | words (all fields); broad queries are walked one year at a time automatically | `MXene nitrate` |
| CiNii Research (`cinii`) | keywords (English or Japanese) | `MXene nitrate` |
| ERIC (`eric`) | Solr; off by default (education) | `catalysis AND laboratory` |
| Europe PMC patents (`europepmc_patents`) | Europe PMC syntax (the script adds `SRC:PAT`) | `"carbon dioxide" AND electrochemical` |
| CORE (`core`, key) | CORE query language: words, quotes, `AND`/`OR`, `title:`, `abstract:` | `title:"nitrate reduction" AND MXene` |
| Scopus (`scopus`, key) | Scopus advanced search | `TITLE-ABS-KEY(MXene AND "nitrate reduction")` |
| Web of Science (`wos`, key) | WoS advanced: `TS=`, `TI=` | `TS=(MXene AND "nitrate reduction")` |
| Springer Nature (`springer`, key) | words, quotes; `title:`, `keyword:` | `"nitrate reduction" MXene` |
| Lens scholarly / patents (`lens`, `lens_patents`, key) | Elasticsearch query string; patents: `title:`, `abstract:`, `claim:` | `abstract:(MXene AND nitrate)` |
| IEEE Xplore (`ieee`, key) | words, quotes, `AND`/`OR` | `"electrochemical CO2 reduction"` |
| NASA ADS (`ads`, key) | ADS syntax: `abs:`, `title:` | `abs:"CO2 electrolysis"` |
| EPO OPS (`epo`, keys `epo_key` + `epo_secret`) | CQL: `ta=` (title+abstract), `ti=`, `cpc=`; at most 2,000 results per query | `ta="carbon dioxide" and ta=electroreduction` |

The default `config.json → databases` comes from the catalog ([databases.md](databases.md)): every keyless database plus the
keyed ones whose keys are present.

## Strict vs loose databases; date filters

- **Strict** (OpenAlex search filter, Europe PMC, S2, PMC, arXiv): results are mostly on-topic; `--count-only` totals
  are meaningful.
- **Loose / relevance-ranked** (Crossref and its preprint servers, Zenodo, DataCite, OSTI, OpenAIRE, HAL, DOAJ,
  CORE ...): they rank any-word matches, so totals are huge. Every such query stops automatically when fewer than
  4 % of a page passes the gate twice in a row; the gate drops the rest. OpenAlex, arXiv, PMC, S2, J-STAGE and the
  patent offices always page to the end.
- OpenAlex queries after the first stop early when a whole page brings no new DOI (overlapping variants).
- `search.py --since YYYY-MM-DD` adds each database's own date filter (OpenAlex publication date, Crossref DOI
  registration date, Europe PMC first publication date, S2 publication date, arXiv submission date, OSTI/OpenAIRE/HAL/
  Zenodo/PMC/PLOS/OSF/Figshare dates; DOAJ by year). Raw hits of an update go to `raw/since-<date>/`.

## The topic gate (config.json → gate)

Applied by `build_list.py` to title + abstract; sources that fail never enter the list (their raw hits stay in
`.scripts/<slug>/raw/`, so a changed gate only needs `build_list.py` again).

```json
"gate": {
  "any": ["CO2RR", "re:\\beCO2RR\\b"],
  "all_groups": [["MXene", "Ti3C2", "re:\\bTi3C2T"], ["nitrate", "nitrite", "re:NO3-?RR"]],
  "title_only": ["re:nitrate[- ]to[- ]ammonia"]
}
```

- A source passes if any `any` term matches, OR at least one term of EVERY `all_groups` group matches, OR (sources with
  no usable abstract) a `title_only` pattern matches the title.
- Rescue rules, for sources of the topic that never write the anchor word (catalysis titles without "cataly", often
  with no abstract in the record): `title_any` terms matched in the title alone (catalytic reactions: "Heck",
  "hydroformylation", "... over Pt/Al2O3"; a `^(?!.*(?:storage|alloy)).*hydrogenation` lookahead vetoes contexts) and
  `journal_any` terms matched in the venue (catalysis journals; only for titles of four words or more, not news
  briefs), `journal_not` vetoing venues (news digests, mixed kinetics journals). Keyword screening keeps such sources in
  scope (score 4, note "rescued by the topic gate (...)"). Measure each rule on raw hits that fail the plain gate and
  read samples before adding it: only rules whose matches are topic sources.
- `"english_only": true` (in the gate) turns away every record whose title or abstract is in another language,
  whatever its terms (on clear evidence only: never on Greek letters, formulas, element symbols, names or a translated
  abstract under an English title; a bilingual title with an English part stays). Records already in the index leave
  only on request: `remove_sources.py --non-english`.
- Terms are case-insensitive phrases; a space also matches a hyphen. Prefix `re:` for a regular expression.
- Typical design: group 1 = the subject (material/organism/system names and acronyms), group 2 = the process or
  property; put unambiguous acronyms in `any`.
- Check it: after `build_list.py`, compare `off_topic_dropped_by_gate` with `unique_sources`, then read 10 random
  titles from the CSV. Too many dropped → add synonyms; noise kept → tighten a group.
- An empty gate keeps every hit; Crossref and OSTI then add thousands of unrelated sources.

## Keys, citation chasing, imported lists

- Databases that need a key are skipped (with a message naming the key) until the key is in
  `~/.scale/sources/keys.txt` — see [databases.md](databases.md) and the skill's README.md. An OpenAlex key is free
  and strongly recommended: without it OpenAlex shares a small daily budget with everyone on your network.
- **Citation chasing** (`search.py --topic <slug> --citing [--since DATE]`): OpenAlex lists every work that cites the
  topic's core sources (relevance >= 4, or all in-scope sources when unscreened). Results land in `raw/citing*/` and go
  through the same gate (`build_list.py --run citing`). It finds sources that describe the topic in other words.
- **Lists from the user** (Web of Science / Scopus / Zotero exports, Google Patents CSV, SCALE corpus lists, DOIs,
  patent numbers, a web page with DOIs): `import_list.py
  --topic <slug> --file savedrecs.txt` (or `--url ...`), then `build_list.py --topic <slug> --run manual`. Imported
  sources skip the gate; the file's abstracts and author keywords are kept.
