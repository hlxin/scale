---
name: curate-dataset
version: 0.1.0
description: Turn a data table or a lab file into a scale-graph document under the schema version it pins — the file as a Dataset with its digest, column dictionary and licence, every record citing its row, values in the file's units with their origin, and the stewardship access its owners set — recording gaps instead of changing the schema.
scale_release: ">=v0.1.0"
inputs:
  - A data file (CSV, a spreadsheet exported to CSV, a JSON or text export of an instrument or a lab notebook)
  - Its column dictionary (what each column means, its unit, how missing values are written), from the file's owners
  - Who owns the data and who may see it (the project and the access level they set)
  - The checklist the document follows (catalysis: the catalysis schema and its one checklist)
allowed-tools:
  - "scale graph describe [labels] --domain <domain>"   # the labels and edges you may use, with the checklist
  - "scale call template '{\"domain\": \"catalysis\"}'"  # a valid starting document
  - "scale graph validate <doc> --source-text <dataset id>=<file>"   # rows quoted verbatim from the file
  - "scale graph filter <doc> --as <id> | --public"     # what each audience may see
  - "scale evidence access <doc>"                       # before anything is committed to the public repository
  - read access to the data file; write access to the working directory only
outputs:
  - A scale-graph document with a Dataset for the file and records citing its rows
  - The validation report (errors, warnings, checklist conformance)
  - Gaps for columns the schema cannot express (missing_concept) and values the file does not give
validation:
  - "`scale graph validate <doc> --source-text <dataset id>=<file>` reports zero errors"
  - The Dataset's sha256 is the digest of the file that was read
  - Every record and link that states something cites a row (evidence kind dataset_row, a locator naming the row and column)
  - Every value is in the file's unit, with the column's stated meaning, and every empty or flagged cell has a typed absence
human-review:
  - Always, by the data's owners, before the document is shared beyond them
  - Whenever a column's meaning, unit or basis is inferred rather than stated in the column dictionary
  - Whenever the document would change its access (filtered for another audience, or committed anywhere)
---

# Curate a data file into a scale-graph document

A data file is a source like a paper, with two differences: its rows are the evidence, and its owners,
not a publisher, decide who may see it. The schema defines what a completed record means; the file
and its column dictionary determine which parts can be populated.

## Procedure

1. **Describe the file as a Dataset.** `data_kind` (`table`, `raw`, `processed`, `time_series`, …),
   `availability`, `version`, `uri` (where it lives), `sha256` (of the exact file read), `media_type`,
   `data_schema` (the column dictionary: each column, its meaning, unit and how a missing value is
   written; or where that dictionary is and its digest) and `licence`. A published dataset may also be
   reported in a Source (its data paper): give the Dataset an evidence item citing that Source (`source`,
   a `locator` such as its data availability statement, a short `quote`), and derive its `REPORTED_IN`
   link from that evidence, as for any other record; a `REPORTED_IN` link that no evidence item backs
   is a validation error.
2. **Set the stewardship.** The graph header's `stewardship` names who contributed it
   (`contributed_by`), the `project` and the `access` its owners set (`project`, `institution`,
   `consortium`, `embargoed` with its date, or `public` only when they cleared it). Project data stays
   in the project's own data repository, never in the public one. Do not
   fill `curated_by`: SCALE records no curator attribution.
3. **Map the columns** to labels and properties with `scale graph describe <Label> --domain
   catalysis`: a row is usually a run (a CatalyticTest, a Characterization) with its catalyst sample,
   feed and reactor; repeated entities (one catalyst in many rows) are one record. A column the schema
   cannot express goes in the records' `unmodeled` list and is raised as a gap; never invent a
   property.
4. **Write the values** in the file's units, as the column dictionary defines them: `origin: measured`
   for a measurement, `origin: assumed` for a set or nominal value, `computed` or `derived` (with
   `produced_by`) for a value the file computed. A unit the dictionary does not state is `"not
   stated"` with a note: a placeholder, not a unit, which queries leave out as `unit_unstated` and no
   plan filters in. An empty cell, a "n.d." or a flagged value is a typed absence
   (`not_reported` with `missing_reason`, `not_measured`, `below_detection_limit` with the limit),
   never 0 and never a typical value. Keys and qualifiers follow the curate-source rules (one key per
   quantity, the species in `target`, the basis in `basis`).
5. **Cite the rows.** Evidence is `{source: <dataset id>, kind: dataset_row, locator: "row 12" (and
   the column), quote: the row's cells as they appear in the file}` so the verbatim check can find it;
   a condition stated once for the whole file (a header line, the dictionary) gets its own evidence
   item. Derive the REPORTED_IN links to the Dataset from the evidence.
6. **Mark the records as first-hand** when the data are the owners' own: `origin: recorded` with
   `recorded_at` on the records written from the file; a third-party dataset's records are
   `origin: reported`.
7. **Validate** with the file as the source text:
   `scale graph validate <doc> --source-text <dataset id>=<file>`; zero errors. A checklist item the
   file does not give makes a record non-conformant, not invalid: declare it missing with its reason.
8. **Check what each audience sees** before sharing: `scale graph filter <doc> --as <project or
   institution id>` (or `--public`), and `scale evidence access <doc>` before anything is committed to
   the public repository.

The steps carry over to any table: the file's digest, the column dictionary, a row per run, the missing
and estimated fields typed.

## What must never happen

- A value converted to another unit, or a missing cell filled, without the file saying so.
- A column given a meaning, unit or basis its owners did not state, without a person checking it.
- Project data shared beyond the access its owners set, or committed to the public repository.
- A curator named in the records (`curated_by`), or review and curation-run fields invented for them.
- A record of one file merged with a record of another source without recorded evidence for the merge.
