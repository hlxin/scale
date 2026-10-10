---
name: curate-source
version: 0.1.0
description: Translate a declared source into a scale-graph document (node-link JSON) under the schema version it pins, preserving source locations, reported values, units, explicit missingness and evidential status; record gaps instead of changing the schema.
scale_release: ">=v0.1.0"
inputs:
  - A declared source set (identifiers and, where licensing permits, local text for verbatim checks)
  - The checklist the document follows (catalysis: the catalysis schema and its one checklist)
allowed-tools:
  - "scale graph describe [labels] --domain <domain>"   # the labels and edges you may use, with the checklist and its cases
  - "scale graph validate <doc> --source-text <id>=<file>"
  - "scale graph index | search"            # vectors and term statistics for the evidence quotes
  - "scale evidence report | cap | rehydrate"   # quoted characters per source against the copyright cap; withheld quotes
  - "scale call template | describe | validate"   # the same through the agent tools
  - "scale gap list | issue (dry run)"
  - "scale corpus check <manifest>"           # every candidate source has a status and the counts add up
  - "scale pages render | region | agree | check | pending | merge-second | import"   # scanned pages: page images checked against OCR, second readings
  - read access to the declared source text
  - write access to the working directory only
outputs:
  - A scale-graph document (graph header, nodes, links) that pins the catalysis schema version and follows its checklist
  - The validation report (errors, warnings, checklist conformance)
  - Gaps classified as missing_concept, extraction_error, absent_source_information, ambiguous_source_information
  - The frozen corpus manifest (every candidate source with its status, and a reason when it is left out)
validation:
  - "`scale graph validate <doc> --source-text <source-id>=<file>` reports zero errors"
  - Every node and link that states something carries evidence (source, locator, kind, quote)
  - Every quote is found verbatim in the source text (whitespace, case and dash variants ignored)
  - Every reported value appears in at least one cited quote
  - "`scale corpus check <manifest>` reports ok: every candidate source accounted for once, the counts adding up"
  - "`scale evidence report <doc>` lists no violation and no source without a rights entry (rights.yaml)"
human-review:
  - Always before the document is treated as reviewed
  - Whenever entity resolution merges two records, or a sample or batch identity would be asserted
  - Whenever evidence is second-hand (a review reporting another group's result)
  - Whenever a gap of kind missing_concept is raised
---

# Curate a source into a scale-graph document

The schema constrains what a completed record means; the source determines which parts can
actually be populated. The extraction model is not the authority that defines the target concepts.
Worked examples of what it produces are the synthetic documents in `domain/examples/scale-graph/`
(one per driving force and combination). Short recording recipes for
situations the schema covers less obviously (set and nominal values, conflicts, kinetics,
thermochemistry, computations, reactor and bed keys, ratios, commercial catalysts, balances and
impurities, driving forces outside the list, characterization results, digitizing a figure) are in `references/recipes.md` beside this file (through the agent tools:
`scale call skills '{"name": "curate-source", "reference": "references/recipes.md"}'`).

## Procedure

1. **Freeze the source set** before curating: which sources, by what rule (e.g. published before a
   cutoff date; a patent by its grant date, not its priority date), with the texts used. Record it
   (`sources.json` in the methanol example) so the corpus can be audited: every candidate source gets
   a `status` (included, or the reason it is left out: not retrieved, off scope, after the cutoff;
   a bare `excluded` needs a `status_reason`), and the `counts` add up to the candidates. Check it
   with `scale corpus check <manifest>`. A declared corpus is not a database search: there are no
   PRISMA identities (identified, screened) to report, only every candidate accounted for once.
2. **Get the text.** Quotes are checked against page texts: the PDF's text layer, or OCR where it
   has none (`scale.sourcetext`; each page records which). Quote OCR text as it is. For a scanned page
   whose values the text loses, read the page image too and let OCR check it (`scale pages`: the
   reading's region and transcription on the evidence, the tool's agreement, an independent second
   reading where OCR does not confirm it; docs/curation.md, "Reading scanned pages: two readers").
3. **Read the schema, not your memory of it:** `scale graph describe <Label> --domain catalysis`
   (the schema is the catalysis graph schema manifest, `domain/graph/scale-graph.yaml`: the
   science kernel plus the catalysis file (`catalysis.yaml`) with its one checklist). What a catalytic test must
   and should report depends on the driving forces it lists (`driving_forces`: the checklist's `when`
   cases), so record the forces the source describes; never add a force to satisfy a checklist.
4. **Start from a template:** `scale call template '{"domain": "catalysis"}'` returns a minimal valid
   document. The header pins `schema_version`, names a `graph_id` and a `title` that states the scope
   as a short name, at most 40 characters, since a platform shows it as the graph's name (e.g. "Nitrate
   to Ammonia on Cu"); the scope's details go in `description` (e.g. "SI and Source Data not examined"), sets `data_status` (`research_data` for
   sources; `synthetic_example` only for invented examples), follows the checklist
   (`follows_domains: ["catalysis"]`) and, for research data, gives the stewardship (`contributed_by`,
   `project`, `access`).
5. **Records.** Nodes `{id, label, props}`, links `{id, source, target, type, props}`; ids are
   CURIE-like (`prefix:path`) and unique across nodes and links. Roles are on links
   (`HAS_COMPONENT {role: support}`), not labels. A run is a CatalyticTest with its conditions and
   results as value objects in the printed unit, linked to the catalyst sample, feed, reactor and
   reaction. A catalyst (the formulation) is not a catalyst sample (a physical specimen); never
   infer batch or replicate identity. Interpretations are Claims, proposals Hypotheses; never write
   an interpretation as a property of a material.
6. **Values** are `{status, value, unit, …}` in the unit the source printed; keep the printed text in
   `as_reported` (or `note`) when it differs ("~", "> 85", "0.05 m"). The schema performs no unit
   conversion. A number printed without a unit keeps `unit: "not stated"` with its printed text in
   `as_reported`, and the note says the source states no unit (until the units proposal gives values
   a unit status). `not stated` is no unit: a query leaves such values out as `unit_unstated`, `scale
   graph stats` counts them under `(no unit)`, and no plan filters in it. Record uncertainty only as the source states it (below, **Uncertainty**).
7. **Evidence on every stating record and every link:** `{source, locator, kind, quote}` with a
   short verbatim quote, within the source's rights (step 8). Derive the REPORTED_IN
   links from the evidence. `scale graph index` then gives each quote a vector (deterministic
   `scale-hash-v1` by default) and term statistics, and each quote records the source passage it
   was found in (`evidence.passage`), so search later finds records by meaning.
8. **Rights and the copyright cap.** Record each source's rights in the folder's `rights.yaml`:
   `sources: {<source id>: {class, licence, basis, text_chars}}` with `class` one of `public_domain`, `open`,
   `restricted`, `in_copyright` or `synthetic`, `licence` an SPDX id (e.g. `CC-BY-4.0`) or a text, `basis` why
   (e.g. "US patent", "published under CC BY 4.0 (publisher page)"), and `text_chars` the length of its text when
   known. A source you cannot place is `in_copyright`. For `restricted` and `in_copyright` sources each quote,
   transcription and second reading is at most **300 characters**, and one source's distinct quoted characters
   are at most **4,000** and at most **10 %** of `text_chars`; public-domain, open and synthetic sources have
   no cap (still only text found verbatim). Claim statements, names and notes are your own words: never copy an
   in-copyright source beyond a short phrase (this is not machine-checked). Check with
   `scale evidence report <doc>`; `scale evidence cap <doc> -o <out>` keeps the texts that fit (evidence of
   quantitative values first, then the shorter) and **withholds** the rest: the item keeps its source,
   locator, kind (and passage, region), the text is removed and `note` records
   `quote withheld: sha256:<hex> chars:<n>` (or `transcription withheld: …`), the digest and length under the
   verbatim checker's normalization. Anyone holding the source restores them with
   `scale evidence rehydrate <doc> --texts <dir> -o <out>`; a reading of a page image is not in the text
   layer and cannot be restored that way. `scale check` runs the report on every committed document that is
   not a synthetic example (`research_data` or `mixed`) and requires every committed document to be public
   (project data not cleared for publication stays out of the repository).
9. **Missingness.** An unknown value is `{status: not_reported, missing_reason: …}`:
   `not_stated_in_source` when the source is silent, `not_curated` when you did not look,
   `ambiguous_in_source` when the source conflicts (keep every variant in `note` and the passages in
   `evidence`). `not_measured` and `not_applicable` are statuses of their own.
   `below_detection_limit` needs the limit and the unit.
10. **Never extend the schema during curation.** Context the schema cannot express goes in the
   record's `unmodeled` list; it is raised as a gap (`missing_concept`).
11. **Validate** with the source text: `scale graph validate <doc> --source-text <source-id>=<file>`
    (or `scale call validate`); zero errors before the record counts. A checklist item that the
    source does not report makes the record non-conformant, not invalid: declare it missing with its
    reason.
12. **Route gaps** (`scale gap issue <gap.json>`, a dry run): only `missing_concept` goes to schema
    evolution (the `evolve-schema` skill). A gap you write by hand states its `access` (`{level, note}`):
    one with none reads as institution, failing closed, and `--submit` files only a gap whose
    `access.level` is `public`, so give that only when its record ids, fields and question may all be
    public.

## Reading runs, tables and figures

- **Pair conditions and results from the same run.** A condition stated once (in Methods, a caption,
  "unless noted") goes on every run it covers, with its own evidence item for that locator, listed in
  the value's `evidence_ids`. When the source does not make the pairing clear, do not pair: the value
  is `not_reported` with `missing_reason: ambiguous_in_source`.
- **Tie each value to its evidence when a record cites several sources.** Give every value of such a
  record its `evidence_ids`, the evidence items that state it. Only they tie a value to its source.
  When `scale graph filter` or an export leaves out a source the audience may not see, a value whose
  `evidence_ids` name evidence that remains stays, cited to it. A value whose ids name only the
  withheld source's items is withheld in its place, and so is a value without `evidence_ids` on a
  record that lost evidence (fail closed). Give them so that values stated by a source the audience
  may see are kept.
- **Read tables cell by cell.** One cell is one value; the locator gives the table, row and column
  ("p. 4, Table 2, row 3, column 'CO conv.'"); the unit comes from the column header; read the
  footnotes; a number in parentheses after a value is its uncertainty when a footnote or the methods
  say so (`1.234(5)` is ± 0.005 in the last digits), and otherwise stays in `as_reported`.
- **Take only the source's own results.** A result the source reports from another work (a comparison
  table, a review) is second-hand: if you record it, give its evidence `evidence_type: ECO:0000033`
  and name the cited work in the locator or note; the source's own work is ECO:0000006 (experimental)
  or ECO:0007672 (computational). When the cited work is in the corpus, curate the value from it
  instead, and never record a cited result as a run of this source.
- **One value, several printed forms.** When text, a table and a figure give the same value, the most
  precise explicit form carries it and the others stay as evidence; forms that disagree are
  `ambiguous_in_source` with every variant in `note`.
- **Read figures against their axes.** Calibrate on at least two ticks per axis and say whether the
  axis is linear or logarithmic. A value read off a plot is `qualifier: approximate` with `uncertainty`
  (`uncertainty_kind: standard_uncertainty`, `uncertainty_evaluation: type_b`: from the reading
  resolution, a half-width a giving a/√3, or the spread of two readings, whichever is larger); put the
  axis scale and the ticks used in the evidence `note`, and keep the second reading. A tool's
  digitization is a computational Experiment (`USES_SOFTWARE`, the value's `produced_by`). Never
  record a value read off a plot without an uncertainty (`references/recipes.md`, "Digitizing a
  figure").

## Uncertainty

| the source prints | record |
|---|---|
| ± of unstated meaning | `uncertainty`, `uncertainty_kind: plus_minus_unspecified` |
| a standard deviation, a standard error | `standard_deviation` or `standard_error`; `replicates` when n is stated |
| a confidence interval | `interval_lower`/`interval_upper` (or a symmetric `uncertainty`), `confidence_interval`, `confidence_level` |
| a coverage interval (Monte Carlo, bootstrap, Bayesian; 5–95 %) | `confidence_interval` with its bounds and `confidence_level` (0.9 for 5–95 %); there is no percentile kind |
| an expanded uncertainty | `expanded_uncertainty` with `coverage_factor` or `confidence_level` |
| a relative uncertainty ("± 5 %" of the value, RSD) | `as_reported` and `note` only, until the schema has a relative form (planned: domain/ROADMAP.md); never convert it to an absolute one |
| an interquartile range | Q1 and Q3 in `note`, until the schema has the kind (planned: domain/ROADMAP.md); never as a confidence interval |

Never record `± 0`: keep the printed text in `as_reported` and leave `uncertainty` out.

## Records that need care

- **Statement kind.** An interpretation is a Claim (`CONCLUDES`, `ABOUT`) and a proposal a Hypothesis
  with `status: hypothesized` links. Once the pinned schema declares `statement_kind` on links
  (`scale graph describe`; planned: domain/ROADMAP.md), set it on interpretive links (HAS_SITE, INHIBITED_BY,
  IDENTIFIED_AS, and CATALYZES when the source infers it) and mark links taken as given as
  `assumption`; never before the schema has it.
- **Keys and qualifiers.** Use one key per quantity and put what the value is about in its fields:
  the species or product in `target`, the basis in `basis`, the measurand in `variable` (a Variable)
  and how it was defined or measured in `definition`. When a source gives several values of one
  quantity, each map key may carry a short suffix (`crystallite_size_cu`), but the `target` still
  says which. Each operating point is its own CatalyticTest, `PART_OF` the run; repeats are linked by
  `REPLICATES`. A product the source does not report is `not_reported`, never 0.
- **Entity resolution.** Never merge catalysts, samples or tests across sources. Share a species only
  when its identity is unambiguous (the formula fixes it, or the InChIKey or InChI matches); a
  different polymorph or phase is a different Material. Uncertain matches stay separate records.
  When the schema has `former_ids` (planned: domain/ROADMAP.md), the surviving record of a merge lists the
  retired ids there; until then the merge map is kept beside the document (the kg-bundle export's
  `--replaced`).
- **Rights follow the copy read.** Read the licence from the copy you read (its first page, the
  publisher's article page), never from aggregator metadata or open-access colour, and say where in
  `rights.yaml` `basis`. Rights follow the text version read (`text_version`). Supporting information
  belongs to its paper's Source.
- **Reinstatement.** A notice that reverses a retraction or an expression of concern is a Source of
  its own with an `UPDATES` link once the schema has `update_type: reinstatement` (planned: domain/ROADMAP.md);
  until then, record it in the retracted source's `unmodeled` list (with the notice's date and
  locator) and never delete the retraction.
- **Personal data.** A graph of project data names people who are not authors of a source by opaque
  ids only (`ex:<project>/person/p01`), never by name.

## Retractions, corrections and other notices

When you know of a notice about a source (a retraction, a withdrawal, an expression of concern, a
correction), record it as a Source of its own and link it, citing the notice as evidence: a
retraction is `RETRACTS` (`reason`, `retracted_on`, `scope` and, for a partial one, `scope_locators`),
any other notice an `UPDATES` link (`update_type`,
`updated_on`, `reason`; evidence required). A partial retraction can also be a Dataset that
`INCLUDES` the affected records, which the notice `RETRACTS`. The publication status is derived from
these links; never type it, and set `claim_status: retracted` only with the notice recorded. Never
delete or rewrite the records of a retracted source: the validator flags them and queries leave them
out unless asked. Record `status_check` (`checked_on`, `checked_via`, `result`) only when
someone actually checked for notices; no tool checks registries yet. Also say which text
version was read (`text_version`, with `text_sha256`, `retrieved_from`, `retrieved_on` where useful) and
link versions, translations and duplicates of one work with `SAME_WORK_AS` (docs/curation.md).

A document pinned to an earlier schema version stays valid under that version; `scale graph migrate`
moves it to the current one when asked.

## What must never happen

- A plausible value filled in for a missing one (typical pH, room temperature, a reference potential).
- A converted value replacing the reported one.
- A record deleted or rewritten because its source was retracted, or a publication status typed by hand.
- Two catalyst names merged without recorded evidence for the merge.
- A figure-only value presented as read from text without saying so, or recorded without an uncertainty.
- A result the source cites from another work recorded as the source's own run.
- A product the source does not report recorded as 0, or `± 0` recorded as an uncertainty.
- Quoted text beyond a source's cap, or a claim statement that copies an in-copyright source beyond a short phrase.
- Project data (stewardship access other than `public`) committed to the public repository.
