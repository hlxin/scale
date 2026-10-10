# Recording recipes (curate-source)

Short recipes for things the schema already expresses, though not obviously. None of them adds a
property: each says which existing label, property or link carries the information, and what to do
until a planned schema change (domain/ROADMAP.md) is merged. Read the schema you pin with
`scale graph describe <Label> --domain catalysis` before following one; when it differs from what a
recipe assumes, the schema wins and the context goes in `unmodeled`.

Every recipe keeps the general rules: values as printed, with their unit and `as_reported`; evidence
on every record and link that states something; typed absences; claim statements and notes in your
own words.

## Set, nominal and specified values

A value the experimenter set or the author specified is not a measurement.

- A set point (a furnace setting, a nominal flow, a pressure the controller held): the value where it
  sits (the test's `conditions` or the property itself, an instrument's `settings`, `HEATED_BY.set_point`)
  with `origin: assumed` ("set by the author, not measured").
- A nominal composition or loading: `HAS_COMPONENT` `fraction` or `loading` with `origin: assumed`;
  a measured one (ICP, XRF) is a Characterization result with `origin: measured`, linked from the
  value by `produced_by` when it sits on the catalyst record.
- A specification (a manufacturer's rating, a reactor's design pressure): the `specifications` map of
  the Reactor or ProcessUnit.
- Where a temperature was measured: `temperature_measured_at` (catalyst bed, wall, furnace, inlet,
  outlet).
- Keep both when the source gives both (a set point and the bed temperature); never replace one with
  the other.

## Conflicts between sources

- Never merge, average or choose between two sources' values: each stays on its own records.
- Within one source, values that disagree are `ambiguous_in_source`, with every variant in `note`
  and every passage in `evidence`.
- A conflict the source itself states ("our rate is ten times that of X") is a Claim
  (`claim_kind: comparison`) with `CONTRADICTS` or `SUPPORTS` from the test, whose `premise_refs`
  point to the values (`{record, path}`, e.g. `/results/space_time_yield`) and whose `warrant` says
  on what the comparison rests.
- A corpus-wide scan for conflicts is the `scan-conflicts` skill. A person decides before anything
  becomes `disputed`.

## Rates and kinetics

- A turnover frequency or number goes in `results` (`turnover_frequency`, `turnover_number`) as
  printed, with the site count it is normalized to in `basis` ("per surface Cu atom, N2O
  chemisorption") and its definition in `definition`. The site count, when the source measures it,
  is a Characterization result of its own.
- A light-off temperature: `results.light_off_temperature` with `definition` ("temperature at 50 %
  CO conversion") and the species in `target`.
- An activation energy: in the `results` of the Analysis that fits it (`analysis_kind: kinetic_fit`,
  `USES_MODEL` the rate law as a Model with `equations` and `parameters`). Say apparent or intrinsic
  in `definition` only as the source says it; when it does not, leave it unsaid.
- Reaction orders: `HAS_REACTION_ORDER` from that Analysis to each species, with its `order` (a value).
- A differential or integral regime, an internal or external diffusion check: the conversion's
  `basis` or `note` ("differential, conversion below 5 %") and an Analysis
  (`analysis_kind: transport_check`) with its `verdict`. Never infer a regime the source does not
  state.

## Reaction thermochemistry

- One Analysis per condition set (`analysis_kind: equilibrium` or `thermodynamic`), `OF_REACTION` the
  reaction, its temperature and pressure as the Analysis's own values.
- An equilibrium constant goes in `results` as printed: `unit` as printed (`atm-2`, or `"1"` when it is
  dimensionless), `basis` saying Kp or Kc and the standard state ("Kp, fugacities, standard state
  1 atm"), and `definition` the expression the source gives.
- ΔH, ΔG and ΔS in `results` with their temperature; a correlation (log Kp = a/T + b) is a Model with
  `equations` and `parameters`, linked by `USES_MODEL`.
- Never put Kp values on different standard states or units under one key or compare them as one.

## Computational details

- A calculation is a Computation (catalysis). The level of theory (functional, basis set, dispersion
  correction) goes in its `method` as the source names it; `method_id` takes an ontology term when
  one exists. The code is `USES_SOFTWARE` (`version`) to a Software record.
- An Experiment with `experiment_kind: computational` (a schema without Computation) has no `method`:
  the level of theory goes in the `parameters` of the Model it uses (`USES_MODEL`; a functional's name
  as `text_value`), or in `unmodeled` when there is no model to hold it.
- A model (a microkinetic model, a force field, a rate law) is `USES_MODEL` to a Model with
  `model_kind`, `parameters` (a map of value objects; a functional's name as `text_value`),
  `assumptions` and `validity_domain`.
- Input and output files are `HAS_INPUT` and `HAS_OUTPUT` to Datasets with `sha256`; the settings
  file is `configuration`, the container or environment lock `execution_environment`.
- One `random_seed`: several seeds go in the configuration Dataset or the note.
- A standard state or reference energy goes in the value's `basis` or `definition`.
- The structured computation fields some platforms use stay with a deferred catalysis schema change;
  until then, these slots are enough.

## Reactor, bed and catalyst-body keys

Map keys, so a value can be found under one name. Most follow quantity names already in use on data platforms (`internal_diameter`, `bed_length`, `bed_volume`, `dilution_ratio`, `particle_size`, `pellet_diameter`,
`pellet_length`, `sieve_size`, `bulk_density`, `void_fraction`); `length`, `wall_material`, `recycle_ratio` and
`purge_fraction` are SCALE's own suggestions, which no host defines yet.

| what | where | key |
|---|---|---|
| reactor volume | `Reactor.volume` | (declared) |
| inner diameter, length, wall material | `Reactor.specifications` | `internal_diameter`, `length`, `wall_material` (text_value) |
| catalyst charged in a test | `USES_CATALYST.amount` (mass or volume, as printed); stacked beds `bed_position` | (declared) |
| bed length, bed volume | the test's `conditions` | `bed_length`, `bed_volume` |
| diluent or inert in the bed | `HAS_COMPONENT {role: diluent \| inert}` from the CatalystSample, with `fraction` and `fraction_basis` | — |
| dilution ratio as printed | the test's `conditions` | `dilution_ratio`, with `basis` (mass, volume) |
| particle, pellet, sieve size | `Catalyst.properties` or `Material.properties` | `particle_size`, `pellet_diameter`, `pellet_length`, `sieve_size` |
| bulk density, void fraction | `Catalyst.properties` | `bulk_density` (`basis`: bulk, tapped, skeletal, envelope), `void_fraction` |
| recycle loop, make-up gas, purge | ProcessUnit (`unit_kind: circulator`, …) with `FEEDS_INTO {order, stream}`; the test's `conditions` | `recycle_ratio`, `purge_fraction` (`definition` as the source gives) |
| per-pass or overall conversion | the conversion's `basis` | "per pass", "overall" |

## Pairwise and metals-only ratios

- A ratio between two components (Cu/Zn = 3): `HAS_COMPONENT` to the numerator with `fraction` (the
  ratio), `fraction_basis: relative_to_component` and `relative_to` the denominator; atomic, molar or
  mass goes in the value's `basis`.
- A fraction on a metals-only basis (mol % Cu of the metals): `fraction_basis: atom` or `mole`, and
  `basis` naming the set ("metals only: Cu + Zn + Al").
- A ratio no edge fits (a Si/Al ratio of a support): the Catalyst's or Material's `properties`, each
  value with its `basis`.

## Commercial catalysts

- The product name as the source gives it is the Catalyst's `name`; a catalogue number or RRID goes in
  `identifiers`.
- The supplier or manufacturer: `DEVELOPED_BY` to an Institution (`institution_kind: company`) with
  `role` ("supplier", "manufacturer").
- The specimen used: a CatalystSample with `preparation_status: purchased` and the lot in
  `batch_identifier`. A grade is a `properties` entry (`text_value`) or the `role` text.

## Balances, impurities and data quality

- A carbon or mass balance: a `results` entry (`carbon_balance`) in %, with its `definition`.
- A feed impurity: the Feed's `HAS_COMPONENT` to the species with `fraction` (ppm as printed),
  `role: other` and `role_detail` ("impurity", "poison").
- A reactant's stated purity (99.99 % H2): a `conditions` entry (`purity`) with the species in
  `target`; a product's purity a `results` entry with its `target`.
- The source's own remark on data quality: a Claim (`claim_kind: data_quality`) `ABOUT` the test.
- The validator warns on a selectivity, conversion, yield or balance above 100 % and on selectivities
  summing above 100 %: check the reading, and keep the value as printed when it is printed so. A one-sided
  bound (`bound`, "< 1 %") is never read as its number: an upper bound never warns and adds nothing to the
  sum, a lower bound counts as the least it allows, and a range warns only when its lower end is above 100 %.

## Driving forces outside the list

`driving_forces: [other]` (with `thermo` when there is heating as well), a `note` naming the force
(electron impact, gamma irradiation), the dose or emission in `conditions` and the readouts in
`results`. Never pick a listed force to satisfy the checklist.

## Characterization results

Until the catalysis schema declares them (planned: domain/ROADMAP.md), characterization results go in the
Characterization's `results` map under these keys, each value with its `definition` (the method and its
range) and, where it is about one phase, species or element, its `target`:

| key | unit as printed | definition (example) |
|---|---|---|
| `specific_surface_area` | m2/g | BET, p/p0 0.05–0.30 |
| `external_surface_area`, `pore_volume`, `pore_diameter` | m2/g, cm3/g, nm | t-plot; BJH desorption branch |
| `metal_surface_area`, `dispersion` | m2/g, % | N2O titration, stoichiometry Cu:O = 2 |
| `gas_uptake` | µmol/g | H2 chemisorption at 308 K (`target`: the gas) |
| `crystallite_size` | nm | Scherrer, (111) reflection (`target`: the phase) |
| `lattice_parameter` | Å | Rietveld, axis a (`target`: the phase) |
| `phase_fraction` | wt% | Rietveld (`target`: the phase) |
| `reduction_peak_temperature`, `desorption_peak_temperature` | °C | TPR in 5 % H2/Ar, 10 K/min (`target`: what is reduced or desorbs) |

Several values of one quantity (two phases, three peaks) get a short suffix each
(`crystallite_size_cu`, `reduction_peak_temperature_1`), and every one keeps its `target`. Name the
technique as the source does in `technique`, and the specimen's state on `CHARACTERIZES {state}`.

## Digitizing a figure

1. Read the figure on the page image at enough resolution to resolve the ticks.
2. Calibrate each axis on at least two labelled ticks; say whether it is linear or logarithmic (on a
   log axis a reading error is relative, so the uncertainty grows with the value).
3. Read each point twice (or have a second reader), and take the uncertainty as the larger of the
   reading resolution (a half-width a gives a/√3) and the spread of the readings.
4. Record the value with `qualifier: approximate`, `uncertainty`,
   `uncertainty_kind: standard_uncertainty` and `uncertainty_evaluation: type_b`, and evidence of
   `kind: figure` whose locator names the figure and panel and whose `note` gives the axis scale and
   the ticks used; keep the second reading on the evidence.
5. A digitizing tool's run is a computational Experiment (`USES_SOFTWARE` with its version) and the
   value's `produced_by`.
6. A point you cannot read reliably is not recorded: list an `extraction_error` gap.
