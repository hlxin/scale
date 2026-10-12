# Graphs

The knowledge graphs SCALE curates and shares. `examples/` holds worked examples
that anyone can reproduce from their files; `graphs/` holds the graphs that grow.

| folder | what it is |
|---|---|
| [`catalysis-commons/`](catalysis-commons/README.md) | SCALE's evolving catalysis graph, grown one source at a time through pull requests (empty so far) |
| [`methanol-synthesis-pre1966/`](methanol-synthesis-pre1966/README.md) | methanol synthesis from CO/CO2 + H2, literature published before 1966: 105 sources |

## A graph here

Every graph is a folder kept as parts ([docs/graph-parts.md](../docs/graph-parts.md)), so that adding a source adds
one file and never collides with another contribution:

| file | content |
|---|---|
| `parts/header.json` | the graph's own object: title, description, schema version, default stewardship |
| `parts/shared.json` | the records several sources refer to: species, reactions, people, institutions |
| `parts/sources/<slug>.json` | one source: its Source record, every record it alone states, and their links |
| `rights.yaml` | each source's rights: its class (public domain, open, in copyright), licence and basis |
| `sources.json` | the corpus: every candidate source with its status (when the graph has one) |
| `stewardship.yaml` | who curates the graph, for which project |

Tools read the folder as one graph: `scale graph validate graphs/<name>`, `scale graph query graphs/<name> PLAN`.

## Each source's rights are respected

- **No source texts.** No PDF or text of a source in copyright is committed; a public-domain source's PDF may be
  (`examples/methanol-synthesis-public/pdfs/`).
- **No quoted text of a source in copyright.** Every `rights.yaml` here sets `limits: {quote_chars: 0,
  source_chars: 0}`: a quote from a source in copyright (or one whose rights are unknown) is withheld, kept only as
  its sha256 and length with its locator, and anyone who holds the source restores it (`scale evidence
  rehydrate`). Public-domain and openly licensed sources are quoted in full. `scale check` enforces it (`scale
  evidence report --all`).
- **Facts in our own words.** Records state values, conditions and claims; a claim is written in the curator's own
  words, never copied.
- **Public only.** Every record is `access: public`; project data not cleared for publication is never committed.

The records themselves are CC-BY-4.0 ([governance/licensing.md](../governance/licensing.md)).

## Not yet

- The improved skills for finding, downloading and curating sources, and the agents that grow the commons with spare
  compute; until then a source is added by a pull request following the `curate-source` skill.
- Merging graphs into bundles, and how the community shares and reuses graphs legally: settled once the commons and
  a few more graphs are curated.
