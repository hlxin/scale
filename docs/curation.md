# Curation as evidence-preserving translation

Procedure for people and agents: [`skills/curate-source/SKILL.md`](../skills/curate-source/SKILL.md),
with its recording recipes in [`references/recipes.md`](../skills/curate-source/references/recipes.md). A data
table or a lab file is curated with [`curate-dataset`](../skills/curate-dataset/SKILL.md).

## Split of responsibilities

| step | who | output |
|---|---|---|
| read the source; identify the records (samples, tests, conditions, results, claims); attach evidence | person or language-model agent following the skill | a **scale-catal document** that pins the catalysis schema version and follows its checklist |
| check the document: validity, checklist conformance, quotes verbatim in the source text, REPORTED_IN backed by evidence | `scale graph validate` (deterministic) | validation report |
| build the evidence index | `scale graph index` (deterministic) | a vector and term statistics per quote, for `scale graph search` and text queries |
| review | catalysis reviewer (`scale review sample` draws a reproducible sample for a Tier 1 check) | the document's review status |

The extraction model is not the authority that defines the target concepts. The catalysis schema
defines what a completed record means, and the source determines which parts can be populated.

## Commands

```bash
scale call template '{"domain": "catalysis"}'            # a minimal valid document to start from
scale graph describe CatalyticTest --domain catalysis      # the properties and the checklist items
scale graph validate my-source.json --source-text ex:source/1=/path/to/your/copy/of/the/article.txt
scale graph index my-source.json                           # optional: saves the evidence index (search builds it otherwise)
```

Before the first source, freeze the corpus: a manifest that lists every candidate source with its `status` (included,
or the reason it is left out, such as `not_retrieved`, `off_scope` or `after_cutoff`; a bare `excluded` needs a
`status_reason`) and `counts` that add up to the candidates. `scale corpus check sources.json` checks it (the methanol example's `sources.json` is one) and
prints the corpus block a kg-bundle carries (`scale graph export --to kg-bundle --corpus …`). A corpus frozen by a
declared rule is not a database search, so it has no PRISMA identities to report.

`--source-text` enables verbatim quote checks. The text is HTML-unescaped **before** matching,
because a leftover `&gt;` makes every quote containing `>` fail (a lesson from an earlier
extraction pipeline). Matching ignores whitespace, case, compatibility forms and dash variants, because PDF
and HTML extraction splits tokens ("NH 3", "h −1"). Source texts are not part of this repository
unless their licence allows it; neither are quotes beyond the copyright cap (below).

## Rights: what may be quoted and who may see it

Every document committed to this repository is **public**: its graph states stewardship access `public`
and no record overrides it (`scale evidence access`, a step of `scale check`). A missing access is not
public: the visibility rule reads it as `institution`, so state `access: public` explicitly. Project data that is not cleared for
publication is never committed: keep it in a data repository of its own, outside this one, until it is cleared.

Quotes are **short, capped excerpts**. Each folder with research-data documents has a `rights.yaml`:

```yaml
sources:
  ex:my/source/1:
    class: in_copyright          # public_domain | open | restricted | in_copyright | synthetic
    licence: all rights reserved # an SPDX id (CC-BY-4.0) or a text
    basis: journal article, 2021; no open licence on the publisher page
    text_chars: 48210            # optional: the characters of the source's text
```

A source without an entry counts as `in_copyright`. For `restricted` and `in_copyright` sources:

| cap | |
|---|---|
| one quoted text (`quote`, `transcription`, `second_reading`) | at most 300 characters |
| distinct quoted characters of one source | at most 4,000, and at most 10 % of `text_chars` when known |

A rights file's `limits: {quote_chars: <n>, source_chars: <n>}`, and a source's own `quote_chars` and `source_chars`,
only lower these caps; 0 keeps no verbatim text of the source. Every graph in `graphs/` sets both to 0
([graphs/README.md](../graphs/README.md)).

Read the licence from the copy you read (its first page, the publisher's article page), never from aggregator metadata
or an open-access colour, and say where in `basis`. Rights follow the text version read (`text_version` on the
Source). Supporting information belongs to its paper's Source.

Public-domain, open and synthetic sources have no cap; their quotes are still only text found
verbatim. Distinct characters count each quoted text once per source (equal texts under the verbatim
normalization, and texts inside a longer quote of the same source, count once). Claim statements, names
and notes are the curator's own words and do not copy an in-copyright source beyond a short phrase
(a curation rule; it is not machine-checked without the text).

```bash
scale evidence report my-source.json                    # quoted characters per source against the cap
scale evidence cap my-source.json -o public.json         # keep what fits; withhold the rest
scale evidence rehydrate public.json --texts my-texts/ -o full.json   # restore from your own copy of the sources
```

`cap` is deterministic: for each capped source it keeps texts in a stable order (evidence of quantitative
values first, then shorter texts first, then by record id) while they fit, and withholds the rest; nothing
is trimmed. A **withheld** text leaves the evidence item with its source, locator, kind (and passage,
region): the text field is removed and `note` records `quote withheld: sha256:<hex> chars:<n>` (or
`transcription withheld: …`), the digest and length of the text under the verbatim checker's normalization,
after `"; "` when the item had a note. The encoding is valid under every scale-catal version. `rehydrate`
finds each withheld text by sliding a window of the recorded length over the normalized source text
(`--texts DIR` holds `<last segment of the source id>.txt`, or `--source-text ID=FILE`) and reports what it
cannot find; a reading of a page image is not in the text layer and cannot be restored this way.
`scale check` runs `scale evidence report --all`: every committed document that is not a synthetic example
(`data_status` `research_data` or `mixed`) needs a rights file, every Source a rights entry, and every capped
source must be within its cap.

## What the curator must record

- **Reported value, as printed**, in a value object (`{status, value, unit}`) in the unit the source
  used, with the printed text in `as_reported` when it differs (`"approximately 16.9 kWh"`, `"> 85"`).
- **Basis** of normalized quantities (geometric area, catalyst mass, ECSA). If the basis is
  inferred from a unit, say so.
- **The quantity a property holds** (scale-catal 0.3.0 on: `scale graph describe` prints each property's contract). A
  value's unit is one of its kind's dimensions, or the validator rejects it: a temperature is never in kg. A
  component's share of the whole is `fraction` (dimensionless, with `fraction_basis`); its concentration (mol/L, g/L) is
  `concentration`; an absolute amount (g, mol) is `amount`; a loading on a support is `loading`; a share relative to
  another component is a `fraction` with `fraction_basis: relative_to_component` and `relative_to`. Write units as
  printed: one the vocabulary cannot read (`L/h per 3 cc catalyst`) is reported, not rejected, and a scientific
  comparison leaves it out.
- **The context a comparison needs**, where the source states it, never assumed: a potential's scale
  (`reference_scale`, or in the unit, `V vs RHE`), a current density's normalization (`current_normalization`, or the
  value's `basis`), a pressure's convention (`barg`, `psig`, or `basis: gauge`), the conditions a gas volume is counted
  at (`sccm`, `mL(STP)/min`, or `basis: STP`), what a space velocity divides by what (`basis: GHSV`), the product of a
  selectivity, yield or efficiency (`target`). The value's statements and its record's must agree; a contradiction is
  reported. A value the curator converts to another context (a potential to RHE) is an **evidenced conversion**:
  `origin: derived`, `produced_by` naming the Analysis that converts it (with what it rests on: the pH, the filling, the
  temperature), the printed number kept in `as_reported`.
- **What a normalized quantity is divided by**, when it must be identified: the value's `normalized_by` names the
  record, and with `path` the value (`{record: <electrode>, path: /electrochemically_active_area}`); that value's own
  `origin` says whether the denominator was measured, derived, computed or assumed.
- **A product reported as a lump** (scale-catal 0.5.2 on). When the source reports a product as a fraction, a class or a
  carbon-number window (C5-C11, "gasoline range", "C2+") and does not identify one species, record a `ProductLump`, not
  a ChemicalSpecies, and link it as the experiment's product (`PRODUCES`, `HAS_OUTPUT`). Say that one lump lies inside
  another with `SUBSET_OF`, so that the selectivity sum check does not add them twice. A species the source names stays a
  ChemicalSpecies. The check cannot tell which species a lump holds, and the lump's basis and boiling range are not
  modelled; put them in `note` or `unmodeled`.
- **Product measurements, one result at a time** (scale-catal 0.4.0 on). A result the source identifies by its product,
  assay, phase or interval goes in the experiment's `result_values`: one value object per result with an `id`, its
  `variable` (a Variable whose `quantity_kind` says what it is: `product_yield`, `selectivity`, `conversion`,
  `faradaic_efficiency`, `production_rate`, `product_amount`, `balance`), the `evidence_ids` of the evidence item that
  states it, its product in `target` (a ChemicalSpecies), and, where the source says so, the assay that measured it in
  `produced_by` (a Characterization: GC of the outlet gas, NMR of the catholyte, with its time on stream in its
  `conditions`, its reference standards as `HAS_INPUT` role `reference_standard` and its raw data a Dataset it
  `HAS_OUTPUT`; or the Analysis that derived it), the calibration it rests on (`calibration`), the `phase` and `stream`
  it was measured in, and its `basis`. A yield is never a selectivity: record each with its own variable. The same
  product by two assays, at two times or in two phases is two results, each with what tells it apart; a reported mean
  of replicates is one result with `replicates` and its uncertainty. A product the source does not identify ("C2+",
  "unidentified oxygenates", the charge no product accounts for) is an `unresolved_target` in the source's words, never
  a guessed species; a product below the detection limit is `below_detection_limit` with the limit. A carbon or charge
  balance is a `balance` result `produced_by` an Analysis (`analysis_kind: balance`) that `HAS_INPUT` the assays it adds
  up, kept as reported (103 ± 4 % stays 103 ± 4 %); never compute a remainder or a closure the source does not state.
  A reference to a result (`TESTS.result_refs`) names it by its id: `{record: <test>, path: /result_values/<id>}`.
- **Driving forces and what a test is read as showing** (scale-catal 0.5.0 on). List every driving force of a test
  (`driving_forces`). A test that lists none has unknown applicability, and its checklist is never complete. Record
  what the source reads the test as showing in `interpretations`, never a reading of your own. The values are
  `intrinsic_kinetics`, `system_performance`, `photothermal_effect`, `nonthermal_light_effect`,
  `plasma_catalyst_synergy`, `performance_stability` and `material_stability`. The checklist then looks for the
  evidence each reading needs in the records connected to the test, so link that evidence as it is reported:
  - **Transport check.** A transport check is an `Analysis` with `analysis_kind: transport_check` that `HAS_INPUT` the
    test. Give it its `evaluation_basis`: `asserted` (stated, not shown), `numerical` (a criterion such as Weisz-Prater
    or Mears, its values in `results`) or `experimental` (runs that vary particle size, flow at constant contact time
    or stirring, each an input of the check and `CONTROL_FOR` the test). Also give its `method`, its `verdict` and the
    `temperature` it applies to.
  - **Dark control.** A dark control is `DARK_CONTROL_FOR` the illuminated test. It states `control_kind`,
    `differs_in` (illumination), how the temperature was matched, where (`temperature_matched_at`: the illuminated
    surface, or a bulk temperature) and over which time (`temperature_matched_over`). Another way of separating light
    from heat is a `ThermalContributionAnalysis` with its `partition_method`.
  - **Plasma synergy.** Record the plasma alone (an Experiment that `USES_PLASMA` with the bare packing) and the
    catalyst alone at the same temperature, each `CONTROL_FOR` the combined test. Record the plasma power
    (`discharge_power`, with how it was determined) apart from what the supply draws (`power_supply_input`).
  - **Stability.** A trace of performance over time is a `TimeSeries` the test `HAS_OUTPUT`. The material after the
    test is a `CatalystState` `REACHED_BY` the test (`timing: after`) and `DETERMINED_BY` its characterization
    (structure after the test, dissolution into the electrolyte). Repeats are `REPLICATES` links, and a planned set of
    repeats is a `Design` (`planned_replicates`, `PART_OF_DESIGN`).
  - **Dynamic operation.** A test operated dynamically `HAS_OPERATION` an `Operation` with its `time_pattern`, its
    `varied_quantities` and its `segments` (each the values held and its duration).

  Never record a criterion value, a conversion level or a control the source does not report, and never infer a
  reading from `test_kind`.
- **Missingness with a reason.** A value the source does not state is `not_reported` with a
  `missing_reason`: `not_stated_in_source`, `not_curated` (you did not look, e.g. SI or source-data
  files not examined), `ambiguous_in_source` (keep every variant), `withheld` or `not_extractable`.
- **Sample identity.** A catalyst (the formulation) is not a catalyst sample (a specimen). Do not
  assert batch or replicate identity the source does not establish; copy replicate statements.
- **Status.** Reported, curated, derived and hypothesized records stay distinct (`origin`);
  interpretations are Claims, proposals Hypotheses.
- **Second-hand evidence.** Record only the source's own results. A result the source reports from
  another work (a comparison table, a review) is second-hand: its evidence has `evidence_type:
  ECO:0000033` and names the cited work in the locator or note (the source's own work is ECO:0000006,
  experimental, or ECO:0007672, computational). When the cited work is in the corpus, curate the value
  from it instead. Queries name second-hand evidence and `own_work_only` leaves it out
  ([querying.md](querying.md)); the validator counts it; a kg-bundle export leaves out a source's edge
  that rests on it alone (`second_hand_not_exported`).
- **Keys and qualifiers.** One key per quantity, with what the value is about in its fields: the
  species in `target`, the basis in `basis`, the measurand in `variable`, the method in `definition`.
  Each operating point is its own test, `PART_OF` the run; repeats are linked by `REPLICATES`. A
  product the source does not report is `not_reported`, never 0.
- **Personal data.** A graph of project data names people who are not authors of a source by opaque
  ids only.

## Reading runs, tables and figures

- **Same run.** A value and its conditions come from the same run. A condition stated once (in
  Methods, a caption, "unless noted") is attached to every run it covers with its own evidence item,
  listed in the value's `evidence_ids`. When the pairing is not clear, do not pair: the value is
  `not_reported` with `ambiguous_in_source`.
- **Several sources on one record.** Every value of a record that cites several sources gets its
  `evidence_ids`, the evidence items that state it: only they tie a value to its source. When
  `scale graph filter` or an export leaves out a source the audience may not see, a value whose
  `evidence_ids` name evidence that remains stays, cited to it; a value whose ids name only the
  withheld source's items is withheld in its place, and so is a value without `evidence_ids` on a
  record that lost evidence (fail closed). Give them, so that the values a source the audience may see
  states are kept.
- **Tables, cell by cell.** One cell is one value; the locator names the table, row and column; the
  unit comes from the column header; footnotes are read; a number in parentheses is an uncertainty
  when a footnote or the methods say so.
- **Several printed forms** of one value: the most precise explicit one carries it, the others stay as
  evidence; forms that disagree are `ambiguous_in_source`.
- **Figures.** Calibrate each axis on at least two ticks and say whether it is linear or logarithmic.
  A value read off a plot is `approximate` with a type-B standard uncertainty (from the reading
  resolution or the spread of two readings); the evidence note gives the axis scale and ticks, and the
  second reading is kept. A tool's digitization is a computational Experiment (`USES_SOFTWARE`,
  `produced_by`). A value read off a plot is never recorded without an uncertainty.
- **Units not printed.** A number printed without a unit has `unit: "not stated"`, its printed text in
  `as_reported` and a note saying so, until the units change gives values a unit status. `not stated`
  (in any case and spacing) is a placeholder, not a unit: a query leaves its values out as
  `unit_unstated`, `scale graph stats` counts them under `(no unit)`, and a filter in it is a plan
  error. Never plan on it: the numbers behind it may be in any unit.

## Reading scanned pages: two readers

Old scans lose values in their text layer and in OCR: table cells run together, exponents and subscripts
vanish, digits turn into letters. Read the **page image** as well as the text, and let OCR check what you read
(`scale pages`, [tools/pagereading.py](../tools/pagereading.py)). The page images and OCR words
reproduce whole pages of the source: they stay in a local pages folder and are never committed or distributed
(keep it outside the repository, or in a `work/` folder under `domain/examples/`, which git ignores); the
curated document keeps the agreements and the OCR engines they were computed with.

1. `scale pages render PDF --source <source id> --pages DIR` renders every page
   (`DIR/<source key>/p<N>.png`) and stores the positioned words of the text layer and of Tesseract OCR
   (`p<N>.words.json`, with the OCR engine that wrote them: Tesseract's version and the renderer's). Look at
   the image of every page with a table, a figure or garbled text.
2. For a table or a dense passage, zoom in: `scale pages region --pages DIR --source <id> <page> x0 y0 x1 y1`
   (page fractions, origin top left) writes a 400 dpi crop and prints what OCR reads there. Read the crop
   yourself; add `--transcription "…"` to see whether OCR reads the same numbers.
3. A value you took from the image gets evidence with the region you read and your transcription:

   ```json
   {"source": "ex:demo/source/s1", "locator": "p. 3, Table II, row 4", "kind": "table",
    "reading": "vision_ocr", "region": [0.08, 0.41, 0.93, 0.44],
    "transcription": "4  Cu-Zn 1:1  300  180  5.2  12.4"}
   ```

   - The locator starts with the PDF page (`p. 3`); the region is on that page.
   - The transcription is what is printed in the region, character for character as you read it (a table
     row with its label, a caption, a sentence). Every number of the record must appear in one of its
     transcriptions or quotes. A transcription counts toward the copyright cap like a quote.
   - Where the text layer or OCR renders the passage legibly, a verbatim `quote` is still best; use both
     when you can.
   - A value read off a plotted curve: `kind: figure`, the region of the point or the curve, the
     transcription of what you read ("curve A at 300 °C: about 42 %"), `qualifier: approximate` (and the
     figure rules above).
4. `scale pages agree DOC --pages DIR` lets the tool compare each transcription with the OCR words in its
   region and write `agreement` (agree, partial, disagree, no_ocr), and the OCR engines it used in the
   document's top-level `ocr_engines` (beside `graph`; not a schema property). Never write `agreement` or
   `ocr_engines` yourself. `scale pages check DOC --pages DIR` recomputes every agreement: a difference is an
   error when the words it reads were written by the recorded engines, and a warning when they were not
   (another Tesseract or renderer can read a region differently; the recorded agreement stands).
   `scale pages import` brings words from another pages folder (an older cache, another machine's).
5. A reading OCR does not confirm needs an **independent second reading**: `scale pages pending DOC --pages DIR`
   lists the regions with their crops (never your transcription) for a second curator, whose readings
   (`{"<region id>": "what they read"}`, one per region) go onto the evidence with
   `scale pages merge-second DOC SECOND.json`. The numbers must be the same (a figure point: within 5 % or
   0.3, since plotted points are read off a grid); a value that neither OCR nor a second reader confirms is
   left out and listed as an `extraction_error` gap. A figure reading always needs a second reading: OCR
   cannot read a plotted point.
6. Never read a value from memory or from another source; the image of this source is the only authority,
   as its text is.
7. Write numbers as printed, in the transcription and in `as_reported`: decimal commas (0,305),
   space-grouped thousands (24 250), powers of ten (2,07 × 10⁻⁵, 4,46 .10-5), raised decimal points (5·2)
   and fractions (2½) are all read by the check. Record the value itself (`"value": 2.07e-5`), never a
   mantissa with the power of ten moved into the unit, and never turn a number into text to satisfy the
   check.
8. A number printed as a label inside a figure (a stream flow on a flow sheet, a condition written on a
   line) is text: give it `kind: text` with the figure in the locator, so that OCR can confirm it.
   `kind: figure` is for values read off a plot's axes.

## Uncertainty

| the source prints | record |
|---|---|
| ± of unstated meaning | `uncertainty` with `uncertainty_kind: plus_minus_unspecified` |
| a standard deviation or standard error | `standard_deviation` or `standard_error`, with `replicates` when n is given |
| a confidence interval | the interval (`interval_lower`/`interval_upper`) or a symmetric `uncertainty`, `confidence_interval` and `confidence_level` |
| a Monte Carlo, bootstrap or Bayesian coverage interval | `confidence_interval` with its bounds and coverage in `confidence_level` (0.9 for 5–95 %) |
| an expanded uncertainty | `expanded_uncertainty` with `coverage_factor` or `confidence_level` |
| a relative uncertainty (RSD, "± 5 %" of the value) | `as_reported` and `note` until the schema has a relative form (planned: [domain/ROADMAP.md](../domain/ROADMAP.md)) |
| an interquartile range | Q1 and Q3 in `note` until the schema has the kind (planned: [domain/ROADMAP.md](../domain/ROADMAP.md)) |

`± 0` is never recorded as an uncertainty.

## Statement kinds

An interpretation is a Claim and a proposal a Hypothesis (links `status: hypothesized`). Once the pinned
schema declares `statement_kind` on links (planned: [domain/ROADMAP.md](../domain/ROADMAP.md); check with `scale graph describe`), interpretive
links (HAS_SITE, INHIBITED_BY, IDENTIFIED_AS, and CATALYZES when the source infers it) say `conclusion`
and links taken as given say `assumption`; the kg-bundle export writes it as `_statement` and, until then,
infers it and counts the inferences.

## Recipes

[`skills/curate-source/references/recipes.md`](../skills/curate-source/references/recipes.md) says how
to record, with what the schema already has: set, nominal and specified values; conflicts between sources; rates and
kinetics; reaction thermochemistry; computational details; reactor, bed and catalyst-body keys; pairwise and
metals-only ratios; commercial catalysts; balances, impurities and data quality; driving forces outside the list;
characterization results; sites in a catalyst state; assignments, operando observations and fits; preparation
recipes (the batch, its lots and its steps; supported-metal impregnation; precipitation and coprecipitation;
activation, storage, transfer and reaction history); characterization recipes (what every measurement keeps; XAS;
electron microscopy; chemisorption and site titration; physisorption; sizes from different techniques; nominal, bulk
and surface composition); digitizing a figure.

## Sites, assignments and operando observations

Since scale-catal 0.6.0, a site population is recorded on the `HAS_SITE` from the `CatalystState` it was counted or
observed in, and holds for that state only: sites change with the conditions, so a count made after reduction is not
the count under reaction (Wrasman et al. 2024, doi:10.1016/j.jcat.2024.115451). Its share, density, exposed atoms
counted and the sites a rate is divided by are four values, each with its origin, uncertainty or bound, the
measurement or analysis that produced it and what the count assumes (a Model's `assumptions`). A turnover frequency
is recorded as reported, with how it was calculated: the count it is divided by (`normalized_by`) and, in its `basis`
or `definition`, what was counted as sites and how (or that the source does not say); the validator warns when it says
neither, and a comparison shows each rate with its count. Which component is active, a spectator, a precursor or an
inhibitor is a Claim with named `ABOUT` roles and its own evidence; abundance is not activity. Operando means
characterized while the kinetics are measured. An observation the source calls operando is kept so; whether the
kinetics were measured on the same specimen while it was made (Tackett et al. 2026, doi:10.1021/acscatal.6c01946; Meyer
et al. 2024, doi:10.1016/j.jcat.2024.115369) is what its `DURING` link states, never read from the label or from an
overlap in time. A fit to an ensemble measurement is an Analysis (`spectral_fit`) with its fitted values and limitations, apart
from the spectrum it fits and from the claim drawn from it. The recipes say how to record each.

## Preparations and characterizations

A catalyst's preparation and characterization are recorded with the structures SCALE has, so that a second person
could repeat them and two preparations of one nominal formula stay two. A batch is a CatalystSample with the batch
identifier the source gives; a purchased lot of a precursor or support is a Sample with its lot number; each step is a
ProcedureStep `PART_OF` the preparation, in order, with what it takes in and gives out and its conditions; each
treatment after it (reduction, passivation, storage) is a Treatment the batch is `TREATED_BY`, in order. A nominal
composition is the formulation's (`origin: assumed`); a measured bulk or surface composition is a result of the
measurement on the specimen, in its state. Each measurand is its own Variable, so a size from microscopy, one from
diffraction and one from light scattering stay three quantities, and a distribution's mean, standard deviation and
count stay three results. A fit keeps its model, references, software and limitations. What the source leaves
unstated stays unstated: a typed absence for a value, "not stated" for a text field, `availability: not_reported` for
data. The recording guidance follows the workshop report on rigor and reproducibility in heterogeneous catalysis
(doi:10.5281/zenodo.8029159) and the papers drawn from it (Alba-Rubio et al. 2024, doi:10.1016/j.jcat.2023.115259, on
synthesis; Meyer et al. 2024, doi:10.1016/j.jcat.2024.115480, on STEM/TEM; Meyer et al. 2024,
doi:10.1016/j.jcat.2024.115369, on XAS; Wrasman et al. 2024, doi:10.1016/j.jcat.2024.115451, on site counting); the
companion reporting checklist is [domain/docs/reporting/catalyst-preparation-reporting.md](../domain/docs/reporting/catalyst-preparation-reporting.md).

## Retractions, corrections and other notices

A source can be retracted, withdrawn, corrected or put under an expression of concern after it was
curated. Record what you know; never delete or rewrite the records that cite it.

- **A notice is a Source of its own** (`kind: retraction_notice`, `correction`, `expression_of_concern`,
  `withdrawal_notice`, `removal_notice` or `addendum`), linked to the source it concerns and citing itself as evidence (locator and, within the
  source's rights, a short quote):
  - a retraction is `RETRACTS` with `reason`, `retracted_on` and `scope` (`full`, or
    `partial` with the retracted parts in `scope_locators`). A partial retraction can also be recorded
    record by record: a Dataset for the retracted part (a table, a figure) `INCLUDES` the affected records,
    and the notice `RETRACTS` that Dataset; link the Dataset `REPORTED_IN` the source it comes from (or
    cite that source in its evidence), since only the records' evidence from that source counts as
    retracted (without either, the tools take the one source the same notice retracts in part, and none
    when it reaches several);
  - any other notice is `UPDATES` with `update_type` (correction, erratum, corrigendum,
    expression_of_concern, addendum, clarification, withdrawal, removal, new_version, new_edition),
    `updated_on` and `reason`; it requires evidence.
- **The publication status is derived** from these links (`retracted`, `withdrawn`,
  `partially_retracted`, `expression_of_concern`, `corrected`, `updated`, else `current_or_unknown`); it
  is never a property you type. Set `claim_status: retracted` only when a notice retracts the claim or its
  source, and record that notice; the validator warns otherwise (`retracted_without_notice`).
- **The records stay.** The validator flags what rests on retracted sources
  (`rests_on_retracted_source`, `partially_rests_on_retracted_source`, `supported_on_retracted_sources`),
  queries leave those rows out unless asked (`include_retracted`), and the kg-bundle export marks them. A
  retraction does not make a finding false; it removes its support.
- **Checking.** Record `status_check` (`checked_on`, `checked_via`, `result`) on a Source or
  Dataset only when someone actually checked for notices, saying when and by what means; never as a
  default. No SCALE tool checks registries yet (Crossref, Retraction Watch); a check is a person's.
- **Reinstatement.** A notice that reverses a retraction or an expression of concern is recorded with
  `UPDATES` once the schema has `update_type: reinstatement` (it needs a kernel change); until then it goes in
  the retracted source's `unmodeled` list with the notice's date and locator, and the retraction stays.
- **The text read.** Say which version of a text was read (`text_version`: submitted or
  accepted manuscript, version of record, …) and, where useful, `text_sha256`, `retrieved_from` and
  `retrieved_on`, so that locators and quotes can be found again; link a preprint and its article, a
  translation or a duplicate publication with `SAME_WORK_AS` (one work, not a replication).

## When the schema is inadequate

Do not add properties. Put the verbatim context in the record's `unmodeled` list; it is raised as a
`missing_concept` gap. Validation reports undeclared properties as errors precisely to stop silent
schema changes during extraction (see the invalid fixture
[`unknown-property.json`](../domain/tests/fixtures/invalid/unknown-property.json)).

## Gap kinds

| kind | example | action |
|---|---|---|
| missing_concept | a property the schema does not declare; a query answered with `schema_gap` | schema change (`evolve-schema`) |
| ambiguous_source_information | a reference electrode named differently in Results and Methods | source review / author query |
| absent_source_information | a pH the source never states | source review; no schema change |
| extraction_error | a value not in its quote, a quote not in the source | re-extract |
| missing_source_coverage | a query with no matching record | curate more sources |

## Entity resolution

Similar names can refer to different batches, and two publications can report the same
measurement. Merges must be recorded with evidence, and uncertain matches stay separate records.

- Never merge catalysts, samples or tests across sources.
- Share a species only when its identity is unambiguous: the formula fixes it, or the InChIKey or
  InChI matches. A different polymorph or phase is a different Material.
- When the schema has `former_ids` (planned: [domain/ROADMAP.md](../domain/ROADMAP.md)), the surviving record of a merge lists the
  retired ids there. Until then the merge map (retired id to survivor) is kept beside the document,
  and the kg-bundle export lists retired released ids on their survivors (`--replaced FILE` with
  `--previous`).
