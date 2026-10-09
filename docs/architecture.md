# Architecture

SCALE links three activities. Each can expose limitations in the others.

```
             ┌──────────────────── gap reports (typed) ─────────────────────┐
             │                                                              │
   sources ──► CURATION ──► scale-graph ──► QUERY ──► rows + evidence       │
             │  (skill,       document        (plans)   + plan + limits     │
             │   validate)    (pins its           │                         │
             │      │          schema version)    │ schema_gap / missing    │
             │      └── unmodeled context ────────┴─► GitHub issue ─────────┤
             │                                                              ▼
             │                                 EVOLUTION (proposal: build · check)
             │                                   │ fixtures · migration · competency questions
             │                                   ▼
             │                         human review (one reviewer per pull request)
             │                                   ▼
             └── kg update / migrate ◄──── apply after the merge (freeze the old version) ──► release
```

## Repository layout

One repository, `hlxin/scale`, holds the science kernel, the catalysis domain, the tools (the Python package
`scale-schema`) and the releases ([decision record 0001](decisions/0001-scale-0.1.0.md)). SCALE is a general
framework: the specification has **two layers, the science kernel and the domains**. A domain builds on the
kernel through its graph schema manifest; catalysis is the first domain and, for now, the only one, so its
folder is `domain/`. There is no repository-wide composition and no third layer. A second domain would revisit
this layout (a folder per domain, and how the one schema version spans them). SCALE has one data format,
scale-graph documents. Paths are named in one place, `tools/scale/layout.py`; review is routed by
[`.github/CODEOWNERS`](../.github/CODEOWNERS).

| path | what it holds | maintained by |
|---|---|---|
| [`scale-release.yaml`](../scale-release.yaml) | the head distribution manifest: distribution, release id, the schema's one version (`schema_version`), `core`, `domain_profiles`, skills | the owner and reviewers |
| [`core/`](../core/README.md) | the science kernel, the general base layer: `CORE.yaml`, the kernel (`graph/kernel.yaml`; the kernels of earlier versions in `graph/frozen/kernel-<version>.yaml`, once there are any), its examples, tests and proposals ([how a domain builds on it](../core/graph/README.md)) | the owner and reviewers |
| [`domain/`](../domain/README.md) | the catalysis domain: `DOMAIN.yaml`, the graph schema manifest `graph/scale-graph.yaml` with the catalysis file (frozen versions in `graph/frozen/`, once there are any), examples, competency questions, tests, proposals, docs | the owner and reviewers |
| [`tools/`](../tools/README.md) | the `scale` package (`tools/scale/`), the skills (`tools/skills/`) and the tool tests | the owner and reviewers |
| `docs/` | tool and framework documentation, [decision records](decisions/0001-scale-0.1.0.md), the gap register | the owner and reviewers |
| [`governance/`](../governance/README.md) | governance documents, the review policy, the registries | the owner and reviewers |
| [`releases/`](../releases/README.md) | releases `vX.Y.Z/` (none built yet) | the owner; nothing inside a release is edited |

## Terms

| term | meaning |
|---|---|
| **domain** | a field's layer on the kernel. The catalysis domain is the folder `domain/` (one folder beside the core), declared by its `DOMAIN.yaml` (`domain: catalysis`); the identifiers `DOMAIN.yaml`, `follows_domains`, `--domain` and `scale domains` name domains |
| **catalysis file** | the scale-graph schema file `domain/graph/catalysis.yaml`, keyed `domain: catalysis` and listed under its manifest's `domains:`, that adds the catalysis vocabulary to the kernel and carries the checklist |
| **checklist** | what a record must and should report: the catalysis file's `checklist:`, named after it and followed by documents as `follows_domains: ["catalysis"]` (`--domain catalysis`). Its `when` cases apply items by a record's property; the catalysis checklist keys them on a test's `driving_forces` |
| **graph schema manifest** | `domain/graph/scale-graph.yaml`: the kernel plus the catalysis file. Its `version` is the schema's one version, which documents pin (`graph.schema_version`). "scale-graph" names the format and schema family (`schema: scale-graph`) |
| **schema version** | one number for the kernel and the catalysis domain together: the manifest's `version`. The kernel and the catalysis file carry none; `CORE.yaml`, `DOMAIN.yaml`, `scale-release.yaml` (`schema_version`) and the kernel-only example manifest state it, and every applied proposal raises it |
| **science kernel** | `core/` ("the core" as a folder): the general base layer that every domain builds on |
| **competency question** | a question the catalysis schema must let people ask: a graph query plan, the public examples it runs on and its expected answer (`domain/competency/`, `scale domains cq`) |

## Layers

| layer | artifact | role |
|---|---|---|
| specification | `core/graph/kernel.yaml`, `domain/graph/scale-graph.yaml` and the files it lists | scale-graph: labeled property graphs in node-link JSON. The catalysis manifest assembles the kernel with the catalysis file (with its checklist); earlier versions are frozen beside it in `graph/frozen/`, their kernels in `core/graph/frozen/`, once a proposal has moved the schema on ([how a domain builds on the kernel](../core/graph/README.md)). |
| declaration | `core/CORE.yaml`, `domain/DOMAIN.yaml` | What each layer holds, who maintains it, and the schema's one version; checked by `scale domains check`. |
| competency | `domain/competency/*.yaml` | What the catalysis schema must answer, run on public examples by `scale domains cq` (a step of `scale check`) and re-run by every proposal check. |
| procedure | `tools/skills/*/SKILL.md` | Instructions for people and agents: inputs, allowed tools, outputs, validation, human-review conditions. |
| tool | `tools/scale` (`scale` CLI, agent tools) | Deterministic operations behind the procedures. |
| release | `releases/vX.Y.Z` | Immutable snapshot, with digests, of the kernel declaration, the kernel and its frozen versions, the catalysis declaration, schema manifest, parts and frozen versions, and the skills; the schema's one version, the spec document of every version, the applied proposals it adds with their decision records, contributors and a semantic comparison with the previous release. |

A skill guides a model or person through a task; a tool performs a defined operation. Versioning
both makes procedure and executed behaviour inspectable without tying the framework to one model
provider or agent host.

## Document model

A scale-graph document is node-link JSON ([the kernel and domain schema guide](../core/graph/README.md)):

- **The header** (`graph`) names the schema (`schema: scale-graph`), the schema version it pins, its
  id and title, its `data_status` (`research_data`, `synthetic_example`, `mixed`), the checklists it
  follows (`follows_domains`) and, for research data, its stewardship (who contributed it, which
  project it belongs to, who may see it).
- **Nodes** are `{id, label, props}`; **links** are `{id, source, target, type, props}`. Labels and
  edge types come from the kernel and the catalysis file; a label stands for itself and every label
  that `is_a` it.
- **Values are value objects** `{status, value, unit, …}`. `status` is `present`, `not_reported`,
  `not_measured`, `not_applicable`, `below_detection_limit` or `below_quantification_limit`; a
  `not_reported` value says why (`missing_reason`). The schema performs no unit conversion.
- **Evidence** sits on every node and link that states something: the source, a locator (section,
  figure, table, dataset row), its kind and a short verbatim quote. `REPORTED_IN` links are derived
  from the evidence and checked against it.
- **Context the schema cannot express** goes in a record's `unmodeled` list and is routed as a gap.

The graph indexes relationships and dependencies. Large arrays, spectra and trajectories stay in
their repositories and are referenced by `Dataset` records (`uri`, `sha256`).

## Versions and releases

The schema has one version for the kernel and the catalysis domain together. The schema is at 0.1.0, kernel and
catalysis together; this repository started its numbering there on 2026-10-08 (the work it continues was numbered
elsewhere, and those numbers name other schemas). A document pins its schema version; the catalysis domain keeps
every earlier version frozen beside its manifest once a proposal has moved the schema on, so a document is read
under the version it pins, and `scale graph migrate` moves it along the version steps when someone asks. Applying
a proposal freezes the version it replaces: its manifest and catalysis file in `domain/graph/frozen/` and its
kernel in `core/graph/frozen/kernel-<version>.yaml`, all under the same version. No release has been built yet;
the release process is in [governance/release-process.md](../governance/release-process.md).

A version number names a schema only within this numbering. Each version has a **spec document**, the assembled
schema as canonical JSON (`lineage: scale`) without where or in what state the repository holds it, so its sha256 is
the same whether the version is the head or frozen: `scale graph spec` writes it, a release ships every version's
(`specs/`, listed in `spec_documents`), and `scale graph verify` fails when a version no longer has the digest a
release holds. A reader binds a schema by that digest (`pgraph.identify`; `scale graph spec --expect <sha256>`). A
version number the tools do not hold is reported as unknown (newer than the head, or not a version of this
repository; the graph of a GALAXY bundle, which pins the bundle's own version, is named as one), never assumed to
be another.

## Code map

All modules are in `tools/scale/`.

| module | responsibility |
|---|---|
| `layout.py` | Every repository-relative path in one place: anchors, the catalysis domain's folder `domain/` (its name read from `DOMAIN.yaml`), graph manifests and their frozen directories, proposals across `core/proposals/` and `domain/proposals/` (named by a six-digit number, global; found by id or path; the next number), competency questions, example roots, what the wheel bundles, the kernel a manifest names (`kernel_path`), and the optional restricted copy (`restricted_path`, `locate`). |
| `pgraph_schema.py` | Assemble one scale-graph schema from the kernel and the files the catalysis manifest lists under `domains:` (and, generically, `modules`, `extensions`, `profiles`), with the manifest's one version for every part (a part that states its own is refused); the catalysis file's checklist is a contract named after it; reject duplicate identifiers; extension prefixes from `governance/registry/`. |
| `pgraph.py` | scale-graph documents: choosing the schema manifest (the catalysis manifest, or `--spec`) and its head or frozen version (`graph/frozen/`) by the document's `schema_version`, validation, `describe`, viewer filters, exports; spec documents, their digests and `identify` (is a pinned version and digest this repository's?); the kernel alone at a version (`kernel_only_spec`). |
| `pgraph_profiles.py` | Checklists (must, should, `unless` and `when` cases) of the catalysis file, profile files, and conformance. |
| `pgraph_science.py` | Checks specific to the science kernel. |
| `pgraph_query.py`, `passages.py`, `sourcetext.py` | Queries over scale-graph documents with typed absences; the evidence index and search; source texts for verbatim quote checks. |
| `pagereading.py` | `scale pages`: readings of scanned pages by two readers, page images and positioned OCR words in a local pages folder, the tool's agreement of each reading with OCR in its region, independent second readings, and the check that every value read from an image is in a transcription or quote. |
| `pgraph_migrate.py` | Move scale-graph documents along the version steps of the catalysis schema. |
| `pgraph_proposal.py` | Schema change proposals on the catalysis manifest (`scale proposal new` scaffolds one): from curation gaps to a candidate (repository-relative paths), the semantic diff and its tier, checks (the target raises the one version), decision record and apply (freezing the base version: its kernel into `core/graph/frozen/kernel-<v>.yaml` and the catalysis domain's manifest and file into its `graph/frozen/`, appending digests to each `SHA256SUMS`, which `scale graph verify` checks; and raising the one version in every file that states it). |
| `review.py`, `policy.py` | Approval records from a merged pull request's GitHub reviews and the PR body; the review policy (`governance/review-policy.yaml`): one approving reviewer other than the author, placeholders never counted, Tier 1 record samples. |
| `apply_merged.py` | `scale proposal apply-merged`: after a merge, evaluate the reviews, record them, decide, apply and run the full `scale check` (the unit tests included), all or nothing (the apply-proposals workflow). |
| `kg.py` | `scale kg update`: move every catalysis scale-graph document in a data repository to a new schema version, validate it and rebuild its evidence index. |
| `competency.py` | Competency questions: run each graph query plan on its public examples and compare the answer with its expectation (`scale domains cq`). |
| `domains.py` | `scale domains list | check`: the `CORE.yaml` and `DOMAIN.yaml` declarations, the one version every file states, imports, one identifier index over the kernel and the catalysis files, competency questions, stewardship targets, CODEOWNERS lines; `new_domain()` scaffolds a synthetic domain as `domain/` of a test repository from `tools/tests/fixtures/domain-template/`. |
| `releases.py`, `versions.py` | Release builds from the head (graph-only, with every version's spec document), the gate on applied proposals and on the one version, the semantic comparison with the previous release, verification, the stability of released spec digests; version constraints and release ids. |
| `ci.py`, `codeowners.py` | `scale ci spec-changes`: what a pull request changed under `releases/` and in the specifications, whether a proposal or decision record covers it, and which owners must review; a small CODEOWNERS evaluator (the last matching pattern wins). |
| `gaps.py` | Gap reports from query results, their classification, GitHub issue rendering and dry-run or real submission. |
| `galaxy.py` | GALAXY knowledge-graph bundles from scale-graph documents: the schema named by version and spec digest, the graph's header and stewardship in `scale_header`, only what the bundle's audience may see. |
| `intake.py` | Community feedback: ingest, cluster, propose, record decisions (`scale triage`); record catalogues with comment links. |
| `api.py`, `mcp_server.py`, `http_server.py`, `updates.py` | The agent tool surface (`scale call`), over MCP and local HTTP; the newer-tool check. |
| `devcheck.py`, `style.py` | `scale check` (every check of CI's `test` jobs); formats, names, links (`scale fmt`, `scale lint`, `scale links`). |

## Principles the code enforces

- **The reported value is never replaced.** There is no implicit unit or scale conversion; a query
  filter compares values only in the unit it states and lists the rest as left out.
- **Missingness has a reason.** `not_reported` ≠ `not_measured` ≠ `not_applicable` ≠
  `below_detection_limit` ≠ a measured zero; a `not_reported` value says whether the source is
  silent, ambiguous, or the curator did not look.
- **Evidential status is explicit.** Reported, curated, derived, hypothesized and synthetic records
  stay distinguishable (`origin`), and a synthetic record inside research data is invalid.
- **Curation never changes the schema.** Context the schema cannot express goes to a record's
  `unmodeled` list and becomes a gap.
- **Absences are answers.** A query says whether it answered, found nothing, lacked context, or
  asked for something the schema cannot express.
- **Releases and frozen versions are immutable.** A document pins its schema version; moving it to
  a newer one is explicit. One version names the whole schema, kernel and catalysis together.
- **Agents propose; people approve** ([review-policy.yaml](../governance/review-policy.yaml)). Every change needs one
  approving review from a reviewer other than its author once a reviewer besides the owner has joined (the owner
  merges under the bootstrap rule until then); new concepts enter as provisional; a merged proposal is applied by a
  workflow a person starts, which checks those reviews again.
- **Formats by author:** machine-written documents are canonical JSON; human-written specifications are block-style
  YAML ([style.md](style.md)).
