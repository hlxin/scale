# Curating one methanol-synthesis source into scale-graph 0.1.0

This guide is for a curator (a person or an agent) curating **one source** of the frozen corpus
(`corpus/manifest.json`: the in-scope sources, published before its cutoff date). It applies the
`curate-source` skill (`tools/skills/curate-source/SKILL.md`) to this corpus. The result is one
**fragment**, `curation/fragments/<slug>.json`, which must pass
`python tools/curation.py check curation/fragments/<slug>.json` before it counts.

Fidelity to the source matters more than coverage. The source is the only authority: nothing
from your own knowledge, from later literature or from the checklist goes in unless this
source's text says it, and never any knowledge of what happened after the source was published.

## 1. Get the brief

```
python tools/curation.py brief <slug>        # run from examples/methanol-synthesis-pre1966/
```

It writes `work/briefs/<slug>/`:

- `text.txt`: the page texts, each page headed `===== PDF page N (text_layer|ocr) =====`. This is
  the text your quotes are checked against. OCR pages contain OCR errors; quote them **as they
  are** (copy the characters exactly) and give a corrected reading in the evidence `note` if it
  matters.
- `schema.json`: every label and edge type you may use, with their properties, and the `catalysis` checklist
  (`scale graph describe --domain catalysis`). Use only what it declares. (The fragments were curated
  under the consortium schema repository's scale-graph 0.1.0 and its `thermocatalysis` driving-force profile; the
  public graph follows today's schema, which has one checklist.)
- `checklist.json`: earlier extractions of this source (claims and data-table rows). It is a
  **checklist of what to look for, not evidence**: find each item in the text and quote it, or
  leave it out. Earlier extractions made mistakes; do not copy their interpretations.
- `brief.json`: the source id, its metadata, and the shared ids.

Read the whole text of a source up to 40 pages. For a longer one (a thesis or a report), read
the contents, the abstract or summary, the conclusions and every section about methanol-synthesis
catalysts, their preparation, their testing, poisons and feed purity, kinetics and equilibrium;
record in `coverage` exactly which pages you read.

## 2. Ids

- Records of this source: `ex:msyn/<slug>/<kind>/<local>`, e.g.
  `ex:msyn/10.1021-ie50228a016/catalyst/cu-zn-1-1`, `.../test/table2-row3`, `.../claim/sulfur-poisons-cu`.
  Links: `ex:msyn/<slug>/link/<n>` (any unique local part).
- Shared chemistry, merged across sources:
  - species `ex:msyn/species/<key>`: a compound by its formula lower-cased, letters and digits only
    (`species/zno`, `species/cr2o3`, `species/co` for carbon monoxide), a single element by its
    name (`species/copper`, `species/cobalt`). The brief lists the common ones with the name to use.
    A named, defined compound ("copper nitrate", "ammonium chromate") may take its formula and the
    shared id: that is its name's meaning, not a claim. A mixture, a commercial product or an
    ambiguous name ("zinc white", "carbonyl") stays source-specific, `ex:msyn/<slug>/species/<name>`;
  - the canonical reactions in the brief (`ex:msyn/reaction/co-hydrogenation-to-methanol`,
    `.../co2-hydrogenation-to-methanol`, `.../water-gas-shift`, …) with exactly the equation given.
    A reaction the source treats differently (another product slate, higher alcohols) is a
    source-specific Reaction.
- Never merge catalysts, samples or tests across sources: two papers' "copper-zinc catalysts" are
  two Catalyst nodes.

## 3. What to record

The source defines what can be recorded; the schema defines what a record means.

| the source says | record |
|---|---|
| a catalyst formulation ("Cu–Zn 1:1", "zinc chromite", "Example 3") | **Catalyst** `{name, catalyst_family, nominal_formula, properties}`; `HAS_COMPONENT {role, fraction, fraction_basis, role_detail}` → ChemicalSpecies or Material. Roles: `active_component`, `promoter`, `support`, `binder`, `precursor`, `inert`, `not_stated` (when the source does not say). |
| a prepared batch that was tested | **CatalystSample** `{sample_kind: batch}` `-HAS_FORMULATION→` Catalyst; `-PREPARED_BY→` **Preparation** `{method, steps, temperature, …}`; `-PREPARED_FROM {role: precursor, amount}→` species; `-TREATED_BY {order}→` **Treatment** `{treatment_kind: reduction, …}` |
| a run, an example of a patent, a table row with a result | **CatalyticTest** `{test_kind: activity \| kinetics \| stability \| control \| screening, driving_forces: [thermo], experiment_kind: physical, temperature, pressure, space_velocity, flow_rate, duration, time_on_stream, conversion, yield, selectivity, space_time_yield, production_rate, results: {…}, conditions: {…}}`; `-USES_CATALYST {state}→` CatalystSample; `-FED_WITH→` **Feed** (`-HAS_COMPONENT {role: reactant \| diluent, fraction}→` species; `ratios`); `-IN_REACTOR→` **Reactor** `{reactor_kind}`; `-OF_REACTION→` Reaction |
| an equilibrium calculation or estimate the source reports | CatalyticTest `{test_kind: equilibrium_estimate, experiment_kind: computational}` or **Analysis**/**Computation** `-OF_REACTION→` Reaction |
| a measurement on a catalyst (X-ray, surface area, analysis) | **Characterization** `{technique, results}` `-CHARACTERIZES {state}→` CatalystSample; `-DETECTS→` Material |
| an interpretation or conclusion of the authors | **Claim** `{statement, claim_kind, claim_status: proposed \| supported, inference_type}`; `test -CONCLUDES→ claim` or `test -SUPPORTS→ claim`; `claim -ABOUT→` what it is about |
| a proposed explanation ("may", "probably", "it is suggested") | **Hypothesis** `{statement, hypothesis_kind, hypothesis_status: proposed}`, links with `status: hypothesized` |
| a poison or inhibitor | `Catalyst \| Reaction \| CatalyticTest -INHIBITED_BY {inhibition_kind, negated}→` species |
| "catalyst X catalyzes reaction Y" | `Catalyst -CATALYZES {context: [tests]}→` Reaction |
| a comparison of catalysts the source makes | `Catalyst -COMPARED_WITH→` Catalyst, with the quote |
| a patent claim | a **Claim** `{claim_kind: generalization, statement}` `-ABOUT→` the catalyst or process; the patent's examples are CatalyticTests |

Not this source's findings: a result the source only **cites** from other work. Leave it out (or,
if the source's own argument depends on it, a Claim with `note: "cited from …"`, never a test).

## 4. Values

A value is a value object in the **unit the source printed**:

```json
{"status": "present", "value": 360, "unit": "°C", "as_reported": "360° C."}
{"status": "present", "lower": 250, "upper": 260, "unit": "°C", "as_reported": "250–260°"}
{"status": "present", "value": 1, "unit": "%", "bound": "upper", "as_reported": "did not exceed one per cent"}
{"status": "not_reported", "missing_reason": "not_stated_in_source"}
```

- A number without a physical unit (a ratio, a count, an equilibrium constant) takes `"unit": "1"`
  and keeps its printed form in `as_reported`; keys of `results` and `conditions` maps are
  lower-case snake_case (`kw`, `h2_co_ratio`), and every map entry is a value object.
- A number that is present but illegible (OCR) is not recorded as a value: list an
  `extraction_error` gap.
- `qualifier` is `exact` or `approximate` ("about", "approximately", "~" → `approximate`); keep the
  source's word in `as_reported`.
- Never convert a unit, never compute a value the source does not give, never fill a typical value.
- A value that exists only in a figure (no printed number): read it only if the figure's scale makes
  it unambiguous; give it `qualifier: approximate`, a `note: "read from Figure N"`, and evidence with
  `kind: figure`, the figure's locator and its caption (or the nearest text about it) as the quote.
  If the points cannot be read reliably, record the test without the value and list a gap.
- A missing value you did not look for is simply left out; a value the source is silent on, and
  that the checklist asks for (must) for a thermally driven test (temperature, pressure, feed), is `not_reported`.
- Quantities without a declared property go in `results` or `conditions` maps as value objects.

## 5. Evidence

Every node has a `name` (a short human-readable label). Every node that states something and
**every link** carries evidence:

```json
{"source": "ex:msyn/source/<slug>", "locator": "p. 3, Table II", "kind": "text | table | figure",
 "quote": "…verbatim from text.txt, a sentence or two (≤ 300 characters)…"}
```

- `locator` starts with the **PDF page** from the `===== PDF page N` header (`p. 3`, `p. 3–4`), then
  what you see (`Table II`, `Example 3`, `claim 2`).
- `quote` is copied character for character from `text.txt` (whitespace and case may differ). It
  must support the record: the quote for a link says what the link says.
- Link `status`: `asserted` (the source states it), `hypothesized` (proposed), `disputed`.
- A quote that spans a column break or page break may be given as two evidence items.
- Use `CONTROL_FOR` only when the source presents a run as a control or blank, and give
  `differs_in`: a list of ids of **Variable** nodes of this source
  (`ex:msyn/<slug>/variable/temperature` with `{"name": "temperature", "scale": "quantitative"}`;
  `"scale": "nominal"` for a catalyst or a feed), naming what differs.

## 4a. Reading scanned pages: page image and OCR together

Old scans lose values in OCR: table cells run together, exponents and subscripts vanish, digits
turn into letters. Read the **page image** as well as the text, and let OCR check what you read.

1. `python tools/curation.py pages <slug>` renders every page (`work/pages/<slug>/p<N>.png`, not
   distributed) and stores the positioned words of the text layer and of Tesseract OCR in
   `curation/ocr/<slug>/` (with the OCR engine that wrote them: Tesseract's version and the
   renderer's; also local, since they reproduce the page). Look at the images of every page with a
   table, a figure or garbled text.
2. For a table or a dense passage, zoom in: `python tools/curation.py region <slug> <page> x0 y0 x1 y1`
   (page fractions, origin top left) writes a 400 dpi crop and prints what OCR reads there. Read the
   crop yourself; add `--transcription "…"` to see whether OCR reads the same numbers.
3. A value you took from the image gets evidence with the region you read and your transcription:

   ```json
   {"source": "ex:msyn/source/<slug>", "locator": "p. 3, Table II, row 4", "kind": "table",
    "reading": "vision_ocr", "region": [0.08, 0.41, 0.93, 0.44],
    "transcription": "4  Cu-Zn 1:1  300  180  5.2  12.4"}
   ```

   - The transcription is what is printed in the region, character for character, as you read it
     (a table row with its label, a caption, a sentence). Every number of the record must appear in
     one of its transcriptions or quotes.
   - Where the text layer or OCR renders the passage legibly, a verbatim `quote` is still best; use
     both when you can.
   - A value read off a plotted curve: `kind: figure`, the region of the point or the curve, the
     transcription of what you read ("curve A at 300 °C: about 42 %"), `qualifier: approximate`.
4. `python tools/curation.py agree curation/fragments/<slug>.json` lets the tool compare each
   transcription with the OCR words in its region and write `agreement` (agree, partial, disagree,
   no_ocr), and the OCR engines it used in the fragment's `ocr_engines`. Never write `agreement` or
   `ocr_engines` yourself. The check recomputes every agreement: a difference is an error when the
   OCR it reads was written by the recorded engines, and a warning when it was not (another Tesseract
   or renderer can read a region differently; the recorded agreement stands). `curation.py
   ocr-import` brings an older cache (`work/pages`) into `curation/ocr/`.
5. A reading OCR does not confirm needs an **independent second reading**: `curation.py pending`
   lists the crops (without your transcription) for a second curator, whose readings go to
   `curation/second-readings/<slug>.json` (`{"<region key>": "what they read"}`, one reading per region)
   and onto the evidence with `curation.py merge-second <slug>`. The numbers must be the same (a
   figure point: within 5 % or 0.3, since plotted points are read off a grid); a value that neither
   OCR nor a second reader confirms is left out and listed as an `extraction_error` gap.
   A figure reading always needs a second reading: OCR cannot read a plotted point.
6. Never read a value from memory or from another source; the image of this source is the only
   authority, as the text is.
7. Write numbers as printed, in the transcription and in `as_reported`: decimal commas (0,305),
   space-grouped thousands (24 250), powers of ten (2,07 × 10⁻⁵, 4,46 .10-5), raised decimal
   points (5·2) and fractions (2½) are all read by the check. Record the value itself
   (`"value": 2.07e-5`), never a mantissa with the power of ten moved into the unit, and never
   turn a number into text to satisfy the check.
8. A number printed as a label inside a figure (a stream flow on a flow sheet, a condition written
   on a line) is text: give it `kind: text` with the figure in the locator, so OCR can confirm it.
   `kind: figure` is for values read off a plot's axes.

## 5a. Conventions

- **A measure only one source uses** (carbon distribution to CO, volumes of gas consumed, a bed's
  "glow", qualitative product slates): put it in the test's `results` map as a value object with
  its `basis`; do not raise a gap for it. A declared property is proposed once a measure recurs
  across sources.
- **Concepts that exist**: a specimen that is not a catalyst is a `Sample`; a
  composition over time is a `TimeSeries`; a non-catalytic conversion is a `Procedure` with
  `HAS_INPUT`/`HAS_OUTPUT`; a start-up or operating sequence is a dynamic `Operation`.
- **A number printed without a unit** keeps `"unit": "not stated"` and its printed text in
  `as_reported`, whatever the property (a space velocity too); dimensionless
  ratios use `"1"`, and a value without a number has no unit.
- **Units** (review of 2026-09-28): `unit` is the unit the printed text denotes, in its usual
  spelling (`kg/cm2`, `mm Hg`, `K`, `atm`, `lb/in2`), with the printed text in `as_reported` and a
  note where reading it took judgement ("printed 'pounds'; a pressure, in pounds per square inch";
  a misprint such as `kg/cm3` for a pressure).
- **"Atmospheric pressure"** is `{value: 1, unit: atm, qualifier: approximate}` with the printed
  text in `as_reported`.
- **Shared species**: a named, defined compound or element takes the shared id even if the source
  is the only one to mention it; only grades, products and mixtures stay source-scoped.
- Measured equilibria are
  `test_kind: equilibrium_measurement`, and the catalysis checklist exempts equilibrium tests (no
  catalyst or feed required); `approach_to_equilibrium`; `ProcessUnit` with `FEEDS_INTO` for purification
  beds, scrubbers and heat exchangers, a feed's purification as `Feed -TREATED_BY→ Treatment
  {treatment_kind: purification}`, stacked beds as `USES_CATALYST {bed_position}`; `design_status`
  on reactors and units of planned plants; `HAS_COMPONENT {amount, relative_to}`; `negated` on
  `PRODUCES` and `DETECTS`; `ChemicalSpecies.isotopic_label`.

## 6. Gaps

Each gap is `{"kind", "about", "locator", "text"}`. A gap is never deleted, because gaps are cited
by position (`<slug>#gap/N`) from proposals and the gap register. A gap a later proposal answers
gets `"status": "resolved"`, `"resolved_by": "<NNNNNN>"` (a proposal's six-digit id such as `000009`) and a `"resolution"` saying how the records
now express it; a gap a new reading of the source answers (an illegible value read from the page
image) gets `"resolved_by": "re-curation YYYY-MM-DD"` and a `"resolution"` naming the value and
where it was read.

List in `gaps` what the schema or the source leaves open:

- `absent_source_information`: the source does not say something a reader needs (no pressure given);
- `ambiguous_source_information`: the source says two things (keep both readings in the records);
- `missing_concept`: the schema cannot express something the source says (say what);
- `extraction_error`: the text is illegible or garbled (an OCR page), so something could not be read.

## 7. Check and finish

```
python tools/curation.py check curation/fragments/<slug>.json
```

Fix every error (the data, not the check) until `"ok": true`. Warnings and `catalysis` checklist violations
are information: a missing pressure the source does not give is correct as `not_reported`.

## What must never happen

- A value, a composition or an identity that the text does not state.
- Knowledge from after the source's publication date, or from any other source, in a record, a
  note or a claim.
- A quote that is not in `text.txt`, or a quote "improved" from an OCR error.
- A hypothesis recorded as a finding, or a cited result recorded as this source's own.
