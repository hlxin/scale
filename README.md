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

**Or in the browser: [the graph explorer](https://hlxin.github.io/scale/).** Pick one of the curated graphs (or
open a graph file) and see it whole, filter it by label or relationship type, open any node with its verbatim
evidence, search the evidence, and explore its data (counts, degrees, numeric properties plotted). SCALE's own code
runs in the browser (Pyodide), so a search or a plan gives the rows `scale graph search` and `scale graph query` give.
With the web service ([`service/`](service/README.md)), signed in with GitHub and with no API key of your own:
**Curate** a paper (a PDF or a DOI) into a graph, ask questions in plain language, and contribute a graph to
catal-commons in one click (a pull request a person reviews). Contributors are credited on a leaderboard. The page is
built by `scale site build` and published by GitHub Pages ([`site/`](site/)).

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
- **A real, fully open example** ([`examples/methanol-synthesis-public/`](examples/methanol-synthesis-public/README.md)):
  55 public-domain sources on methanol synthesis from CO/CO2 and H2 published before 1966, with their PDFs and page
  texts and every quote in full, kept as one part per source, with the manuscript's questions as query plans. The
  tests run on it.
- **Graphs** ([`graphs/`](graphs/README.md)): the graphs SCALE curates and shares, each source quoted only as far as
  its rights allow: catal-commons, an evolving graph grown one source at a time, and the methanol-synthesis
  graph (105 sources before 1966, no quoted text of a source in copyright).
- **Tools** ([`tools/`](tools/README.md)): the `scale` Python package and command, the agent skills and their
  tests.
- **The site** ([`site/`](site/)): the graph explorer (the repository's graphs, searched and queried in the browser
  with the `scale` package) and, with the web service ([`service/`](service/README.md)), one publication into a graph.
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

The schema is at **0.8.0**; 0.1.0 (2026-10-08) was the first version of this repository's numbering. The schema was
named `scale-graph` until 0.1.0 and is `scale-catal` from 0.2.0 on (a breaking change: documents pin the name):

| version | spec digest (sha256 of the spec document) |
|---|---|
| scale-graph 0.1.0 (frozen) | `3c2fa7205a7bae5e0bbfa7d87826ff7ab7803e78536129064101c7d5a2c02006` |
| scale-catal 0.2.0 (frozen) | `166bfc5539df7f44de075a4fb504c54170af32d6b3a01a916d6171bfcecec714` |
| scale-catal 0.2.1 (frozen) | `f14b9a0146e5c42cd1ec573d3695fc517ffa8b9042ff062da64853f6e188fb09` |
| scale-catal 0.3.0 (frozen) | `46983cc2151b46cb7fcd5ec15ee9b4b6168cfc22d083fade48895a0de75aa4e1` |
| scale-catal 0.4.0 (frozen) | `c747fbb6308d0c404076b1a23b2f8d992d8659101cbfb3d101d7235ee7b2dba3` |
| scale-catal 0.5.0 (frozen) | `704a4b511ac841c8e0254b25530c5172f4945b9268a8dcb34e7c088d85419b58` |
| scale-catal 0.5.1 (frozen) | `4a95e26b4f8c65c30c0a0657c6cd40134bd98dce41be941dd597d035907f8a53` |
| scale-catal 0.5.2 (frozen) | `753659c27dfbe30c7946f3915b06474cc14275cdc04c75cd8e5672e8183e6207` |
| scale-catal 0.6.0 (frozen) | `19dec18ed1b90cdd13f695c2da6ba5401b1054ac90f1b94925ca930a6c565035` |
| scale-catal 0.7.0 (frozen) | `37dc3aa00f769f4282173211830eab40b18015e54731ab189554e60e8895c2be` |
| scale-catal 0.7.1 (frozen) | `b4ffe60d58b717196cf729b5806941b7cfc3b9337fc5c7c281b22e36591c706f` |
| scale-catal 0.7.2 (frozen) | `dfe75643daf531d2a18e0c9d87187eab99965115e1801814d4a5c4053d6706ce` |
| scale-catal 0.7.3 (frozen) | `9a130df582c6696b4d6a302a84c1d44d6f2eaa90ff6886c9ecd76822f7d6c27d` |
| scale-catal 0.7.4 (frozen) | `6d266815385765e2f3cbc7b81ccc433ba9b9d65ba58cfc1438025b7ab7ff6533` |
| scale-catal 0.7.5 (frozen) | `704b56a2c8baa40d21b4521fc1cbc4e9aca5530e85d04db2be0995351dcc4d63` |
| scale-catal 0.7.6 (frozen) | `08d1813af14e741874046a47ebeef1309fbc5c5e3f1826ddfaf0c4471e6620fb` |
| scale-catal 0.7.7 (frozen) | `ca78352410ccc5fadc4ebec58c62f074c2e8b46164a0139ed723768ff7f0c286` |
| scale-catal 0.7.8 (frozen) | `135f9a2b5a5d238b91d733a119516ba67b72863cf117d99b854a22cff4507c1e` |
| scale-catal 0.7.9 (frozen) | `80e8f6aa02446a8af7f172422041851b684cfa951d69debc1973c94aa8b013e8` |
| scale-catal 0.8.0 | `7cc40d129e77e771254a5b48576b1f0c4f239bc3d7ccbc63adc200bb4eff749b` |

A version number only means something within this repository, so identify a schema by its digest
(`scale graph spec` prints it).

**Documents from the earlier contents of github.com/hlxin/scale.** This repository replaced them (its own
scale-graph numbering 0.1.0-0.8.0, package scale-catalysis); versions here restart at 0.1.0 and are a separate
line. Re-curate documents from there; do not validate them as they are.

## Contribute

Every change is one pull request. Anyone can suggest a change in an issue or a comment
([comment form](https://github.com/hlxin/scale/issues/new?template=comment.yml),
[contribution form](https://github.com/hlxin/scale/issues/new?template=contribution.yml)) or open a pull request.
`@scale-agents` pick up collaborators' issues, comments and reviews on their own (anyone else's once a collaborator
comments on it) and prepare the pull request. One
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
[Curation](docs/curation.md) · [Querying](docs/querying.md) · [Schema evolution](docs/evolution.md) · [Mappings to ontologies](docs/mappings.md) ·
[The catalysis domain](domain/README.md) · [The science kernel](core/graph/README.md) · [Tools](tools/README.md) ·
[Governance](governance/README.md) · [Changelog](CHANGELOG.md)

## Licence and citation

Code is under the MIT licence ([LICENSE](LICENSE)); the vocabulary, curated records and documentation are under
CC-BY-4.0. [REUSE.toml](REUSE.toml) gives every file its licence; third-party material is listed in [NOTICE](NOTICE).

Records quote sources only in short, capped excerpts. Only public documents are committed; project data not
cleared for publication never is ([governance/licensing.md](governance/licensing.md)). To cite SCALE, see
[CITATION.cff](CITATION.cff).
