# Queries that return context, not just answers

Procedure: [`skills/query-graph/SKILL.md`](../skills/query-graph/SKILL.md). Competency
questions: [`domain/competency/`](../domain/competency). The plan format is
documented in `tools/pgraph_query.py`.

## Query plans

```yaml
question: Which ammonia Faradaic efficiencies were measured, under which control mode, on which catalyst?
match:                                   # the records the answer is about
  label: CatalyticTest                   # a label (labels that is_a it included)
  as: test
  where:
    - {prop: faradaic_efficiency, op: exists}
steps:                                   # follow edges; each binds a new variable
  - {from: test, edge: USES_CATALYST, to: CatalystSample, as: sample}
  - {from: sample, edge: HAS_FORMULATION, to: Catalyst, as: catalyst}
  - {from: test, edge: CONTROL_FOR, direction: in, to: Experiment, as: control, optional: true}
where:                                   # filters on bound records, in a stated unit
  - {var: test, prop: temperature, op: le, value: 300, unit: K}
  - {var: test, prop: "faradaic_efficiency.*[target=ex:df-electro/species/ammonia]", op: ge, value: 80, unit: "%"}
return: [test.name, test.control_mode, test.faradaic_efficiency, catalyst.name, control.name]
evidence: true                           # the rows' evidence: source, locator, quote, year
order_by: [{var: test, prop: temperature}]
limit: 50
```

(Competency questions are written in block-style YAML; the flow style here is for brevity.)

A step's `to` binds the label and every label that is_a it, and its `edge` follows the edge type and every edge type
that specializes it: a step on `CONTROL_FOR` also follows `DARK_CONTROL_FOR` (a dark control is a control), on
`HAS_INPUT` also `FED_WITH`, `IN_ELECTROLYTE` and `USES_ELECTRODE`, on `USES_INSTRUMENT` also `IN_REACTOR`, `IN_CELL`,
`ILLUMINATED_BY`, `USES_PLASMA`, `HEATED_BY` and `TEMPERATURE_MEASURED_BY`. Name the specialized type to follow it
alone. CQ-11 binds dark controls both ways.

```bash
scale graph query domain/examples/scale-catal/driving-force-examples/electro.json plan.yaml --format markdown
```

A plan may also search the evidence by words and meaning (`text: {query, vars, mode, min_score}`,
which reads the evidence index saved by `scale graph index`, or builds it in memory from the document when
none is saved beside it), ask for sources published before a date
(`published_before`), leave out rows that rest only on second-hand evidence (`own_work_only: true`) and read embargoes on a
given day (`as_of`, see Result).

A plan's text search ranks only the evidence of the records its rows still hold, after the plan's other filters
(`where`, retractions, `published_before`): its `k` hits (500 by default) and an `rrf` fusion are counted among
them, so quotes of rows a filter left out never crowd out those of the rows it kept. The text search has four modes. `hybrid` (the default) averages BM25 keyword relevance, scaled to the best hit, with
the cosine of the quote vectors (negative counted as 0), so its scores run from 0 to 1; `keyword` and `vector` use one
of them; `rrf` (reciprocal rank fusion) adds 1 / (60 + rank) from the keyword ranking and from the vector ranking,
each read to its 1000th item (with a filter, such as `published_before`, a ranking of the items it keeps), so an `rrf` score is at most 2/61, about 0.033, and a `min_score` written for
`hybrid` (0.25, say) leaves out every row in `rrf`. Every mode is exact: each quote is scored, and ties go by item id.
For large graphs, `scale graph index` saves the index (`<graph>.evidence.jsonl`, `.i8` and `.terms`, its keyword
postings) so that a query reads it instead of building it; in a long-running process (the agent tools, MCP) the
vectors are kept in memory after the first query when they fit 2 GB (about a million quotes).

To run several plans on one document from Python, build its query graph once, `g = pgraph_query.Graph(doc, spec)`,
and pass it to each `pgraph_query.run(doc, spec, plan, index, g)`: what every query needs whatever its plan (the
document's digest and access, its sources' publication status, its evidence quotes) is computed once. The agent
tools do this for a document given by path and keep it until the file changes.

An evidence index records the digest of the document it was built from (`graph_sha256`). `scale graph
query` (text) and `scale graph search`, and the agent tools, use an index only for a document whose evidence quotes it
holds exactly, whatever digest it records (a header is no proof of what the index holds); another document's index,
a less open one, a stale copy or one that names the document but holds other text, is refused with the advice to rebuild it, and a text
plan never lets a quote the queried document does not hold choose a row. A `scale graph search` result
carries `access` as a query result does: its hits are the document's verbatim quotes.

Before writing filters, `scale graph stats <graph>` shows what the document holds: the properties in
use per label, the units in use per label (or link type) and property path (`units_in_use`, map
entries as `results.<key>`, list entries as `<property>.*`; a value that states no unit, the
placeholder `not stated` included, is counted under `(no unit)`), and the link patterns
(`link_patterns`: source label, link type, target label and count).

## Units

A numeric filter compares numbers in the unit it states: `lt`, `le`, `gt`, `ge`, and `eq`, `ne`
with a number or `in` with numbers (`temperature eq 380 °C` holds for 380 °C, or for a reported
range that holds 380 °C; `ne` for neither). One rule decides which values it compares, and nothing
is converted:

- The filter states its `unit`. A value is compared only when it holds a number (`value`, or
  `lower`/`upper`), its `unit` is text spelled as the filter's, case included, once each run of
  whitespace counts as one space and the ends are trimmed (`°C` and ` °C ` are one unit; `mPa` and
  `MPa`, `°c` and `°C`, `mol %` and `mol%` are two each), and its `basis` is the filter's `basis`,
  compared the same way, or absent as the filter's is. There are no synonyms and no
  conversion tables: `mol%` is not `%`, `barg` is not `bar`, `1/h` is not `h-1`, and a value in K
  or °F is never compared with a filter in °C.
- Any other value is left out with its reason, and counted (`coverage.excluded.by_reason`, or on a
  step's own `where` the step's `left_out_by_reason`):
  - `unit_unstated`: the filter states no unit, the value states none, or a plain number meets a
    filter that states one. A value whose unit is `not stated` (in any case and spacing: the
    placeholder a curator writes for a number the source prints without a unit) states none: its
    number may be in any unit, so it is never compared, and a filter in `not stated` is a plan
    error. Never plan on it;
  - `incompatible_unit`: the value's unit is another, or is not text (a number, a list);
  - `other_basis`: the value states another basis, or a basis is stated on one side only (`3 MPa`
    with `basis: gauge` against `le 5 MPa`; a selectivity on `carbon basis` against a filter that
    states none; a value that states none against a filter with `basis: carbon basis`);
  - `not_a_number`: the value holds no finite number (text, a boolean, NaN).

  A malformed value (a unit, basis, number or note of the wrong kind) never stops a query. `limitations` counts the values left out for their unit
  or basis: run one plan per unit and basis (`scale graph stats` lists the units in use) and report
  each apart.
- No basis is read from anything but `basis`: not from the unit (`psig` is simply another unit),
  the reported text (`20 bar (gauge)`) or the note. A value whose basis is written only there is
  compared as one that states none, so `coverage.compared_in_unit` counts the values compared and a
  limitation says to read each one's `as_reported` and `note` before stating it. Curate a basis in
  `basis`.
- A numeric filter without `unit` on a property the schema declares as a value is a plan error.
  Where the schema cannot tell (a step without `to`), the value is left out as `unit_unstated`. A
  plain number (a source's `year`) has no unit: a filter without one compares it. On a step's own
  `where`, such values are counted on the step (`left_out_by_reason`,
  `coverage.not_evaluated_in_steps`) and `limitations` says so. A row that a required step leaves out
  because none of its links passed and one could not be compared is counted too
  (`rows_not_evaluated`), and with no row returned it makes the status `missing_context`, not
  `no_matching_record`. An optional step's comparisons, and those on rows that pass the step (and
  that a later stage may leave out), are only counted: they never change the status.
- A unit that is not non-empty text, a `basis` that is not non-empty text or sits on a filter that
  compares no number in a unit, a filter number that is not a number, and `convert` are plan
  errors. Unit conversion is planned with the units change; until then, run one plan per unit.
- A value that is a one-sided bound (its `bound`: `upper`, "did not exceed 1 %", or `lower`, "at
  least 2") is never read as the exact number. It passes a filter only when every number the bound
  allows passes (at most 1 % passes `le 2 %`), fails when none does (`gt 1.5 %`), and is left out
  otherwise with the reason `one_sided_bound` (at most 1 % against `gt 0.5 %`), counted, and
  `limitations` says so. `eq` and `in` never hold for a bound alone. `order_by` sorts a bound by its
  number, as reported.
- A value with the status `below_detection_limit` or `below_quantification_limit` (its `value` the limit, with
  its unit) can only lie below that limit, so a numeric filter reads it as `bound: upper` at the limit, keeping the
  unit and basis checks: `le 5 %` passes a value below a 2 % limit, `ge 5 %` fails it, `le 1 %` leaves it out as
  `one_sided_bound` (named "below the detection limit 2 %; le 1 cannot be decided"), and `eq` and `in` never hold.
  Without a number it stays absent (reason: its status). A scientific `order_by` does not rank it (`one_sided_bound`);
  `exists` still counts it as present. The limit itself counts as possible, so a strict `lt`, `gt` or `ge` at exactly
  the limit is left out as `one_sided_bound` rather than decided.

## Scientific comparison

A plan compares values as reported unless it says otherwise: a number in the filter's unit and on its basis (above). With
`comparison: scientific` (scale-catal 0.3.0 on), every numeric filter and every `order_by` also reads each value under
its **quantity contract** (core/graph/README.md, "Quantity contracts"): the kind its property is bound to (`quantity:` in
the schema; `scale graph describe` shows it), or the `quantity_kind` of the Variable it names.

- **Dimension.** The value's unit must read as one of its kind's dimensions (`kg` is no temperature, `mol/L` no
  fraction): otherwise it is left out as `incompatible_unit`, and so is a unit the vocabulary cannot read (`L/h per 3 cc
  catalyst`), whose dimension is unknown. A filter in a unit of another dimension on a bound property is a plan error.
- **Context.** A kind lists the contexts two of its values must share (`compare_by`): an electrode potential its
  `potential_reference` (the scale: RHE, SHE, Ag/AgCl …), a current density its `current_normalization` (geometric area,
  ECSA, catalyst mass), a pressure its `pressure_convention` (absolute or gauge), a volumetric flow and a gas space
  velocity their `flow_reference` (STP, NTP, normal, standard, operating conditions), a space velocity its
  `space_velocity_basis` (GHSV, LHSV, WHSV, per catalyst mass), a composition fraction its `fraction_basis`, and a
  selectivity, yield, conversion, Faradaic efficiency, quantum or photonic yield, energy yield or partial current
  density, and a turnover frequency (scale-catal 0.6.0), the `species` its target names. A context is read from what
  the value states (its unit: `V vs RHE`, `barg`,
  `sccm`; its `basis` and `definition`; its `target`; the property its `normalized_by` names) and from the sibling
  property its binding names (`reference_scale`, `current_normalization`, `fraction_basis`). The statements must agree.
- **Check or group.** A filter or a ranking that states a context, `context: {potential_reference: rhe}`, checks it: a
  value on another one is left out as `incompatible_context`. One that states none groups: every row carries
  `comparison_group` and `compared` (the unit and contexts of each value it was compared on, an evidenced conversion,
  the denominator it is divided by), `comparison.groups` lists the groups, and a ranking orders rows within a group
  only. There is no ranking across groups. An `order_by` may also state its `unit`, then ranking only values in it.
- **Never assumed.** A value whose context nothing states, or states as `other` or `not_reported`, is left out as
  `missing_context` (a current density with no stated normalization is not taken as geometric). One whose statements
  disagree (its basis says ECSA, its record `geometric_area`) is left out as `incompatible_context` and the validator
  reports it. The exception is an **evidenced conversion**: a value derived or computed (`origin`) by the experiment
  its `produced_by` names, on another context than its record's (a potential converted from Ag/AgCl to RHE by a stated
  Analysis), keeps its own context and may enter that context's ranking; nothing is converted by the query.
- **Denominators.** A value whose `normalized_by` names a value that is not reported, or that the view withholds, is
  left out as `missing_context`. One divided by a one-sided bound is compared as reported (a rate divided by at most
  30 µmol/g of sites is at least the quotient, `bound: lower`; the validator warns when it does not say so). A row
  compared on a denominator whose own `origin` is `assumed` is named in `limitations`, and the row's `compared` gives
  the denominator's record, path, origin and bound.
- **Turnover frequencies** (scale-catal 0.6.0) are used as reported, with how they were calculated: what each is
  divided by (`normalized_by`) and, in its `basis` or `definition`, what was counted as sites and how. Rates of one
  product per exposed atom, per site of a kind and per atom are compared with one another, each row showing its basis
  and denominator, so a reader sees how each was calculated; none is left out for its count. The validator warns about
  one that does not say how it was calculated. CQ-15 shows five rates of one methanol rate side by side.
- **Basis.** On a kind whose contexts read the value's `basis`, a scientific filter states `context`, not `basis`
  (a plan error otherwise), and a value's basis is read through the contexts. A turnover frequency's basis says how it
  was calculated and is read, never compared as text. On any other kind the basis is compared as text, as in an
  ordinary plan.

```yaml
question: Which current densities have compatible area bases and potential references?
comparison: scientific
match: {label: CatalyticTest, as: test, where: [{prop: current_density, op: exists}]}
return: [test.name, test.electrode_potential, test.reference_scale, test.current_density, test.current_normalization]
order_by:
  - {var: test, prop: electrode_potential}                  # grouped by unit and reference scale
  - {var: test, prop: current_density, context: {current_normalization: geometric_area}}   # checked: geometric only
```

The answer's status follows the usual rule: rows left out only for their context make it `missing_context`. `coverage`
gains `comparison` (the mode, the number of groups, the values left out for their context by reason) and `limitations`
say how many groups there are and why values were left out. An ordinary plan is unchanged; when its numeric filters or
ranking compared values on several contexts (or on none stated), a limitation names them and points here. Competency
question CQ-06 (`domain/competency/cq-06-comparable-current-densities.yaml`) runs this on the public comparison example.

## Results

A result is identified by more than its record: its metric, its product, the assay that measured it, its phase and
its interval (core/graph/README.md, "Result entries"). A plan binds **one result per row** with an `entries` step,
and every filter, returned value, ranking and evidence item on that variable is then that result's:

```yaml
question: Which methanol yields were measured, by which assay and in which phase?
match: {label: CatalyticTest, as: test}
steps:
  - {from: test, entries: [result_values, yield], kind: product_yield, as: result}   # one row per yield
  - {from: result, field: target, to: ChemicalSpecies, as: product,
     where: [{prop: formula, op: eq, value: CH3OH}]}
  - {from: result, field: produced_by, to: Experiment, as: assay, optional: true}
where:
  - {var: result, prop: value, op: ge, value: 30, unit: "%", basis: carbon}
return: [test.name, result, result.phase, assay.name, product.name]
evidence: true
```

- **`entries`** names a value property of a node variable (`result_values`, a per-product list such as
  `faradaic_efficiency`, a map such as `results`, a scalar such as `yield`), or a list of them; `kind` keeps the
  entries of those quantity kinds (the property's binding, else the entry's Variable's `quantity_kind`), so
  `kind: product_yield` never binds a selectivity or a conversion. A filter on the bound variable reads `value` (the
  value object itself, compared in its unit as any value is), `kind`, or a field of the value (`phase`, `stream`,
  `basis`, `status`, `unresolved_target`, `id`, …). The row's `bound` names the entry as a record_ref (`record`,
  `path`: `/result_values/<id>`) with its `kind`.
- **`field`** follows a field of a bound entry that names a record (`target`, `variable`, `produced_by`, `calibration`,
  `ref_value`, `normalized_by`) and binds it, of the label `to` names only: a Source never binds as a `ChemicalSpecies`.
  An entry whose product the source does not identify (`unresolved_target`) is left out of a step that follows its
  target, counted as `unresolved_target`, never taken for one species.
- **Evidence.** A row cites the evidence items its bound entry names (`evidence_ids`), labelled with the entry's
  variable and `entry` path, and never an item of its record that only other results cite; an item no value cites
  stays the record's. The assay's evidence comes with it when a field step binds it.
- **Repetition.** Two results of one record that nothing tells apart (one variable, target, producer, phase, stream,
  basis, definition and normalization) are an ambiguous repetition: an ordinary answer returns both, each row flagged
  (`ambiguous_repetition`), and a scientific comparison leaves them out (counted in `coverage.comparison.left_out`).
  They are never averaged. Results told apart by their assay, interval or phase are distinct rows.
- **Scientific comparison.** A bound entry is read under its contract like any value (its property's, else its
  Variable's), with its record's siblings; a filter in a unit of another dimension than the entry's kind leaves that
  entry out as `incompatible_unit` (entries of several kinds may be bound) rather than stopping the plan.

Competency questions CQ-01 (ammonia's Faradaic efficiency, never hydrogen's), CQ-07 (a methanol yield, never a
selectivity) and CQ-08 (Faradaic efficiencies by product, phase and assay) bind results this way.

A value's `normalized_by` may name a link: a turnover frequency's site count is a value on the `HAS_SITE` from the
state the sites were counted in. A field step follows it into that link when it names the link's type and which end
it binds (scale-catal 0.6.0):

```yaml
steps:
  - {from: test, entries: result_values, kind: turnover_frequency, as: tof}
  - {from: tof, field: normalized_by, link: HAS_SITE, end: source, to: CatalystState, as: counted_in, edge_as: count}
  - {from: tof, field: normalized_by, link: HAS_SITE, end: target, to: ActiveSite, as: site}
  - {from: test, edge: IN_STATE, to: CatalystState, as: measured_in}
return: [tof, measured_in.name, counted_in.name, site.name, count.site_inventory, count.exposed_metal_count]
```

`link` names the edge type (its specializations count), `end` the end `as` binds (`source` or `target`), `edge_as`
binds the link for filters and returns, and `edge_where` filters it; the row cites the link's evidence. An entry whose
`normalized_by` names a node, a link of another type or nothing is left out of the step with its reason
(`names_a_node`, `names_another_link`, `not_curated`), and a field step without `link` that meets a link is left out
as `names_a_link`. CQ-15 follows rates to their site counts and shows when a count was made in another state than the
rate.

## Paths into maps and lists

A filter's `prop` and a `return` field may address an entry of a map or a list of values:

| path | addresses |
|---|---|
| `results.methanol_yield` | the map entry with that key |
| `levels.0` | the list entry at that position |
| `results.*` | every entry |
| `results.*[target=ex:t/species/co]` | the entries whose value refers to that record (`value.target`) |
| `levels.*[variable=ex:t/variable/p]` | the entries whose value names that variable (`value.variable`) |
| `result_values.meoh_yield_gc` | the list entry with that `id` (a result entry is named so) |
| `result_values.*[variable=…][target=…][produced_by=…]` | the entries with every one of these fields (also `calibration`, `phase`, `stream`, `id`) |
| `selectivity[target=…]` | a single value, if it refers to that record |

Filters on one path that selects entries are held by **one entry together**: `results.*[target=…] ge 70` and
`results.*[target=…] le 50` hold only for a record with one entry meeting both, never for two assays meeting one each,
and returning that path gives the entries that held them (and the row cites their evidence, below, "Results"). A
filter on several entries holds when one of them passes and fails only when every one of them fails.
When none passes and one cannot be compared (not reported, withheld, in another unit, a one-sided bound),
the record is left out with that entry's reason (`missing_context`), never taken as failing: an entry that
fails never hides one that might pass. A record with the map but no entry that the path selects is left out
with `no_matching_entry`, and a returned path that selects none gives the same reason. A numeric filter on a
whole map or list of values (`energy_yield ge 0`) is a plan error: name its entries (`energy_yield.*`). A
returned path gives the entry it names, or the entries it selects (by key for a map, in order for a list).
`exists` holds when one selected entry is there and `missing` when none is; neither can be decided on a
value withheld from the view (`withheld`), which is left out with that reason. Put the species, product or basis of a value
in its `target`, `basis` or `variable` rather than in the key when curating: a key such as
`selectivity_co_250c` can be found only by its spelling.

## Second-hand evidence and source kinds

Every evidence item carries its source's `source_kind` (article, patent, thesis, preprint, report;
`dataset` for a Dataset) and `source_peer_reviewed` (as recorded; `null` when the graph does not say).
An item whose `evidence_type` is ECO:0000033 (author statement supported by traceable reference: the
source reports another work's result) or its child ECO:0000304 carries `second_hand: true`. A row whose
evidence is all second-hand carries `second_hand` (`cited_by`, the citing sources, and a note:
"second-hand (cited by …)", naming each source by title when the whole document is public and by id
otherwise). `own_work_only: true` leaves such rows out, with the reason
`second_hand_only` and the sources. Like a row resting on a retracted source, it is left out on purpose,
not for missing context.

## Optional variables

A filter on an optional variable that found nothing holds for `missing` and fails for every other op,
so a plan can ask for what has no link of a kind: bind it optionally and filter
`{var: notice, prop: id, op: missing}` ("the tests whose source no notice reaches"). Before this was
fixed (2026-10-06), such a filter dropped every row. A `where` filter names a variable that `match` or a
step declares; any other name (a misspelling) is an error, not a filter that every row passes.

## Retracted and corrected sources

A source's publication status is derived from the notices recorded in the graph, never typed by hand
(`tools/lifecycle.py`): a `RETRACTS` link from a notice Source makes it `retracted`
(`partially_retracted` with `scope: partial`), and an `UPDATES` link makes it `withdrawn`, `expression_of_concern`, `corrected` or `updated` by its
`update_type`. Without a notice it is `current_or_unknown`: current, or nobody has looked
(`status_check` says who looked, when and how).

- Every returned evidence item carries `source_status`. For a partial retraction recorded record by
  record (a retracted Dataset that `INCLUDES` the records), an item also carries `retracted_in_dataset`
  when the dataset comes from its source (the Source the dataset is `REPORTED_IN` or cites; failing
  both, the one Source the same notice retracts in part): only that evidence is retracted, and the
  record's evidence from any other source still stands, even one the notice corrects or retracts in part. Each dataset retracts only the evidence from its own sources; a record that a
  retracted dataset includes without citing any of that dataset's sources rests on the dataset itself.
- A row whose evidence rests only on retracted or withdrawn sources (or evidence retracted with a
  dataset) is left out by default: it goes to `excluded` with the reason `rests_on_retracted_source`,
  the `sources` that are themselves retracted and, apart, the retracted `datasets`, and `limitations`
  says how many. `include_retracted: true` in the plan keeps such rows, their evidence labelled.
- A retraction never deletes a record and does not make a finding false; it removes its support.
  The validator flags the same records (`rests_on_retracted_source`,
  `partially_rests_on_retracted_source`), and the kg-bundle export marks them (`source_status`).

A graph that records no notice answers exactly as before, apart from the `source_status` of each
evidence item.

## Result

Every result carries:

- the plan, the queried graph's id, its schema version and the digest of the document;
- `rows`: the records bound, the returned values as reported, a `second_hand` note for rows resting only on second-hand evidence, and (with `evidence`) the evidence
  items with their sources, years, publication status, kind and peer review. A row carries no access of
  its own;
- `access` (`level`, `note`), the same for every result, `schema_gap` included, and failing closed: the
  least open effective stewardship found anywhere in the queried document, its header
  (`graph.stewardship`) and every node and link, whether or not a row shows it (a notice that decides a
  `source_status` or a retraction, a cited source, a dataset, a record no row reaches), read as `scale
  graph filter` reads it (a missing or malformed access is `institution`; an embargo is read on the
  plan's `as_of`, an ISO date `YYYY-MM-DD`, or today, whichever is earlier, which the note then names;
  today is the earlier of the local and the UTC date, the one clock `scale graph filter`, `scale graph
  search` and the exports read embargoes by:
  it counts as lapsed only when it has lapsed on both, so a later `as_of` never opens an embargo still
  in force, and an `as_of` that is not such a date is a plan error). The note says how many records,
  and whether the header, are less open than public. No part of an answer (a row, a value, a record
  named as left out, a count) is read as more open than the whole document: an answer from a document
  that is not all public goes only where the whole document may go, and a limitation says so and how
  to get a public answer: run the query on the document `scale graph filter --public` makes (or `--as
  <id>` for one reader), whose answers have that view's own access. A view whose reader may not see
  the original header declares the reader's audience in its header (each record keeping its own
  access), so a public view answers `public` when its embargoes have lapsed on the day they are read.
  The limitation never sends a public view back to the filter: on one made before the filter declared
  its audience (it kept the original header) it says to make the view again from the original
  document;
- `excluded`: the first 500 records left out, each once per reason (a record that several rows hold, such
  as a test with two catalyst samples, or that several filters leave out for one reason, is one entry,
  the first filter's), with its reason. The reasons are:
  - a value the plan needs is missing or not comparable: `not_reported`, `not_curated`,
    `ambiguous_in_source`, `withheld` (a value the document queried does not share, as `scale graph
    filter` leaves it: not the source being silent), `not_extractable`, `not_measured`, `not_applicable`,
    `unit_unstated`, `incompatible_unit`, `other_basis`, `not_a_number`, `one_sided_bound` or
    `no_matching_entry`;
  - a row cites a source too late for `published_before`: `cites_later_source` or `no_dated_source`;
  - a row rests only on retracted sources: `rests_on_retracted_source`, unless the plan sets
    `include_retracted`;
  - a row rests only on second-hand evidence and the plan sets `own_work_only`: `second_hand_only`.
- `missing_context`: returned fields that are not reported or not curated, each record's field once
  (however many rows hold the record, and whichever variables bind it: a record that two variables bind is
  listed once, under the first path that returns it);
- `coverage`: what the plan considered, counted in full:
  - `candidates`: the records the match bound;
  - `steps`: each stage's rows in and out, in order (match, every step, where, retracted,
    published_before, own_work_only, text, limit). A step also counts the links or records its filters
    could not evaluate (`left_out_by_reason`, each link or record once per reason) and, when optional, the
    rows it left unbound;
  - `link_types`: the link types traversed;
  - `excluded`: `total`, `listed` and `by_reason`, counted before the 500 cap, each record once per reason
    (records, not rows or filters: the counts never exceed the records the plan reached);
  - `compared_in_unit`: the values a numeric filter compared in its unit, each value once (a record's
    property, however many rows or filters read it);
  - the rows left out for retraction, date or second-hand evidence (`retracted`, `published_before`,
    `second_hand_only`) and the rows returned that rest only on second-hand evidence
    (`second_hand_rows`);
  - `missing_context` (`total`, `listed`);
  - `not_evaluated_in_steps` (`total`, `by_reason`, `rows`): the comparisons the steps' filters could not
    make, summed over the steps, and the rows a required step left out because one of them could not be
    made (no link passed; each step's `rows_not_evaluated`); when no row comes back, those rows make the
    status `missing_context`, the comparisons alone never do;
  - `unfiltered`: the plan narrows nothing (no filter, no text, date or own-work rule, no step a row
    must find), so its rows are a listing;
  - `filtered_for`, when the document is a view `scale graph filter` made: a value it withheld reads as
    `withheld`, but a reference it removed (a ref, a ref-list entry, a map entry keyed by a withheld id)
    is simply not there, so a limitation says that the absences read as `not_curated` or
    `no_matching_entry` may be withheld.
- `limitations`, among them that an absence is an absence in this graph, not in the literature, what
  was left out by reason, the values compared by number, unit and stated basis alone, second-hand rows, a listing, a filtered document, an
  `order_by` that sorted values in several units, and an access that is not public;
- `status`: `answered`, `no_matching_record`, `missing_context` or `schema_gap` (the plan names a
  label, edge or property the schema does not declare; `schema_gaps` lists them).

`--format markdown` prints the access (and its note when it is not public), the rows, the second-hand
notes, the evidence with each source's kind, and the coverage.

Nothing is converted: a numeric filter (`eq`, `ne` and `in` with numbers included) compares only
values in the unit it states, spelled the same, and on the basis it states.

## Competency questions

The catalysis competency questions (`domain/competency/*.yaml`) are plans with the public
example documents they run on and their expected answer (`expect`: status, row counts, values that
must be returned, records excluded by reason code, counted in full from `coverage`, publication
statuses the evidence must carry). A question
may add `variants`: the same plan with some keys changed and what it must answer then (CQ-05 shows the
default exclusion of a retracted source's row and the `include_retracted` opt-in). `scale domains cq`
runs them; `scale check` re-runs them, so a schema change that changes an
answer updates it in the same pull request.

## Feedback into evolution

`scale gap from-query result.json --out-dir gaps/` converts absences into gaps. Every gap carries the
result's `access`: its record ids, fields and question come from the queried document, so a gap whose
access is not public goes only where that document may go. `scale gap issue` says so in the issue body
and on stderr, and `--submit` refuses it; make the gap from a query of the public view instead, or file
it by hand within the document's audience. A gap that states no access, one written by hand or by a
`scale gap from-query` older than this rule, is read as institution, failing closed: it states
`access.level: public` before `--submit` files it.

| absence | gap kind |
|---|---|
| schema_gap | `missing_concept` |
| a value left out or missing, reason `not_reported` | `absent_source_information` |
| a value left out or missing, reason `ambiguous_in_source` | `ambiguous_source_information` (review the source or ask the authors; keep every variant) |
| a value left out or missing, reason `not_curated` | none (curation backlog; in a filtered document, possibly withheld: see `coverage.filtered_for`) |
| a value left out or missing, reason `withheld` or `not_extractable` | none (the source reports it; this view does not share it, or it could not be extracted) |
| a value left out or missing, reason `not_measured` or `not_applicable` | none (the source says it was not measured, or that the property does not apply) |
| a value left out as `one_sided_bound` (a bound, or a value below its detection or quantification limit), or for its unit or basis | none (the source states it; the filter cannot compare it) |
| no_matching_record | `missing_source_coverage` |

## Presenting results

A generated explanation presents the retrieved evidence; it does not replace it. Quote reported
values as reported, attribute interpretations to their authors, keep incompatible bases apart,
say when evidence comes from a retracted, withdrawn or corrected source (its `source_status`), and put
extrapolations in a separately labelled paragraph.

The query-graph skill ([`skills/query-graph/SKILL.md`](../skills/query-graph/SKILL.md)) has
the reading rules, one line each. In short:

- Traverse every link type the question names: a link type not queried is never absent.
- `answered` means only that rows came back; a listing (`coverage.unfiltered`) is not an answer.
- Before reporting "none", give the number of candidates and run at least one other plan (other
  vocabulary, label or direction, a lower `min_score`).
- Name preprints, patents, theses, reports, sources recorded as not peer reviewed, and second-hand
  evidence.
- Count independent works once (SAME_WORK_AS; one primary work cited by several sources).
- Call a conflict only after checking the entity, conditions, unit and basis and interval overlap, and
  say which differs.
- Follow incoming CONTRADICTS and SUPPORTS for returned Claims and values, or say "none recorded".
- Read the units in use before a numeric filter and end with a Limits line from the coverage block.
- A filter reads a value's number, unit and `basis` only: before stating a value, read its
  `as_reported` and `note` for a basis or condition written only there, and say so when there is one.
- Keep Kp and Kc values on different standard states or units apart.
- An answer, and every part of it, goes only where the whole queried document may go (`access`: the
  least open stewardship anywhere in it). For a public answer, query the document `scale graph filter
  --public` makes; for one reader, `--as <id>`.
