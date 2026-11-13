---
name: query-graph
version: 0.3.1
description: Answer a scientific question from scale-catal documents by writing and running a graph query plan that returns rows as reported, with evidence, the records left out and why, its coverage and the kind of answer — reporting absences instead of filling them. When the question asks what to do (how to make a material, how to run a test), the answer is a proposal built from the graph's closest records, each step citing the record it comes from, checked before it is presented and reviewed once by a second agent. Use whenever the user asks what the sources report about something, or how to make a material or run a test, from scale-catal documents.
scale_release: ">=v0.3.0"
inputs:
  - A natural-language question
  - The scale-catal documents to query (each pins its schema version)
allowed-tools:
  - Bash(scale graph describe:*)   # what the schema can express
  - Bash(scale graph stats:*)   # the units in use and the link patterns of a document
  - Bash(scale graph query:*)   # patterns, filters, evidence search, dated paths
  - Bash(scale graph search:*)   # evidence by words and meaning (vectors + BM25)
  - Bash(scale graph recipe:*)   # a preparation read whole: its stages and steps in order
  - Bash(scale graph filter:*)   # the view a reader may see, for an answer that may go to them
  - Bash(scale call describe:*)   # the same through the agent tools
  - Bash(scale call query:*)
  - Bash(scale call search:*)
  - Bash(scale call recipe:*)
  - Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*)   # scripts/precedents.py (a proposal's precedents) and scripts/check_quotes.py (its quotes)
  - Bash(scale gap from-query:*)   # local files; nothing filed
  # write access to the working directory only
outputs:
  - The query plan (YAML) that was executed, and any other plan run before reporting an absence
  - The query result (JSON) with rows, values as reported, evidence, the records left out, the coverage block and the kind of answer
  - A presentation of the result that cites evidence locators, labels hypotheses separately and ends with a Limits line citing the coverage
  - For a question that asks what to do, the proposal: each requirement and how it is met, the steps with the record each comes from, what to measure to confirm it, and what stays open
validation:
  - Every factual sentence in the presentation maps to a returned row and its evidence
  - Numbers are reproduced as reported (value, unit and the reported text), with any computed or converted value labelled as yours
  - Every number computed for an answer (amounts scaled to a ratio, moles from masses and formulas, a sum) is recomputed by code before it is stated
  - Every step of a proposal is tagged retrieved, adapted or hypothesis; a retrieved or adapted step cites its record's step and quote on its Record line, an adapted step lists each change and its reason
  - A proposal is one procedure a person can run as written: every amount, temperature, time and atmosphere is fixed in its step, and nothing outside the steps changes one
  - Every recommendation is labelled as one, sits next to the step it concerns, leaves that step valid as written, and is never presented as a record's step
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
     and run `scripts/precedents.py` (again only when a test was written wrong, or within the chosen route; search
     the evidence only for a requirement no record states). Its default plan (`references/precedents-plan.json`)
     returns every particle state of a scale-catal document with its catalyst and composition, class, shape, size, phases, components and
     preparation; the script ranks the preparations by the requirements they meet, the first listed weighing most,
     counts the records that do not state each one, and lists for each requirement the closest records that meet it.
   - **Choose with the graph: it gives the options, you choose among them.** Run it with `--consensus 50`: it reads
     the best-ranked records whole and counts, each count with records to cite, their routes, the precursors of each
     metal with the routes each is used in, their inputs by function (the reducing agent, the capping agent, the
     solvent), the temperature and time of each action and their commonest sequences. These are the options: what
     has been done for targets like this one. Choose among them as a chemist would for this target, not by the count
     alone and not by copying one record:
     1. the route the question names; else the one among the options that suits what it asks (the support and how
        a support is loaded, the phase, the size and the shape), saying why when it is not the commonest. Weigh the
        options against the route a chemist would reach for first for this kind of target, the standard and
        well-controlled one: when the graph holds records of it, prefer it to a route that is harder to control or
        needs unusual equipment or purification, unless the question's requirements need that route; when the graph
        holds no record of it, name it in one line and say why the records' route is followed. Then count again within
        the chosen route (`--within <the route's requirement>`);
     2. for each metal, a precursor the records use in that route and that fits the rest of the procedure (the
        solvent, the reducing agent, the support, the temperatures);
     3. the reducing agent, capping agent, solvent, temperatures, times and order of the steps that the records of
        that route use.

     Give each choice with its count and records. The chemistry (route and precursors) follows a single record only
     when it has the same metals, route and kind of support. A record that matches only the size, shape, phase or
     class guides the conditions that set them (temperatures, times, capping agent, ratios). Your own knowledge of
     the chemistry decides between options; it brings in a choice of its own only where the options are empty or
     thin (under three records), labelled as such, and never replaces an option the graph holds without saying why
     that option does not apply.
   - **Read whole only** the one or two records most of the choices come from (for the amounts and the order of the
     steps) and a close record you follow, with `scale graph recipe <graph> --preparation <id>`.
   - **What a record measured, and what its authors say they obtained, outrank its labels.** A record's composition,
     class, phase, shape and size may be what its authors aimed at or what they obtained; the check below lists, for
     each record you name, what a characterization of its samples measured and the authors' own outcome claims.
     - A record whose measurement or outcome claim shows it missed a requirement (another measured composition,
       segregation, a phase that did not form) is evidence against its route for that requirement, not a precedent
       for it. Name it as such, choose another base or say that none reached the requirement, and say what the
       record's result implies for the route you propose.
     - A record that measured what it claims is the stronger precedent for that requirement: prefer it.
     - A requirement a record meets only by its label (nothing measured) is said once to be the record's label.
     - A stated composition that differs from the record's own feed is what the record reports obtaining from that
       feed. Keep that feed when the record's product is the asked composition.
   - **Take from a record only what its own product supports.** The check also lists what each named record
     obtained: its shape, architecture and phases, as measured or as a label. Before a step comes from a record,
     compare that product with the requirements the step can affect.
     - Some transfers cross a difference: a growth sequence, ligand set, ratio or temperature taken from a record whose
       product had another shape, another architecture (core–shell, Janus, heterodimer, separate particles) or a
       secondary phase (an oxide, a sulfide). For each one, say what the record obtained and the mechanism that may
       carry over (growth habit, ligand binding, a phase that forms at that ratio), and label the step a hypothesis.
       Prefer a record whose product meets the requirement.
     - A record whose product was not the target, at the target's composition or with the target's reagents, is
       evidence against that combination. Weigh it when choosing the route and the reagents, not only in the Limits.
   - **A check inside the procedure accepts only what the question asks.**
     - A composition gate uses the asked ratio with a stated tolerance.
     - A phase is accepted only by the measurements that tell it from its alternatives, never by one peak. For a
       disordered alloy: several reflections and no superlattice ones, plus element maps for mixing. For an ordered
       phase: its superlattice reflections.
     - A shape is accepted by a counted fraction.
     - A looser check that only decides whether to go on is labelled exploratory, apart from acceptance.
   - **A condition no record states** (a time, a pressure, a sealed vessel) is a hypothesis. One with a hazard (a
     solvent above its boiling point in a closed vessel, H2, thiols or sulfur at high temperature) says what must be
     assessed before it is run.

   A requirement is never dropped silently, and general knowledge never replaces a record the graph holds without
   saying why that record does not apply. Each step cites one record's step and its quote, or is a labelled
   hypothesis; records are named by their full ids. Read every composition and quantity on the basis its record
   states (by mass, by atoms) before computing with it, set the amounts to the question's ratio and compute the moles
   by code.

   **Check the chemistry in this target's context.** A step that worked in its record may not work once it is moved
   to other metals, another solvent, support, scale or equipment. So read the whole procedure once more as the chemist
   who will run it:
   - Can each reductant reduce each precursor, in this solvent and at this pH?
   - Does the solvent or medium destroy or prematurely reduce a reagent?
   - Do two of the reagents form a precipitate?
   - Does the support, solvent or vessel tolerate each temperature and atmosphere?
   - Does the equipment do what the step asks?
   - Is there a capping agent or support where particles must stay small?
   - Do the amounts give the asked ratio?

   Your knowledge of the chemistry is the check, and the steps carry what it finds, so that the proposal is one
   procedure a person can run as written. Where the check finds that a step would fail in this context, or that another
   choice would clearly work better here, change the step itself and label it *adapted*: in one line, what its record
   does and why this target needs otherwise. The record's step and quote stay cited, so the step stays traceable.
   Nothing outside the steps may change what a step says: no recommendation, note or condition ("if …, use … instead")
   overrides an amount, temperature, time, atmosphere or reagent the step gives. A **Recommendation (not from a
   record)** is only optional advice that leaves the step valid as written (a check to run, a precaution, a
   refinement), added where it makes sense; most steps have none. Options to try instead of the proposed procedure go
   in a short list of alternatives after the steps. A parameter a person needs that the records do not state (the
   atmosphere, a gas flow, a ramp, the vessel) is filled with a typical value, labelled "typical, not from a record".
   It is not left open.

   **Check before presenting** with `scripts/check_quotes.py`: every quotation is looked up in the records
   the proposal names, whose compositions it lists with their unit and basis, and beside them what each record
   obtained (shape, architecture, phases), what a characterization of its samples measured and the authors' outcome
   claims (or that none is recorded). **Review once,** by a second agent you
   launch with a fresh context and only the question, the proposal and the check's output (otherwise yourself as
   someone else would; the person who asked waits only for the final answer), kept light: at most five findings, on
   what the check cannot see. First comes chemistry that would fail in this context: a reductant that cannot reduce a
   precursor, a medium or pH that destroys a reagent, a precipitate, a temperature or atmosphere the support or
   solvent cannot take, equipment that cannot do the step, no stabilizer where size matters. Then come a step its
   record does not support, a number on the wrong basis or a ratio the amounts do not give, a precedent whose own
   measurement or outcome claim contradicts what the proposal takes from it, a step taken from a record whose own
   product differs from the target in what that step controls (shape, architecture, a secondary phase), an acceptance
   check looser than the requirement or unable to tell the asked phase from its alternatives, a closer record left out,
   a transfer from other elements, sizes or shapes treated as the same context, a missing parameter a person
   needs to run a step, and anything outside the steps that changes what a step says. Fix what it finds once, by editing the proposal (no
   new search unless a finding names a record to read) and running the check again; what stays open goes in the
   Limits, never argued away. A finding about the chemistry of a step is settled by changing the step (labelled
   adapted, with what its record does in one line), not by a recommendation beside it; a finding that a step does not
   say what its record says is fixed in the step. The final proposal is still one procedure that runs as written.
7. **Present.** Lead with the supported answer. For each value give it as reported, with its source,
   year and locator. Keep incompatible units and bases apart. Label interpretations as the source
   authors'. Put any extrapolation in a separate, labelled paragraph. End with a **Limits** line
   from the coverage block: candidates, rows, what was left out and why, and that the values were
   compared by number, unit and stated basis alone (in a scientific comparison: and within one context,
   group by group, with the values left out for their context, `missing_context` and
   `incompatible_context`, named as such: there is no ranking across groups). A proposal fits in about two pages
   (about 1,000 words for the parts before the steps and after them).

   **A proposal's layout, in this order:**
   1. What it proposes, in two or three sentences.
   2. The counts the choices rest on, and any close record followed.
   3. Each requirement and how it is met (by the base, transferred, unresolved).
   4. The steps.
   5. The alternatives.
   6. The charges and the ratio, recomputed.
   7. What to measure to confirm the result.
   8. The Limits, with the review's open findings.

   **Each step** keeps four kinds of content apart, so a reader always sees what comes from a record, what was
   changed, and what is the proposer's own reasoning:

   ```
   ### Step N. <action in a few words> — RETRIEVED | ADAPTED | HYPOTHESIS
   **Do:** the instruction as a person runs it, complete (every amount, temperature, time, atmosphere), with
   chemical formulas written with sub- and superscripts (HAuCl₄·3H₂O, N₂, min⁻¹). A charge lists its reagents as
   bullets.
   **Record:** `<full record id>`, step <n>: "<the verbatim quote it rests on>" (retrieved and adapted steps only).
   **Changed:** each difference from that record, as "<record's value> → <this proposal's value>" (adapted only).
   **Why:** the proposer's reasoning for the change, or for a hypothesis step, in one or two sentences.
   **Typical:** the values no record gives, filled with a common value (a ramp, a gas flow, a hold), if any.
   **Hazard:** what must be assessed before the step is run, if anything.
   ```

   - **The tag:** RETRIEVED takes the record's step as it is; ADAPTED changes it; HYPOTHESIS has no record to rest
     on.
   - **The quote:** a quote may be garbled by the source's text extraction. It stays verbatim (the check looks it up)
     but only on the Record line; the Do line never copies it.
   - **What stays in the working files:** the records set aside, the review and how each finding was settled, and the
     check's output.

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
