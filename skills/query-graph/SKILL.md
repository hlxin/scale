---
name: query-graph
version: 0.2.0
description: Answer a scientific question from scale-catal documents by writing and running a graph query plan that returns rows as reported, with evidence, the records left out and why, its coverage and the kind of answer — reporting absences instead of filling them. When the question asks what to do (how to make a material, how to run a test), the answer is a proposal built from the graph's closest records, each step citing the record it comes from, checked before it is presented and reviewed once by a second agent.
scale_release: ">=v0.3.0"
inputs:
  - A natural-language question
  - The scale-catal documents to query (each pins its schema version)
allowed-tools:
  - "scale graph describe [labels] --domain <domain>"   # what the schema can express
  - "scale graph stats <graph>"                         # the units in use and the link patterns of a document
  - "scale graph query <graph> <plan.yaml>"             # patterns, filters, evidence search, dated paths
  - "scale graph search <graph> <text>"                 # evidence by words and meaning (vectors + BM25)
  - "scale graph recipe <graph> [--preparation <id>]"   # a preparation read whole: its stages and steps in order
  - "scale graph filter <graph> --public | --as <id> --out <view>"   # the view a reader may see, for an answer that may go to them
  - "scale call describe | query | search | recipe"     # the same through the agent tools
  - "python3 -I scripts/precedents.py --requirements <req.json> --graph <graph>"   # a proposal's precedents, in one plan
  - "python3 -I scripts/check_quotes.py <proposal.md> --graph <graph>"   # its quotes and the basis of its records
  - "scale gap from-query (dry run)"
  - write access to the working directory only
outputs:
  - The query plan (YAML) that was executed, and any other plan run before reporting an absence
  - The query result (JSON) with rows, values as reported, evidence, the records left out, the coverage block and the kind of answer
  - A presentation of the result that cites evidence locators, labels hypotheses separately and ends with a Limits line citing the coverage
  - For a question that asks what to do, the proposal: each requirement and how it is met, the steps with the record each comes from, what to measure to confirm it, and what stays open
validation:
  - Every factual sentence in the presentation maps to a returned row and its evidence
  - Numbers are reproduced as reported (value, unit and the reported text), with any computed or converted value labelled as yours
  - Every number computed for an answer (amounts scaled to a ratio, moles from masses and formulas, a sum) is recomputed by code before it is stated
  - Every step of a proposal cites one record's step and its quote, or is labelled a hypothesis
  - Every typed absence and every record left out in the result is reported, not smoothed over
  - The Limits line gives the candidates, what was left out by reason and the values compared by unit and stated basis alone, from the coverage block
human-review:
  - Before a query result is used to support a publication, decision or new experiment
  - Whenever the presentation goes beyond the returned rows (extrapolation or hypothesis)
  - Always before a proposed procedure is run in a laboratory, with a hazard assessment
---

# Query scale-catal documents

A generated explanation is a presentation of the retrieved evidence, not a replacement for it.

## Procedure

1. **Name the distinctions** the question needs (a composition, a feed, a driving force, a control,
   a date, an evidence path, each link type the question names). "Which observations support this
   assignment?" needs evidence; "which rates are comparable?" needs compatible conditions and units.
   List each requirement the question states (a composition and its ratio, a phase, a shape, a size, a
   support, a route) as a distinction of its own.
2. **Find the vocabulary:** `scale graph describe CatalyticTest HAS_COMPONENT … --domain catalysis`;
   `scale graph stats <graph>` for the units in use per property (`units_in_use`) and the link
   patterns (`link_patterns`: source label, link type, target label, count); search the evidence for
   the words the sources use: `scale graph search <graph> "sulfur poisoning" --published-before 1959`.
3. **Write a plan** (`tools/pgraph_query.py` and docs/querying.md document the format):
   `match` a label, follow `steps` along edges (`direction: in` for incoming ones; `edge_as` binds
   the link), `where` filters on value objects with a `unit` (and a `basis` when the values state
   one; nothing is converted, so one plan per unit and basis), paths into maps and lists
   (`results.*[target=<species id>]`), optional `text` search over the evidence (it ranks only the evidence of the
   records its `vars` name and of the links the rows bind: name the records that carry the quotes), `published_before`
   for a dated question, `own_work_only` to leave out second-hand rows, `return` fields,
   `evidence: true`, `order_by`, `limit`. A question that compares or ranks values ("which rates are
   comparable?", "the highest current density") takes `comparison: scientific` (scale-catal 0.3.0 on): each
   value is then compared only within one unit and one context its quantity contract names (a potential's
   reference scale, a current density's normalization, a pressure's convention, a flow's reference
   conditions, a share's species; a computed energy's kind, reaction, level of theory and charge treatment,
   scale-catal 0.7.0 on), stated with `context: {potential_reference: rhe}` to check one, or left
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
   assignment rests on; CQ-18 how batches of one nominal catalyst differ, CQ-19 nominal and measured compositions,
   CQ-20 sizes by technique, CQ-21 what a fitted coordination number rests on and CQ-22 what a source leaves
   unstated). A step on an edge
   type follows its specializations too (`CONTROL_FOR` finds `DARK_CONTROL_FOR` links), as `to` finds subtypes.
   A question with several requirements takes one plan that asks for them all and one plan per requirement,
   whatever else the records hold: the record that reaches a 5 nm size or an ordered phase with other elements
   is found too, and is often the one that says how (for a proposal, step 6's `scripts/precedents.py` does this with
   one plan).
4. **Run it:** `scale graph query <graph> plan.yaml --format markdown` (or `scale call query`). Run the plans of a
   question together, in one script, and read their rows by code. On a large document, call the tools through one
   process that keeps it loaded (`scale mcp`, `scale serve`, or `ScaleToolkit` in Python): each `scale graph` or
   `scale call` command reads the whole document again.
5. **Read the kind of answer and the coverage:** `answered`; `no_matching_record` (none in this
   graph, which says nothing about the literature); `missing_context` (records match but a value
   needed is missing or in another unit; see `excluded` and `missing_context`); `schema_gap` (the
   schema cannot say it: route to schema evolution). `coverage` gives the candidates, each stage's
   rows in and out, everything left out by reason, each record once (`excluded` lists only the first
   500), the values compared in a filter's unit (`compared_in_unit`), `unfiltered` and, for a
   filtered view, `filtered_for`. `access` says where the answer may go: the least open stewardship
   anywhere in the queried document.
6. **Propose, when the question asks what to do** (how to make a material, how to run a test the graph holds
   no record of).
   - **Precedents, in one call.** Write the requirements as tests on the fields of one plan, hardest first (the
     elements, then the phase and the shape, then the size; a support last, since it is usually a step of its own),
     and run `scripts/precedents.py` once (again only when a test was written wrong; search the evidence only for
     a requirement no record states). Its default plan (`references/precedents-plan.json`) returns every particle
     state of a scale-catal document with its catalyst and composition, class, shape, size, phases, components and
     preparation; the script ranks the preparations by the requirements they meet, the first listed weighing most,
     counts the records that do not state each one, and lists for each requirement the closest records that meet it.
   - **A base for the skeleton, each aspect from the record that controls it.** The base gives what the steps share:
     the solvent, the temperature range, the atmosphere, the work-up. Take the top candidate unless a lower one shares
     more of what is hard to change. Each aspect it does not meet comes from the closest record that meets it (the
     same elements first, then the same majority element): the precursors from one, the capping agent that sets a
     size from another, the treatment that orders a phase from a third, each compatible with the skeleton (its
     solvent, temperatures, atmosphere), cited, with why it should hold here. An aspect no record reaches is
     unresolved: say what is tried instead, labelled as general knowledge.
   - **Read whole only** the base, the other preparations of its source (its controls and variants often hold what a
     requirement needs) and the record each aspect comes from, with `scale graph recipe <graph> --preparation <id>`:
     about six recipes, not every preparation of every source.

   A requirement is never dropped silently, and general knowledge never replaces a record the graph holds without
   saying why that record does not apply. Each step cites one record's step and its quote, or is a labelled
   hypothesis; records are named by their full ids. Read every composition and quantity on the basis its record
   states (by mass, by atoms) before computing with it, set the amounts to the question's ratio and compute the moles
   by code. **Check before presenting** with `scripts/check_quotes.py`: every quotation is looked up in the records
   the proposal names, whose compositions it lists with their unit and basis. **Review once,** by a second agent you
   launch with a fresh context and only the question, the proposal and the check's output (otherwise yourself as
   someone else would; the person who asked waits only for the final answer), kept light: at most five findings, on
   what the check cannot see: a step its record does not support, a number on the wrong basis or a ratio the
   amounts do not give, a closer record left out, a transfer from other elements, sizes or shapes treated as the same
   context, a missing parameter a person needs to run a step. Fix what it finds once, by editing the proposal (no
   new search unless a finding names a record to read) and running the check again; what stays open goes in the
   Limits, never argued away.
7. **Present.** Lead with the supported answer. For each value give it as reported, with its source,
   year and locator. Keep incompatible units and bases apart. Label interpretations as the source
   authors'. Put any extrapolation in a separate, labelled paragraph. End with a **Limits** line
   from the coverage block: candidates, rows, what was left out and why, and that the values were
   compared by number, unit and stated basis alone (in a scientific comparison: and within one context,
   group by group, with the values left out for their context, `missing_context` and
   `incompatible_context`, named as such: there is no ranking across groups). A proposal fits in two pages (under
   about 1,000 words): what it proposes, the few candidates considered (what each meets, and why the base), each
   requirement and how it is met (by the base, transferred, unresolved), the numbered steps, each with its basis (retrieved, adapted or hypothesis) and its record, the charges and the
   ratio recomputed, what to measure to confirm the result, and the Limits with the review's open findings. The
   records set aside, the review and how each finding was settled, and the check's output stay in the working files.
   It is a proposal for a person to review, never a validated procedure.
8. **Route failures.** `scale gap from-query result.json --out-dir gaps/` turns a schema gap into a
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
- A size, a composition or any other characterization result is the measurand its Variable names: ask for one by its
  Variable (a field step to `variable`, filtered on its `quantity_kind`, CQ-20), and report a microscopy size, a
  crystallite size and a hydrodynamic size apart. Report a nominal value as nominal and a measured one with its
  technique, information depth and state (CQ-19); two batches or two purchased lots of one formulation are two
  records, never one batch.
- An assignment of activity is a claim (`ABOUT` roles active, spectator, precursor, inhibitor): report it as the
  authors', with what supports and contradicts it, never a phase as active because it is abundant. Operando means
  characterized while the kinetics are measured: an observation labelled operando was made so only where its `DURING`
  link states it (same specimen, timing simultaneous, kinetics measured); an overlap or a change that tracks the
  activity is not evidence of activity.
- An answer goes only where the whole queried document may go: the result's `access` is the least open stewardship anywhere in it (its header, every record, the notices, sources and datasets no row shows included), and no part of the answer (a row, a value, a record named as left out, a count) is more open. When it is not public and the answer is for readers the document does not admit, never pass it on: query the view `scale graph filter --public` (or `--as <id>`) makes for them, whose answers have that view's own `access`, and say that the view holds only what they may see. A second-hand note names its sources by id unless the document is all public. Embargoes are read today, the earlier of the local and the UTC date, as every SCALE path reads them (an `as_of` YYYY-MM-DD may read them on an earlier day, never a later one). A `scale graph search` result carries the same `access`.
- Synthetic examples (`data_status: synthetic_example`) are not evidence about the world; use them only to test a plan, and label them.
- An absence means absence in the queried graph, never in the literature.
- A record agents extracted and no person checked (its stewardship's `autonomy_level`) is a lead: say so when a
  decision of a proposal rests on one of its values (a size, a shape, a phase, a class).
- What a proposal aims at is a hypothesis until it is measured: a nominal ratio does not prove the composition
  obtained, a treatment below a transition does not prove the phase, a low loading does not prove isolated atoms.
  Name the measurement that would show each.
- Rows resting only on retracted or withdrawn sources are left out by default (`excluded`, reason `rests_on_retracted_source`); bring them back only on purpose (`include_retracted: true`) and say so. Every evidence item carries its source's `source_status`: name a retracted, withdrawn, corrected or concerned source when you cite it (docs/querying.md).
