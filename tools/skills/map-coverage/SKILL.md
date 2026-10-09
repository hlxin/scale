---
name: map-coverage
version: 0.1.0
description: Build a coverage map of scale-graph documents — materials by properties by conditions — from query plans and stats, keeping apart what the sources did not state, what they say was not measured or does not apply, what was not curated, what is withheld from the view, what is ambiguous, what is a one-sided bound, what is recorded in another unit or basis and what the schema cannot say, and route the gaps.
scale_release: ">=v0.1.0"
inputs:
  - The scale-graph documents to map (each pins its schema version)
  - The axes of the map (e.g. catalyst families × results × temperature bands), or a question the map should answer
allowed-tools:
  - "scale graph describe [labels] --domain <domain>"   # what the schema can express
  - "scale graph stats <graph>"                         # counts, the units in use per property path and the link patterns
  - "scale graph query <graph> <plan.yaml>"             # one plan per column (or cell), with its coverage block
  - "scale call describe | query"                       # the same through the agent tools
  - "scale gap from-query (dry run)"                    # schema gaps and source gaps from a query result
  - "scale graph filter <graph> --public | --as <id> --out <view>"   # the view a reader may see, for a report that goes to them
  - write access to the working directory only
outputs:
  - The query plans, one per column or cell, and their results
  - The map (CSV, Markdown or JSON) whose cells give the values present and, separately, each kind of absence with its count
  - The gaps routed from the results (`scale gap from-query`), as a dry run
validation:
  - Every cell's counts come from a returned result (rows, coverage.excluded.by_reason, schema_gaps), never from a guess
  - Each kind of absence is counted apart; an empty cell says what kind of empty it is
  - The map names the documents, their schema versions and the date it was built
human-review:
  - Before the map is used to decide what to curate, measure or fund
  - Whenever a cell is read as "untested" beyond the queried graph
---

# Map what scale-graph documents cover

A coverage map shows where the evidence is and where it is not. Its value is in the empty cells,
so each must say why it is empty: the source did not state it, the source says it was not measured
or does not apply, nobody looked, the source is ambiguous, the value is withheld from this view, the
value is a one-sided bound the band cannot decide, the value is there in another unit or basis, or the
schema cannot express it.

## Procedure

1. **Choose the axes.** Rows: the entities (catalysts by family or composition, materials, reactions).
   Columns: the properties (declared ones, or `results` keys with their `target`). Optional bands of
   a condition (temperature, pressure, a driving force).
2. **Read the vocabulary and the units:** `scale graph describe <Label> --domain catalysis` for what
   can be said; `scale graph stats <graph>` for the units in use per property path (`units_in_use`;
   map entries as `results.<key>`) and the link patterns that connect rows to columns.
3. **Write one plan per column** (or per cell when the bands differ): match the row entities, follow
   the links to the records that carry the property, filter on the band with a stated unit (and
   `basis` where the values state one; nothing is converted, so one plan per unit and basis in use;
   never a plan in `not stated`, the placeholder for a number printed without a unit, which stats count
   under `(no unit)` and every plan leaves out as `unit_unstated`),
   return the value and `evidence: true`. Address map entries by key or by what they refer to
   (`results.*[target=<species id>]`).
4. **Run them** and read each result's `coverage`: the candidates, the rows, everything left out by
   reason (`coverage.excluded.by_reason`, each record once), the values compared
   (`compared_in_unit`), `unfiltered` and, for a document `scale graph filter` made, `filtered_for`.
5. **Fill the cells.** For each row and column give:
   - the number of values present (and of independent works: SAME_WORK_AS or one primary work cited
     twice counts once);
   - not stated: excluded as `not_reported` with no `missing_reason` or `missing_reason:
     not_stated_in_source`, the source being silent: a source gap;
   - `not_measured`: the source says it was not measured; `not_applicable`: the property does not
     apply to the record. Each is a statement of the source, a status of its own: count each apart,
     never as the source being silent, and neither is a gap;
   - `not_curated`: nobody looked (curation backlog, not a gap of the source). On a filtered document
     (`coverage.filtered_for`), a reference the filter removed (a ref, a ref-list entry, a map entry
     keyed by a withheld id) reads as `not_curated` or `no_matching_entry`: count those cells as
     "not curated or withheld", never as backlog alone, and say why (the result's limitation does);
   - `withheld`: the source reports it, but the document queried does not share it (a value `scale graph
     filter` or an export withheld for this audience, kept in its place, a map entry under its key and a
     list entry at its position): never the source being silent and never a gap; count it apart, and say
     it only within the audience the map goes to;
   - `not_extractable`: the source has it but it could not be extracted (an extraction task, not a
     source gap);
   - `ambiguous_in_source`: the source contradicts itself: not silence, but a gap of its own (review
     the source or ask the authors; keep every variant);
   - other unit or basis: excluded as `incompatible_unit`, `other_basis`, `unit_unstated` or
     `not_a_number` (the value is there; a plan in its own unit and basis, another column, may count
     it);
   - one-sided bound: `one_sided_bound` (the value is "at most" or "at least" a number, and the band
     can hold it or not: the value is there, a bound; count it apart, never as the number);
   - below a limit: `below_detection_limit` or `below_quantification_limit` (measured, under the limit
     the value gives; never zero, never "not stated");
   - no such entry: `no_matching_entry` (the record has the map, but no entry the path selects: that
     key, or an entry for that target or variable, was not recorded; on a filtered document, possibly
     withheld, as above);
   - any other reason code in `coverage.excluded.by_reason` (a date or retraction rule, second-hand
     evidence left out) gets its own column, named by its code;
   - `schema_gap`: the schema cannot say it (route to schema evolution);
   - nothing at all (`no_matching_record`): untested in this graph, never untested.
6. **Route the gaps:** `scale gap from-query <result.json> --out-dir gaps/` turns schema gaps into
   missing-concept gaps, source silences (`not_reported`) into source-review gaps and ambiguous values
   (`ambiguous_in_source`) into source-review and author-query gaps (`ambiguous_source_information`);
   values not curated are backlog, and values withheld, not extractable, not measured, not applicable,
   one-sided bounds or in another unit or basis are no gaps. Every gap keeps the answer's `access`:
   one that is not public goes only where the queried document may go (`scale gap issue --submit`
   refuses it), so route it there, or make it from a query of the public view.
7. **Publish the map** with its plans, the documents and their schema versions, the date, and a
   Limits line from the coverage blocks.

## Rules

- Never fill a cell with a typical value, and never merge two kinds of absence into one "missing".
- A link type the map did not traverse is "not queried", never "absent".
- Keep incompatible units and bases in separate columns: nothing is converted, and a basis written only
  in a value's reported text or note is not read by the filter (read `as_reported` and `note`).
- Name second-hand evidence (ECO:0000033) and sources that are preprints, patents, theses, reports or
  not peer reviewed in the cells that rest on them.
- The map, every cell, count and record it names, goes only where every queried document may go: each
  result's `access` is the least open stewardship anywhere in its document (its header and every
  record, whether or not a cell counts it). For readers a document does not admit, map the view `scale
  graph filter --public` (or `--as <id>`) makes for them; its results have that view's own access, and
  the cells it withholds read as `withheld`. A map of project data stays within that project.
- Synthetic examples are not evidence about the world; a map built on them says so.
