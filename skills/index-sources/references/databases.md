# Databases: what the skill searches, what needs a key, what it skips

## Contents
- Automated databases by group (keyless and with a key)
- Found through another database
- Deliberately not queried
- Default selection and changing it

The catalog lives in `scripts/_databases.py` (`CATALOG`): 34 automated databases (25 keyless, 9 with a key), 20 reached through another database, 15 deliberately not queried. `keys.py` shows which keyed databases are ready on this computer. Query syntax per database: [queries.md](queries.md).

## Automated databases by group

### Broad aggregators

| Key | Database | Needs | Default | Covers |
|---|---|---|---|---|
| `openalex` | OpenAlex | optional `openalex` | yes | ~250M works; citations, OA locations, institutions; filter syntax |
| `crossref` | Crossref | optional `crossref` | yes | every Crossref DOI; publisher-deposited licenses; relevance-ranked (loose) |
| `s2` | Semantic Scholar | optional `s2` | yes | Semantic Scholar ~200M sources; strong CS/physics coverage; slow without a key |
| `openaire` | OpenAIRE | — | yes | OpenAIRE Graph: EU repositories, funder links, theses |
| `core` | CORE | `core` | yes | CORE ~300M OA records from repositories, full-text search |
| `lens` | Lens.org | `lens` | yes | Lens.org scholarly works (Microsoft Academic heritage + Crossref + PubMed) |

### Citation indexes (institutional key)

| Key | Database | Needs | Default | Covers |
|---|---|---|---|---|
| `scopus` | Scopus | `scopus` | yes | Elsevier Scopus abstract & citation index (key + institutional entitlement) |
| `wos` | Web of Science | `wos` | yes | Web of Science Starter API (key; institutional subscription) |

### Publisher platforms

| Key | Database | Needs | Default | Covers |
|---|---|---|---|---|
| `springer` | Springer Nature | `springer` | yes | Springer Nature metadata incl. Nature, BMC, SpringerOpen |
| `ieee` | IEEE Xplore | `ieee` | yes | IEEE Xplore (electrochemical energy, sensors, power-to-X engineering) |
| `doaj` | DOAJ | — | yes | DOAJ fully-OA journals (MDPI, Frontiers, Hindawi, SAGE Open, RSC Advances ...) |
| `plos` | PLOS | — | yes | PLOS journals |

### Repositories

| Key | Database | Needs | Default | Covers |
|---|---|---|---|---|
| `europepmc` | Europe PMC | — | yes | Europe PMC: PubMed, PMC, preprints (bioRxiv, ChemRxiv, Research Square ...), theses |
| `pmc` | PubMed Central | optional `ncbi` | yes | PubMed Central full-text OA |
| `hal` | HAL | — | yes | HAL (French open archive) |
| `zenodo` | Zenodo | optional `zenodo` | yes | Zenodo publications (and datasets with {"type": "dataset"}) |
| `figshare` | Figshare | — | yes | Figshare articles; publisher SI files are attached to their source, not listed |

### Preprint servers

| Key | Database | Needs | Default | Covers |
|---|---|---|---|---|
| `arxiv` | arXiv | — | yes | arXiv (cond-mat, physics.chem-ph, materials); paced 1 request / 3 s |
| `crossref_preprints` | Crossref (preprint servers) | — | yes | preprint servers registered in Crossref: ChemRxiv, Research Square, SSRN, Preprints.org, bioRxiv, medRxiv, TechRxiv, EngrXiv, Authorea, ESS Open Archive |
| `osf` | OSF Preprints | — | yes | OSF Preprints (title search): EngrXiv legacy, SocArXiv, PsyArXiv and other OSF servers |

### Government reports

| Key | Database | Needs | Default | Covers |
|---|---|---|---|---|
| `osti` | OSTI | — | yes | OSTI.GOV: US DOE reports, journal articles, theses, patents (catalysis-heavy) |
| `ntrs` | NASA NTRS | — | yes | NASA Technical Reports Server (CO2 electrolysis, ISRU, life support) |

### Regional

| Key | Database | Needs | Default | Covers |
|---|---|---|---|---|
| `jstage` | J-STAGE | — | yes | J-STAGE: Japanese journals and proceedings |
| `cinii` | CiNii Research | optional `cinii` | yes | CiNii Research: Japanese articles, theses, KAKEN reports |

### Domain

| Key | Database | Needs | Default | Covers |
|---|---|---|---|---|
| `ads` | NASA ADS | `ads` | yes | NASA ADS (physics, planetary/ISRU catalysis) |
| `eric` | ERIC | — | no | ERIC: chemistry-education literature |

### Datasets

| Key | Database | Needs | Default | Covers |
|---|---|---|---|---|
| `datacite` | DataCite | — | yes | DataCite DOIs: datasets, theses, reports, preprints from Zenodo, Dryad, institutional repositories, Mendeley Data ... |
| `openaire_data` | OpenAIRE (datasets) | — | yes | OpenAIRE research datasets |
| `dataverse` | Harvard Dataverse | — | yes | Harvard Dataverse datasets |
| `dryad` | Dryad | — | yes | Dryad datasets (often linked to a paper) |
| `mcloud` | Materials Cloud Archive | — | yes | Materials Cloud Archive (DFT / computational catalysis datasets) |

### Patents

| Key | Database | Needs | Default | Covers |
|---|---|---|---|---|
| `europepmc_patents` | Europe PMC (patents) | — | yes | EPO patent abstracts indexed by Europe PMC (biocatalysis-leaning, keyless) |
| `lens_patents` | Lens.org (patents) | `lens` | yes | Lens.org patents: 150M+ records, 100+ jurisdictions |
| `epo` | EPO (patents) | `epo_key`, `epo_secret` | yes | EPO Open Patent Services (EP, WO, worldwide DOCDB); CQL queries |

### Citation chasing

| Key | Database | Needs | Default | Covers |
|---|---|---|---|---|
| `citations` | Citation chasing (OpenAlex) | — | no | forward citation chasing through OpenAlex (search.py --citing); not a query database |

## Found through another database

| Database | Reached through | Why not queried directly |
|---|---|---|
| chemrxiv | crossref_preprints, europepmc, s2 | ChemRxiv's own API sits behind a Cloudflare challenge; its DOIs (10.26434) are in Crossref |
| biorxiv | crossref_preprints, europepmc | the bioRxiv/medRxiv API lists by date only |
| medrxiv | crossref_preprints, europepmc | same API as bioRxiv |
| research square | crossref_preprints, europepmc | no search API; DOIs 10.21203 |
| ssrn | crossref_preprints | no search API; DOIs 10.2139 |
| engrxiv | crossref_preprints, osf | DOIs 10.31224 in Crossref |
| essoar | crossref_preprints | now ESS Open Archive on Authorea (10.22541) |
| techrxiv | crossref_preprints | DOIs 10.36227 in Crossref |
| preprints org | crossref_preprints | DOIs 10.20944 in Crossref |
| socarxiv | osf | hosted on OSF |
| psyarxiv | osf | hosted on OSF (out of domain) |
| pubmed | europepmc | Europe PMC indexes all of PubMed |
| unpaywall | classify_access.py | not a search engine: DOIs that OpenAlex does not know are looked up there for access type and license (≤ 90,000 calls per UTC day on this machine) |
| publisher oa | crossref, openalex, doaj | BMC, Elsevier OA, Frontiers, Hindawi, MDPI, SAGE Open, SpringerOpen and Wiley OA have no search APIs; their sources are indexed through Crossref/OpenAlex/DOAJ and downloaded from their CDNs |
| jstor open | crossref | no public search API |
| scielo | crossref, openalex, doaj | search.scielo.org is behind a bot challenge |
| citeseerx | s2, openalex | service offline (redirects to the Wayback Machine) |
| catalysis hub | openalex, crossref | its GraphQL endpoint did not answer (2026-10); its datasets cite journal papers |
| nomad | datacite | computational data entries, not literature |
| custom url | import_list.py --url | a journal TOC, lab page or reference list is imported by DOI extraction |

## Deliberately not queried

| Database | Reason |
|---|---|
| base | BASE answers only IP-registered clients (ask Bielefeld UB to register the institution's IP, then it can be wired) |
| dimensions | needs an institutional Dimensions API subscription |
| dblp | bot wall (Anubis) on the API; CS venues are covered by S2/OpenAlex |
| ia scholar | scholar.archive.org answers scripted clients with a verification page; the Wayback Machine is used for dead OA links instead |
| google scholar | no API and its terms forbid scraping |
| google patents | no official API (BigQuery needs a Google Cloud project); patents come from Lens, EPO and Europe PMC |
| wipo patentscope | no free API |
| patentsview | search.patentsview.org no longer resolves (2026-10); US patents come from Lens/EPO, US patent PDFs from the USPTO image server |
| researchgate | terms forbid scraping; uploads there are often unlicensed |
| academia edu | terms forbid scraping; uploads there are often unlicensed |
| scifinder reaxys | subscription platforms whose terms forbid bulk export |
| cnki wanfang | subscription platforms without a public API |
| proquest | subscription; theses are partly covered by OpenAIRE, DataCite, HAL, CORE |
| repec | economics only; no API |
| shadow libraries | Sci-Hub, LibGen and similar pirate sites are never used |

## Default selection and changing it

A new topic gets every keyless database marked default plus every keyed database whose keys are in keys.txt
(`init_topic.py`). Keyed databases added to `config.json` without their key are skipped with a message, never
queried. ERIC (education) is off by default. Edit `.scripts/<slug>/config.json` → `databases`, give each chosen
database at least one query in `queries.json`, and run `init_topic.py --slug <slug> --check`.

Datasets (DataCite, Zenodo with `{"type": "dataset"}`, Dryad, Dataverse, Materials Cloud, OpenAIRE) and
patents (Lens, EPO, Europe PMC) are indexed with `Doc type` dataset / patent. Datasets are never downloaded;
US patent PDFs come from the USPTO image server; other patents keep their Espacenet / Lens link. Figshare files
that a publisher deposited as a source's SI are set aside (they belong to the source, not to the index).
