# Core

SCALE's schema has two layers: the science kernel (this directory, "the core" as a folder) and the domains
(catalysis, the first and for now the only one, in `domain/`). The science kernel is the general base layer
that a domain builds on through its schema manifest, so a change here reaches the catalysis schema too. It is
looked after by the owner, `@hlxin`, and the reviewers of the review policy (one reviewer group for the kernel
and the catalysis domain) and declared in [CORE.yaml](CORE.yaml).

## Scope

The science kernel, [`graph/kernel.yaml`](graph/kernel.yaml) (`scale-kernel`):

- the method of science: Question, Hypothesis, Prediction, Experiment, Procedure, Protocol,
  Operation, Design, Variable, Claim;
- what is studied (ObjectOfStudy) and what science is done with (Instrument, Model, Dataset,
  Source);
- who does it (Person, Institution, Project, Software);
- the value object, evidence items, record references, stewardship, the source lifecycle (notices that
  retract, correct or update a source; status checks), common properties and extension keys, and the links
  between them (SUPPORTS, CONTRADICTS, TESTS, PRECEDES, RETRACTS, UPDATES, …).

| path | what |
|---|---|
| `CORE.yaml` | the declaration: the schema version, maintainers, scope, compatibility policy, examples, tests |
| `graph/kernel.yaml` | the science kernel (it carries no version of its own) |
| `graph/frozen/` | the kernel of each earlier schema version (`kernel-<version>.yaml`, `SHA256SUMS`), written when a schema change moves the schema on (`scale schema bump`); none yet |
| `graph/README.md` | [the two layers and how a domain builds on the kernel](graph/README.md) |
| `mappings/ontologies.yaml`, `mappings/kernel.yaml` | the ontologies SCALE's terms are mapped to, and the kernel's labels and edge types mapped to their terms (OBI, IAO, COB, SIO, PROV and others; [mappings](../docs/mappings.md)) |
| `examples/science-kernel-only.yaml`, `examples/science-examples/` | the kernel on its own, with five synthetic cases ([examples](examples/README.md)) |
| `tests/` | the kernel's tests |

There is no repository-wide composition. The catalysis domain's manifest
([`domain/graph/scale-catal.yaml`](../domain/graph/scale-catal.yaml)) assembles the kernel with one catalysis
file (`catalysis.yaml`), with one vocabulary and one checklist.

## Science kernel or domain?

A concept belongs in the science kernel when it is a general scientific distinction that is not specific to one
field and is built only from kernel parts. Everything specific to catalysis belongs in the catalysis domain.

| belongs in the science kernel | belongs in the catalysis domain |
|---|---|
| the method of science, evidence, provenance, the source lifecycle, people and institutions | catalysis entities: species, catalysts, reactions, catalytic tests |
| general distinctions that recur in other sciences in the same form | the checklist of what a catalysis record must and should report; example data, competency questions and reporting guidance |

The kernel changes only by a pull request that changes it. The catalysis domain never copies kernel files or redeclares a
kernel identifier; `scale domains check` reports both.

## One version

- **The schema has one version for the kernel and the catalysis domain together**: the `version` of the
  catalysis manifest, `domain/graph/scale-catal.yaml`. Today the schema is at 0.7.3 (kernel and catalysis
  together). The kernel file carries no version of its own (one that states one does not load); `CORE.yaml`
  states the same number (`version`), as do `domain/DOMAIN.yaml`, `scale-release.yaml` (`schema_version`) and
  `examples/science-kernel-only.yaml`, and `scale domains check` requires them to agree.
- Every schema change raises it in its own pull request, whether it changes the kernel, the catalysis file or
  both: additive changes raise the third number (0.1.0 -> 0.1.1); breaking changes (removals, narrowed ranges,
  newly required properties, changed meaning) raise the second (0.1.0 -> 0.2.0) and need a migration rule.
  Prefer deprecation to removal.
- `scale schema bump` freezes the version it replaces: the kernel of that version into
  `graph/frozen/kernel-<version>.yaml`, beside the catalysis manifest and file frozen in
  `domain/graph/frozen/`. A release build refuses schema content changed since the previous release under the
  same version.

## Changing the core

1. Open a [science-kernel issue](https://github.com/hlxin/scale/issues/new?template=core-change.yml) for anything
   larger than a fix.
   @scale-agents take it up and make the change.
2. The change edits `graph/kernel.yaml` directly, adds a fixture that uses what it adds, raises the one version
   (`scale schema bump --base origin/main`) and passes `scale schema check`
   ([`skills/evolve-schema/SKILL.md`](../skills/evolve-schema/SKILL.md)).
3. The pull request says how the change affects the catalysis domain; `scale ci spec-changes` lists who reviews,
   and CI writes a summary of the schema change for the reviewer.
4. Review: one approving review by a reviewer other than the author, as for every change
   ([governance/GOVERNANCE.md](../governance/GOVERNANCE.md)).
   The kind of change (breaking or additive) is information for the reviewer.

## `CORE.yaml`

| key | meaning |
|---|---|
| `core` | `scale-core` |
| `title` | display name |
| `summary` | one line |
| `version` | the schema's one version (the catalysis manifest's); `scale domains check` requires it to agree |
| `kernel` | `graph/kernel.yaml` |
| `maintainers` | `team` (the code owner as CODEOWNERS names it: `@hlxin` today, or a team `@org/team`) and `people`: each with `name`, `github`, optional `orcid`, `since` and `roles`; an entry for nobody yet has `placeholder: true` (no `since`), is nobody and is never credited |
| `scope` | what the core covers |
| `compatibility` | the versioning policy above |
| `examples`, `tests`, `docs` | paths, relative to `core/` |
| `mappings` | the kernel's terms mapped to ontology terms (always `mappings/kernel.yaml`), checked by `scale domains check` ([mappings](../docs/mappings.md)) |
| `example_documents` | `graph`: kernel-only documents (globs allowed) that `scale domains check` validates against the kernel of the version they pin |
| `review_areas` | `[kernel]` |
| `contributors` | credit for core, tooling and documentation work: each with `name`, optional `github`, optional `orcid`, and `roles`; added with consent |

## Known follow-ups

These wait for a kernel change (each its own pull request):

- The kernel's informational `extensions.registry` string names `registry/extension-prefixes.yaml`; the
  registry is `governance/registry/extension-prefixes.yaml`.
- The kernel's `Operation` description still says "driving-force domains say what is driven"; the driving forces
  are cases of the catalysis domain's one checklist (`follows_domains: ["catalysis"]`).
- The example in the `graph.follows_domains` description, `thermocatalysis@0.1.0`, names a frozen driving-force
  profile of the consortium schema repository's earlier numbering, which this repository does not hold; it becomes
  `catalysis` or `catalysis@0.1.0` ([domain/ROADMAP.md](../domain/ROADMAP.md), "The schema's wording", which also
  lists the catalysis checklist's `basis` text).
- The kernel's text still speaks of modules in places: the `extensions` description ("a property no module
  declares", "graduate into a module"), Experiment and Procedure ("Modules specialize it"), Variable.of ("a
  module's …"), ObjectOfStudy ("Domain modules …") and EXAMINES ("Modules add the physical specimens"). A
  kernel change rewords them as "domains".
