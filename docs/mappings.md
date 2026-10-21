# Mappings to ontology terms

SCALE does not take its meaning from an ontology: its terms are defined by its own schema
([core/graph/kernel.yaml](../core/graph/kernel.yaml), [domain/graph/catalysis.yaml](../domain/graph/catalysis.yaml)).
Ontologies still hold much of what catalysis research needs to say, and other people's data is described with their
terms. A **mapping** says how a SCALE term relates to a term someone else defines, so that data can be found and
exchanged across both. It changes nothing that SCALE validates or queries.

## Where they are

| File | What it holds |
|---|---|
| [core/mappings/ontologies.yaml](../core/mappings/ontologies.yaml) | The ontologies and vocabularies that mappings cite: name, what a prefix stands for (`iri`), what a term looks like (`pattern`), homepage, the licence the ontology states for itself, and the release its terms were looked up in (`checked`) |
| [core/mappings/kernel.yaml](../core/mappings/kernel.yaml) | The science kernel's labels and edge types mapped (OBI, IAO, COB, SIO, STATO, SEPIO, BFO, RO, PROV, DCAT, Dublin Core, FOAF, Schema.org, SOSA), and its quantity kinds and units mapped to QUDT (below) |
| [domain/mappings/catalysis.yaml](../domain/mappings/catalysis.yaml) | The catalysis labels, edge types and values mapped (ChEBI, the Chemical Methods Ontology, REX, MOP, the Allotrope Foundation Ontology, OBI, CHEMINF, EDAM, ENVO, RO), and the areas of catalysis research (below) |

The files sit beside the schema, not in it: a mapping can be added or corrected without a new schema version, and a
schema change never waits for one. `core/CORE.yaml` and `domain/DOMAIN.yaml` declare them (`mappings`).

## What a mapping says

Each entry is keyed by a SCALE term and lists the other terms it relates to:

```yaml
Treatment.treatment_kind=calcination:
- match: close
  term: CHMO:0001467
  label: calcination
```

- **The SCALE term**: a label (`Catalyst`), an edge type (`HAS_INPUT`), a property (`Label.property`) or a value
  of one (`Label.property=value`).
- **term**: the other term as a CURIE, `prefix:local id`; the registry says what the prefix stands for, so
  `CHMO:0001467` is <http://purl.obolibrary.org/obo/CHMO_0001467>.
- **label**: the other term's label as its ontology gives it, so that a reader sees what it is and a misspelt
  identifier shows.
- **match**: how the two relate, as the SKOS mapping relations say.

| match | Meaning | Example |
|---|---|---|
| exact | The two mean the same and can be used one for the other | ReferenceElectrode and CHMO's *reference electrode* |
| close | Nearly the same: fine for finding data, not for automatic reasoning | ChemicalSpecies and ChEBI's *molecular entity* |
| broad | The other term is broader: every SCALE one is one of them, not the other way round | Electrode and CHMO's *electrode* (SCALE keeps the reference electrode apart) |
| narrow | The other term is narrower | Experiment and OBI's *assay* (a SCALE experiment can also be a computation) |
| related | Associated, but neither is the other: a thing and the role it plays, a change and the treatment that causes it | the reduction treatment and MOP's *reduction* |

- **note** (optional): why, where the match is not obvious.

Mappings cite identifiers and labels only, never an ontology's definitions.

## Quantity kinds and units

The kernel's set maps the kinds of quantity SCALE compares (`kinds`, by name) and the units its unit vocabulary reads
(`units`, spelled as SCALE reads them) to [QUDT](https://qudt.org/), the units and quantities vocabulary many data
standards use, release 3.5.3:

```yaml
units:
  "°C":
  - match: exact
    term: unit:DEG_C
    label: Degree Celsius
kinds:
  flow_rate:
  - match: narrow
    term: quantitykind:VolumeFlowRate
    label: Volume Flow Rate
```

- **Units** are exact matches where both mean the same unit: °C, kPa, mL/min, h-1, kJ/mol, m2/g and some 100
  more. SCALE reads a unit by its dimension only, so a gallon, a ton, a calorie or a Btu is whichever one the source
  printed; each of QUDT's definitions (US or UK gallon, thermochemical or international calorie) is narrower.
  Normal and standard volumes (Nm3, scf) are close: SCALE does not fix their reference temperature and pressure,
  and QUDT counts them as amounts of substance (it gives the normal cubic metre no conversion factor), so QUDT's
  conversion factors do not apply to SCALE's volumes.
  A percent or ppm is the unit only; what the share is of (mass, mole, volume) stays a context of the value.
- **Kinds** are close where QUDT has the same quantity (temperature, pressure, electric current); narrow where
  QUDT's kind is one form SCALE's takes (a volumetric, molar or mass flow rate; an amount or mass concentration or a
  molality; QUDT's efficiency, a ratio of powers, where SCALE's may also be of charge or photons); broad where QUDT
  names only the general quantity, in every dimension SCALE reads the kind in (a conversion, a selectivity, a yield
  or a faradaic efficiency is a dimensionless ratio); and related where neither holds: a reaction energy or enthalpy
  is read in eV or in kJ/mol, so it is neither always QUDT's energy nor always its molar energy; QUDT's current
  density is the local current density, a vector, where SCALE's is a reported current divided by an electrode area
  or a catalyst mass; QUDT's amount of substance or count is any amount or count, where SCALE's product amount or
  site count is of one product or of sites. An enzyme's turnover frequency at saturation is SBO's catalytic rate
  constant (kcat), narrower than SCALE's turnover frequency. QUDT has no term for an activation energy, a space
  velocity, a site density or most catalysis-specific shares, so they stay unmapped.

## How they are checked

`scale domains check` (part of `scale check`) and `scale schema mappings --check` check that:

- every SCALE term is one the head schema declares, and a layer's labels and edge types are its own; every
  quantity kind is one the kernel's contracts declare, and every unit one its unit vocabulary reads;
- every term is a CURIE of a registered ontology and looks like a term of it;
- every match is one of the five words;
- no term is mapped twice for one SCALE term, and an exact match is the only exact one in that ontology (a
  warning);
- a set that `core/CORE.yaml` or `domain/DOMAIN.yaml` declares (`mappings`) exists, and so does the registry;
- no key is given twice in a mapping file (YAML would keep the second and drop the first silently), and every
  section has its shape (a subject lists its mappings).

The tests do not reach the ontologies. Whether a term exists and is not obsolete is looked up when a mapping is
written, in the release the registry names. The first terms were looked up on 2026-10-20 in
[EBI OLS](https://www.ebi.ac.uk/ols4/) and in the W3C and Schema.org vocabulary files. Two terms the kernel's
`maps_to` names in words are obsolete in OBI: *planned process* (OBI:0000011) and *device* (OBI:0000968). OBI points
to COB's *completely executed planned process* (COB:0000035) and *device* (COB:0001300). An experiment or a procedure
maps to COB's broader *planned process* (COB:0000082), since SCALE also records proposed, running, failed and aborted
ones; only a completed one (`Experiment.experiment_status=completed`) is a completely executed planned process.

## How to add one

1. Look the term up in [EBI OLS](https://www.ebi.ac.uk/ols4/) (or the ontology's own files), and read its
   definition, not only its label.
2. Choose the match by the definitions: exact only when they mean the same; close when they nearly do; broad or
   narrow when one is a kind of the other; related otherwise.
3. Add the entry, with the term's label as the ontology gives it. A new ontology also needs a registry entry, with
   the release you looked the term up in (`checked`) and the licence the ontology states.
4. Run `scale schema mappings --check`.

## Seeing and exporting them

- `scale graph describe <Label>` (and the agents' `scale_describe`) shows a term's mappings (`mappings`) and those
  of its properties and values (`property_mappings`), each with the IRI the term stands for.
- `scale schema mappings [--layer kernel|catalysis]` lists them.
- `scale schema mappings --layer catalysis --format sssom` writes a layer's set as SSSOM TSV, the Simple Standard
  for Sharing Ontological Mappings, which ontology tools read. A SCALE term's identifier there is the schema file
  that declares it followed by the term, such as `scalecatal:Treatment.treatment_kind=calcination`, with any
  character an IRI does not allow percent-encoded. Every identifier is a CURIE of the file's `curie_map`, as SSSOM
  TSV requires, the schema file the subjects come from included (`subject_source: scale:domain/graph/catalysis.yaml`);
  the metadata is written by a YAML writer, and a cell holding a double quote is quoted. Both sets pass the SSSOM
  validator of sssom-py 0.4.21 (`sssom validate`).

## Areas of catalysis research

Ontologies4Cat classifies ontologies by fourteen areas of catalysis research (A. S. Behr, H. Borgelt and N.
Kockmann, J. Cheminform. 2024, 16, 16, [doi:10.1186/s13321-024-00807-2](https://doi.org/10.1186/s13321-024-00807-2);
its metadata collection is [github.com/nfdi4cat/Ontology-Overview-of-NFDI4Cat](https://github.com/nfdi4cat/Ontology-Overview-of-NFDI4Cat),
CC BY 4.0). The paper found that no ontology contains heterogeneous, homogeneous, photo- or electrocatalysis,
synthesis data, or heat, transport and kinetic data, and that one each contains biocatalysis, operando data,
performance data, and process design, energy and cost data (the collection, at the commit below, lists two for the
last: OEO and OntoCAPE).
The catalysis set records, for each area, the SCALE terms that record it, what SCALE lacks for it (SCALE's own
reading), and the ontologies the collection classifies under it, as of its commit 399b788.
`scale schema mappings --areas` shows them, with the ontologies SCALE's mappings already cite.

| Area | What SCALE records it with | What SCALE lacks |
|---|---|---|
| Biocatalysis | nothing yet | an enzyme or whole-cell catalyst; enzyme activity |
| Heterogeneous catalysis | Catalyst, CatalystSample, ActiveSite, CatalystState, CatalyticTest, Reactor, Feed | |
| Homogeneous catalysis | Catalyst (family molecular_complex), CatalyticTest | a ligand or solvent role; a turnover number |
| Photocatalysis | LightSource, ILLUMINATED_BY, IlluminatedCell, Photoelectrode, ThermalContributionAnalysis | |
| Electrocatalysis | Electrode, ReferenceElectrode, Electrolyte, ElectrochemicalCell, USES_ELECTRODE | |
| Chemical substance modelling | ChemicalSpecies, Reaction, HAS_PARTICIPANT | |
| Material modelling | Material, StructureModel, HAS_PHASE | |
| Process modelling | ProcessUnit, FEEDS_INTO, Reactor, Mechanism, ElementaryStep, Computation | |
| Synthesis data | Preparation, ProcedureStep, Treatment, Sample, CatalystSample, PREPARED_FROM | |
| Operando data | Characterization, DURING, TimeSeries, CatalystState | |
| Performance data | CatalyticTest, Analysis | |
| Characterisation data | Characterization, CHARACTERIZES, DETECTS, TimeSeries | |
| Heat, transport and kinetic data | Analysis, Mechanism, ElementaryStep, Heater, TemperatureProbe | a quantity kind for a transport criterion, a Thiele modulus or an effectiveness factor |
| Process design, energy and cost data | ProcessUnit | energy consumption beyond plasma tests; cost |

## Not done yet

- Checked external identifiers on records, such as a characterization's technique identifier.
- The kernel's `maps_to` still names vocabulary terms in words; the mapping set gives their identifiers.
- Exports do not yet take a type's IRI from an exact mapping.
