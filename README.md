# SCALE

**Shared Concepts, Attributes, and Links with Evidence: one shared framework for evidence-backed scientific
knowledge graphs across domains.**

SCALE is a schema, tools and agent skills for building knowledge graphs in which every record
stays linked to its evidence.

- **Concepts** are the kinds of nodes, edges, properties and values.
- **Attributes** are the properties of nodes and edges.
- **Links** are typed, directed edges.
- **Evidence** is a source, a locator and a short verbatim quote. Every node and edge that states something
  carries it.

People and AI agents curate sources into graphs and query them. Every value keeps its source, its reported unit
and its quote.

The schema has two layers. The **science kernel** holds what all sciences share: questions, hypotheses,
experiments, claims, sources, people. **Domains** build on it. **Catalysis** is the first and, for now, only
domain: thermal, electro-, photo- and plasma catalysis, and their combinations.

## Use it

```bash
pip install git+https://github.com/hlxin/scale
```

Then `scale call status` to start, or `claude mcp add scale -- scale mcp` to give an AI agent the tools
([docs/integrate.md](docs/integrate.md), [AGENTS.md](AGENTS.md)).

## What's inside

- **The science kernel** ([`core/`](core/README.md)): the base layer shared by all sciences, with the value
  object, the evidence item and record references ([how a domain builds on it](core/graph/README.md)).
- **The catalysis domain** ([`domain/`](domain/README.md)):
  - `catalysis.yaml`: species, materials, reactions, catalysts and the terms for each driving force (heat,
    electrical heating, potential, light, plasma). [`domain/graph/scale-catal.yaml`](domain/graph/scale-catal.yaml)
    joins it with the kernel. Its checklist says what a record **must** and **should** report; the items for a
    catalytic test depend on the driving forces the test lists. A document follows it with
    `follows_domains: ["catalysis"]`. Every concept is provisional.
  - competency questions: query plans with their expected answers, run on public examples (`scale domains cq`);
  - [synthetic examples](domain/examples/scale-catal/) with invented values, one per driving force and
    combination.
- **A real example** ([`examples/methanol-synthesis-pre1966/`](examples/methanol-synthesis-pre1966/README.md)):
  105 sources on methanol synthesis from CO/CO2 and H2 published before 1966, curated into one graph with short
  quotes. The tests run on it.
- **A fully open example** ([`examples/methanol-synthesis-public/`](examples/methanol-synthesis-public/README.md)):
  its 55 public-domain sources, with their PDFs and page texts and every quote in full, kept as one part per source.
- **Tools** ([`tools/`](tools/README.md)): the `scale` Python package and command, the agent skills and their
  tests.
- **Governance** ([`governance/`](governance/GOVERNANCE.md)): who reviews, how changes are approved, versions and
  releases.
- **Releases** ([`releases/`](releases/README.md)): fixed, digested releases built by a person; the first
  is `v0.1.0`.

There is one data format: scale-catal documents (node-link JSON), each naming the schema version it follows.
Your model does the judgement work, such as extracting values and writing queries; SCALE's tools are
deterministic. Queries decline rather than guess. See the [implementation status](docs/implementation-status.md)
and the [architecture](docs/architecture.md).

## Schema versions

The kernel and the catalysis domain share **one version number**, set in `domain/graph/scale-catal.yaml`.
`core/CORE.yaml`, `domain/DOMAIN.yaml` and `scale-release.yaml` repeat it, and `scale domains check` makes sure
they agree. Every schema change raises it: the second number for a breaking change, the third for an additive
one. The old version is frozen in `graph/frozen/`, so a document stays readable under the version it names.

The schema is at **0.2.0**; 0.1.0 (2026-10-08) was the first version of this repository's numbering. The schema was
named `scale-graph` until 0.1.0 and is `scale-catal` from 0.2.0 on (a breaking change: documents pin the name):

| version | spec digest (sha256 of the spec document) |
|---|---|
| scale-graph 0.1.0 (frozen) | `3c2fa7205a7bae5e0bbfa7d87826ff7ab7803e78536129064101c7d5a2c02006` |
| scale-catal 0.2.0 | `166bfc5539df7f44de075a4fb504c54170af32d6b3a01a916d6171bfcecec714` |

A version number only means something within this repository, so identify a schema by its digest
(`scale graph spec` prints it).

**Documents from the earlier contents of github.com/hlxin/scale.** This repository replaced them (its own
scale-graph numbering 0.1.0-0.8.0, package scale-catalysis); versions here restart at 0.1.0 and are a separate
line. Re-curate documents from there; do not validate them as they are.

## Contribute

Every change is one pull request. Anyone can suggest a change in an issue or a comment
([comment form](https://github.com/hlxin/scale/issues/new?template=comment.yml),
[contribution form](https://github.com/hlxin/scale/issues/new?template=contribution.yml)) or open a pull request.
`@scale-agents` pick up every new issue, comment and review on their own and prepare the pull request. One
reviewer approves and merges it; this may be the person who suggested it. Agents never approve or merge.

A schema change edits the schema files directly and raises the version in the same pull request
(`scale schema bump`, checked by `scale schema check`). See [CONTRIBUTING.md](CONTRIBUTING.md) and
[governance/GOVERNANCE.md](governance/GOVERNANCE.md).

## Develop

```bash
git clone https://github.com/hlxin/scale && cd scale && uv run --extra dev scale check
```

This sets up the environment and runs every check CI runs. Add `--fast` to skip the tests.

## Documentation

[Commands](docs/commands.md) · [Using SCALE with agents](docs/integrate.md) · [Architecture](docs/architecture.md) ·
[Curation](docs/curation.md) · [Querying](docs/querying.md) · [Schema evolution](docs/evolution.md) ·
[The catalysis domain](domain/README.md) · [The science kernel](core/graph/README.md) · [Tools](tools/README.md) ·
[Governance](governance/README.md) · [Changelog](CHANGELOG.md)

## Licence and citation

Code is under the MIT licence ([LICENSE](LICENSE)); the vocabulary, curated records and documentation are under
CC-BY-4.0. [REUSE.toml](REUSE.toml) gives every file its licence; third-party material is listed in [NOTICE](NOTICE).

Records quote sources only in short, capped excerpts. Only public documents are committed; project data not
cleared for publication never is ([governance/licensing.md](governance/licensing.md)). To cite SCALE, see
[CITATION.cff](CITATION.cff).
