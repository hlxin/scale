# Catalysis (`domain/`)

The catalysis domain of SCALE (Shared Concepts, Attributes, and Links with Evidence), the first domain of the
framework and, for now, the only one. SCALE's schema has **two layers: the science kernel and the domains.**
The science kernel ([`core/`](../core/README.md)) is the general base layer; this folder, `domain/`, is the
catalysis domain built on it. Its graph schema is the kernel plus one catalysis file,
[`graph/catalysis.yaml`](graph/catalysis.yaml) (one vocabulary and one checklist), assembled by its graph schema
manifest, [`graph/scale-catal.yaml`](graph/scale-catal.yaml). It covers thermocatalysis, electrocatalysis,
photocatalysis and plasma catalysis, and their combinations, as driving forces of one checklist. The owner owns
the folder in `.github/CODEOWNERS` (the `/domain/` line, ready for the domain's own maintainers), and its
stewards are named in [`DOMAIN.yaml`](DOMAIN.yaml). A second domain would revisit the one-folder layout
([docs/architecture.md](../docs/architecture.md)).

| | |
|---|---|
| status | `stable`, `founding: true` (its stewardship targets are warnings) |
| schema version | 0.7.1 (kernel and catalysis together) |
| maintainers | `@hlxin` (the owner) and the reviewers of the review policy, open to more as they join |
| stewards | Hongliang Xin (`hlxin`), since 2026-09-26 |
| review areas | `catalysis`, `thermo`, `electrothermo`, `electro`, `photo`, `plasma` |
| declaration | [DOMAIN.yaml](DOMAIN.yaml) (`domain: catalysis`) |
| decision record | [0001](../docs/decisions/0001-scale-0.1.0.md): SCALE 0.1.0, with catalysis stable from the start |
| open work | [ROADMAP.md](ROADMAP.md) |

The catalysis domain has one steward today. Its stewardship target is two or more; until more stewards
join, `scale domains check` reports the unmet target as a warning.

The word "domain" names the folder `domain/`, the declaration `DOMAIN.yaml` and its key `domain: catalysis`, the
document key `follows_domains: ["catalysis"]`, the option `--domain catalysis`, the commands
`scale domains list | check | cq` (also `scale domain …`) and the agent tool `scale_domains`. The domain's name,
`catalysis`, is what documents follow, and `--domain` selects; the folder's
name is not.

## Scope

**In scope:** catalytic chemistry and its evidence, in scale-catal documents (labeled property graphs):

- the catalysis domain's graph schema, with one vocabulary (chemical species, materials, samples, reactions,
  reactors, preparations, characterizations, computations, mechanisms, catalysts, active sites, feeds, catalyst
  samples and catalytic tests, the role a substance plays being on the edge, and the terms of every driving
  force: heat, electrically delivered heat, an applied potential or current, light, plasma, and where they act
  together) and one **checklist** of what a record must and should report. The checklist's items for a
  catalytic test apply by the driving forces the test lists (`driving_forces`: `when` cases for thermo,
  electrothermo, electro, photo, plasma, photo with thermo, electro with photo); documents follow it as
  `follows_domains: ["catalysis"]` and `scale graph describe --domain catalysis` prints it.
- competency questions: what the schema must let people ask, as graph query plans with expected
  answers on public examples (`scale domains cq catalysis`).

**Out of scope:** the science kernel (questions, hypotheses, experiments, claims, sources, people…),
which is in [`core/`](../core/README.md) and changes only by a kernel change. The electrochemical
terms (electrodes, electrolytes, cells) and the other driving-force terms stay here.

## Terms

| term | meaning |
|---|---|
| the catalysis domain | the folder `domain/` with its `DOMAIN.yaml` |
| the schema version | one number for the kernel and the catalysis domain together: the manifest's `version`; `DOMAIN.yaml` states it too |
| the science kernel | the general base layer (`core/`) |
| the catalysis file | `domain/graph/catalysis.yaml`, a scale-catal schema file keyed `domain: catalysis` that adds the catalysis vocabulary to the kernel and carries the **checklist** (`checklist:`: what a record must and should report, with `when` cases that apply items by a record's property, e.g. the driving forces of a catalytic test); it carries no version of its own |
| graph schema manifest | `domain/graph/scale-catal.yaml`: the science kernel (`core/graph/kernel.yaml`) plus the catalysis file, listed under `domains:`. Its `version` is the schema's one version, which documents pin (`graph.schema_version`); there is no repository-wide composition |
| checklist | what documents follow (`follows_domains: ["catalysis"]`, selected with `--domain catalysis`): the catalysis file's `checklist:` |
| concept promotion | a concept moves from `maturity: provisional` to `stable` through a schema change; the stable catalysis domain holds provisional concepts |

## Contents

```
domain/
├── DOMAIN.yaml         # the declaration below; checked by `scale domains check`
├── README.md           # this file: scope, maintainers, contents, the declaration's fields, how to contribute
├── ROADMAP.md          # open work
├── graph/              # scale-catal.yaml (the graph schema manifest), catalysis.yaml (with the checklist)
├── competency/         # competency questions: cq-NN-*.yaml (graph query plans with expected answers)
├── examples/           # public synthetic example documents
├── mappings/           # catalysis.yaml: the catalysis terms mapped to ontology terms, and the areas of catalysis research
├── docs/               # catalysis documentation (reporting guidance)
└── tests/              # test_*.py, collected by pytest; fixtures
```

| path | what |
|---|---|
| `graph/scale-catal.yaml` | the catalysis graph schema manifest: the schema's one version, the science kernel (`../../core/graph/kernel.yaml`) and the catalysis file |
| `graph/catalysis.yaml` | the catalysis file (`domain: catalysis`): the vocabulary and the checklist |
| `graph/frozen/` | the frozen schema versions (`scale-catal-<version>.yaml`, `v<version>/`, `SHA256SUMS`), written when a schema change moves the schema on (`scale schema bump`); none yet |
| `competency/` | competency questions CQ-01 … CQ-11 and CQ-14 … CQ-28: graph query plans over the public examples, with their expected answers |
| `examples/` | the public synthetic examples ([overview](./examples/README.md)) |
| `mappings/catalysis.yaml` | the catalysis labels, edge types and values mapped to ontology terms (ChEBI, the Chemical Methods Ontology, REX, MOP, Allotrope, OBI and others), and the fourteen areas of catalysis research of Ontologies4Cat with the SCALE terms that record each ([mappings](../docs/mappings.md)) |
| `docs/` | [catalyst-state reporting](docs/reporting/catalyst-state-reporting.md), [catalyst-preparation reporting](docs/reporting/catalyst-preparation-reporting.md) and the [supporting-information index](docs/supporting-information.md) |
| `tests/` | the catalysis tests and the invalid scale-catal fixtures (`fixtures/invalid/`, each rejected for the reason `expect.yaml` states) |

Code that the catalysis domain needs goes in `tools/` ([tools/README.md](../tools/README.md)).

The examples, in `examples/scale-catal/`: a synthetic thermocatalytic test (`example.json`, invented values and an
invented source), one synthetic document per other driving force or combination (`driving-force-examples/`), a
source's lifecycle (`source-lifecycle/`), current densities a scientific comparison keeps apart
(`comparison-examples/`) and product measurements identified by metric, product, assay, phase and interval
(`product-measurement-examples/`), what a test is read as showing with the evidence connected to it, a
heating ramp and the stability of electrodes (`evidence-examples/`), and the site populations of a catalyst's states,
the site counts its turnover frequencies are divided by, activity assignments with their evidence and operando
observations with and without the kinetics measured while they ran (`state-site-examples/`), and preparations and
characterizations recorded step by step: two impregnated batches of one nominal formula with their lots, activation,
storage and transfer, two coprecipitations in opposite orders of addition, and a high-entropy alloy's nominal, bulk,
surface and working-state compositions and three sizes (`preparation-examples/`), all public.

## Versions

| part | version |
|---|---|
| the schema (`graph/scale-catal.yaml`: the kernel with the catalysis file), which documents pin; `DOMAIN.yaml`, `core/CORE.yaml` and `scale-release.yaml` state it | 0.1.0 |
| the kernel and the catalysis file | none of their own |

This repository started its numbering at 0.1.0 on 2026-10-08. `scale graph spec` gives each version's digest
([README](../README.md#schema-versions)), which does not depend on where the files are.

## `DOMAIN.yaml`

Block-style YAML ([docs/style.md](../docs/style.md)). Paths are relative to `domain/`, except
`decision_record`, which is relative to the repository root (decision records are numbered globally
under `docs/decisions/`). Unknown keys are errors.

Two directories have fixed names, because the tools read them there and nowhere else:
`competency` and `tests` are named after their key. `scale domains check` rejects any
other value.

| key | required | meaning |
|---|---|---|
| `domain` | yes | the domain's name (`catalysis`): lowercase letters, digits and `-`. Documents follow its checklist by this name, and `--domain` selects it |
| `title` | yes | display name |
| `status` | yes | `experimental`, `stable` or `deprecated`; the catalysis domain is `stable` |
| `founding` | no | `true` for catalysis; an unmet stewardship target (below) is then a warning |
| `version` | yes | the schema's one version (the manifest's); `scale domains check` requires them to agree and `scale schema bump` raises both |
| `depends_on` | no | empty: there is no other domain to depend on |
| `alternative_to` | no | kept for the code and unused (null); it may only name a scale-catal file. Disagreement inside catalysis is a pull request plus `contradicts` links ([governance](../governance/GOVERNANCE.md#disagreement)) |
| `summary` | yes | one line |
| `scope` | yes | what is in scope and what is not |
| `maintainers` | yes | `team` (the code owner as CODEOWNERS names it: a user such as `@hlxin`, or a team `@org/team`) and `people`: each with `name`, `github`, optional `orcid`, `since` and `roles` (`steward` or `maintainer`); an entry for nobody yet has `placeholder: true` and no `since`, and is never counted or credited |
| `review_areas` | yes | the review-policy areas of catalysis changes |
| `graph` | no | `manifest` only (required with `graph`): the graph schema manifest, `graph/scale-catal.yaml`, which lists the catalysis file under `domains:` |
| `examples` | yes | example directories |
| `example_documents` | yes | `graph`: scale-catal documents (globs allowed) that `scale domains check` validates under their pinned versions |
| `competency` | yes | the competency-question directory (always `competency`): graph query plans with expected answers, run on public examples by `scale domains cq` |
| `tests` | yes | the test directory (always `tests`; at least one `test_*.py`) |
| `docs` | no | the documentation directory |
| `mappings` | no | the catalysis terms mapped to ontology terms (always `mappings/catalysis.yaml`), checked by `scale domains check` ([mappings](../docs/mappings.md)) |
| `roadmap` | yes | the roadmap file |
| `decision_record` | for `stable` and `deprecated` | the decision record that accepted it, repository-relative (`docs/decisions/NNNN-*.md`; for catalysis, 0001) |
| `deprecation` | for `deprecated` | why it is deprecated and what replaces it |
| `contributors` | yes | credit: each with `name`, optional `github`, optional `orcid`, and `roles`. People are added only with their consent. |

An excerpt (the full file is [DOMAIN.yaml](DOMAIN.yaml)):

```yaml
domain: catalysis
title: Catalysis
status: stable
founding: true
version: 0.1.0
maintainers:
  team: '@hlxin'
  people:
    - name: Hongliang Xin
      github: hlxin
      since: '2026-09-26'
      roles:
        - steward
review_areas:
  - catalysis
  - thermo
  - electrothermo
  - electro
  - photo
  - plasma
graph:
  manifest: graph/scale-catal.yaml   # lists graph/catalysis.yaml (domain: catalysis), with the one checklist
```

Release manifests take their credits from `maintainers` and `contributors` (deduplicated by GitHub handle, or
ORCID, or name, when there is no handle; with their roles and `scopes`, the kernel or the catalysis domain that
credits them) and record the schema's one version and the catalysis domain's `status` and schema manifest; they
carry the manifest, its parts and the kernel.

## Stewardship targets

`scale domains check` reports, as warnings for catalysis (`founding: true`), the stewardship targets of a
stable domain: two or more maintainers with the role `steward`; three or more competency questions that
run and answer as expected (`scale domains cq`); example documents that validate; a decision record,
named in `decision_record`. Catalysis has one steward today, so the first target is a warning.

## What `scale domains check` checks

- `DOMAIN.yaml` and `core/CORE.yaml` have the required keys and types and no unknown keys, valid
  semver, and `domain` is a name; every declared path exists and the fixed directory names are used.
- The schema's one version: `DOMAIN.yaml`, `core/CORE.yaml`, `scale-release.yaml` (`schema_version`) and
  `core/examples/science-kernel-only.yaml` state the manifest's `version`; the kernel and the catalysis file
  state none (they do not load if they do).
- The tests directory has at least one `test_*.py`; the competency directory has questions;
  `maintainers.people` is not empty; `depends_on` is empty.
- Every scale-catal `imports` resolves to the kernel or the catalysis domain's own files, and names no version.
- The graph schema manifest (`graph.manifest`) uses the kernel (`core/graph/kernel.yaml`), lists under
  `domains:` only files inside `domain/`, among them the one named after the domain (`domain: catalysis`),
  and loads; it has no `modules:`, `extensions:` or `profiles:`, and each of its files names itself with
  `domain:`.
- **Identifiers:** one name index is built over the kernel and the catalysis graph files (labels, edge
  types, and `adds_properties` keys per label). Declaring a name that already exists is an error
  naming both owners. Extending is `is_a`, `extends`, or `adds_properties` with a new key.
- No copies of kernel files anywhere in the catalysis domain, its frozen versions included (no
  `kernel:` file, no file byte-identical to a kernel file); frozen kernels live only in
  `core/graph/frozen/`.
- `scale-release.yaml` `domain_profiles:` lists exactly `domain/DOMAIN.yaml`, and it has no
  `graph:` key (there is no repository-wide composition).
- `.github/CODEOWNERS` gives `core/CORE.yaml` to the code owner named in it, and has a `/domain/` line naming
  the domain's code owner, which owns `DOMAIN.yaml`.
- `example_documents` validate: graph documents against the catalysis manifest at the version they
  pin (the head, or `graph/frozen/scale-catal-<version>.yaml`); the core's against the kernel of the version
  they pin.
- A warning when no one in `governance/review-policy.yaml` lists the catalysis `review_areas`.

It runs at the repository root only, as part of `scale check`.

## How to contribute

- **Comment** without Git: the [comment form](https://github.com/hlxin/scale/issues/new?template=comment.yml),
  or 💬 next to a record in a catalogue (`scale catalogue <document>`).
- **Curate a source** into an example, following `skills/curate-source/SKILL.md` (public, open-access
  sources and short, capped quotes only).
- **Suggest a schema change** on an issue (@scale-agents take it up), or make it in a pull request that edits
  `graph/catalysis.yaml` and raises the one version (`scale schema bump`;
  `skills/evolve-schema/SKILL.md`). It needs one approval and passing checks.
- **Add a competency question** in `competency/`: a graph query plan, the public examples it runs on
  and its expected answer; `scale domains cq catalysis` runs it.
- **Become a maintainer:** ask on an issue. When the owner agrees, they add you to `DOMAIN.yaml`, the review
  policy and `.github/CODEOWNERS` in a pull request ([governance/working-groups.md](../governance/working-groups.md)).

See [CONTRIBUTING.md](../CONTRIBUTING.md) for branches, pull requests and review.
