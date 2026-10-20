---
name: query-graph
version: 0.1.0
description: Answer a scientific question from scale-catal documents by writing and running a graph query plan that returns rows as reported, with evidence, the records left out and why, its coverage and the kind of answer — reporting absences instead of filling them.
scale_release: ">=v0.1.0"
inputs:
  - A natural-language question
  - The scale-catal documents to query (each pins its schema version)
allowed-tools:
  - "scale graph describe [labels] --domain <domain>"   # what the schema can express
  - "scale graph stats <graph>"                         # the units in use and the link patterns of a document
  - "scale graph query <graph> <plan.yaml>"             # patterns, filters, evidence search, dated paths
  - "scale graph search <graph> <text>"                 # evidence by words and meaning (vectors + BM25)
  - "scale graph filter <graph> --public | --as <id> --out <view>"   # the view a reader may see, for an answer that may go to them
  - "scale call describe | query | search"              # the same through the agent tools
  - "scale gap from-query (dry run)"
  - write access to the working directory only
outputs:
  - The query plan (YAML) that was executed, and any other plan run before reporting an absence
  - The query result (JSON) with rows, values as reported, evidence, the records left out, the coverage block and the kind of answer
  - A presentation of the result that cites evidence locators, labels hypotheses separately and ends with a Limits line citing the coverage
validation:
  - Every factual sentence in the presentation maps to a returned row and its evidence
  - Numbers are reproduced as reported (value, unit and the reported text), with any computed or converted value labelled as yours
  - Every typed absence and every record left out in the result is reported, not smoothed over
  - The Limits line gives the candidates, what was left out by reason and the values compared by unit and stated basis alone, from the coverage block
human-review:
  - Before a query result is used to support a publication, decision or new experiment
  - Whenever the presentation goes beyond the returned rows (extrapolation or hypothesis)
---

# Query scale-catal documents

A generated explanation is a presentation of the retrieved evidence, not a replacement for it.

## Procedure

1. **Name the distinctions** the question needs (a composition, a feed, a driving force, a control,
   a date, an evidence path, each link type the question names). "Which observations support this
   assignment?" needs evidence; "which rates are comparable?" needs compatible conditions and units.
2. **Find the vocabulary:** `scale graph describe CatalyticTest HAS_COMPONENT … --domain catalysis`;
   `scale graph stats <graph>` for the units in use per property (`units_in_use`) and the link
   patterns (`link_patterns`: source label, link type, target label, count); search the evidence for
   the words the sources use: `scale graph search <graph> "sulfur poisoning" --published-before 1959`.
3. **Write a plan** (`tools/pgraph_query.py` and docs/querying.md document the format):
   `match` a label, follow `steps` along edges (`direction: in` for incoming ones; `edge_as` binds
   the link), `where` filters on value objects with a `unit` (and a `basis` when the values state
   one; nothing is converted, so one plan per unit and basis), paths into maps and lists
   (`results.*[target=<species id>]`), optional `text` search over the evidence, `published_before`
   for a dated question, `own_work_only` to leave out second-hand rows, `return` fields,
   `evidence: true`, `order_by`, `limit`. A question that compares or ranks values ("which rates are
   comparable?", "the highest current density") takes `comparison: scientific` (scale-catal 0.3.0 on): each
   value is then compared only within one unit and one context its quantity contract names (a potential's
   reference scale, a current density's normalization, a pressure's convention, a flow's reference
   conditions, a share's species), stated with `context: {potential_reference: rhe}` to check one, or left
   unstated to group the rows; a value whose context is not stated is left out as `missing_context`, never
   assumed. A question about one result (a yield, a selectivity, a Faradaic efficiency of one product) binds it
   with an `entries` step (`{from: test, entries: [result_values, faradaic_efficiency], kind: faradaic_efficiency, as:
   fe}`) and follows its product or assay with a `field` step (`{from: fe, field: target, to: ChemicalSpecies, as:
   product, where: [{prop: formula, op: eq, value: NH3}]}`): every filter, returned value and evidence item on `fe` is
   then that one result's, never another assay's, and `kind` keeps a yield from standing in for a selectivity.
   Worked plans: the catalysis competency questions (`domain/competency/*.yaml`, also returned by
   `scale call domains`; CQ-06 compares current densities, CQ-01, CQ-07 and CQ-08 bind results, CQ-09 follows the
   transport check into a test, CQ-10 a test's dynamic operation and CQ-11 its dark controls; CQ-14 the site
   populations of a specimen's states, CQ-15 a turnover frequency into the site count it is divided by, CQ-16
   activity assignments and CQ-17 operando observations made while the kinetics were measured, and the fits an
   assignment rests on). A step on an edge
   type follows its specializations too (`CONTROL_FOR` finds `DARK_CONTROL_FOR` links), as `to` finds subtypes.
4. **Run it:** `scale graph query <graph> plan.yaml --format markdown` (or `scale call query`).
5. **Read the kind of answer and the coverage:** `answered`; `no_matching_record` (none in this
   graph, which says nothing about the literature); `missing_context` (records match but a value
   needed is missing or in another unit; see `excluded` and `missing_context`); `schema_gap` (the
   schema cannot say it: route to schema evolution). `coverage` gives the candidates, each stage's
   rows in and out, everything left out by reason, each record once (`excluded` lists only the first
   500), the values compared in a filter's unit (`compared_in_unit`), `unfiltered` and, for a
   filtered view, `filtered_for`. `access` says where the answer may go: the least open stewardship
   anywhere in the queried document.
6. **Present.** Lead with the supported answer. For each value give it as reported, with its source,
   year and locator. Keep incompatible units and bases apart. Label interpretations as the source
   authors'. Put any extrapolation in a separate, labelled paragraph. End with a **Limits** line
   from the coverage block: candidates, rows, what was left out and why, and that the values were
   compared by number, unit and stated basis alone (in a scientific comparison: and within one context,
   group by group, with the values left out for their context, `missing_context` and
   `incompatible_context`, named as such: there is no ranking across groups).
7. **Route failures.** `scale gap from-query result.json --out-dir gaps/` turns a schema gap into a
   missing-concept gap, values the source does not report into source-review gaps
   (`absent_source_information`) and values the source reports ambiguously (`ambiguous_in_source`)
   into source-review and author-query gaps (`ambiguous_source_information`: keep every variant);
   values not curated are curation backlog, and values withheld from the view, not extractable, not
   measured or not applicable (what the source says), or left out for their unit, basis or one-sided
   bound are no gaps. Every gap carries the answer's `access`: one that is not public names records of
   a document that is not all public, so it goes only where that document may go (`scale gap issue
   --submit` refuses it); route it there, or make the gap from a query of the public view. A gap you
   write by hand states its access too: one with none reads as institution, and `--submit` files only a
   gap whose `access.level` is `public`.

## Rules

- Never compute with a missing input, and never convert units: a numeric filter (`eq`, `ne` and `in` with numbers too) states its unit and compares only values in that unit, spelled the same, case included, once runs of whitespace count as one space (`mPa` is not `MPa`, `mol%` is not `%`, `barg` is not `bar`), on the basis it states (`basis`) or, when it states none, values that state none. Run one plan per unit and basis and report each apart. `not stated` (any case and spacing) is the placeholder for a number printed without a unit, not a unit: `scale graph stats` counts it under `(no unit)`, its values are left out as `unit_unstated`, and a filter in it is a plan error; never plan on it. A value left out as `unit_unstated`, `incompatible_unit`, `other_basis` or `not_a_number` is there but not compared: never an absence.
- A filter reads only a value's number, unit and `basis`: before stating a filtered value, return it and read its `as_reported` and `note` for a basis or condition written only there (gauge, on hydrogen, per pass), and say so when there is one.
- Read the units in use (`scale graph stats`) before a numeric filter, and cite the coverage block in the Limits line.
- Traverse every link type the question names; a link type not queried is never reported as absent.
- `answered` means only that rows came back: check that they answer the question; a listing (`coverage.unfiltered`) is not an answer.
- Before reporting "none", state the number of candidates and run at least one other plan (other vocabulary, label or link direction, or a lower `min_score`).
- A `not_reported` value with `missing_reason: not_curated` was not looked for (curation backlog); `withheld` (the reason a filtered document or an export gives a value it does not share) means the source reports it but this view does not show it; `not_extractable` means it is there but could not be extracted. None of these is the same as the source not stating it, and none is a source gap. `ambiguous_in_source` means the source is contradictory: not silence either, but a gap of its own (`ambiguous_source_information`: review the source or ask the authors, and report every variant). `not_measured` and `not_applicable` are what the source says (it was not measured; the property does not apply): report them as such, never as silence, and they are no gap.
- A filter on several entries (`results.*[target=…]`) holds when one passes; when none passes and one could not be compared, the record is left out with that reason (`missing_context`), never counted as failing. Filters on one such path are held by one entry together, and returning the path gives the entries that held them. A row flagged `ambiguous_repetition` binds a result that nothing tells apart from another of its record: report both, never their average. An `unresolved_target` is a product the source does not identify: report it in the source's words, never as a species. A value withheld from the view is neither there nor missing (`exists` and `missing` leave it out as `withheld`). In a document `scale graph filter` made (`coverage.filtered_for`), a reference the filter removed reads as `not_curated` or `no_matching_entry`: say that such absences may be withheld, and never count them as curation backlog.
- A value with a `bound` is a one-sided bound ("did not exceed 1 %": at most 1 %): report it as the bound, never as the number. A filter the bound cannot decide leaves it out (`one_sided_bound`, counted), and `eq` or `in` never holds for a bound alone.
- Name the kind of a preprint, patent, thesis or report, and of a source recorded `peer_reviewed: false` (`source_kind`, `source_peer_reviewed` on each evidence item).
- Name second-hand evidence (`second_hand`: ECO:0000033, a source reporting another work's result) and cite the primary work where the graph holds it; `own_work_only: true` leaves it out.
- Count independent works: sources joined by SAME_WORK_AS, or one primary work cited by several sources, count once.
- Call a conflict only after checking the entity, the conditions, the unit and basis, and whether the intervals overlap; say on which of these the values differ.
- For returned Claims and values, follow incoming CONTRADICTS and SUPPORTS, say whether they are disputed, and say "none recorded" when no such link is there.
- Keep equilibrium constants (Kp, Kc) on different standard states or units apart.
- A site population holds for the state its `HAS_SITE` starts from: never report it for another state of the sample.
  Report each turnover frequency as reported, with how it was calculated (its basis and the site count it is divided
  by, from the row's `compared`), and say when it does not say. When its site count was made in another state than
  the rate (CQ-15), say so. Never recalculate a rate on another count.
- An assignment of activity is a claim (`ABOUT` roles active, spectator, precursor, inhibitor): report it as the
  authors', with what supports and contradicts it, never a phase as active because it is abundant. Operando means
  characterized while the kinetics are measured: an observation labelled operando was made so only where its `DURING`
  link states it (same specimen, timing simultaneous, kinetics measured); an overlap or a change that tracks the
  activity is not evidence of activity.
- An answer goes only where the whole queried document may go: the result's `access` is the least open stewardship anywhere in it (its header, every record, the notices, sources and datasets no row shows included), and no part of the answer (a row, a value, a record named as left out, a count) is more open. When it is not public and the answer is for readers the document does not admit, never pass it on: query the view `scale graph filter --public` (or `--as <id>`) makes for them, whose answers have that view's own `access`, and say that the view holds only what they may see. A second-hand note names its sources by id unless the document is all public. Embargoes are read today, the earlier of the local and the UTC date, as every SCALE path reads them (an `as_of` YYYY-MM-DD may read them on an earlier day, never a later one). A `scale graph search` result carries the same `access`.
- Synthetic examples (`data_status: synthetic_example`) are not evidence about the world; use them only to test a plan, and label them.
- An absence means absence in the queried graph, never in the literature.
- Rows resting only on retracted or withdrawn sources are left out by default (`excluded`, reason `rests_on_retracted_source`); bring them back only on purpose (`include_retracted: true`) and say so. Every evidence item carries its source's `source_status`: name a retracted, withdrawn, corrected or concerned source when you cite it (docs/querying.md).
