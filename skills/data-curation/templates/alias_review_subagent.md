# Alias review — which near-duplicate nodes are the same entity?

The deterministic merge already unified nodes with identical ids. This pass catches the duplicates it missed:
- **Lexical variants** — spelling, separator or case (`Catalyst:cunanocubes` vs `Catalyst:cu-nanocubes`); listed in
  the candidate clusters below.
- **Semantic synonyms** — an acronym, its written-out form and other names the field uses for ONE entity. They share
  no prefix, so they are not in the clusters: find them among the high-degree hub nodes.

## Inputs
- Candidate clusters (lexical, same label): `{{CLUSTERS_PATH}}`
- Hub nodes per label (highest degree; scan these for semantic synonyms): `{{HUBS_PATH}}`
- Schema (labels, never-merge rules): `{{SCHEMA_PATH}}`

## How to decide
- Merge only members that denote the **same real-world entity**, within ONE label (two labels are never one node).
- **Never merge things the domain treats as distinct** — the schema's `never_merge` rules apply strictly:
{{NEVER_MERGE}}
  Always distinct as well: entities differing only in a stated output (a process making A vs making B); a species and
  its charged/protonated form; the same material at different loadings, supports, facets, sizes or treatments.
- Choose the cleanest canonical id (standard name, lowercased slug).
- When unsure, do NOT merge: a false merge corrupts provenance; a missed merge only leaves a duplicate.

## Output — write to `{{OUTPUT_PATH}}`
```json
{"merges": [{"canonical": "Catalyst:cu-nanocubes", "aliases": ["Catalyst:cunanocubes"], "reason": "same material, separator variant"}]}
```
Only the merges you want; `{"merges": []}` is a valid answer. Use only `Read` and `Write`.

## Report (under 150 words)
For each merge: canonical, number of aliases, one-line reason; and clusters deliberately left unmerged, with why.
