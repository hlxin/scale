# Upgrade report: Methanol Synthesis CO/CO2+H2 Pre-1966 — scale-catal 0.2.0 → 0.8.2

> The report `scale graph upgrade` wrote for this graph at 0.2.0, kept as the record of its upgrade. Option 2 was
> taken: the graph was upgraded mechanically (`--write`) and nothing was read again.

4866 records, 16584 links, 19647 values; 20 schema steps: **6 needs attention**, **11 optional**, **3 nothing to do**.

## Summary

- **Mechanical upgrade:** 47 rewrites by migration rules, every record id kept. Validation errors 0 → **0**, warnings 105 → 111.
- **Newer checklist:** 0 items the records now lack (112 lacking before → 112 after). Not errors: the records stay valid and queries report what is missing.
- **Comparability:** 2317 values are compared by a context they do not state; queries keep them apart from values that state it, never mix them.
- **Targeted re-reading:** 1224 records in 78 sources. Only their cited passages would be read again.

**Your options:**

1. **Stay at 0.2.0.** Nothing to do; the graph stays valid and queryable under its own version.
2. **Upgrade mechanically** (`scale graph upgrade <graph> --write`): the graph pins 0.8.2; nothing is read again, and what the newer version could record stays unrecorded.
3. **Upgrade and re-read the worklist** (the upgrade-curation skill), all of it or only the sources at the top of the table below.

## Step by step

| step | what changed | for this graph |
|---|---|---|
| 0.2.0 → 0.2.1 | no change in meaning: the description of Preparation.steps names PART_OF with order (#34) | **nothing to do** |
| 0.2.1 → 0.3.0 | breaking: quantity contracts (a value's unit by its kind's dimension; the contexts a comparison needs; normalized_by; HAS_COMPONE… | **needs attention**: 1 changes to properties its records hold; 47 rewrites; 1 new properties on HAS_COMPONENT; 153 unit contracts |
| 0.3.0 → 0.4.0 | breaking: result entries (Experiment.result_values with value ids, phase, stream, unresolved_target); conversion, product_yield, … | **needs attention**: 3 changes to properties its records hold; 4 new properties on Analysis, CatalyticTest, Characterization, Computation |
| 0.4.0 → 0.5.0 | breaking: the catalysis checklist applies a test's cases by its driving_forces (a test that lists none has unknown applicability,… | **needs attention**: 1 checklist changes; 6 new properties on Analysis, CatalyticTest, Characterization, Computation |
| 0.5.0 → 0.5.1 | Represent bifunctional (tandem) catalysts: component function, integration mode and scale, site proximity (provisional) | **optional**: 4 new properties on Catalyst, HAS_COMPONENT |
| 0.5.1 → 0.5.2 | additive: ProductLump (a product reported as a lump or fraction) and SUBSET_OF; HAS_OUTPUT.to and PRODUCES.to accept a ProductLum… | **nothing to do** |
| 0.5.2 → 0.6.0 | breaking: site populations of a catalyst state (HAS_SITE from CatalystState with population_fraction, site_density, exposed_metal… | **needs attention**: 2 changes to properties its records hold; 1 new properties on Analysis |
| 0.6.0 → 0.7.0 | breaking: computed energies and kinetic parameters compared under explicit definitions (the kinds electronic_energy, reaction_ene… | **needs attention**: 2 changes to properties its records hold; 10 new properties on Computation, ElementaryStep; 3 unit contracts |
| 0.7.0 → 0.7.1 | additive change: kinds for enzyme activity, a Michaelis constant, a turnover number, transport criteria, an effectiveness factor,… | **optional**: 1 new properties on CatalyticTest |
| 0.7.1 → 0.7.2 | what TRACE-AI asks of agentic campaigns, models and their validations; the autonomy of curation and people's checks of records | **optional**: 6 new properties on EVALUATES |
| 0.7.2 → 0.7.3 | the programs that drive a test, the analyses of its responses, and the reactor treatment, interval method and identifiability of … | **optional**: 18 new properties on Analysis, Operation |
| 0.7.3 → 0.7.4 | Analysis kind thermal_contribution with partition_method; ThermalContributionAnalysis deprecated, still valid | **optional**: 1 new properties on Analysis |
| 0.7.4 → 0.7.5 | methods as records (Method, USES_METHOD) and benchmarks of a method; a failed calculation's status_reason and failure_kind; ident… | **optional**: 5 new properties on Analysis, CatalyticTest, Characterization, Computation |
| 0.7.5 → 0.7.6 | syntheses of any method: preparation methods, design aims and strategy; the function of each input; energy input and repetitions … | **optional**: 6 new properties on HAS_INPUT, Preparation |
| 0.7.6 → 0.7.7 | ligand removal (an action and the agent's function), a hold step; checklist: a stage of a family counts for growth_control and co… | **nothing to do** |
| 0.7.7 → 0.7.8 | Synthesis conditions: pH, stirring, fill fraction, gas flow mode and cooling of a step; concentration, stock concentration, fract… | **optional**: 6 new properties on HAS_INPUT, Treatment |
| 0.7.8 → 0.7.9 | What curated nanoparticle-synthesis recipes asked for: an anneal step and an annealing treatment; the functions isolating_medium,… | **optional**: 2 new properties on HAS_INPUT, HAS_PHASE |
| 0.7.9 → 0.8.0 | breaking: a selectivity is compared by what it counts (selectivity_count: carbon atoms, mole, mass) and what it is a share of (se… | **needs attention**: 2 changes to properties its records hold |
| 0.8.0 → 0.8.1 | additive change | **optional**: 3 new properties on CatalyticTest, HAS_COMPONENT, Reactor |
| 0.8.1 → 0.8.2 | additive change | **optional** |

Verdicts: *needs attention*: the step rewrites records, asks the checklist for more, or compares values this graph holds by something they may not state; *optional*: new properties or value fields the records could record; nothing in them changes; *checked automatically*: unit contracts: validation after the upgrade checks every value against them; *nothing to do*: nothing in it concerns the labels, properties or values this graph uses.

### 0.2.1 → 0.3.0

breaking: quantity contracts (a value's unit by its kind's dimension; the contexts a comparison needs; normalized_by; HAS_COMPONENT.concentration)

*Migration rule:* quantity contracts: a HAS_COMPONENT fraction in an amount unit moves to amount, one in a concentration unit to concentration (the value object whole, its fraction_basis dropped); a value of another dimension than its quantity stops the step; every record, id and other value kept

*Rewrites (47):* ex:msyn/10.1021-j150293a009/link/8: fraction 200 g -> amount (mass (M)), fracti…; ex:msyn/10.1021-j150293a009/link/9: fraction 22 g -> amount (mass (M)), fractio…; ex:msyn/10.1021-ja01409a015/link/3: fraction 2 mol -> amount (amount (N)), frac…; ex:msyn/10.1021-ja01409a015/link/4: fraction 1 mol -> amount (amount (N)), frac…; ex:msyn/10.1246-nikkashi1898.54.504/link/188: fraction 0.85 g/100 m3 -> concent… …

*Changes to properties its records hold:*
- edges.HAS_COMPONENT.fraction: context fraction_basis from None -> 'fraction_basis' (911 records hold it)

### 0.3.0 → 0.4.0

breaking: result entries (Experiment.result_values with value ids, phase, stream, unresolved_target); conversion, product_yield, selectivity, production_rate, product_amount and balance kinds; in catalysis a species is a ChemicalSpecies (context_targets)

*Migration rule:* result entries: nothing is rewritten (no value moves into result_values; the scalar results, the results map and the per-product lists keep their meaning); a value counted for a species whose target is not a ChemicalSpecies stops the step; every record, id and value kept

*Changes to properties its records hold:*
- context_targets.species: a value's target read as its species names a ChemicalSpecies (None records hold it)
- nodes.CatalyticTest.conversion: quantity species_fraction -> conversion (241 records hold it)
- nodes.CatalyticTest.yield: quantity species_fraction -> product_yield (81 records hold it)

### 0.4.0 → 0.5.0

breaking: the catalysis checklist applies a test's cases by its driving_forces (a test that lists none has unknown applicability, never a complete checklist) and looks for connected evidence; CatalyticTest.interpretations, Analysis.evaluation_basis, power_supply_input and the dark control's control_kind, differs_in, temperature_matched_at and temperature_matched_over are new (provisional)

*Migration rule:* reporting applicability and connected evidence: nothing is rewritten and nothing stops the step (a test that lists no driving force has unknown applicability; no interpretation is inferred); every record, id and value kept

*Checklist changes on labels this graph uses:*
- CatalyticTest: applies its cases by driving_forces (a record that states none is unknown)

### 0.5.2 → 0.6.0

breaking: site populations of a catalyst state (HAS_SITE from CatalystState with population_fraction, site_density, exposed_metal_count and site_inventory); the site_fraction, site_density and site_count kinds; a turnover frequency compared by its species, divided by a site count or a site density, and saying how it was calculated (a warning when it does not); operando defined as characterized while the kinetics are measured; DURING's specimen, timing, kinetics and benchmark; Analysis spectral_fit and limitations; the checklist's operando and spectral-fit cases (provisional)

*Migration rule:* site populations and site-normalized rates: nothing is rewritten (no population moves onto a state, no operando label or DURING link changes); a turnover frequency whose target is no chemical species, or whose denominator is not a site count or a site density, stops the step; every record, id and value kept

*Changes to properties its records hold:*
- quantities.kinds.turnover_frequency: its denominator names a site_count or a site_density only (None records hold it)
- quantities.kinds.turnover_frequency: denominator ['dimensionless', 'amount'] -> ['dimensionless', 'amount', 'amount_per_mass', 'number_per_mass', 'amount_per_a… (None records hold it)

### 0.6.0 → 0.7.0

breaking: computed energies and kinetic parameters compared under explicit definitions (the kinds electronic_energy, reaction_energy, reaction_enthalpy, reaction_free_energy, activation_energy, activation_free_energy, apparent_activation_energy and degree_of_rate_control; the contexts process, structure, level_of_theory and charge_treatment, the last two read from the value's producer; what a kind shows); ElementaryStep energies and RATE_CONTROL's degree of rate control bound to their kinds; Computation's method fields, Model.stored_in and REPRESENTS aspect and assumptions (provisional)

*Migration rule:* computed energies and kinetic parameters: nothing is rewritten (no method text read into a level of theory, no reaction, charge treatment or setting filled in, balance_status kept); a value whose unit is of another dimension than its kind's, or whose target is not a record its kind's context names, stops the step; every record, id and value kept

*Changes to properties its records hold:*
- context_targets.process: a value's target read as its process names a ElementaryStep or Reaction (None records hold it)
- context_targets.structure: a value's target read as its structure names a StructureModel (None records hold it)

### 0.7.9 → 0.8.0

breaking: a selectivity is compared by what it counts (selectivity_count: carbon atoms, mole, mass) and what it is a share of (selectivity_whole: converted reactant, products without CO2, a pool named by the new value field relative_to); a value that states neither is compared only with such values (provisional)

*Migration rule:* selectivity basis: nothing is rewritten (no basis or definition text is read into a count or a whole, no relative_to is filled in) and nothing stops the step; every record, id and value kept

*Changes to properties its records hold:*
- quantities.units: mass% dimensionless, fraction_basis mass -> dimensionless, fraction_basis mass, selectivity_count mass (None records hold it)
- quantities.units: wt% dimensionless, fraction_basis mass -> dimensionless, fraction_basis mass, selectivity_count mass (None records hold it)

## New properties available (optional)

Records could hold these; none needs them. Name the ones worth re-reading for with `--enrich Label.property` and they join the worklist.

| property | since | records of that label |
|---|---|---|
| `HAS_COMPONENT.concentration` | 0.3.0 | 1626 |
| `Analysis.result_values` | 0.4.0 | 81 |
| `CatalyticTest.result_values` | 0.4.0 | 684 |
| `Characterization.result_values` | 0.4.0 | 132 |
| `Computation.result_values` | 0.4.0 | 16 |
| `Analysis.evaluation_basis` | 0.5.0 | 81 |
| `Analysis.power_supply_input` | 0.5.0 | 81 |
| `CatalyticTest.interpretations` | 0.5.0 | 684 |
| `CatalyticTest.power_supply_input` | 0.5.0 | 684 |
| `Characterization.power_supply_input` | 0.5.0 | 132 |
| `Computation.power_supply_input` | 0.5.0 | 16 |
| `Catalyst.integration_mode` | 0.5.1 | 484 |
| `Catalyst.integration_scale` | 0.5.1 | 484 |
| `Catalyst.site_proximity` | 0.5.1 | 484 |
| `HAS_COMPONENT.function` | 0.5.1 | 1626 |
| `Analysis.limitations` | 0.6.0 | 81 |
| `Computation.charge_treatment` | 0.7.0 | 16 |
| `Computation.computation_kind` | 0.7.0 | 16 |
| `Computation.dispersion` | 0.7.0 | 16 |
| `Computation.hubbard_u` | 0.7.0 | 16 |
| `Computation.level_of_theory` | 0.7.0 | 16 |
| `Computation.settings` | 0.7.0 | 16 |
| `Computation.solvation` | 0.7.0 | 16 |
| `Computation.spin_treatment` | 0.7.0 | 16 |
| `ElementaryStep.activation_free_energy` | 0.7.0 | 7 |
| `ElementaryStep.reaction_free_energy` | 0.7.0 | 7 |
| `CatalyticTest.catalysis_mode` | 0.7.1 | 684 |
| `EVALUATES.folds` | 0.7.2 | 5 |
| `EVALUATES.generalization` | 0.7.2 | 5 |
| `EVALUATES.grouped_by` | 0.7.2 | 5 |
| `EVALUATES.preprocessing_within_split` | 0.7.2 | 5 |
| `EVALUATES.split_seed` | 0.7.2 | 5 |
| `EVALUATES.split_strategy` | 0.7.2 | 5 |
| `Analysis.concentration_measure` | 0.7.3 | 81 |
| `Analysis.demodulation_harmonic` | 0.7.3 | 81 |
| `Analysis.modulation_period` | 0.7.3 | 81 |
| `Analysis.phase_reference` | 0.7.3 | 81 |
| `Analysis.phase_reference_species` | 0.7.3 | 81 |
| `Analysis.rate_basis` | 0.7.3 | 81 |
| `Analysis.reactor_model` | 0.7.3 | 81 |
| `Analysis.standard_pressure` | 0.7.3 | 81 |
| `Analysis.thermodynamic_consistency` | 0.7.3 | 81 |
| `Operation.amplitude` | 0.7.3 | 2 |
| `Operation.bit_duration` | 0.7.3 | 2 |
| `Operation.levels` | 0.7.3 | 2 |
| `Operation.program_detail` | 0.7.3 | 2 |
| `Operation.pulse_amount` | 0.7.3 | 2 |
| `Operation.pulse_width` | 0.7.3 | 2 |
| `Operation.sequence_length` | 0.7.3 | 2 |
| `Operation.time_origin` | 0.7.3 | 2 |

… and 24 more (JSON report).

## What the newer checklist asks that the records lack

Nothing new: the records meet the newer checklist as well as they met the old one.

## Comparisons that now need a context the values do not state

Re-reading settles each one either way: the passage states it (gauge or absolute, which reactant a conversion counts), or it does not, and the value records that the source is silent, so that a query can say why it keeps the value apart.

| kind | context | values | records | sources |
|---|---|---|---|---|
| pressure | `pressure_convention` | 649 | 649 | 73 |
| composition_fraction | `fraction_basis` | 488 | 488 | 57 |
| space_velocity | `space_velocity_basis` | 402 | 402 | 38 |
| space_velocity | `flow_reference` | 381 | 381 | 37 |
| conversion | `species` | 239 | 239 | 21 |
| product_yield | `species` | 81 | 81 | 8 |
| flow_rate | `flow_reference` | 77 | 77 | 14 |

## Re-reading worklist, by source

Only these sources' cited passages would be read again, the top ones first. Each record, its locators and what it lacks are in the JSON report (`--format json`).

| source | records with a gap | records for a new property | passages |
|---|---|---|---|
| (139)Synthesis of Methanol from Carbondioxide and Hydrogen I (1952) | 119 | 0 | 27 |
| Zinc Oxide–Chromium Oxide Catalysts for Methanol Synthesis (1935) | 102 | 0 | 69 |
| A Study of the Synthesis of Methanol (1928) | 88 | 0 | 22 |
| Production of methanol and other carbon compounds and catalytic agents (1936) | 57 | 0 | 23 |
| Synthesis of Methanol from Carbon Monoxide and Hydrogen (1928) | 54 | 0 | 14 |
| Methanol from Hydrogen and Carbon Monoxide (1928) | 45 | 0 | 48 |
| Synthetic methanol process (1932) | 38 | 0 | 13 |
| Synthesis of Alcohols Higher than Methanol from Carbon Monoxide and Hy (1928) | 35 | 0 | 16 |
| The Equilibrium between Carbon Monoxide, Hydrogen, Formaldehyde and Me (1934) | 32 | 0 | 8 |
| Catalysts for the Formation of Alcohols from Carbon Monoxide and Hydro (1928) | 29 | 0 | 25 |
| Behavior of Zinc Oxide and Zinc Oxide Chromium Oxide Catalysis in the  (1928) | 26 | 0 | 28 |
| Catalysts for the production of methanol and other carbon compounds (1933) | 26 | 0 | 9 |
| Catalyst for synthetic methanol production (1928) | 22 | 0 | 26 |
| The engineering problems associated with the high pressure synthesis o (1945) | 21 | 0 | 15 |
| Methanol synthesis at I. G. Farbenindustrie Plant at Oppau (1946) | 21 | 0 | 12 |
| Adsorption Measurements during the Synthesis of Methanol at Lower Pres (1965) | 20 | 0 | 21 |
| Synthesis of Methanol from Carbon Dioxide and Hydrogen over Copper-Alu (1945) | 18 | 0 | 25 |
| Concentration and Temperature Profiles in a Tubular Reactor for Methan (1962) | 18 | 0 | 19 |
| Über eine thermographische Methode zur Beurteilung der Aktivität des K (1965) | 17 | 0 | 16 |
| Rate of Methanol Synthesis (1958) | 17 | 0 | 34 |
| Catalyst for synthetic-methanol production (1927) | 17 | 0 | 9 |
| Methanol from Coal Mine Gas (1961) | 16 | 0 | 7 |
| Catalyst for synthetic-methanol production (1927) | 16 | 0 | 10 |
| De technische synthese van methanol (1950) | 15 | 0 | 2 |
| De fabricage van methanol: verslag van een fabrieksschema (1955) | 15 | 0 | 14 |

… and 53 more sources.

---

Generated by `scale graph upgrade`. Nothing was written unless `--write` was given; the graph stays valid at 0.2.0 either way.
