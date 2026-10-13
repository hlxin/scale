# Catal commons

SCALE's evolving catalysis graph. It starts empty (its steward and project only) and grows one source at a time:
each pull request adds `parts/sources/<slug>.json`, the source's entry in `rights.yaml` and, where it reaches
species, reactions or people the graph already holds, links to them in `parts/shared.json`. Agents will grow it
with spare compute; the skills and the workflow for that come later.

## Adding a source

1. Curate the source with the `curate-source` skill into a scale-catal document (`ns` `scale:commons`: the source is
   `scale:commons/source/<slug>`, its records `scale:commons/<slug>/...`), reusing the ids of the shared records
   already here (`parts/shared.json`).
2. Record its rights in `rights.yaml` (class, licence, basis, text_chars). A source in copyright keeps no quoted
   text: `scale evidence cap <doc> --rights graphs/catal-commons/rights.yaml --output <doc>` withholds it.
3. Add it as parts: `scale graph split <doc> --out <scratch>`, then copy its `sources/<slug>.json` here and merge its
   new shared records into `parts/shared.json`.
4. `scale graph validate graphs/catal-commons` (0 errors) and `scale check`, then open the pull request.

Rules for every graph here: [../README.md](../README.md).
