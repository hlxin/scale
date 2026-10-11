# scale-graph — the science kernel and how a domain builds on it

scale-graph is the knowledge and data graph schema: a labeled property graph in node-link JSON (as
NetworkX writes and D3 reads). Nodes and edges both carry typed properties; evidence sits on every
node and edge that states something. The decisions behind it are in
[decision record 0001](../../docs/decisions/0001-scale-0.1.0.md); every concept is provisional.
Naming rules: [docs/style.md](../../docs/style.md). "scale-graph" names the format and the schema
family that documents pin (`schema: scale-graph`, `graph.schema_version`).

![architecture](../../docs/figures/scale-graph-architecture.png)

## Two layers

SCALE has **two layers: the science kernel (core) and the domains**. Catalysis is the first domain and, for now,
the only one: the folder `domain/`, declared by `domain/DOMAIN.yaml` as `domain: catalysis`. The catalysis
**graph schema** is the kernel plus the domain's own file(s), assembled by its graph schema manifest; there is no
repository-wide composition and no third layer between the kernel and the domain. The catalysis graph schema is
the kernel plus one domain file, `catalysis.yaml`, with one vocabulary and one checklist. The schema has **one
version** for the kernel and the catalysis domain together: the manifest's `version` (0.1.0).

| file | maintained by | what it holds |
|---|---|---|
| [`core/graph/kernel.yaml`](kernel.yaml) | core | The **science kernel**: the document format, the value object, the evidence item, record references, stewardship, the source lifecycle, common properties and extension keys; and the method of science — Question, Hypothesis, Prediction, Experiment, Procedure, Protocol, Operation, Design, Variable, Claim; what is studied (ObjectOfStudy); what science is done with (Instrument, Model, Source, Dataset); who does it (Person, Institution, Project, Software). Every domain file sees it without importing it. It carries no version of its own. |
| `core/graph/frozen/` | nobody (frozen) | The **kernel of each earlier schema version**, `kernel-<version>.yaml`, with their digests in `SHA256SUMS`, written when a schema change moves the schema on (`scale schema bump`; none yet). Frozen kernels live only here. |
| [`domain/graph/scale-graph.yaml`](../../domain/graph/scale-graph.yaml) | the catalysis domain | The catalysis **graph schema manifest**: the schema's one version, which documents pin, the kernel (`../../core/graph/kernel.yaml`) and the domain's files under `domains:` (`[catalysis.yaml]`), each path relative to the manifest. |
| [`domain/graph/catalysis.yaml`](../../domain/graph/catalysis.yaml) | the catalysis domain | The **catalysis domain file** (`domain: catalysis`), catalysis as a whole: species, materials, samples, reactions, reactors, preparations, treatments, characterizations, computations, analyses, mechanisms and elementary steps, catalysts, active sites, feeds, catalyst samples, catalytic tests, process units. The role a substance plays is on the edge: `HAS_COMPONENT {role: support, promoter, binder, …}`, `PREPARED_FROM {role, amount, supplier, grade}`, `INHIBITED_BY`. It also holds the terms of every driving force (below) and the domain's one **checklist**. It carries no version of its own. |
| `domain/graph/frozen/` | nobody (frozen) | The catalysis domain's **frozen versions** (none yet): `scale-graph-<version>.yaml` with its parts under `v<version>/`, byte-identical to what documents pinning that version were written against, and pointing at the kernel of that version in `core/graph/frozen/`; digests in `SHA256SUMS`. |

Terms: the catalysis domain is the folder `domain/`; its name, `catalysis`, is the `domain:` its
`DOMAIN.yaml` declares. Its **domain file** (`domain: catalysis`, listed under the manifest's `domains:`)
holds the vocabulary it adds to the kernel and its **checklist**. Documents follow the checklist by the
domain's name (`follows_domains: ["catalysis"]`) and `--domain catalysis` shows it. The domain may split its
vocabulary over further files inside `domain/`; the file named after the domain is required. `DOMAIN.yaml`
declares the manifest (`graph.manifest`); `scale domains check` verifies that it uses the core's kernel,
lists only files inside `domain/`, among them the one named after the domain, and loads, that the domain
declares no name the kernel declares, and that every file stating the schema version agrees
([domain/README.md](../../domain/README.md)). Documents pin only `graph.schema_version`; `scale graph validate`
reads the catalysis manifest (or `--spec`) and then the head or the frozen copy of the pinned version.
`scale graph verify` checks that the manifest and its frozen versions load and that every frozen directory
matches its `SHA256SUMS`.

A manifest may also list vocabulary-only files (`modules:`) and optional vocabularies (`extensions:`); the loader
reads them, and `scale domains check` keeps a domain's own manifest to `domains:`. There are no profile files: they
are retired by design. A domain file carries its checklist, documents follow it with `follows_domains`, and a manifest
that lists `profiles:` is refused.

## How a domain file builds on the kernel

A domain file never copies or redeclares a kernel name; it builds on the kernel, which it sees without
an import:

- **`is_a`** — a new label refines a kernel label and inherits its properties and required list
  (`CatalystSample is_a ObjectOfStudy`, `CatalyticTest is_a Experiment`, `Reactor is_a Instrument`); it
  may `fix` an inherited value (a Reaction is an ObjectOfStudy with `object_kind: phenomenon`).
- **`specializes`** — a new edge type narrows a kernel edge and stays inside its endpoints
  (USES_CATALYST specializes EXAMINES; IN_REACTOR, HEATED_BY and ILLUMINATED_BY specialize
  USES_INSTRUMENT; FED_WITH and USES_ELECTRODE specialize HAS_INPUT), so a kernel-level query finds
  domain-level facts.
- **`adds_properties`** — new properties on a label the file can see (the driving-force terms on
  CatalyticTest); a name already declared is an error.
- **`extends`** — new endpoints on an edge type it can see (`HAS_COMPONENT.from` gains Electrolyte).

The kernel and the catalysis files change by pull request, each change raising the same one version.

## Driving forces in the catalysis domain

A catalytic test lists its driving forces (`CatalyticTest.driving_forces`). The catalysis domain file
holds the terms of each:

| driving forces | entities | relationships |
|---|---|---|
| thermo | Heater, TemperatureProbe | HEATED_BY, TEMPERATURE_MEASURED_BY |
| electro | Electrode, ReferenceElectrode, Electrolyte, ElectrochemicalCell | USES_ELECTRODE, IN_ELECTROLYTE, IN_CELL |
| photo | LightSource | ILLUMINATED_BY |
| plasma | PlasmaSource | USES_PLASMA |
| electrothermo (heat delivered electrically) | ElectricHeater | ELECTRICALLY_HEATS |
| photo + thermo | ThermalContributionAnalysis | DARK_CONTROL_FOR |
| electro + photo (a photoelectrode, or an electrogenerated species, absorbs the light) | Photoelectrode, IlluminatedCell | ILLUMINATES, ELECTROGENERATES, PHOTOEXCITES |

## The checklist: must, should and cases

A domain file's `checklist` says, per label and per edge type, what a record **must** report (checked: a
missing item makes the record non-conformant) and **should** report (scored as completeness). It can
narrow units and enum values, and exempt records (`unless: {test_kind: [equilibrium_estimate,
equilibrium_measurement]}`: an equilibrium needs no catalyst or feed). Items that depend on the record
sit in `when` cases, each a condition on a list or enum property (`any_of` or `all_of` of its values)
with the items that then apply. The catalysis checklist keys its cases on `driving_forces`: the thermal
items apply to thermo and electrothermo tests, the electrical heating items to electrothermo tests,
the electro, photo and plasma items to tests that list them, and the items where forces meet to tests
that list photo and thermo, or electro and photo. Items of a case that does not match are neither
checked nor counted. A document names the checklist it follows in `follows_domains` (the graph's
list, or a node's own); `scale graph describe --domain catalysis` prints the cases.

Validity and conformance are reported separately: a document that is valid (kernel and domain
vocabulary) can fail a checklist, and that is an answer about what its sources report — historical
sources stay usable.

## Mechanisms the loader enforces

- **Inheritance:** `is_a`; a label may `fix` an inherited value (a Reaction is an ObjectOfStudy with
  `object_kind: phenomenon`; a Reactor is an Instrument of kind `reactor`); a fixed value must agree with
  its ancestors'.
- **Composition:** `adds_properties` adds properties to a label the file can see (the kernel's, its
  own, those of the files it imports; clashes are errors); `extends` adds endpoints to such an edge;
  `bridges` apply only when another named file is loaded.
- **Specialization of kernel edges:** a domain edge may `specialize` a kernel edge and must stay
  inside its endpoints.
- **One owner per name:** a label, edge type or property is declared once, by the kernel or by one
  domain file; a second declaration fails to load.
- **Extension keys:** properties outside the schema are `_<prefix>_<name>`, with the prefix
  registered in [`governance/registry/extension-prefixes.yaml`](../../governance/registry/extension-prefixes.yaml). They are kept, not checked, and never change
  the meaning of a declared property; a new driving force starts there and enters the catalysis
  domain file (its terms and a checklist case) by a schema change.

## Use and evolve

```bash
scale graph describe CatalyticTest --domain catalysis         # labels, edges, properties and the checklist with its cases
scale graph validate DOC.json [--source-text ID=FILE]         # validity; conformance to follows_domains
scale schema diff | bump | check                              # a schema change on a branch (skills/evolve-schema)
scale graph verify                                            # the catalysis manifest and its frozen versions load and verify
scale graph spec                                              # the spec document of the head version and its sha256
scale domains check                                           # the domain's files: imports, the one version, no redeclared identifiers
```

A schema change is a pull request that edits the schema files directly
([`skills/evolve-schema/SKILL.md`](../../skills/evolve-schema/SKILL.md)): additive operations, a fixture
and a counterexample, the competency questions that change, and one person's review under
[`governance/review-policy.yaml`](../../governance/review-policy.yaml). Every change raises the one schema version,
whichever file it changes (breaking: the second number; additive: the third). `scale schema bump` freezes the
current version so documents that pin it keep validating: its kernel into
`core/graph/frozen/kernel-<version>.yaml`, the catalysis parts into `domain/graph/frozen/v<version>/` with the
manifest `frozen/scale-graph-<version>.yaml`, all under the one version; digests are appended to each `SHA256SUMS`; it also registers the migration step.
`scale schema check` (CI) checks all of it.
A release build refuses schema content changed since the previous release under the same version, and `scale
graph verify` fails when a version no longer has the spec digest a release published for it.

The kernel's informational `extensions.registry: registry/extension-prefixes.yaml` predates the move of the
registry to `governance/registry/`; the string changes only with a kernel change (the loader reads the registry
from `governance/registry/`).
