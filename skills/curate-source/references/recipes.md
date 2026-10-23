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
- A nominal composition or loading: `HAS_COMPONENT` `fraction` or `loading` with `origin: assumed`, on the
  formulation (the Catalyst, or the Material for an alloy's or a mixed oxide's nominal formula); a loading goes on the
  link to the active phase (`role: active_phase`, with `loading_basis`). A measured one (ICP-OES, XRF, XPS) is a result
  entry of the Characterization that measured it, on the specimen it measured, never on the formulation (below,
  "Composition: nominal, bulk and surface").
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

- A turnover frequency goes in the test's `result_values` as printed (a Variable of kind
  `turnover_frequency`, its product in `target`), and says how it was calculated (scale-catal 0.6.0). When
  the source gives the site count it divides by, the value names it with `normalized_by`: the
  `exposed_metal_count` (exposed atoms, each taken as a site) or the `site_inventory` (the sites of a kind
  the source divides by) of the `HAS_SITE` from the state the sites were counted in (below, "Sites in a
  catalyst state"). Say in `basis` what the sites are, in the source's words ("per exposed Cu atom", "per
  Zn-decorated step site", "per metal atom, every Cu atom taken as a site"), and in `definition` how they
  were counted when the source says it. When the source does not say, write that in `definition`; never
  supply a method. The validator warns about a rate that says none of it, and a comparison shows each rate
  with its count: rates on different counts are compared as reported, never recalculated. A rate divided
  by a count that is only an upper bound is itself a lower bound (`bound: lower`). A turnover number (events
  per site or per molecule of catalyst over the run, dimensionless) goes in `result_values` with a Variable of
  kind `turnover_number` (scale-catal 0.7.1), its product in `target` and in `definition` what it counts per
  what ("mol octane per mol Rh charged, after 2 h"); it is never a turnover frequency, which is per time.
- A light-off temperature: `results.light_off_temperature` with `definition` ("temperature at 50 %
  CO conversion") and the species in `target`.
- An activation energy from the temperature dependence of measured rates (an Arrhenius plot) is the
  apparent activation energy of that rate: a `result_values` entry of the Analysis that fits it
  (`analysis_kind: kinetic_fit`, `USES_MODEL` the rate law as a Model with `equations` and `parameters`,
  `HAS_INPUT` the tests whose rates it fits), its Variable of kind `apparent_activation_energy` (scale-catal
  0.7.0), its product or reactant in `target`, and the Analysis's `temperature` the range of the fit
  (`lower`, `upper`). It is never an elementary step's activation energy. When the source attributes a
  fitted activation energy to one step of a model (the rate-determining step, after correcting for the
  adsorption enthalpies), it is that step's `activation_energy`, `origin: fitted`, `produced_by` the fit,
  with what the correction assumes in the rate law's Model. Say apparent or intrinsic in `definition` as
  the source says it; when it does not, leave it unsaid. A source that gives Ea/R in K: keep it in K.
- Reaction orders: `HAS_REACTION_ORDER` from that Analysis to each species, with its `order` (a value).
- A differential or integral regime, an internal or external diffusion check: the conversion's
  `basis` or `note` ("differential, conversion below 5 %") and an Analysis
  (`analysis_kind: transport_check`) that `HAS_INPUT` the test, with its `verdict`, the `temperature`
  it applies to and its `evaluation_basis` (scale-catal 0.5.0 on): `asserted` when the source only
  states it, `numerical` when it computes a criterion, `experimental` when it varies particle size, flow at
  constant contact time or stirring (each run an input of the check). A computed criterion goes in the
  check's `result_values` with a Variable of kind `transport_criterion` (scale-catal 0.7.1), naming the
  criterion in `definition` ("Weisz-Prater criterion", "Mears criterion for external diffusion", "Carberry
  number"); values of two criteria are never compared, and one whose criterion is not named is left out of a
  comparison. Mears gave several criteria, so a Mears value names the transport it judges too (external or
  internal diffusion; heat transfer between the fluid and the particle, intraparticle heat transfer, radial heat
  transfer in the bed), as the source says it: one that says only "Mears criterion" is left out of a comparison.
  An effectiveness factor and a Thiele modulus are results of their own kinds (`effectiveness_factor`,
  `thiele_modulus`): say in `definition` whether the factor is the internal or the overall one, and with which
  length (the particle radius, or Vp/Sp) and in which form (first order, or generalized) the modulus was
  computed. Never infer a regime the source does not state, and never judge a criterion value: what the source
  concludes is the check's `verdict`.
- An enzyme's activity (scale-catal 0.7.1) goes in the assay's `result_values` with a Variable of kind
  `enzyme_activity`, as printed: per time in enzyme units (`U`, `mU`, a micromole per minute) or katal (`kat`,
  `nkat`), per mass of the enzyme or of the preparation (`U/mg`, a specific activity) or per volume of a solution
  (`U/mL`), the substrate or product it counts in `target`, and in `definition` what was counted and what it is
  divided by (or name that value, `normalized_by`). The assay's temperature is the test's; its pH, buffer and
  substrate concentration are condition entries (`conditions`), each with its `definition`. A Michaelis
  constant is a result of the Analysis that fits the rates (`analysis_kind: kinetic_fit`, `USES_MODEL` the
  Michaelis-Menten rate law), of kind `michaelis_constant`, its substrate in `target`; kcat is a turnover
  frequency, divided by the amount of enzyme it counts (`normalized_by`).

## Transients and the programs that drive them

- **The program** (scale-catal 0.7.3) is the test's `Operation` (`HAS_OPERATION`, operation_mode `dynamic`): what
  varies (`varied_quantities`), its `time_pattern` and `waveform` (square, sinusoidal, triangular, pulse_train,
  pseudo_random_binary), the `levels` it switches between (numbers with units, or text values for what is exchanged:
  12CO and 13CO), its `period`, `duty_cycle` and `cycles`, a pulse's `pulse_amount` and `pulse_width`, a pseudo-random
  sequence's `sequence_length` and `bit_duration`, the `segments` of a chemical loop (each with its `label` as a text
  value and its `duration`), and `time_origin` (what t = 0 is). `program_detail` says what the source gives: `exact`
  (every switch, or the generator and seed that regenerate the sequence), `parametric` (the pattern's parameters
  only) or `descriptive` (in words). Never reconstruct a sequence the source does not give.
- **The responses** are TimeSeries the test `HAS_OUTPUT`, each with its `time_resolution`, its `delay` (the line or
  cell dead time, as measured or stated) and whether the series was shifted for it (`delay_corrected`). An observation
  made during the test is a Characterization `DURING` it; say in `synchronization` how the two were put on one time
  axis.
- **What the responses give** is an Analysis that `HAS_INPUT` the test and the series: `isotopic_transient` for an
  isotope switch at steady state (its products' `surface_residence_time` and `surface_intermediate_amount` in
  `result_values`, each with its product in `target`; Shannon and Goodwin, Chem. Rev. 1995, doi:10.1021/cr00035a011),
  `modulation_excitation` for phase-sensitive detection (each band's or species' `phase_delay`; the analysis states
  what the delays are measured against, `phase_reference` stimulus or species_response with `phase_reference_species`,
  the `modulation_period` it read and the `demodulation_harmonic`, and delays against two references, or at two periods,
  are two analyses; Urakawa, Burgi and Baiker, Chem. Eng. Sci. 2008, doi:10.1016/j.ces.2007.06.009), `pulse_response`,
  `step_response` (`response_time_constant`) or `frequency_response`. The surface species are ChemicalSpecies records
  named as the source names them, with their band ("CO adsorbed linearly on Pt (2070 cm-1)"). That a species is an
  intermediate or a spectator is a Claim the analysis SUPPORTS (premise_refs: the delays it rests on), never read off a
  delay by the curator.
- **A kinetic model fitted to the responses** is an Analysis of kind `kinetic_fit` that states its `reactor_model`
  (differential, stirred_tank, plug_flow, axial_dispersion, batch, knudsen_pulse), its `rate_basis`, its
  `concentration_measure` (and `standard_pressure` for activities) and `thermodynamic_consistency`, as the source says;
  `not_reported` when it does not. Each fitted constant is a value of its kind in its `result_values` (an elementary
  step's activation energy with the step in `target`), `origin: fitted`, `produced_by` the fit, with how its interval
  was obtained (`interval_method`: curvature for a covariance or Hessian estimate, profile_likelihood, bootstrap,
  bayesian_posterior, …) and, when the source says, whether the data determine it (`identifiability`). The same model
  fitted under two reactor treatments is two Analyses; a comparison shows each constant's treatment.

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

The fields below are scale-catal 0.7.0; a document pinning an earlier version keeps the method in
`method` and the settings in a Model's `parameters`, as before.

- **One calculation, one Computation.** Give it its `computation_kind` (`electronic_structure`,
  `machine_learned`, `force_field`, `microkinetic`, `kinetic_monte_carlo`, `thermodynamic`). Keep the
  method in the source's words in `method`. The code is `USES_SOFTWARE` (`version`) to a Software record.
  A study that computes several surfaces is one Computation per surface (or per condition set), `PART_OF`
  the study, so that each result names the structure it is of. Results of one variable and one reaction
  in one record that nothing tells apart are an ambiguous repetition.
- **What a comparison reads.** `level_of_theory`: the functional as the source names it, as a text value
  (`RPBE`, `PBE`, `BEEF-vdW`, `HSE06`); another method by its name (`CCSD(T)/def2-TZVP`); for a
  machine-learned model, the model and its checkpoint. When the source does not say, record it as
  `not_reported` with `missing_reason: not_stated_in_source`; a scientific comparison then leaves the value
  out and says why. `charge_treatment`: `constant_charge` for an ordinary calculation (a fixed number of
  electrons, a computational hydrogen electrode included), `constant_potential` for one the source runs at
  a held electrode potential (grand canonical), with its `electrode_potential` (the scale in the unit:
  `V vs SHE`) and `reference_scale`. A value whose computation states no charge treatment is compared only
  with values that state none either.
- **What a comparison shows.** `dispersion` (a text value: `D3`, `D3(BJ)`, `none`), `hubbard_u` (the U of
  each element, only when applied), `spin_treatment`, `solvation` (and its model in `settings`), the
  computation's `temperature`, `pressure` and `electrode_potential`. They are shown with each compared
  value, and a group whose values state them differently is named; they are never assumed.
- **Numerical settings:** `settings`, a map of values by key: `cutoff_energy`, `kpoints` (a text value,
  "4×4×1"), `smearing` (its method in `definition`), `scf_convergence`, `force_convergence`,
  `pseudopotentials`, `basis_set`, `dipole_correction`, `transition_state_method` (`CI-NEB`, `dimer`),
  `initial_magnetic_moments`, `solvation_model`, `thermochemistry` (how free energies were obtained:
  harmonic adsorbate, ideal gas), `potential_method`. Only what the source states.
- **Files:** the input files are the `configuration` Dataset and the container or environment lock the
  `execution_environment` Dataset, each with `version` and `sha256`; outputs are `HAS_OUTPUT` Datasets.
  One `random_seed`; several go in the configuration Dataset or the note.
- **Structures:** each structure is a StructureModel the Computation `USES_MODEL`: its `representation`
  (`periodic_slab`, `bulk`, `cluster`, `molecule`), `composition`, `facet`, and in `parameters` the
  `supercell` (a text value, "p(2×2)"), `layers`, `fixed_layers`, `vacuum`, `lattice_constant` (and how it
  was obtained, in `definition`), `boundary_conditions` and `relaxation`. Its coordinates are the Dataset
  it is `stored_in` (`version`, `sha256`). A transition state is a StructureModel the step names with
  `TRANSITION_STATE`.
- **Coverage and the state a model stands for.** What adsorbs on the model, and how much, is a computed
  CatalystState that is `STATE_OF` the model and `DETERMINED_BY` the computation, with `HAS_COMPONENT`
  (role `adsorbate`, `coverage`, `bound_to` the site); the computation is `IN_STATE` it. Add no specimen
  for it. When the source says which sample or state the model stands for, the model `REPRESENTS` it,
  with what of it (`aspect`: "the (111) terraces of its Pt particles") and what that assumes
  (`assumptions`: a clean surface, no support, a coverage).
- **Computed energies.** Each energy is a `result_values` entry of the computation, or a value of the
  step that holds it (`produced_by` the computation), of its kind: `electronic_energy` (a total energy;
  its `target` the StructureModel), `reaction_energy` (an electronic energy change; an adsorption energy
  is one), `reaction_enthalpy`, `reaction_free_energy`, `activation_energy` (an elementary step's
  barrier), `activation_free_energy`. A reaction or adsorption energy names, as its `target`, the Reaction
  it is the energy change of, whose participants (`HAS_PARTICIPANT` with `coefficient` and `phase`) are
  its reference states: "H2O(g) − H2(g) + * → O*" and "1/2 O2(g) + * → O*" are two reactions, never one
  energy. When the source does not say what an energy is relative to, write its words in
  `unresolved_target`. A value the source reports with the opposite sign (a binding energy that is
  positive for stronger binding) is the energy of the reverse reaction: name that reaction, keep the
  number as printed, and never flip a sign. A zero-point-corrected energy says so in `definition`. A free
  energy or an enthalpy is evaluated at its computation's `temperature` (and `pressure`,
  `electrode_potential`): the validator warns about one that states none.
- **A value converted from one treatment to another** (a constant-charge energy converted to constant
  potential, a potential converted to another scale) stays on the record of the calculation it was
  converted from, `origin: derived`, `produced_by` the Analysis that converted it (with what it used:
  its own `temperature` and `electrode_potential`), and says in `definition` what it now is ("converted
  to constant potential by charge extrapolation, at 0.9 V vs SHE"). Only so is it compared with values of
  the treatment it was converted to.
- **Kinetic parameters.** An elementary step's Arrhenius parameters (`pre_exponential_factor`,
  `temperature_exponent`, `activation_energy`, `sticking_coefficient`, `coverage_dependence`) are the
  step's, with their origin and `produced_by`; a mechanism file is a Mechanism with `uri` and `sha256`.
  The sensitivity of a rate to one step (the degree of rate control) is `RATE_CONTROL` from the
  microkinetic Computation to the step, `degree_of_rate_control` with its product in `target`; a
  sensitivity at other conditions is another Computation (`PART_OF` the model), each with its
  `temperature`, `pressure`, `conditions` (partial pressures, conversion) and the state it is `IN_STATE`.
- **Machine-learned predictions.** The computation (`computation_kind: machine_learned`) `USES_MODEL` the
  trained Model, with its `version` (the checkpoint) and the Dataset its weights are `stored_in`. The data
  it was fitted to is what an Experiment that `EVALUATES` it with `evaluation_kind: calibration` takes as
  `HAS_INPUT {role: training_data}`; each validation is an Experiment that `EVALUATES` it with
  `evaluation_kind: validation` (its criterion and outcome, and its errors in `result_values`) on the data
  it `HAS_INPUT` as `validation_data` or `test_data`. The validator reports a validation on data the model
  was fitted to: a fit to its own data is a calibration, not independent validation. A predicted value
  is `origin: predicted`; one that sits on another record names the computation in `produced_by`.
- **Balances.** List every participant of a reaction or step with its `role` and `coefficient`, and give
  each species its `elemental_composition` (or a formula that can be read) and its `charge`. The
  validator then reports whether the participants balance in atoms and in charge, each on its own; a
  species whose charge is not stated leaves the charge balance not checkable, and is never taken as
  neutral. `balance_status` is what the source says; never change it to match the check.
- An Experiment with `experiment_kind: computational` that is not a Computation (a fit, a validation)
  keeps the level of theory in the `parameters` of the Model it uses (`USES_MODEL`; a functional's name as
  `text_value`), or in `unmodeled` when there is no model to hold it.

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
- Two purchases of one product are two CatalystSamples that share their formulation (`HAS_FORMULATION`), never a
  batch: give each the lot number the source states, none when it states none, and its own characterizations. Nothing
  measured on one lot (a dispersion, a surface composition) is recorded for the other.

## Catalysis mode, enzymes and molecular catalysts

- A test's `catalysis_mode` (scale-catal 0.7.1) is how its source describes the catalysis: `heterogeneous`,
  `homogeneous` or `biocatalytic`. Record it only when the source says it; never infer it from the catalyst. An
  immobilized complex or enzyme is what the source calls it.
- An enzyme or whole-cell catalyst is a Catalyst of `catalyst_family` `enzyme` or `whole_cell`. The enzyme
  is a ChemicalSpecies of `species_kind` `macromolecule`, named as the source names it, with its EC number
  (and a UniProt accession when given) in `identifiers` and no formula; when it is immobilized, the carrier is
  its `support` (HAS_COMPONENT). The reaction mixture is a Feed: the substrate a `reactant`, the cofactor (NAD+,
  a metal ion) a `cofactor`, the liquid a `solvent` (a buffer named in `role_detail`).
- A molecular catalyst is a Catalyst of `catalyst_family` `molecular_complex`: the complex its
  `active_component`, a ligand added beyond the complex a `ligand` (its ratio to the complex a `fraction`
  with `fraction_basis: relative_to_component` and `relative_to`), an activator a `cocatalyst`. The solvent is
  a component of the Feed. A catalyst loading relative to the substrate (mol%) is the test's `USES_CATALYST`
  `amount` as printed.

## Energy use

- The energy a process takes per product (scale-catal 0.7.1) goes in `result_values` with a Variable of kind
  `energy_consumption`, as printed: per amount (kJ/mol) or per mass (kWh/kg) of the product in `target`, which
  are kept apart. Say in `definition` which energy (the electrical energy, the heat supplied, every input) and
  over which boundary (the cell, stack, reactor or discharge; or the plant, with its separation or compression):
  values of two energies or two boundaries are never compared, and one that says neither is left out of a
  comparison. An energy efficiency (dimensionless) is of kind `efficiency`;
  a plasma test's `energy_yield` and `specific_energy_input` stay where they are.

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

Record a characterization's results as result entries (`result_values`), each naming the Variable of what it
measured, with its `definition` (the method and its range) and, where it is about one phase, species or element, its
`target` (below, "Characterization recipes"). The keys below are the names to give those Variables' `quantity_kind`,
so that one measurand has one name across documents; until the kernel declares them they are recorded as stated, and
their units are not checked. An older document may hold the same values in the Characterization's `results` map under
these keys; both read the same way.

| quantity_kind | unit as printed | definition (example) |
|---|---|---|
| `specific_surface_area` | m2/g | BET, p/p0 0.05–0.30 |
| `external_surface_area`, `pore_volume`, `pore_diameter` | m2/g, cm3/g, nm | t-plot; N2 at p/p0 0.99; BJH desorption branch |
| `metal_surface_area` | m2/g | N2O titration, stoichiometry Cu:O = 2 |
| `site_fraction` (declared) | % | a dispersion: exposed atoms as a share of all atoms of the metal |
| `gas_uptake` | µmol/g | H2 chemisorption at 308 K (`target`: the gas) |
| `crystallite_size` | nm | Scherrer, (111) reflection (`target`: the phase) |
| `microscopy_particle_size`, `microscopy_particle_size_spread`, `count` | nm, nm, 1 | a microscopy distribution's mean (or median), its standard deviation, the particles counted |
| `hydrodynamic_size`, `polydispersity_index` | nm, 1 | DLS Z-average and PDI of a colloid |
| `dispersion_equivalent_size` | nm | the size a dispersion gives for an assumed particle shape |
| `coordination_number` | 1 | a fitted EXAFS coordination number (an Analysis result) |
| `composition_fraction`, `loading` (declared) | at%, wt% | a measured metal fraction or loading (`target`: the element) |
| `lattice_parameter` | Å | Rietveld, axis a (`target`: the phase) |
| `phase_fraction` | wt% | Rietveld (`target`: the phase) |
| `reduction_peak_temperature`, `desorption_peak_temperature` | °C | TPR in 5 % H2/Ar, 10 K/min (`target`: what is reduced or desorbs) |

Several values of one quantity (two phases, three peaks) are separate entries, each with its own `id` and `target`
(in a `results` map, a short suffix each: `crystallite_size_cu`, `reduction_peak_temperature_1`). Name the technique as
the source does in `technique`, and the specimen's state on `CHARACTERIZES {state}`. A count of sites or of exposed
atoms for a state also goes on the `HAS_SITE` from that state (below), `produced_by` the characterization or the
Analysis that turns its uptake into sites.

## Sites in a catalyst state

- Record a site population on the `HAS_SITE` from the `CatalystState` it was counted or observed in (scale-catal
  0.6.0): after reduction, under reaction, after the test. The state is `STATE_OF` the specimen when the source says
  which; one the source gives only for the formulation is `STATE_OF` the Catalyst (never add a specimen for it); a
  computed one is `STATE_OF` the model (a StructureModel), with the Computation that `DETERMINED_BY` names.
- Four values, each its own property: `population_fraction` (a share; `basis` names the whole, "of the exposed Cu
  atoms"; a share in words is `text_value`), `site_density` (per area or mass), `exposed_metal_count` (exposed atoms
  counted) and `site_inventory` (the sites a rate is divided by). Give each its `origin` (measured, derived, computed,
  assumed), its `uncertainty` or `bound` ("at most 30 µmol/g"), its `produced_by` and its `evidence_ids`.
- How it was counted: `produced_by` the Characterization (chemisorption, titration, spectroscopy) or an Analysis that
  `HAS_INPUT` it and `USES_MODEL` a Model whose `assumptions` say what the count assumes (the adsorbate's
  stoichiometry, which atoms count as sites, the particle shape); or a short `definition` when the source says no
  more. A metal surface area (m2/g) is not a count of sites: it stays a characterization result, and a count derived
  from it with the source's atoms per area is a derived value with its producer.
- Never carry a count from one state to another. When the source divides a rate measured under reaction by a count
  made after reduction, the rate names that count, in the state it was made in.

## Assignments, operando observations and fits

- **An assignment** (this phase, site or species is active for this reaction in this state) is a Claim
  (`claim_kind: structure_property`; `mechanism` for a route) `ABOUT` the component in its role (`active`,
  `spectator`, `precursor`, `inhibitor`), the state (role `state`), the reaction and product
  (`reaction`, `product`), the test it concerns (`test`) and any elementary step or mechanism (`step`,
  `mechanism`). What it rests on `SUPPORTS` or `CONTRADICTS` it, with `premise_refs` to the results
  (`/result_values/<id>`, `/results/<key>`) and a `warrant`. One claim per assignment: a competing or a spectator
  interpretation is a claim of its own, with its own evidence (`CONTRADICTS` when the source sets them against each
  other). Never assign activity to a phase because it is the majority one.
- **An operando observation** (operando: characterized while the kinetics are measured): `observation_mode` as
  the source says. `DURING` the test it overlapped, with what the source states: `specimen` (the same specimen,
  another of its batch, another), `timing` (`simultaneous`: the kinetics measured while it ran, continuously or by
  product analysis at intervals; `sequential`: before or after it; the protocol in the evidence) and `kinetics`
  (`measured` in the cell; `matched_to_benchmark`, with the conventional reactor's or cell's test as `benchmark`;
  products only detected; not measured). Leave out what the source does not state: never infer that the kinetics
  were measured at the same time or on the same specimen.
- **A spectrum and its fits**: the measured spectra are a Dataset (`data_kind: spectrum`) the characterization
  `HAS_OUTPUT`; a fit is an Analysis (`analysis_kind: spectral_fit`) that `HAS_INPUT` the Dataset (role `data`) and
  its references (role `reference_standard`), with its `method`, its fitted parameters in `results` (`origin:
  fitted`, `produced_by` the analysis, with their uncertainties) and its `limitations` (what it cannot tell apart,
  what was held fixed). An alternative model of the same data is another Analysis. A site assignment drawn from it is
  a Claim that cites the parameter with `premise_refs`.

## Preparation recipes

How a catalyst was made, activated, stored and moved, so that a second person could follow it and two preparations of
one nominal formula stay two (scale-catal 0.6.0; the preparation examples,
domain/examples/scale-catal/preparation-examples/, and CQ-18, CQ-19 and CQ-22 show each step). What the source does
not state stays unstated: a value is a typed absence (`status: not_reported`, `missing_reason: not_stated_in_source`),
a text field reads `not stated`, and nothing is filled from a typical recipe.

### The batch, its lots and its steps

- **The batch** is a CatalystSample (`sample_kind: batch`) with the `batch_identifier` the source gives (none when it
  gives none), `HAS_FORMULATION` its Catalyst. Two batches of one nominal formula are two CatalystSamples sharing the
  formulation; nothing else joins them. Record every batch the source reports; its statement that the batches agreed,
  or that the material was made once, is a Claim (`claim_kind: data_quality`) `ABOUT` them.
- **A purchased lot** (a precursor, a support, a reference foil) is a Sample (`preparation_status: purchased`) with its
  lot number in `batch_identifier`, `HAS_COMPONENT` the ChemicalSpecies or Material it is a lot of (`role: precursor`
  or `support`). The supplier and the purity as stated go on `PREPARED_FROM.supplier` and `PREPARED_FROM.grade`, from
  the batch to the chemical, with the amount used; a catalogue number in the lot's `identifiers`; the dates it was
  bought and opened, and any purification before use (drying, distillation), in its `note` or as a Treatment. A
  support property the supplier gives (surface area, pore volume) is a value in the lot's `properties` whose
  `definition` says so; one the authors measured is a characterization result.
- **Hydration is identity:** H2PtCl6·6H2O is a ChemicalSpecies of its own, its `formula` with the water. A hydrate the
  source gives without its water content keeps `·xH2O` and a `note`; never supply the number.
- **The preparation** is a Preparation (`method` as the source names it) that `HAS_OUTPUT` the batch (`PREPARED_BY` is
  the same link read the other way: record one). When the source follows a written procedure, the Preparation
  `FOLLOWS_PROTOCOL` a Protocol, with what it changed in `FOLLOWS_PROTOCOL.deviations`.
- **Each step** is a ProcedureStep (`action`: dissolve, impregnate, precipitate, age, filter, wash, dry, calcine,
  reduce, …) `PART_OF` the preparation with `order` 1, 2, 3 …. What it takes in is `HAS_INPUT` with its `role`
  (`reagent` for what is added, `material` for what it is added to or what is treated) and `amount` as printed; what
  it gives out is `HAS_OUTPUT`.
- **A solution** made in one step and used in another is a Sample (`sample_kind: other`) with
  `HAS_COMPONENT.concentration` for each solute as stated (mol/L, g/L), the output of its dissolving step and an input
  of the step that uses it.
- **Conditions of a step:** `ProcedureStep.temperature`, `duration`, `ramp_rate` and `atmosphere` are its own
  properties; anything else is a `conditions` entry (`ph`, `final_ph`, `addition_rate`, `stirring_rate`,
  `incipient_volume`, `filtrate_conductivity`, `vessel_volume`), each value with its unit and a `definition` when its
  key alone does not say what it is ("the pH of the slurry when the addition ended"). The stirrer (type, size), the
  vessel and how it was heated go in the step's `method`; what was seen during it (a colour change, turbidity) in its
  `note`.
- **Sensitivities:** what the source says the synthesis is sensitive to (a precursor lot, air, the passivation rate),
  or that it knows none, goes in the Preparation's `note`, with its evidence.

### Supported-metal impregnation (incipient wetness, wet impregnation)

Name the method, incipient wetness or wet impregnation, in the Preparation's `method` as the source does.

1. The incipient volume: a step (`action: other`, `method` saying how) that takes in the support lot (`role:
   material`, `amount`) and the solvent, with `conditions.incipient_volume` (mL/g). A pore volume by N2 is a
   characterization result of its own; the two need not agree. The precursor's solubility, when the source gives
   it, is a condition of the dissolving step.
2. Dissolving the precursor: takes in the precursor lot (`amount`) and the solvent (`amount` in mL), gives out the
   solution.
3. Impregnating: takes in the solution (`role: reagent`) and the support (`role: material`, `amount`); `method` says
   how it was added and mixed ("added dropwise with intermittent mixing"). Each portion of a successive impregnation
   is a step of its own, with the drying between them.
4. Drying and calcining, as steps of the preparation (`temperature`, `duration`, `ramp_rate`, `atmosphere`: "static
   air", "flowing air, 100 mL/min"), or as Treatments when the source applies them to the made batch (below). For a
   wet impregnation, how the support and the solution were mixed, and the drying apparatus (a rotary evaporator's
   speed and bath temperature) in the drying step's `method` and `conditions`; the amount of powder and the crucible
   of a calcination in its `conditions`.
5. The nominal loading on the formulation (`HAS_COMPONENT` to the active phase, `loading`, `loading_basis`, `origin:
   assumed`, its `definition` saying how it was set); the measured loading a result of the batch's ICP-OES or XRF.

### Precipitation and coprecipitation

1. Dissolving the salts and the precipitating agent: two steps, two solutions with their concentrations.
2. Combining them: one step (`action: precipitate`) that takes in the solution added (`role: reagent`) and the one it
   is added to (`role: material`), so the order of addition is two links. For a co-feed of both into a vessel, both
   are `reagent` and the vessel's starting liquid is `material`. `conditions` holds the `addition_rate`, the
   `stirring_rate`, the pH (`ph` held, or `initial_ph` and `final_ph`, each with its `definition`; a tolerance as
   its `uncertainty`, "7.0 ± 0.1"; the pH measured besides the one targeted) and how it was held in `method` ("pH held
   at 7.0 by the base feed"); `temperature` is the step's. For a deposition-precipitation, the pH over time is a
   Dataset or TimeSeries the step `HAS_OUTPUT`.
3. Aging (`temperature` and `duration`, both; in the mother liquor or not, in `method`), filtering, washing (the
   solvent with its `amount` and temperature, the number of washes as `conditions.washes`, the criterion as a
   condition: `filtrate_conductivity` with `bound: upper`), drying and calcining, each a step in order.
4. The nominal metal ratio on the formulation (`HAS_COMPONENT.fraction`, `fraction_basis`, `basis` naming the set,
   "metals only: Cu + Zn + Al", `origin: assumed`); the measured ones on the characterizations (below).

### Activation, storage, transfer and reaction history

- Each action applied to a made batch is a Treatment, in order: `TREATED_BY` from the batch with `TREATED_BY.order`,
  and `PRECEDES` from the action before it (the preparation, a treatment, a test). `treatment_kind`: `calcination`,
  `reduction`, `oxidation` for a passivation (`method: passivation`), `exposure` for storage or an air exposure.
- `Treatment.temperature`, `duration` and `atmosphere` as stated ("10 % H2 in Ar"); a flow rate, a space velocity,
  a ramp rate, the bed (fixed or fluidized, how much powder) or a cooling method in `conditions`. The switch from one
  gas to another (H2 flushed with inert before the passivating gas) is a step of its own or the Treatment's
  `method`.
- **Storage** is a Treatment (`treatment_kind: exposure`, `method` naming the container and the place: bench,
  desiccator, glovebox) with its duration, atmosphere and temperature as stated, and light, humidity or a glovebox's
  O2 and H2O contents in `conditions`: "not stated" and typed absences when the source gives none. The form the
  catalyst was stored in (passivated, as a suspension, as a dried powder) is the state before the storage.
- **A transfer** to a measurement is the Characterization's `transfer` ("mounted in air", "in a sealed holder under
  Ar") and `observation_mode`; the specimen's state is on `CHARACTERIZES {state}` and, when the source tells it apart,
  a CatalystState `REACHED_BY` the action before it and `DETERMINED_BY` the measurement.
- **The reaction history:** each test `USES_CATALYST` the batch in its state and `PRECEDES` the next action; the
  states under reaction and after it are CatalystStates `REACHED_BY` the test (`timing: during`, `after`). A batch
  split between cells is a CatalystSample per portion, each with the batch's `batch_identifier`.

## Characterization recipes

What every measurement keeps, then what each technique adds (scale-catal 0.6.0; CQ-19, CQ-20 and CQ-21 show the
queries). A value is in the unit printed; a fitted or derived value names its producer; an uncertainty keeps its
`uncertainty_kind`.

### What every measurement keeps

- **The specimen and its state:** `CHARACTERIZES {state}` the batch or portion measured; `technique` as named;
  `observation_mode`, `information_depth` (bulk, surface, projection), `sampling` (ensemble, single_particle);
  `temperature` and `atmosphere` during the measurement; `transfer`.
- **The technique's term:** `technique_id`, the Chemical Methods Ontology term of the technique the source names,
  where one fits it (the validator warns when `technique_id` is no ontology term). Looked up in CHMO's 2026-05-28
  release:

  | Technique as sources name it | `technique_id` |
  |---|---|
  | X-ray diffraction (XRD); powder XRD | CHMO:0000156; CHMO:0000158 |
  | X-ray photoelectron spectroscopy (XPS) | CHMO:0000404 |
  | transmission electron microscopy (TEM); high-resolution TEM | CHMO:0000080; CHMO:0000084 |
  | scanning electron microscopy (SEM) | CHMO:0000073 |
  | scanning transmission electron microscopy (STEM); HAADF-STEM | CHMO:0000086; CHMO:0000730 |
  | energy-dispersive X-ray spectroscopy (EDX, EDS) | CHMO:0000309 |
  | X-ray fluorescence (XRF) | CHMO:0000307 (X-ray emission spectroscopy, XRF its exact synonym) |
  | X-ray absorption spectroscopy (XAS); EXAFS; XANES (NEXAFS) | CHMO:0000298; CHMO:0000300; CHMO:0000305 |
  | Raman spectroscopy | CHMO:0000656 |
  | Fourier-transform infrared spectroscopy (FTIR); DRIFTS | CHMO:0000636; CHMO:0000645 |
  | UV-vis spectroscopy | CHMO:0000292 |
  | temperature-programmed reduction (TPR); oxidation (TPO); desorption (TPD) | CHMO:0002908; CHMO:0002907; CHMO:0002673 |
  | N2 physisorption, BET surface area | CHMO:0001168 (sorption measurement) |
  | thermogravimetry (TGA); differential scanning calorimetry (DSC) | CHMO:0000690; CHMO:0000684 |
  | NMR spectroscopy; EPR (ESR) spectroscopy | CHMO:0000591; CHMO:0000328 |
  | ICP-OES (ICP-AES); ICP-MS | CHMO:0000267; CHMO:0000538 |
  | Mössbauer spectroscopy | CHMO:0000417 |
  | gas chromatography (GC) | CHMO:0001002 |
  | cyclic voltammetry; electrochemical impedance spectroscopy | CHMO:0000025; CHMO:0000423 |
  | atomic force microscopy (AFM) | CHMO:0000113 |

  CHMO has no term for a chemisorption measurement as such; leave `technique_id` unset rather than use a broader
  one. Other ontology terms (an OBI assay, an IRI) are accepted too.
- **Acquisition settings:** `Characterization.conditions` (edge, detection mode, accelerating voltage, scans, regions
  imaged), the Instrument it `USES_INSTRUMENT` with its `settings`.
- **Standards and calibration:** a reference measured with the specimen is `HAS_INPUT {role: reference_standard}`; a
  calibration is its own Characterization (`goal: calibrate`) that takes in the standard, the Instrument is
  `CALIBRATED_BY` it, and a value that rests on it names it in `calibration`.
- **Raw data:** a Dataset the characterization `HAS_OUTPUT` (`data_kind`: raw, spectrum, image, table), with
  `availability: available` and its `uri`, or `not_reported` when the source deposits none.
- **Processing and fitting:** an Analysis that `HAS_INPUT` the data (`role: data`) and the references (`role:
  reference_standard`), `USES_MODEL` a Model whose `assumptions` say what it assumes and holds fixed, `USES_SOFTWARE`
  with its version, with its `method` and `limitations`; its fitted values `origin: fitted`, `produced_by` the
  analysis.
- **One Variable per measurand:** each result entry names a Variable whose `quantity_kind` and `definition` say what
  was measured (the table above). A statistic is a measurand: a distribution's mean, its standard deviation and the
  number of items counted are three entries.

### XAS

- The Characterization: the edge, the detection mode (transmission, fluorescence), the energy calibration ("Pt foil
  measured downstream at the same time, first inflection set to 11564 eV") and the number of scans in `conditions`;
  the monochromator and its crystal, the harmonic rejection, the beam size and the ion-chamber gases there or in the
  Instrument's `settings`; the sample's form and amount (a pellet of so many mg); `temperature`, `atmosphere`,
  `observation_mode`, and for a cell under reaction its flows and pressure; a check for beam damage in `note`; the
  foil or reference measured with it `HAS_INPUT {role: reference_standard}`; the spectra a Dataset (in E, k and R
  when the source deposits them).
- The fit is an Analysis (`analysis_kind: spectral_fit`): `method` with the k-weight, the k- and R-ranges and the
  parameters fitted; the shell model a Model (the paths included, S0^2 and where it comes from, what was held fixed);
  the coordination number, distance, sigma^2 and E0 shift as fitted values with their uncertainties (how they were
  derived in `definition`); the goodness of fit (the reduced chi-square when models are compared), the independent
  points and the parameters fitted as results; a structure file the paths came from a Dataset input (`data_kind:
  structure`); `limitations`: what the average cannot tell apart (species below about a tenth of the absorbing
  atoms, different size distributions with one coordination number). A linear combination fit is another Analysis, its references as inputs. A claim drawn from the fit cites
  the parameter with `premise_refs` (above, "Assignments, operando observations and fits").

### Electron microscopy: particle-size distributions

- The Characterization (`technique`: HAADF-STEM, TEM), `information_depth: projection`, `sampling: single_particle`;
  in `conditions` the accelerating voltage, the regions and images measured, the magnification or pixel size, the
  smallest size the mode resolves (`lower_size_limit`), the electron dose and dose rate, and for STEM the probe current
  and angles; the microscope and its detectors an Instrument; how the specimen was prepared and loaded on the grid in
  `transfer`; the images a Dataset; a gas cell's conditions as for a reactor.
- The distribution as reported: one entry per statistic, each with its own Variable (`microscopy_particle_size` for the mean or
  the median, its `definition` saying which and of what: "number-weighted mean of the projected-area-equivalent
  diameters"; `microscopy_particle_size_spread` for the standard deviation; `count` for the particles counted). The standard
  deviation of a distribution is its width, never the `uncertainty` of its mean.
- A histogram or the list of diameters is a Dataset (`data_kind: table`) when the source deposits it; a skew, or
  how the mean was computed (arithmetic, surface-weighted), is one more entry or the mean's `definition`; the image
  processing an Analysis that `HAS_INPUT` the images.

### Chemisorption and site titration

- The Characterization (`technique`: "H2 chemisorption, volumetric, two isotherms", "N2O reactive frontal
  chromatography"): the adsorption `temperature`, the probe's partial pressure, the adsorption and purge times and the
  pretreatment in `conditions` (or as Treatments before it), the uptake as an entry (`gas_uptake`, its `target` the
  gas), with its replicates and uncertainty. A blank on the bare support is a Characterization of the support lot
  that is `CONTROL_FOR` the measurement (`control_kind: blank`); a check on a material of known dispersion or site
  density is `CONTROL_FOR` it with `control_kind: reference`.
- What the uptake is turned into (a dispersion, a metal surface area, exposed atoms, a size) is an Analysis that
  `HAS_INPUT` the chemisorption and the measured metal content (`role: parameter`), `USES_MODEL` the stoichiometry
  (its `assumptions`: one H per surface Pt; the metal content used; the particle shape for a size). The dispersion is
  a `site_fraction` (exposed atoms as a share of all atoms of the metal), and a count of exposed atoms for a state
  goes on the `HAS_SITE` from it (above, "Sites in a catalyst state").

### Physisorption (BET)

- The Characterization (`technique`: "N2 physisorption at 77 K", "Ar physisorption at 87 K"): the amount and form
  of the sample and the degassing vacuum, temperature and time in `conditions`; the isotherm a Dataset (both branches
  when measured).
- The BET area is a fitted value of an Analysis (`method`: "BET, p/p0 0.05–0.30, 6 points") that `USES_MODEL` the BET
  equation (its `assumptions`: the cross-section per molecule), with the C constant among its results when the
  source gives it; a pore volume or a BJH size names its branch and point in `definition`, and a pore analysis its
  thickness model or its NLDFT kernel and source in its Model. When the source gives only the number, a result entry
  with its `definition` on the Characterization is enough.

### Sizes from different techniques

- A microscopy size (`microscopy_particle_size`: the projected size of the particles counted), a diffraction size
  (`crystallite_size`: the coherent-domain size from a reflection's width), a hydrodynamic size (`hydrodynamic_size`:
  a particle with its shell, diffusing in a liquid) and a size from a dispersion (`dispersion_equivalent_size`) are
  four measurands. Each is a result with its own Variable; a plan that asks for one follows the entry to its Variable
  and gets that one only (CQ-20). A microscopy size is not the `particle_size` key of a catalyst body (the size of the
  grains in a bed, above, "Reactor, bed and catalyst-body keys").
- XRD gives an average crystallite size, not a distribution, and small domains may give no reflection: then a value
  `below_detection_limit` with the limit the source gives, or `not_reported` with a `note` when it gives none. Never
  put a microscopy size in its place.
- The hydrodynamic size is of the colloid or suspension measured, a Sample of its own, not of the supported catalyst.

### Composition: nominal, bulk and surface

- **Nominal:** on the formulation (above, "Set, nominal and specified values").
- **Measured bulk** (ICP-OES, XRF) and **measured surface** (XPS, LEIS) compositions: result entries of their
  Characterizations (`composition_fraction` or `loading`, `target` the element, `basis` naming the set: "metals
  only"), each on the specimen and in the state it was measured, with `information_depth`; an ICP-OES digestion and
  calibration in `conditions` and the value's `calibration`; impurities as entries of their own. Bulk and surface fractions
  share a kind and a basis, so a plan that asks for one names its Variable or the information depth; a scientific
  comparison keeps fractions on another basis, or on none ("4.7 %" with no "wt"), apart.
- **Under reaction conditions:** the measurement in that atmosphere (`observation_mode` as the source says), and the
  CatalystState it establishes (`state_kind: working`, `DETERMINED_BY` it), with the phases it shows (`HAS_PHASE`
  with `location` and `dominance`). A high-entropy alloy or mixed oxide is recorded the same way: its nominal formula
  on the Material, each measured composition on its measurement.

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
