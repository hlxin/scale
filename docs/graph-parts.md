# A graph kept as one part per source

A graph that grows one publication at a time is kept in its folder as **parts**: one file per source, one file of
shared records and a header. A contribution adds or changes one source's file, so contributions do not collide, a
reviewer checks one source against its text, and a source can be recurated, replaced or removed on its own. Tools
read the folder as the one graph its parts build.

```
<graph folder>/
├── parts/
│   ├── header.json            the graph's own object: id, title, description, schema version, stewardship
│   ├── shared.json            the records several sources refer to (species, reactions, people, institutions)
│   └── sources/<slug>.json    one source: its Source record, every record it alone states, and their links
└── <folder>.graph.json        the built graph (scale graph build), when a copy is wanted
```

## Which record goes where

- **A source's records** are its Source record (`<ns>/source/<slug>`) and every record whose id starts with
  `<ns>/<slug>/`: its catalysts, samples, tests, conditions, claims.
- **Shared records** are all others. Sources refer to them by id (`ex:msyn/species/zno`), and that shared id is
  what connects the sources in the built graph: 39 of the 55 sources of the public methanol example point to the same ZnO.
- **A link** goes with the source of its first endpoint that belongs to one; a link between two shared records is
  shared. A link between the records of two sources has no part yet and is refused.
- **Every part states the schema version** it follows, which must be the header's.

## Commands

```bash
scale graph split G.graph.json --out DIR             # DIR/parts/ from a document
scale graph split G.graph.json --out DIR --sources @list.txt   # only these sources and what they reach
scale graph build DIR                                # DIR/<DIR>.graph.json, every node and link sorted by id
scale graph build DIR --check                        # the parts build, and a built copy is current
scale graph validate DIR                             # any command reads DIR as the graph it builds
```

`build` is deterministic, and it refuses a record in the wrong part, an id used twice, a part at another schema
version or a link to a record no part holds. Splitting a graph and building it back gives the same document: the
public methanol example (55 sources) does, and so does the full methanol graph (105 sources, 261 shared records,
[`graphs/methanol-synthesis-pre1966/`](../graphs/methanol-synthesis-pre1966/README.md)).

A subset (`--sources`) keeps the sources named, the shared records they reach (through their links, then through
links between shared records) and those the header names, and keeps in shared records only the evidence of those
sources. [`examples/methanol-synthesis-public/`](../examples/methanol-synthesis-public/README.md) is such a subset.

## Next

The skills that find, download and curate sources for the commons (`graphs/catal-commons/`); merging graphs into
bundles, once the commons and a few more graphs are curated; a registry of shared records with a check for near-duplicates
(`dreyfus-henry` and `dreyfus-hnnry` are both in the methanol graph today); and a file for links between sources
(one source confirms or contradicts another).
