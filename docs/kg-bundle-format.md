# Knowledge-graph bundles (kg-bundle format)

SCALE writes a scale-graph document as a **knowledge-graph bundle**: a self-describing folder, shipped as one zip,
that a platform reading this format can load and display without SCALE. SCALE follows the format as published by
its maintainers; it neither defines nor endorses any platform that reads it. The scale-graph document stays the
lossless original; a bundle is an export of it.

## What a bundle holds

```
<bundle_id>_v<version>/
├── bundle.json        manifest: format and version, bundle id and version, previous release, counts, corpus, scale_header
├── CHANGELOG.md       one "## <version>" entry per release
├── SHA256SUMS         digest of every file except itself and validation.json
├── validation.json    the format validator's report for this exact bundle (written when it seals the bundle)
└── kg/
    ├── schema.json    the bundle schema: node and edge types, typed properties, `extends` naming scale-graph
    └── graph.json     the graph, node-link JSON
```

A source text ships under `text/` only when its licence allows redistribution (`--text ID=FILE:LICENCE`). The zip is
named `<bundle_id>_v<version>.zip` with the folder at its top.

## Format version 1.1.0

SCALE writes format **1.1.0** (the identifier the format requires in `bundle.json` is `FORMAT_ID` in
`tools/scale/kgbundle.py`). Beyond 1.0.0 it carries the two things SCALE's rules need:

- **Withheld quotes.** Evidence whose quote is withheld under SCALE's copyright cap is `quote_withheld`: the sha256
  and length of the quote under `scale-match-text-1` (SCALE's verbatim normalization, `match_text` in
  `tools/scale/util.py`), with its source and locator. A reader holding the source finds and checks the passage; no
  text is shipped. A link whose quotes are all withheld stays an edge.
- **Typed absences.** A value the source does not report, did not measure, or gives below a limit is a
  `_value_status` entry (status and, for `not_reported`, the reason), not a missing property.

The bundle schema names scale-graph by version **and** spec digest (`extends`), so two bundles of one schema can be
recognized as such.

## Making, checking and loading one

```bash
scale graph export G.json --to kg-bundle --out DIR --bundle-id ID --version 1.1.0 \
    --previous PREVIOUS_BUNDLE_DIR --corpus sources.json      # --previous: ids kept, the release it follows recorded
```

The export seals the folder (SHA256SUMS) and prints its report: what was converted, what could not be carried
(intervals, replicates, notes, a detection limit), what was withheld for the bundle's audience. Check the folder
with the format's validator (`bundle_validate.py`, with `--previous` for a later release, then `--seal`), and zip
it. The tests run the validator when `SCALE_BUNDLE_VALIDATOR` names that file. Any platform that reads the format
loads the zip as it is: the first release as a new graph, each later release as an update of it, in order.

The mapping from scale-graph to the bundle (ids, units, evidence, statements, access) is described in the module
docstring of `tools/scale/kgbundle.py`, and the export skill (`tools/skills/export-graph/SKILL.md`) says when to choose
a bundle over the native document.

## Bundles in this repository

| bundle | version | graph | edges | notes |
|---|---|---|---:|---|
| [`methanol-synthesis-pre1966_v1.1.0.zip`](../examples/methanol-synthesis-pre1966/methanol-synthesis-pre1966_v1.1.0.zip) | 1.1.0 | the methanol example | 17,563 | follows 1.0.0 (git history at `a169872`); 3,274 substantive edges rest only on withheld quotes; 227 typed absences |
