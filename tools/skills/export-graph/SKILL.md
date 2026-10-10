---
name: export-graph
version: 0.1.0
description: Hand a scale-graph document to another system — validated under the public schema it pins, its quotes within the copyright cap, filtered for the audience that will see it, as the native document or as a kg-bundle whose losses are read and stated, with texts shipped only under a stated licence, sealed and linked to its previous release.
scale_release: ">=v0.1.0"
inputs:
  - A scale-graph document (it pins its schema version)
  - The audience the export is for (the public, a project, an institution) and the system that will read it
  - For a later release, the previous release's bundle folder
allowed-tools:
  - "scale graph validate <doc> [--source-text <id>=<file>]"   # under the version the document pins
  - "scale graph spec --version <v>"                           # the digest a reader binds the schema by
  - "scale evidence report | cap <doc>"                        # quotes within each source's cap
  - "scale evidence access <doc>"                              # what is public
  - "scale graph filter <doc> --as <id> | --public"            # what the audience may see
  - "scale corpus check <manifest>"                            # the frozen corpus, for the bundle's corpus block
  - "scale graph export <doc> --to kg-bundle --out <dir> [--public | --as <project id> | --as <institution id> ...] [--version <v>] [--previous <dir> | --ids-from <dir>] [--replaced <file>] [--corpus <manifest>] [--text <id>=<file>:<licence>]"
  - write access to the working directory only
outputs:
  - The exported document or bundle (sealed, with SHA256SUMS), for the stated audience
  - The export report (what was converted, kept as text, left out, withheld or inferred) and a short statement of the losses for the receiver
validation:
  - "`scale graph validate` reports zero errors under the schema the document pins, a version this repository holds"
  - "`scale evidence report` lists no source beyond its cap in what is exported"
  - The export declares the audience it is for (scale_header.stewardship) and holds nothing that audience may not all see (no access_at_export.less_open_kept, no access_warning naming another audience)
  - A later release names its previous release, keeps its ids and lists retired ids on their survivors
human-review:
  - Always before an export leaves its owners: a person decides who receives it and where it is published
  - Whenever the export is not public (access_warning), and before any text ships under text/
---

# Export a scale-graph document to another system

SCALE assumes nothing about the receiving system. A native scale-graph document is lossless; a
knowledge-graph bundle (kg-bundle format) is a node-link folder other platforms can load, and it loses what that format
has no place for. Either way the export is valid, capped, filtered for its audience, and says what it
lost.

## Procedure

1. **Validate under the public schema the document pins:** `scale graph validate <doc>` with zero
   errors. A document pinning a version this repository does not hold is refused by validate and by the
   export: never relabel its version (a number names a schema only within one numbering). A receiver binds
   the schema by its digest
   (`scale graph spec --version <v>`; the kg-bundle's `extends.sha256`), not by the number alone.
2. **Cap the quotes:** `scale evidence report <doc>`; if a source is beyond its cap, `scale evidence cap
   <doc> -o <capped>` withholds the texts that do not fit (with their digests), and you export the
   capped document.
3. **Filter for the audience:** `scale graph filter <doc> --public` (or `--as <project or institution
   id>`) keeps only what that audience may see under each record's stewardship. The kg-bundle export
   declares its audience in `scale_header.stewardship`: the graph's stewardship by default, the public
   with `--public`, or the viewer's own with `--as`, which takes one project id or one or more
   institution ids (a person, several projects or a mix is refused: for a person, export for their
   institution). It withholds records part of that audience may not see and warns (`access_warning`)
   when the bundle is not public; such a bundle goes to no person, host or model outside that audience.
   Never use `--keep-less-open` for a bundle that leaves its owners: a bundle that kept such records
   counts them in `access_at_export.less_open_kept`, each goes only to its own audience
   (`scale_access`, `scale_access_project`, `scale_access_institutions`), and the bundle as a whole only
   to those who may see every record in it.
4. **Choose the form:**
   - **native** — the scale-graph document itself: value objects, typed absences with their reasons,
     ranges and bounds, the source lifecycle, evidence with passages and readings. The receiver
     should validate it with `scale graph validate` and answer with SCALE's query rules. Choose it
     when the receiver must report missing context or retractions.
   - **kg-bundle** — `scale graph export <doc> --to kg-bundle --out <dir>`: read the `export_report`
     (`values_as_text`, `not_exported_links`, `absences`, `withheld_too_long`, `statement_inferred`,
     `bounds`, `approximate_values`, `access`, `withheld_less_open`, whose `evidence_cut` counts the kept
     records that lost evidence of a withheld source, whose values without `evidence_ids` are withheld
     in their place) and tell the receiver what the
     bundle cannot carry (intervals, replicates, notes, a detection limit; the module docstring of
     `tools/scale/kgbundle.py` lists them).
5. **Ship texts only under a stated licence:** `--text <publication id>=<file>:<licence>` for a source
   whose licence allows redistribution (a US patent, an open licence), never a text you may only quote.
6. **Seal and link the release.** The export writes SHA256SUMS. A later release names its predecessor
   and keeps its ids: `--previous <previous bundle folder> --version <later version>`; records merged
   since are listed on their survivors with `--replaced <map of retired id to survivor id>`; an earlier
   build whose ids to keep without recording it as the previous release is `--ids-from`. The corpus
   block comes from the frozen manifest: `--corpus <manifest>` after `scale corpus check <manifest>`.
7. **Hand over** the folder, its export report and your statement of the losses to the person who
   decides where it is published. Publishing, uploading and releasing are their actions.

## Rules

- Never export a document that does not validate under the version it pins, or one pinning a version this
  repository does not hold.
- Never export records to an audience their stewardship does not admit; a filtered export says so.
- Never ship a text whose licence is unknown or does not allow redistribution.
- Never edit a released bundle: a correction is a new release with `--previous`.
- Synthetic examples are exported with their `synthetic_example` status visible (the bundle's topic
  and scope say so); never present them as research data.
