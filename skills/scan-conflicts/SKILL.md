---
name: scan-conflicts
version: 0.1.0
description: Find values in scale-graph documents that seem to disagree, by pairing them with query plans that state units and bases, and classify each pair as a genuine conflict, an apparent one (with the axis that explains it) or not comparable — as a report, or as comparison claims a person reviews; never rewriting a value.
scale_release: ">=v0.1.0"
inputs:
  - The scale-graph documents to scan (each pins its schema version)
  - What to scan (a quantity on a kind of record, e.g. methanol space-time yield of Cu/ZnO catalysts), or a question
allowed-tools:
  - "scale graph describe [labels] --domain <domain>"   # what the schema can express
  - "scale graph stats <graph>"                         # the units in use per property and the link patterns
  - "scale graph query <graph> <plan.yaml>"             # the values to pair, with their conditions and evidence
  - "scale graph search <graph> <text>"                 # the words the sources use
  - "scale graph validate <doc>"                        # a document with the records this skill proposes
  - "scale graph filter <graph> --public | --as <id> --out <view>"   # the view a reader may see, for a report that goes to them
  - "scale call describe | query | search | validate"   # the same through the agent tools
  - write access to the working directory only
outputs:
  - The query plans that returned the values, with their results (coverage blocks included)
  - A conflict report (JSON or Markdown) listing each pair with its values as reported, evidence, classification and the axis it differs on
  - Optionally, after a person agreed, a document (or a patch) adding comparison Claims with CONTRADICTS or SUPPORTS links
validation:
  - Every pair in the report cites both values as reported (value, unit, as_reported) and their evidence locators
  - Every pair called genuine names the checks it passed (entity, conditions, unit and basis, interval overlap)
  - "Records added, if any, validate (`scale graph validate`) and change no existing value or status"
human-review:
  - Always, before a conflict is written into a document, and before anything is set to disputed
  - Whenever the pair spans sources of different kinds (a patent and an article, a review and its primary work)
---

# Scan scale-graph documents for conflicting values

A conflict is two statements about the same thing under the same conditions that cannot both hold.
Most disagreements between sources are not that: they differ in the catalyst, the conditions, the
basis or the definition. This skill finds the pairs, says which kind each is and why, and leaves the
values as they are.

## Procedure

1. **Fix the scope.** Name the quantity (a property, or a `results` key with its `target`), the kind
   of record it sits on and the entities to compare (catalysts of one family, one reaction).
   Catalysts, samples and tests are never shared across sources, so a cross-source pair compares
   records that are alike, not the same record.
2. **Read what is there:** `scale graph stats <graph>` (the units in use for the property, the link
   patterns), `scale graph describe <Label> --domain catalysis`.
3. **Return the values with what decides comparability.** Write a plan (the query-graph skill, and
   docs/querying.md) that returns the value with its unit, the conditions that matter (temperature,
   pressure, feed, space velocity, the catalyst's composition and state), the source and its year,
   and `evidence: true`. Every numeric filter states its unit and compares only values in that unit,
   spelled the same, case included, once runs of whitespace count as one space (`mPa` is not `MPa`,
   `mol%` is not `%`, `barg` is not `bar`), and on the basis it states (`basis`), or none when it
   states none: nothing is converted, so write one plan per unit and basis in use (`scale graph
   stats`), never one in `not stated`: that placeholder for a number printed without a unit is no unit
   (stats count it under `(no unit)`, and a plan leaves its values out as `unit_unstated`). Read the coverage block: what was left out, and why (`incompatible_unit`, `other_basis`,
   `unit_unstated`, `not_a_number`), is part of the answer. A filter reads only a value's number,
   unit and `basis`: read each value's `as_reported` and `note` for a basis or condition written
   only there (gauge, per pass, on hydrogen) before you pair it.
4. **Pair** the rows that a reader would compare: same quantity, same reaction, alike catalysts.
5. **Classify each pair:**
   - **apparent** when the values differ on an axis that explains it: the entity (another
     composition, phase, support or loading), a condition, the unit or basis (gauge or absolute, per
     pass or overall, carbon or mole basis), the definition (apparent or intrinsic, Kp or Kc, another
     standard state), the catalyst's state, or the time on stream. Name the axis.
   - **genuine** only when the entity, the conditions (within the precision printed), the unit and
     basis and the definition agree and the stated intervals (uncertainty, ranges, bounds) do not
     overlap.
   - **not comparable** when a value needed to decide is missing (`not_reported`, a basis not
     stated) or the two are in different units (nothing is converted; a conversion you make yourself
     is yours, labelled, never the sources'): say which.
6. **Report.** For each pair: both values as reported with their sources, years and locators, the
   classification, the axis or the checks passed, and the plans that returned them. Count independent
   works (sources joined by SAME_WORK_AS, or one primary work cited twice, count once), and name
   second-hand evidence (ECO:0000033) and sources not peer reviewed.
7. **Record, only when a person agrees.** A genuine conflict, or an apparent one worth keeping, may
   be written as existing kernel records, never as new properties:
   - a comparison Claim (`claim_kind: comparison`, `claim_status: proposed`, `origin: curated`, its
     statement in your own words: what differs and on which axis) `ABOUT` both tests, with a
     `SUPPORTS` link from each test whose `premise_refs` point at its value (`{record, path}`, e.g.
     `/results/space_time_yield`);
   - or, when one source's finding is already a Claim, a `CONTRADICTS` link from the other source's
     test to that Claim, with `premise_refs` to both values.

   Each link's `warrant` names the axes checked, `assessed_by` is the scanning Software and
   `assessed_at` the date, and its evidence is the evidence items of the values it cites. Give each
   Claim and link its own `stewardship`, stated, never inherited from the header: the least open of
   the stewardships of the records it is about, the values it cites and the sources of their evidence
   (the results' `access` level when you cannot tell, since nothing in the document is less open).
   Its statement describes those values, so `scale graph filter` and an export must withhold it
   wherever they withhold what it describes. When those stewardships are not all one audience (a test
   of project P beside one of project Q, a project's record beside an institution's), none of them is
   the least open, and neither is either project's stewardship: do not write the Claim into the shared
   document (keep the pair in the report, which goes only where every queried document may go), or
   give it and its links `access: institution` with `contributed_by` naming only institutions that
   may see every record, value and source it describes, never one project's stewardship. Validate the
   result. A person, never this skill, sets a `disputed` status.

## Rules

- Never rewrite, average, delete or choose between values; never change a record's status.
- Never call a pair a conflict before checking the entity, the conditions, the unit and basis, the
  definition and whether the intervals overlap; say which of these the values differ on.
- A missing value makes a pair not comparable, never "agrees".
- An absence of conflicts means none found in the queried graph, never none in the literature; say
  how many pairs were examined.
- The report, and every pair in it, goes only where every queried document may go: each result's
  `access` is the least open stewardship anywhere in its document (rows carry none of their own, and no
  part of a result is more open). For readers a document does not admit, scan the view `scale graph
  filter --public` (or `--as <id>`) makes for them instead; its results have that view's own access.
- Synthetic examples (`data_status: synthetic_example`) are not evidence about the world; use them
  only to test plans, and say so.
