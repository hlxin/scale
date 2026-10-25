# Changelog

## Unreleased

- **Schema 0.7.7 (additive): what curating a real synthesis paper asked for.** Curating the syntheses of Gao et al.,
  Nat. Commun. 2022, 13, 2338 (doi:10.1038/s41467-022-29926-w; ordered B2 CuPd nanocubes in oleylamine, loaded on
  carbon and soaked in acetic acid) under 0.7.6 found four things the schema could not say or checked wrongly. All
  new terms are provisional.
  - **Ligand removal.** A step that takes capping ligands or surfactants off the particles is `action: remove_ligands`
    (it is not a wash, an etch or a ligand exchange), and what removes them is `synthesis_function:
    ligand_removal_agent`.
  - **A hold.** A step that keeps a temperature already reached is `action: hold`; the checklist asks it its
    temperature and duration, not a ramp, which a heated step is asked.
  - **Stages in the checklist.** A preparation whose stages are preparations of their own lists their families; what
    controls a colloid's growth, and an ALD's co-reactant, are now found on a stage of that family, which is asked on
    its own (0.7.6 asked the whole and found nothing).
  - **Fits.** A spectral fit and a numerical transport check are asked their `result_values`, the result entries the
    recipes record, instead of the older `results` map, which 0.7.6 asked for and so counted recorded results as
    missing.
  - An example (staged-colloid), a counterexample (the ligand-removal action given as an input's function), tests, the
    recipes.
    Existing documents keep 0.7.6; the migration step rewrites nothing.

- **Schema 0.7.6 (additive): syntheses of heterogeneous catalysts by any method, chemistry and strategy.** Requested
  by @hlxin: the schema recorded a preparation's steps with their conditions but not what kind of synthesis it was,
  what each chemical did in it, what it was designed to achieve or the structure it gave, so a question about capping
  agents, structure-directing agents, shapes, facets or single-atom syntheses came back as a schema gap. All new
  terms are provisional.
  - **The method and the strategy.** A Preparation lists its method families (`preparation_methods`, 59 values from
    impregnation, ion exchange, strong electrostatic adsorption and deposition-precipitation through sol-gel,
    hydrothermal, colloidal, polyol, seeded growth and hot injection, solid-state, mechanochemical, pyrolysis, thermal
    shock and exsolution, flame spray pyrolysis, CVD, ALD, PVD and cluster deposition, electrodeposition, dealloying and
    templating), what the source says it is designed to control (`design_aims`) and how (`strategy`), how much one run
    made (`batch_scale`) and what it gave (`outcomes`). A stage made by a method of its own is a Preparation `PART_OF`
    the whole.
  - **What each input does.** `HAS_INPUT.synthesis_function` (reducing agent, capping agent, shape- and
    structure-directing agent, template, mineralizer, linker, modulator, fuel, carbon or nitrogen source, etchant,
    co-reactant and 21 more), several per input where the source says so; the kernel's role stays. A domain file can
    now add properties to a kernel edge type it sees (`adds_properties`), as it could to a label.
  - **What drives a step.** `ProcedureStep.energy_input` (thermal, microwave, ultrasound, mechanical,
    electrochemical, light, laser, plasma, flame, Joule heating, electron or ion beam), `repetitions` for a step
    repeated as one block with its sub-steps `PART_OF` it (an ALD cycle), and 28 more actions (inject, reflux,
    crystallize, centrifuge, sonicate, exchange, deposit, pyrolyze, leach, etch, replace, mill, spray, dose, purge,
    carburize, nitridize, …).
  - **The structure obtained.** A CatalystState states its `particle_shape`, `architecture` (single atoms, clusters,
    core-shell, yolk-shell, intermetallic, encapsulated, egg-shell, …), `exposed_facets` and `dimensionality`; it is
    `REACHED_BY` the preparation and `DETERMINED_BY` what shows it. That an aim was reached, or how the structure
    formed, stays the authors' Claim.
  - **The checklist** asks a Preparation for its method, families, output, steps and precursors; a colloidal synthesis
    for what controls its growth; an ALD for its co-reactant; a synthesis with a structural aim for the structure
    observed; a heated step for its temperature, time, gas and ramp (should items, provisional).
  - 31 mappings of the method families and step actions to CHMO terms (one to OBI's centrifugation); the recipes (Syntheses by any method, with a table by
    family) and section G of the preparation reporting checklist; an example of six syntheses (synthesis-examples),
    CQ-37 to CQ-39, four counterexamples, tests. Existing documents keep 0.7.5; the migration step rewrites nothing.

- **Schema 0.7.5 (additive): the methods calculations apply, benchmarks of a method, and failed calculations.**
  Requested by @hlxin (computational records for corpora that mix in silico and physical experiments). A calculation
  named its functional only in text (`level_of_theory`), so a benchmark of a functional or a limitation a source states
  about it could not be found from the calculations that use it, and nothing said why a calculation failed. All new
  terms are provisional.
  - **Methods as records.** A Method (kernel) is a named method or approximation: an exchange-correlation functional
    (with its rung, `functional_class`), a dispersion correction (its variant, such as D3's damping, in `version`), a
    basis set, a pseudopotential set, a solvation model, a family of interatomic potentials or a statistical method,
    with its `aliases` and defining `reference`. An experiment `USES_METHOD` it; `level_of_theory` keeps the name the
    source gives, and the validator warns when it is none of the names of the electronic-structure method the
    calculation uses. A benchmark `EVALUATES` the Method (`evaluation_kind: benchmark`), and a limitation a source states
    is a Claim `ABOUT` it.
  - **Failures.** An experiment that failed or was aborted states why (`status_reason`, kernel); a Computation states
    what stopped it (`failure_kind`: electronic_not_converged, geometry_not_converged, saddle_point_not_found,
    unintended_state, numerical_error, resource_limit, input_error, software_error). The checklist asks a failed
    calculation for both; the rerun that succeeded `REPLICATES` it.
  - **Identifiers.** Schemes for a functional's libxc names (`GGA_X_RPBE+GGA_C_PBE`, which tells RPBE from revPBE), a
    Catalysis-Hub.org publication and a NOMAD entry.
  - **Why these first.** An audit of ten open-access catalysis papers that combine DFT or microkinetics with
    experiments found that all nine with atomistic calculations cite their functional, five benchmark it against
    reference values and seven state its limitations; four of nine name D3 without its damping.
  - An example (method-examples), CQ-35 and CQ-36, three counterexamples, tests. Existing documents keep 0.7.4; the
    migration step rewrites nothing.

- **Fewer skills, named for what they act on.** `curate-source` and `curate-dataset` are merged into **`curate-corpus`**
  (version 0.3.0): one skill curates one publication, one data file (its section *A data file*) or a frozen corpus of
  many sources (a run through subagents with a second reading, `references/runs.md` and `scripts/curate_run.py`).
  `scale call skills` and the MCP prompts still find it by the old names (`renamed_from`). The literature skill
  `paper-acquisition` becomes **`index-sources`** (version 4.0.0), listed in `scale-release.yaml`; `curate-topic` is
  replaced by the request table in `skills/README.md`. What is catalysis's, not the skills' (the topic vocabulary,
  the CO2 reduction paper index's filter and query tool) moves to `graphs/catal-commons/literature/`; index-sources
  reads its vocabulary from a path, `$INDEX_SOURCES_VOCAB`, the project's `.scripts/vocab.json` or that file.
- **Sources, not papers; fetching is its own skill.** The literature skills follow SCALE's names: a *source* is a
  paper, preprint, patent, thesis or report (SCALE's `Source`; a dataset found with them becomes a `Dataset` when
  curated), the services that find them are *databases*, and `sources/index.db` is *the index* (it was
  `publications/papers.db`): tables `sources`, `source_*`, `databases`, `source_databases`, `topics` and
  `source_topics` (were `collections`), columns `source_id`, `licence*` (SCALE's spelling) and `retrieved_from`,
  `retrieved_url`, `retrieved_on` (as SCALE's `Source` names them). A topic's PDFs are in `sources/<topic>/files/`,
  the machine-wide keys in `~/.scale/sources/`; `database.md` maps the index's document types to `Source.kind`. A project made before is upgraded in place the first time a script opens it (`upgrade.py
  --db` for a database that came alone, such as a shared catalog). index-sources' download mode becomes
  **`fetch-corpus`** (version 1.0.0): it fetches the files of a frozen corpus (`--corpus`), paywalled ones only
  through the library's EZproxy, and `settle_corpus.py` records in the manifest which files it got and why the others
  are missing. `freeze_corpus.py` now selects a corpus by its rule before anything is fetched, so a part of a large
  catalog is fetched without making a subtopic.

- **Schema 0.7.4 (additive): one analysis kind for how much of a rate is heating, for any driving force.** Requested by
  @hlxin (ThermalContributionAnalysis was the one analysis that was a record type of its own, it covered light only,
  and its results were fields of its own). An Analysis may now be of kind thermal_contribution: it separates the
  heating a driving force causes from its other effects on a rate (light, a plasma, a field, a current), HAS_INPUT the
  driven test and the controls it compares, states its partition_method (now the analysis's, with the general
  control_at_matched_temperature beside dark_control_at_matched_temperature) and gives the shares as result entries.
  ThermalContributionAnalysis is deprecated, the first record type to be: it stays valid, inherits partition_method
  from Analysis, and a document of 0.7.4 or later that uses it is told what replaces it (a warning; `scale graph
  describe` says it too). The light checklist accepts either form; a new case asks a thermal_contribution analysis for
  its method, partition, results, limitations and the test it separates (one driven by something besides heat). A
  synthetic example (`thermal-examples/thermal-contribution.json`, light and a plasma), CQ-34, a counterexample and
  tests.

- **Schema 0.7.3 (additive): tests driven by a program, the analyses of their responses, and fitted kinetic
  constants.** Requested by @hlxin (grow toward transient kinetics). SCALE could say that a test was operated
  dynamically (an Operation's pattern, period and segments), but not the levels it switched between, a pulse, a
  pseudo-random sequence, what t = 0 was or whether the program could be rebuilt; nor what an isotope switch or a
  modulation measured, nor how a fit treated its reactor. All new terms are provisional.
  - **The program.** An Operation states its waveform (square, sinusoidal, triangular, pulse_train,
    pseudo_random_binary), its levels (numbers, or text values such as 12CO and 13CO), amplitude, a pulse's amount and
    width, a sequence's length and bit duration, a segment's label (the half-cycles of a chemical loop), what t = 0 is
    (time_origin) and how much of it the source gives (program_detail: exact, parametric, descriptive). A time series
    states its time resolution, its delay and whether it was corrected for it; a DURING link how the observation and the
    kinetics were synchronized.
  - **What the responses give.** An Analysis may be an isotopic_transient, pulse_response, modulation_excitation,
    step_response or frequency_response, with new kinds of result: surface_residence_time and
    surface_intermediate_amount (an isotope switch at steady state; Shannon and Goodwin, Chem. Rev. 1995), phase_delay
    (phase-sensitive detection; Urakawa, Burgi and Baiker, Chem. Eng. Sci. 2008) and response_time_constant, each
    compared by the species it is of. A modulation analysis states what its delays are measured against
    (phase_reference: the stimulus or another species' response, phase_reference_species), the modulation_period and
    the demodulation_harmonic, and a phase delay is compared only within one reference, period (its exact number) and
    harmonic; a delay without a reference or a period, or recorded on a test with no analysis, is left out (a context
    may read a producer whose label lacks its property as stating none: without_property). That a species is an
    intermediate or a spectator stays a Claim the analysis supports.
  - **Fitted constants.** A kinetic fit states its reactor_model (differential, stirred_tank, plug_flow,
    axial_dispersion, batch, knudsen_pulse), rate_basis, concentration_measure (and standard_pressure) and
    thermodynamic_consistency (Mhadeshwar, Wang and Vlachos, J. Phys. Chem. B 2003); a value states how its interval was
    obtained (interval_method: curvature, profile_likelihood, bootstrap, bayesian_posterior, …) and, when fitted,
    whether the data determine it (identifiability; Raue et al., Bioinformatics 2009). A comparison of a step's
    activation energy shows each value's reactor treatment and names a group that mixes treatments.
  - **Fixed (the tools, every schema version with the contract, 0.7.0 on):** a value whose producer states no charge
    treatment was left out of a scientific comparison as missing_context; it is now compared with the others that
    state none ("not stated"), as the contract has said since 0.7.0.
  - An example (transient-examples), CQ-31 to CQ-33, six counterexamples, the checklist's cases for pseudo-random,
    periodic and pulsed programs, transient analyses (a modulation analysis's reference, period and harmonic) and
    kinetic fits. Existing documents keep 0.7.2; the migration
    step rewrites nothing.

- **Schema 0.7.2 (additive): what TRACE-AI asks of agentic catalysis, and who checked the records an agent
  extracted.** Requested by @hlxin. TRACE-AI (Xin et al., Chem Catal. 2026, doi:10.1016/j.checat.2026.101755) is the
  reporting checklist for catalysis enabled by AI: data, models, workflow and executable artifacts (items A1-D3). SCALE
  could record a model and its validations, but not most of what TRACE-AI asks, and it said nothing of how its own
  records were curated. All new terms are provisional.
  - **Agentic campaigns.** A Design states its autonomy_level as the source declares it (TRACE-AI's A0-A5), its
    human_oversight, interventions and intervention_count, the agent_policy and objectives, safety_bounds and
    safety_measures, why it stopped (stop_reason, beside stopping_criterion), what it did with failed or excluded runs
    (negative_results_policy, excluded_count) and what changed unplanned (post_hoc_changes). A proposal's PROPOSED_BY
    says what a person decided about it (human_decision). The catalysis checklist asks an adaptive design for them.
  - **Models and their validations.** A Model states its architecture, hyperparameters, training_objective, pretraining
    and uncertainty_method, with the uncertainty it reports (uncertainty_components), how that was checked
    (uncertainty_calibration) and used (uncertainty_use). A validation's EVALUATES states how it split the data
    (split_strategy: random, grouped, time_based, out_of_distribution, prospective, external; grouped_by, folds,
    split_seed, preprocessing_within_split) and what its results reflect (generalization). A validation that states
    it split one table (random, grouped, time-based, out of distribution) is no longer flagged for sharing that dataset
    with the fit (the folds of a cross-validation), nor for what both reach only through it; an observation both take
    directly, or a record reached through another dataset, is still flagged, and so is a validation called external or
    prospective on the training data. A Dataset may be a notebook.
  - **How the records were curated, and who checked them.** A stewardship's autonomy_level says how much of the
    curation an agent did (TRACE-AI's scale read for extraction). graph.checks records each check a person made of
    records against their source (record_check): who, when, which records, what against what, the fields checked,
    wrong and missed (the extraction's precision and recall), the outcome, and warnings acknowledged with a reason,
    which validation lists apart from the open ones (an acknowledgement matches exactly one warning). A filtered view,
    a bundle or a graph of some sources keeps the checks of the records it holds, leaves no id of a record it leaves
    out, and drops the counts of a check it keeps only in part (a record left out, or one with a value or an evidence
    item cut). `scale review sample` returns the check to fill in.
  - **`scale trace-ai G [--source ID]`** (agent tool `scale_trace_ai`) reads the checklist on a graph's records
    (domain/reporting/trace-ai.yaml: query plans per item): what they support, partly or not at all, what does not
    apply and why, and what a person checks in the source; it flags a random split and a metric stated without its
    uncertainty, and says how the records were curated. Items about a model, a dataset or a campaign are read record
    by record. A plan that asks for a value an older vocabulary lacks is reported as not assessed
    (`schema_gaps(..., values=True)`); a query's own answers are unchanged. It decides nothing about a source. See
    docs/trace-ai.md.
  - An example (agentic-examples), CQ-29 and CQ-30, five counterexamples. Existing documents keep 0.7.1; the migration
    step rewrites nothing.

- **Identifiers on records checked by their scheme (no schema change).** Requested by @hlxin (stronger connections to
  outside resources). A record's `identifiers` (a DOI, an InChIKey, a CAS number, an EC number, …) and a technique's
  `technique_id` were free text that nothing checked, so a misspelt identifier or a technique written as "XRD"
  pointed nowhere. Now core/mappings/identifiers.yaml lists 17 schemes with their patterns and resolvers, and the
  validator warns, never rejects, about an identifier that does not match its scheme or fails its check digit (CAS,
  ORCID), and about a `technique_id` or `method_id` that is no ontology term. The curation recipes list the Chemical
  Methods Ontology terms of 32 common characterization techniques (XRD is CHMO:0000156). The real graphs gain no
  warning. See docs/mappings.md.

- **Schema 0.7.1 (additive): terms for the subdomains of catalysis research SCALE lacked.** Requested by @hlxin (use
  what the ontologies for catalysis know to develop the catalysis schema). Mapping SCALE onto the fourteen subdomains of
  Ontologies4Cat (Behr, Borgelt and Kockmann 2024, doi:10.1186/s13321-024-00807-2) showed four that SCALE did not
  cover; the survey found no ontology that contains two of them (homogeneous catalysis; heat, transport and kinetic
  data) and one each for the other two. All new terms are provisional.
  - **Biocatalysis.** A catalyst of family enzyme or whole_cell; the enzyme a macromolecule, named with its EC number;
    the roles cofactor and solvent; the kinds enzyme_activity (per time in the enzyme unit, U, or the katal, with their
    prefixes; per mass, U/mg; per volume, U/mL; what it is divided by named or stated) and michaelis_constant. Basis:
    the Systems Biology Ontology's enzyme activity, specific activity and Michaelis constant.
  - **Homogeneous catalysis.** The roles ligand and cocatalyst (the photoelectrode's description already named a
    cocatalyst role that did not exist); the kind turnover_number (dimensionless, the amount of catalyst or the count of
    sites it is divided by named or stated), never compared with a turnover frequency.
  - **Heat, transport and kinetic data.** The kinds transport_criterion, compared by the criterion its definition
    names (Weisz-Prater, Mears, Carberry, Anderson) and, for a Mears criterion, by the transport it judges (mass or
    heat transfer, to, in or across the particles), since Mears gave several; effectiveness_factor, internal or
    overall; thiele_modulus, by its length (the particle radius, or its volume over its external surface) and its
    form (first order or generalized). A value that does not say is left out of a comparison, never guessed. A
    transport check kept its criterion values as untyped results before. Basis: Fogler's chapter on diffusion and
    reaction; Mears (1971); Aris (1957); Bischoff (1965).
  - **Energy.** The kind energy_consumption (energy per amount or per mass of product; a new dimension, specific
    energy), compared by the energy it counts (electrical, heat, every input) and its boundary (the device, or the
    process with its separation).
  - **How the source describes the catalysis.** A test's catalysis_mode (heterogeneous, homogeneous, biocatalytic),
    as the source says it, never inferred.
  - Mapped where an ontology defines them (REX's homogeneous and heterogeneous catalysis, SBO's enzyme, ChEBI's ligand,
    solvent and cofactor, QUDT's enzyme unit and katal; QUDT's catalytic activity and specific energy as related). An
    example (area-examples), CQ-27 and CQ-28, three counterexamples. The examples move to 0.7.1 (their version line only); the migration step rewrites nothing.

- **Units and quantity kinds mapped to QUDT (no schema change).** Requested by @hlxin (stronger connections to
  ontologies). SCALE's units and kinds of quantity named no external term, so a unit could not be matched with another
  system's or converted by a units service. Now 106 units are mapped to QUDT 3.5.3 (°C is unit:DEG_C, mL/min is
  unit:MilliL-PER-MIN, mostly exact) and 28 quantity kinds to QUDT quantity kinds (temperature, pressure, current
  density, …). Where SCALE leaves a unit open, the mapping says so: a gallon, a ton, a calorie or a Btu maps to each of
  QUDT's definitions as narrower, a normal or standard volume as close (QUDT counts it as an amount of substance, so
  its conversion factors do not apply). A kind is broader only where QUDT's kind holds in every unit SCALE reads it
  in; a reaction energy (eV or kJ/mol), a current density (QUDT's is a local vector) and a product amount are
  related. An enzyme's turnover frequency at saturation is SBO's catalytic rate constant (kcat). Every term was looked up in the QUDT release files and EBI OLS; none is
  deprecated. See docs/mappings.md.

- **SCALE's terms mapped to ontology terms (no schema change).** Requested by @hlxin: use what the ontologies for
  catalysis know, and make SCALE's connection to them stronger, without SCALE taking its meaning from an ontology.
  Before, the kernel named related vocabulary terms in words only (`maps_to: OBI planned process`), and no catalysis
  term was mapped. Now 135 mappings give each term's identifier and say how close it is (exact, close, broader,
  narrower or related): the kernel's labels and edge types to OBI, IAO, COB, SIO, STATO, SEPIO, BFO, RO, PROV, DCAT,
  Dublin Core, FOAF, Schema.org and SOSA; the catalysis labels and values to ChEBI, the Chemical Methods Ontology, REX,
  MOP, the Allotrope Foundation Ontology, OBI, CHEMINF, EDAM and ENVO (calcination is CHMO:0001467; a reference
  electrode is exactly CHMO:0002345). They sit beside the schema (core/mappings/, domain/mappings/), with a registry of
  the ontologies they cite, so a mapping is corrected without a new schema version. `scale domains check` keeps every
  mapping on a term of the schema and of a registered ontology; `describe` shows them; `scale schema mappings` lists
  them and exports a layer's set as SSSOM. Every term was looked up in the ontology's current release: two that the
  kernel names in words are obsolete in OBI (planned process, device), and their mappings name COB terms instead (an
  experiment or a procedure is COB's planned process; only a completed one is its completely executed planned
  process, since SCALE also records proposed, running and failed ones). The catalysis set also records the fourteen subdomains of catalysis research by which Ontologies4Cat
  classifies ontologies (Behr, Borgelt and Kockmann, J. Cheminform. 2024, 16, 16, doi:10.1186/s13321-024-00807-2),
  with the SCALE terms that record each and what SCALE lacks (biocatalysis; a ligand role and a turnover number; transport
  criteria; energy use beyond plasma and cost). See docs/mappings.md.

- **Schema 0.7.0 (breaking): computed energies and kinetic parameters are compared under explicit definitions.**
  Requested by @hlxin ("Define computational energy and mechanism comparison requirements"). Before, a computed
  adsorption energy was a number in eV like any other: a scientific comparison could rank an electronic adsorption
  energy with an adsorption free energy, energies relative to different reference molecules, constant-charge and
  constant-potential results, or values whose method was never stated.
  - **Kinds of energy.** The kernel names eight kinds (provisional): total electronic energy, reaction energy (an
    adsorption energy is one), reaction enthalpy, reaction free energy, an elementary step's activation energy and
    activation free energy, the apparent activation energy of an overall rate, and the degree of rate control. An
    energy is in eV, kJ/mol, Ha or Ry; an activation energy also in K (Ea/R, as Cantera allows). A comparison never
    puts two kinds in one group, even in one unit (this also keeps a fraction and an efficiency apart).
  - **What makes two energies comparable.** A reaction, adsorption or activation energy names the reaction or step it
    is the energy change of; that reaction's reactants and products, with their coefficients, are its reference states
    (O relative to H2O and H2 is another energy than O relative to O2). The computation that produced it states its
    level of theory (the functional) and whether it held the charge or the potential constant. A value that states no
    reaction, or whose computation states no level of theory, is left out of a comparison with that reason; one whose
    charge treatment is not stated is compared only with others that do not state it. A constant-charge result that an
    analysis converted to constant potential is compared with constant-potential ones. Basis: Catalysis-Hub (Winther et
    al. 2019, doi:10.1038/s41597-019-0081-y: energies from different codes and functionals are not necessarily directly
    comparable); constant inner potential DFT (Melander et al. 2024, doi:10.1038/s41524-023-01184-4).
  - **Shown, not grouped.** The dispersion correction, +U, spin treatment, solvation, temperature, pressure and
    electrode potential of the computation are shown with each compared value, and a group that mixes them is named; the
    validator warns when a free energy or an enthalpy states no temperature. Basis: AQCat25 (Allam et al. 2026,
    doi:10.1038/s41524-026-02099-6: spin treatment can change an adsorption energy by about 1 eV on magnetic surfaces).
  - **Computations.** A Computation states its kind (electronic structure, machine-learned, microkinetic, …), its level
    of theory, dispersion, +U, spin, solvation, charge treatment and numerical settings; input files, environment and
    structures stay in versioned, checksummed Datasets (a model's new `stored_in`). A state computed on a structure model
    has no specimen of its own; the model says which specimen or state it stands for, and what that assumes
    (`REPRESENTS` with `aspect` and `assumptions`). A machine-learned prediction names its model, checkpoint, training
    data and validations; the validator reports a validation made on the data the model was fitted to.
  - **Kinetic parameters.** An elementary step's activation and reaction energies, and a degree of rate control, are bound
    to their kinds (the breaking part: their units are now checked). An apparent activation energy from an Arrhenius fit
    is its own kind, never returned as a step's barrier; a degree of rate control is shown with the temperature and
    pressure of the run that found it.
  - **Balances.** The validator reports whether a reaction's or a step's recorded participants balance in atoms and in
    charge, each check on its own, naming what it lacks (a species whose charge is not stated is never taken as
    neutral). An imbalance is a warning; the source's `balance_status` is kept as it is. Basis: Cantera's element
    balance check.
  - **Examples and questions:** a synthetic computation example (domain/examples/scale-catal/computation-examples/) and
    CQ-23 to CQ-26; three counterexamples; recipes in skills/curate-corpus/references/recipes.md (Computational details).
  - **Migration:** the 0.6.0 -> 0.7.0 rule rewrites nothing; it stops on a value it cannot map (an activation energy in
    volts, an adsorption energy whose target is the adsorbate). Every example document moved to 0.7.0 unchanged.
  - **Also:** an `order_by` can rank a property of a link bound with `edge_as` (it returned nothing before).

- **Recording recipes for preparations and characterizations, with examples and competency questions (no schema
  change; scale-catal 0.6.0).** Requested by @hlxin ("Add reproducible synthesis and characterization recipes").
  - **Recipes** (skills/curate-corpus/references/recipes.md): the batch, its purchased lots and its steps; supported-
    metal impregnation; precipitation and coprecipitation; activation, storage, transfer and reaction history; what
    every characterization keeps (specimen and state, settings, standards and calibration, raw data, processing and
    fitting); XAS; electron-microscopy size distributions; chemisorption and site titration; physisorption; sizes from
    different techniques; nominal, bulk and surface composition. Each uses fields the schema has, and a test checks
    that every label, link and property the recipes name is declared.
  - **Examples** (domain/examples/scale-catal/preparation-examples/, synthetic): two impregnated batches of one
    nominal formula with their lots, histories and characterizations, and two purchased lots of a commercial catalyst;
    two coprecipitations in opposite orders of addition, with what the paper leaves unstated; a high-entropy alloy's
    nominal, bulk, surface and working-state compositions and three sizes.
  - **Questions:** CQ-18 to CQ-22 (how batches of one nominal catalyst differ; nominal and measured compositions, with
    a supported comparison and a missing-context one; sizes by technique; what a fitted coordination number rests on;
    what a source leaves unstated).
  - **Reporting:** a companion checklist, domain/docs/reporting/catalyst-preparation-reporting.md (draft 0.1).
  - **Conventions, not schema:** characterization measurands are named in their Variable's `quantity_kind`
    (`microscopy_particle_size`, `crystallite_size`, `hydrodynamic_size`, `count`, …), recorded as stated and not unit-checked
    until the kernel declares them; a distribution's statistics are separate results.

- **Schema 0.6.0 (breaking): site populations belong to a catalyst state, a turnover frequency says how it was
  calculated, and operando means characterized while the kinetics are measured.** Requested by @hlxin ("Scope site
  populations and activity assignments to catalyst states"); the turnover-frequency, operando, role and bound rules
  follow @hlxin's review. Before, a site could be attached only to a catalyst or a sample, so a population counted
  after reduction read as the population under reaction too, and the schema had no place for the count a turnover
  frequency was divided by.
  - **Sites in a state.** `HAS_SITE` can start from a `CatalystState` and holds for that state only, so nothing is
    carried to another state or from a sample to its states. It takes four values (provisional): `population_fraction`
    (a share of a stated whole), `site_density`, `exposed_metal_count` (the exposed atoms counted) and `site_inventory`
    (the sites a rate is divided by). Each keeps its origin (measured, derived, computed, assumed), its uncertainty or
    bound, what produced it and its evidence. What a count assumes goes in the counting Model's `assumptions`. A
    computed population sits on a state of the model, and a count for the formulation on a state of the Catalyst, with
    no specimen added. The kernel gains the kinds `site_fraction`, `site_density` and `site_count` and the count-per-area
    and count-per-mass dimensions.
  - **Turnover frequencies (the breaking part).** A turnover frequency is used as reported and says how it was
    calculated: the count it is divided by (`normalized_by`) and, in its `basis` or `definition`, what was counted as
    sites and how. One that says none of it is a warning, never an error (the denominator's `unstated: warning`).
    Rates of one product on different counts (per exposed atom, per site of a kind, per atom) are compared as
    reported, each row showing its basis and count; a rate is compared only with rates of the same product, as
    selectivities and yields are, so one that names no product is left out of a scientific comparison as missing
    context. Its denominator must be a site count or a site density, and may be per gram. A value divided by a
    one-sided bound that does not state its own bound is a warning; it stays in comparisons, its row showing the
    bound.
  - **Assignments.** Which phase, site or species is active, a spectator, a precursor or an inhibitor is a `Claim`
    with named `ABOUT` roles, supported or contradicted by the records it rests on (`premise_refs`). Co-active is left
    out, an open point of the reporting draft. This
    replaces the `ACTIVE_FOR` link the reporting draft had planned. No new label: the example shows the existing
    records express and query it.
  - **Operando.** Operando now means characterized while the kinetics are measured (before: "under reaction
    conditions while activity is measured or runs"). `observation_mode` stays the source's label, kept as reported.
    `DURING` states which specimen was observed, whether the kinetics were measured while the observation was made
    (`timing`: simultaneous or sequential) and what of them (`kinetics`: measured, matched to a conventional reactor or
    cell with its test as `benchmark`, products only detected, not measured); all provisional. A new checklist case
    asks an observation the source calls operando for the kinetics measured on the same specimen at the same time
    (`kinetics_while_characterizing`, a should item): a missing one lowers completeness, never validity.
  - **Spectra and fits.** `Analysis.analysis_kind: spectral_fit` and `Analysis.limitations` keep a fit, its
    alternatives and what it cannot tell apart, separate from the spectrum and from the claim drawn from it. The
    description of ensemble sampling no longer says categorically that an ensemble signal cannot tell phases apart:
    that depends on the technique, the data, the references and the model.
  - **Queries.** A `field` step can follow `normalized_by` into a link (`link`, `end`, `edge_as`), so a rate reaches
    the state and the site of its denominator.
  - **Examples and questions.** A new public example (`domain/examples/scale-catal/state-site-examples/`) and CQ-14 to
    CQ-17 (CQ-12 and CQ-13 are left to open pull requests). Six invalid examples cover the new rules. The 0.5.0
    examples and invalid examples are re-pinned to 0.6.0. The reporting draft (0.2) and the roadmap say what is done.
  - **Migration.** `scale graph migrate` rewrites nothing. It stops on a turnover frequency whose product is not a
    chemical species, or whose denominator is not a site count or density. A turnover frequency that names no product
    stays valid, but is no longer compared scientifically, and one that does not say how it was calculated is warned
    about. The kernel's meta-analysis example has four such rates: it pins 0.2.0 and is left as it is.
  - **Sources.** Wrasman et al. 2024 (doi:10.1016/j.jcat.2024.115451) on site counting, Meyer et al. 2024
    (doi:10.1016/j.jcat.2024.115369) on XAS, and Tackett et al. 2026 (doi:10.1021/acscatal.6c01946) on operando
    studies; the checklist cases cite them.

- **Schema 0.5.2 (additive): a product reported as a lump.** Answers #39. `ProductLump` (provisional) records a
  product the source reports as a fraction, a class or a carbon-number window rather than a species (C5-C11, gasoline
  range, "C2+"), with `SUBSET_OF` for a lump inside a wider one; `HAS_OUTPUT.to` and `PRODUCES.to` accept it (17 targets
  loosened). Existing records move unchanged (no migration rule). The selectivity sum check warns when selectivities of
  one record to a lump and to a lump or species it overlaps exceed 100 %; it drops containers (a lump that contains
  others) from the sum, reads no `result_values`, and cannot declare a species inside a lump. Fixtures, five
  counterexamples and competency question CQ-13 are added.
- **Query fix (#38): a value below its detection or quantification limit is read as an upper bound at its limit.** A
  numeric filter (`graph query`) left such a value out with the reason `below_detection_limit`; it now passes `le`/`lt`
  and fails `ge`/`gt` when every number below the limit decides, is left out as `one_sided_bound` when the limit
  straddles the filter, and never holds for `eq`/`in`. No schema change.
- **Schema 0.5.1 (additive): bifunctional (tandem) catalysts.** Requested by @hlxin (#40). A catalyst of two or more
  components that perform different steps (an oxide that activates CO, a zeolite that couples or isomerizes) can now
  say what each component does and how they are combined. `HAS_COMPONENT.function` lists the Reaction records a
  component performs; a Catalyst has `integration_mode` (granule mixture, core-shell, supported-on, dual bed),
  `integration_scale` and `site_proximity` (the authors' description). All are provisional. Competency question CQ-12
  and a fixture with five counterexamples cover them; CQ-01 to CQ-11 are unchanged. Records of earlier versions need
  no change.
- **Bundle schema: an endpoint declared `ANY` is exported unconstrained (tooling; no schema version raised).** Requested
  in #44. `REVISES` (both ends) and the targets of `HAS_INPUT`, `HAS_OUTPUT`, `ABOUT` and `INCLUDES`, which the
  kernel declares `ANY`, were written as all 55 kinds in the bundle's `edge_types`; they are now `[]`, which the
  conformance check reads as unconstrained, and so is `REPORTED_IN`'s source (any entity reports; its target stays
  `Publication`). The declared kind pairs drop from 6,014 to 1,395, the pairs the schema types; the pairs that occur
  are left to consumers to draw from the data. The other typed lists (`HAS_PART` 14 x 14, `PART_OF`, `PRECEDES` and
  the like) stay as the schema declares them; narrowing them is a separate schema change. The spec, its digest and the
  frozen versions are untouched.
- **Schema 0.5.0 (breaking): the checklist says when a test's reporting cannot be judged, and checks the evidence a
  reading needs.** Requested by @hlxin ("Check reporting applicability and connected kinetic evidence"). Before, a test
  that listed no driving force matched none of the checklist's driving-force cases, so a test stripped of every
  electrochemical item looked complete. The checklist could also read only a test's own fields and outgoing links, never
  a transport check or a control pointing at it.
  - **Applicability.** The catalysis checklist applies a test's cases by its `driving_forces` (`applies_by`). A test that
    lists none has unknown applicability: its driving-force items are neither checked nor met, and the report is never
    complete. An equilibrium estimate stays exempt. Documents pinned to an earlier version keep that version's reading.
  - **Connected evidence.** A checklist item can look for records linked to a test, up to two links away, in either
    direction. A test records what the source reads it as showing (`CatalyticTest.interpretations`, provisional), and
    each reading asks for its own evidence, as should items:
    - intrinsic kinetics: a transport check (an Analysis with `analysis_kind: transport_check`) whose new
      `evaluation_basis` says it was asserted, computed or tested; one that is more than asserted;
    - system performance: its reactor or cell, and no transport check;
    - light and heat separated: a dark control matched at a stated place and time, or a `ThermalContributionAnalysis`.
      A non-thermal effect needs the match at the illuminated surface, since a bulk match alone does not show it;
    - plasma-catalyst synergy: the plasma alone and the catalyst alone at the same temperature;
    - performance stability: a time series. Material stability needs the catalyst characterized during or after the
      test, because a constant performance trace alone does not show it.

    No conversion level, criterion value or control is required of every test. These follow the catalyst-testing
    chapter of the community report on rigor and reproducibility (Schweitzer, Gounder and Rioux 2023,
    doi:10.5281/zenodo.8029159) and Van Turnhout et al. 2025 (doi:10.1039/D5EY00027K), and the cases cite their
    sources.
  - **Controls and power.** `DARK_CONTROL_FOR` now states `control_kind` and `differs_in`, as `CONTROL_FOR` does (#41),
    and where and over which time the temperature was matched. `power_supply_input` keeps what the plasma supply draws
    apart from the plasma power (`discharge_power`).
  - **Queries.** A step on an edge type also follows the edge types that specialize it: a `CONTROL_FOR` step finds dark
    controls.
  - **Examples and questions.** New public examples (`domain/examples/scale-catal/evidence-examples/`) show transport
    checks by basis, dark controls, plasma controls, a heating ramp and the stability of replicate electrodes. CQ-09,
    CQ-10 and CQ-11 are new. The reporting guidance no longer calls transport checks unmodeled.
  - **Migration.** `scale graph migrate` changes no values and stops on nothing. Only what the checklist reports changes.
- **Schema 0.4.0 (breaking): each result recorded on its own, and queries that keep one result together.** Requested
  by @hlxin ("Make product measurements and their analytical context queryable"). Before, a query checked each
  condition on a test's results separately. Two analyses that reported a methanol yield of 40 % and of 80 % together
  passed "yield ≥ 70 % and ≤ 50 %", and a condition on a yield could pass on a selectivity.
  - **A list of results** (`Experiment.result_values`, provisional). Each result says what was measured (a Variable),
    for which product, by which analysis (`produced_by`) and calibration, in which phase and stream, on which basis,
    and which evidence states it. Its time comes from the analysis or the test. Each result has an `id`, and a
    reference names it by that id, never by its place in the list. These fields follow the Open Reaction Database's
    product measurements (Kearnes et al. 2021, doi:10.1021/jacs.1c09820). Single values, `results` maps and
    per-product lists stay as they are.
  - **Separate kinds** for conversion, yield, selectivity, production rate, product amount and balance, so a yield
    never stands in for a selectivity. A balance above 100 % is kept as reported. A warning says whether 100 % lies
    within its uncertainty.
  - **A product is a chemical species** in catalysis, so a source can never be a product. A product the source does
    not identify is kept in the source's words (`unresolved_target`). A product below the detection limit keeps its
    limit.
  - **Queries** (`scale graph query`). An `entries` step takes one result per row, and a `field` step follows its
    product or analysis. Two conditions on one list must be met by the same result, and the answer cites only that
    result's evidence. Two results that nothing tells apart are flagged, never averaged.
  - **Exports.** The kg-bundle and Neo4j exports now say that they carry results as plain text.
  - **Examples and questions.** CQ-01 now asks for ammonia by name, and a hydrogen-only blank in the pulsed
    electrochemistry example checks it. CQ-07 and CQ-08 are new, on a new public example
    (`domain/examples/scale-catal/product-measurement-examples/`). Eight invalid examples cover the new rules.
  - **Migration.** Documents pinned to 0.3.0 stay valid. `scale graph migrate` changes no values, and it stops only
    on a product that is not a chemical species.
- **Schema 0.3.0 (breaking): quantity contracts, and a scientific comparison mode in queries.** The kernel's new
  `quantities:` block says, for the quantities most often compared (temperature, pressure, electrode potential, current
  and current density, fractions, concentrations, flow and space velocity, product yields and efficiencies), the
  dimensions a value may be in, what a normalized quantity is divided by and the context without which two values are
  not comparable (a potential's reference scale, a current density's normalization, a pressure's convention, a volumetric
  flow's reference conditions, a space velocity's basis, a share's species); 47 catalysis properties bind one
  (`quantity:`, and `context:` for the sibling that states a context, such as `reference_scale` or
  `current_normalization`), and a Variable's `quantity_kind` brings its kind's to its values. The validator now rejects a
  unit of another dimension (a temperature in kg; mol/L under `HAS_COMPONENT.fraction`), reports a unit it cannot read,
  a basis that contradicts its record (except an evidenced conversion: derived or computed, with `produced_by`) and a
  reported percentage of a share above 100 %. `HAS_COMPONENT.concentration` is new, and the electrolyte examples record
  their salts' concentrations there instead of as fractions. The value field `normalized_by` (a record_ref) names the
  record and value a quantity is divided by (an electrode's ECSA); it is validated (record, path, dimension), and the
  viewer filter and the kg-bundle export withhold a value with what it names. `scale graph query` with `comparison:
  scientific` compares and ranks a value only within one unit and one context (stated with `context` to check it, or
  grouped), leaving out a value whose context is not stated (`missing_context`) or contradictory
  (`incompatible_context`); an ordinary plan is unchanged and names the contexts it compared across. Competency question
  CQ-06 asks which current densities have compatible area bases and potential references, on a new public example
  (`domain/examples/scale-catal/comparison-examples/`). Nothing is converted. Migration: documents pinning 0.2.x stay
  valid under their frozen version; `scale graph migrate` (and `scale kg update`) moves a `HAS_COMPONENT` fraction in an
  amount unit (g, mol) to `amount` and one in a concentration unit (mol/L, g/m3) to `concentration`, and stops on a value
  of another dimension it cannot map. The schema diff now classifies a change to a contract (a kind's dimensions, a
  context it is compared by, what a unit or a term reads as, a property's binding).
- **The agents' commits are credited to `claude[bot]`.** `anthropics/claude-code-action` writes the commit email
  with its default bot id, 41898282, which is `github-actions[bot]`'s, so GitHub credited the agents' commits (#20,
  #35) to `github-actions[bot]`. The workflow now sets `bot_id: "209825114"` (`claude[bot]`, the Claude GitHub App
  that opens their pull requests). Earlier commits keep their author.
- **Schema 0.2.1 (no change in meaning): `Preparation.steps` wording.** The description says steps link `PART_OF` with `order`; `HAS_PROCEDURE_STEP` is declared nowhere. Synthetic fixtures and a counterexample (`tools/tests/fixtures/procedure-steps`) cover it. Frozen v0.1.0 text is left unchanged. Answers #34.
- **`scale schema bump` carries the whole version change.** Besides freezing the base, raising the version and
  registering the step, it now records the new version's spec digest in README.md's table (the base marked frozen),
  pins the fixture and example documents the branch adds to the new version, and writes a step note that reads as the
  kind of change; it checks the table before writing anything. `scale schema check` asks for the digest row and for
  no added document pinning the base, and a test keeps README.md recording every version held.
- **One publication into a graph, in the browser: `service/` and `site/`.** A page (linked from the README) takes a
  PDF, a DOI or a link. A small service curates it with a model through the scale-catal tools: the curate-source
  skill, `scale source start`, and `scale source check` until it passes. The graph comes back with every quote capped
  by the source's rights, and the service keeps nothing. The page shows the graph with each record's values and
  evidence, and answers questions by the query-graph skill over the same `query` and `search` code as the CLI.
  Curating and asking need GitHub sign-in with an allowlisted account and are limited by daily budgets. Viewing,
  querying and searching a graph do not. Deploying it (the host, the OAuth app, the API key, GitHub Pages) is a
  person's to do (service/README.md).
- **Contribute a graph to catal-commons: `scale graph contribute`, and a button on the page.** The command adds a
  one-source graph to a graph kept as parts. It refuses a source already there: the same DOI, identifier, text
  digest, or title and year. Otherwise it moves the ids into the folder's namespace, adds the source's rights entry,
  caps the quotes under the folder's limits (none of a source in copyright in graphs/) and merges the evidence into
  the shared records it reaches. It writes only when the folder builds and validates. On the page, **Contribute to
  the commons** checks catal-commons on main and the open contributions, then has the service's bot open a pull
  request that credits the contributor. Only the graph the service curated and signed for that user can be
  contributed, and a person approves and merges.
- **One publication into a graph: `scale source start | check | finish`.** For a subgraph that studies one paper, patent or
  report. `start` takes a DOI, a PDF or both (or the text): it resolves the DOI's metadata (Crossref), and with a contact
  address (`--email` or `SCALE_CONTACT_EMAIL`, never assumed) downloads an open-access PDF (Unpaywall) only when it
  carries an open licence; reads the PDF's page texts (OCR where a page has none); and writes a working folder, by
  default in the SCALE working directory: the graph to fill, pinned to the chosen schema version (`--version`,
  `--domain`) with its Source, steward and project, the source's rights (`rights.yaml`), the page texts and `BRIEF.md`.
  The agent fills the graph following the curate-source skill; `check` validates it with every quote checked against
  the page texts (`--derive-links` writes the REPORTED_IN links the evidence implies), and `finish` builds the evidence
  index, a copy with quoted text capped (`--public`) and a kg-bundle with a short title (`--bundle`). The same three
  steps are agent tools (`scale_source_start | check | finish`).
- **`graphs/`: the graphs SCALE curates and shares.** A new top-level folder for graphs that grow, apart
  from the worked examples. Every graph is kept as parts with its `rights.yaml`, `stewardship.yaml` and corpus, and
  quotes each source only as far as its rights allow: `limits: {quote_chars: 0, source_chars: 0}` withholds every
  quote of a source in copyright (sha256 and length kept, `scale evidence rehydrate` restores it), and no source text
  is committed. `graphs/catal-commons/` is SCALE's evolving catalysis graph (empty: its steward and project);
  `graphs/methanol-synthesis-pre1966/` is the full methanol graph back in the repository (105 sources: the 55
  public-domain ones quoted in full, the 50 in copyright with no quoted text); the public example is checked again to
  be exactly its public-domain part. A rights file's `limits`, and a source's own
  `quote_chars` and `source_chars`, lower the copyright cap (0: no verbatim text). The skills for finding,
  downloading and curating sources for the commons, and merging graphs into bundles, come later.
- **The full methanol example leaves the repository; the public one stays.** `examples/methanol-synthesis-pre1966/`
  (105 sources, most in copyright: the graph with capped quotes, its corpus list, rights and the bundle zip) is removed
  and kept outside the repository, until a legal way to curate community graphs is settled. The public-domain example,
  `examples/methanol-synthesis-public/` (55 sources with their PDFs and page texts), stays and now carries the
  manuscript's seven query plans (`queries/`), and its tests check their answers. The test that it is exactly the
  public-domain part of the full graph runs where a restricted copy holds that graph (docs/commands.md); the
  parts round-trip test uses the public example. The earlier versions remain in the git history.
- **The package carries the public example.** `examples/` is bundled into the wheel (`scale/_data/examples/`): the
  public-domain methanol example whole, its parts, PDFs, page texts and query plans, shared directly as they are. The
  wheel grows from about 0.8 MB to about 27 MB; an installed package validates and queries the example on its own.
- **Only a collaborator's event starts @scale-agents**, now that the repository is public: a run spends the owner's
  Claude usage. Anyone's issue or comment is welcome; a collaborator's comment on it starts the team, which reads the
  whole thread as data.
- **scale-catal is on PyPI** from v0.2.0 (`uvx scale-catal …`); the documents no longer say it is not.
- **An approval with no text no longer starts @scale-agents.** It asked nothing, and the run failed for want of an
  `OUTCOME:` line (reported by a reviewer on #23). The instructions say a run that does nothing still ends with
  `OUTCOME: nothing`.
- **@scale-agents loads its instructions on every event.** On an event about a pull request the action restores
  `.claude/` from `main` (the head is untrusted), which removed the copied `.claude/CLAUDE.md` and roles: the agents
  ran without their rules and ended without an `OUTCOME:` line (#24). The workflow installs the instructions and
  roles, as on `main`, in `~/.claude/` (user memory and subagents), and the prompt says how to read the event
  (`scale thread`) and how to end.
## v0.2.0 — 2026-10-11

Schema 0.2.0, renamed `scale-catal` (breaking: the name only; documents at 0.1.0 migrate with `scale graph migrate`),
the `scale-catal` tools 0.2.0 and the skills; graphs kept as one part per source, and a fully open methanol example
with its public-domain sources, PDFs and page texts.

- **A graph kept as one part per source; a fully open methanol example.** `scale graph split` writes a graph as
  `parts/` (the header, the shared records, one file per source) and `scale graph build` builds it back, sorted by id;
  every command reads such a folder as one graph. The methanol graph splits and builds back to the identical file.
  `examples/methanol-synthesis-public/` holds its 55 public-domain sources (16 articles of 1923-1930, 39 patents)
  as parts, with their PDFs and page texts (`LicenseRef-PublicDomain-US`, NOTICE) and every quote in full; a test
  finds every quote in its source's page texts. The publication and copyright checks read a parts folder as one
  graph.
- **No bypass of the `main` ruleset.** The repository admin's bypass is removed: every change to `main`, the owner's
  included, is a pull request approved by a reviewer other than its author.
- **What testing @scale-agents on GitHub showed, fixed.** `scale thread N` gives the agents the whole thread of an
  issue or pull request, the line comments of reviews included (`gh pr view` leaves them out). A manual run names its
  issue and waits its turn with the other runs on it. The evidence verifier reads every line a rename changed, and a
  test keeps history under the names things had. The agents may change `governance/` and `.github/` (not workflows)
  when a change needs it, listed under Governance changes in the pull request. A run fails when the agents end
  blocked or do not say how they ended. `scale schema check` lists the committed bundles a schema change leaves at an
  older version, as a follow-up for a separate issue. The package and the schema keep their own versions: a release
  always raises the package version; the schema version moves only when the schema changes.
- **Two reviewers join; every reviewer is asked, one approval is enough.** Tianyou Mou (`@mutianyou2013`) and Raul
  Diaz (`@diazr04`) join as reviewers; the list stays open, with no fixed number, and more are added as they join. CODEOWNERS names every reviewer on every line, so GitHub asks all of them, and `scale domains check`
  fails when one is missing. A new `reviewers` workflow withdraws the open review requests when one reviewer approves
  (and comments who approved and merges) and, after a push, asks again every reviewer whose approval the push
  dismissed or who asked for changes. A request for changes still blocks the merge until its reviewer approves. The
  documents no longer speak of reviewer seats or of a bootstrap rule pending a second reviewer.
- **Package 0.2.0, with the schema renamed.** The package version is raised to 0.2.0 for the next release, v0.2.0
  (the package and the schema keep their own versions; here both move). The methanol example's bundle is re-exported at schema scale-catal 0.2.0 (`methanol-synthesis-pre1966_v3.0.0.zip`,
  following 2.0.0; 17,563 edges, unchanged), and the governance documents name the schema `scale-catal`.
- **Breaking: the schema `scale-graph` is renamed `scale-catal` (0.1.0 -> 0.2.0, issue #16).** The kernel
  `scale-graph-kernel` is `scale-kernel`; the manifest is `domain/graph/scale-catal.yaml`, the examples are in
  `domain/examples/scale-catal/`, and documents pin `"schema": "scale-catal"`. No label, edge type or property changes.
  Version 0.1.0 is frozen as it was (`domain/graph/frozen/scale-catal-0.1.0.yaml` and `core/graph/frozen/`, which still
  say `scale-graph`; digest unchanged), so a document pinning `scale-graph` 0.1.0 still validates against it. Migration
  step 0.1.0 -> 0.2.0 rewrites the pin (`scale graph migrate`, `scale kg update`); a document at 0.2.0 that still
  names `scale-graph` is rejected with a message pointing to it. `scale schema diff` reads a renamed schema or kernel
  as a breaking change. The kg-bundle schema and its `extends` entry are both `scale-catal` (`extends` names the graph
  schema's own name, `scale-graph` at 0.1.0); the version and the spec digest identify them, and the descriptions say
  which is which. The methanol graph is migrated to 0.2.0 (only the pin changed); its bundle is still the sealed
  release exported from 0.1.0. Spec digest of scale-catal 0.2.0: `166bfc5539df7f44de075a4fb504c54170af32d6b3a01a916d6171bfcecec714`.
  The v0.1.0 release and the 0.1.0 entries below keep the old name as history.
- **Fixes from a second code review.** Profile files are retired by design: a manifest listing `profiles:` is refused,
  and conformance reads `follows_domains` only. Bundle export: a released Publication keeps its id in later releases;
  two records never share a bundle id; every destination is checked before the first write (no link, nothing inside
  `--previous`), so a refused export changes nothing; a text may not be named like the manifest in any case. Evidence
  index: vectors not saved with their items, and a `.terms` file whose words changed, are rebuilt. Queries: a plan's
  text search ranks only the evidence of the rows it keeps (the methanol evidence-search plans now find q2 86, q3 92
  and q5 108 rows); a description shares no object with the kept schema. Schema change: a nested change that can
  invalidate documents is breaking. Validation: NaN and infinity are not values; a long chain is checked for cycles
  without recursion. REPORTED_IN ids of sources ending alike are distinct. Page reading compares every record of a
  PDF with its digest. The MCP server answers a line it cannot parse.
- **Fixes from a code review.** Bundle export: a parallel link with other values is listed, never merged under
  another's values (six in the methanol graph); distinct sources never share a Publication id; an export is never
  written over the release it follows; a shipped text is a plain file in `text/`, and one named by its source id is
  that publication's (quoted, never withheld); a typed absence goes where its unit and basis put it. Queries and the
  agent toolkit: a result shares no object with the document; a kept schema, document or index is read again when its
  files change (identity and change time included). Evidence search: an index is used only when it holds the
  document's quotes, whatever digest it names; a `.terms` file whose arrays changed is rebuilt; `k` is at least 1; `rrf`
  with a filter ranks only the items it keeps. The MCP server answers a malformed message and keeps serving. Stale
  counts and statements in the docs and the methanol example are corrected.
- **Simpler layout:** the skills are in `skills/` at the root, and the package's modules sit directly in
  `tools/` (the folder is the package `scale`; there is no `tools/scale/`).

## v0.1.0 — 2026-10-10

The first official release: schema 0.1.0 (the science kernel and the catalysis domain), the `scale-catal` tools
and the skills, with the methanol-synthesis example.

- **The Python package is `scale-catal`** (was `scale-schema`): SCALE is more than a schema. The commands are
  `scale` and `scale-catal`; the README installs it with one line.
- **One pull request for every change; proposals retired.** Anyone, a person or an agent, suggests a change (an
  issue, a comment) or opens a pull request; agents do the work; one person approves and merges, any reviewer, the
  person who suggested the change included. A schema change is a pull request like any other: it edits
  `core/graph/kernel.yaml` or `domain/graph/catalysis.yaml` directly and raises the one version in the same pull
  request, a breaking change the second number (0.1.0 -> 0.2.0), an additive change the third (0.1.0 -> 0.1.1).
  New commands: `scale schema diff | bump | check` (`tools/scale/schema_change.py`); `bump` freezes the base version,
  raises the version everywhere it is stated and registers the migration step, and `check`, run by CI's
  `specification-changes` job, asks for the version, the frozen base, the step (and rule, if breaking), a test for
  what is added and a CHANGELOG line, and writes a summary for the reviewer. Removed: the proposal folders
  (`core/proposals/`, `domain/proposals/`), `scale proposal …`, `scale review status`, `scale ci proposal-check |
  proposals`, `scale release build --proposal`, the apply-proposals and proposal-check workflows, the `APPLY_TOKEN`
  secret and decision records per change (`docs/decisions/` keeps decisions about the project). `@scale-agent`
  becomes `@scale-agents` (`.github/workflows/scale-agents.yml`), a team that starts on its own on every new issue,
  comment and pull-request review, with no tag or label: a discovery strategist frames the use case and coordinates; a
  data scientist proposes the corrections to records or changes to schema definitions; a protocol compiler writes
  the tests with their expected outcomes; an evidence verifier assesses the support, the counterexamples and the
  effects on existing records and queries; a systems engineer packages the change set (patch, evidence record,
  test cases, migration assessment) as the pull request (`.github/scale-agents/`). The
  `main` ruleset no longer requires `proposal-check` (re-apply `governance/github/ruleset-main.json`). Review policy
  version 4.
- **A knowledge-graph bundle's schema is the vocabulary: scale-catal 0.1.0.** `kg/schema.json` is no longer the
  subset of types a graph uses, named after the bundle and versioned with it: it is the catalysis vocabulary of the
  scale-graph version the graph pins, every label and edge type with every property a bundle can carry, the same in
  every bundle of that version, named `scale-catal` (catalysis) with the scale-graph version (`scale-kernel` for a
  kernel-only graph). Its `extends` names scale-graph 0.1.0 by its spec digest, which identifies it. A value not of its
  property's declared type is kept as text in `<property>_as_reported` (no type is changed for a graph), property
  names are snake_case (`pH` is `ph`), and every exported record is checked against the schema before anything is
  written. `scale graph validate` refuses a bundle's `kg/graph.json`, whatever version it names. The methanol bundle is
  released as 2.0.0 (`methanol-synthesis-pre1966_v2.0.0.zip`, following 1.1.1), titled "Methanol Synthesis CO/CO2+H2
  Pre-1966"; every type and property of 1.1.1's schema is in it; the format's validator reports 0 errors and one
  warning, that the schema's version is lower than 1.1.1's (the schema is another one, so its numbering restarts).
- **A knowledge-graph bundle has a short title by default.** A platform names an imported graph after the bundle's
  title (`topic`, and the schema's `title`). `scale graph export --to kg-bundle` takes `--title`; by default the title
  is the graph's own when it has at most 40 characters, and otherwise its leading words, cut at a word boundary and
  ending in "…", with the full title kept in the bundle's scope (the export says so). The curate-source skill asks for a
  short graph title with the scope's details in `description`. The methanol graph's title is now "Methanol Synthesis
  CO/CO2+H2 Pre1966" (its former title opens its description), and its bundle is released as 1.1.1 (`methanol-synthesis-pre1966_v1.1.1.zip`, following 1.1.0; only the title changed; the format's validator: 0
  errors, 0 warnings).
- **Maintained by researchers, independent of any institution or project.** The stewardship registry names one
  steward, "SCALE researchers" (`scale:org/scale-researchers`), and one project, `scale:project/methanol-synthesis-pre1966`
  (the methanol benchmark); the institutions, the funder and the funded project it named before
  are removed, as is the `vt` extension prefix (`exmpl` is now owned by the steward). The methanol example's
  stewardship, its graph's header and its stewardship records name that steward and project.
- **Knowledge-graph bundles in format 1.1.0: withheld quotes and typed absences.** The kg-bundle format 1.1.0 carries a quote
  withheld under the copyright cap (`quote_withheld`: its sha256 and length under `scale-match-text-1`, SCALE's
  verbatim normalization) and a value the source does not report (`_value_status`). `scale graph export --to kg-bundle`
  now writes both instead of dropping them: a link whose quotes are all withheld is an edge, and a typed absence says
  why the record has no value. The methanol graph exports as 17,563 edges instead of 14,107 (3,274 substantive edges
  resting only on withheld quotes) with 227 typed absences, and passes the format's validator with 0 errors and 0
  warnings. A withheld quote longer than the format's 600 characters is left out and counted (`withheld_too_long`: one
  in the methanol graph). The bundle is in the example folder (`methanol-synthesis-pre1966_v1.1.0.zip`), and
  [docs/kg-bundle-format.md](docs/kg-bundle-format.md) notes the format SCALE writes. The exporter is
  `tools/scale/kgbundle.py`, and its target `scale graph export --to kg-bundle`.
- **The methanol example, simplified and ready to recurate.** `examples/methanol-synthesis-pre1966/` keeps only what
  a reader and a recuration need: `sources.json` (the frozen corpus, all 178 candidates with their status, each of the
  105 in-scope sources with its PDF `pdfs/<slug>.pdf` and the PDF's sha256; it replaces `corpus/manifest.json`,
  `corpus/manifest-co-co2-hydrogenation.json` and `corpus/sources.json`), the graph, `rights.yaml`,
  `stewardship.yaml` and `queries/*.yaml`. The PDFs are local and git-ignored, named by slug: the DOI with `/` as `-`
  (a patent or report without a DOI: its number or corpus id). Removed and kept in the git history (commit `a169872`):
  release `v1.0.0` (a second copy of the graph), its kg-bundle (regenerated with `scale graph export --to
  kg-bundle`), the curation guide and assembly report, and the conversion tools of the earlier pipeline; recuration
  follows the `curate-source` skill. The query answers are unchanged.
- **Methanol example: 9 runs get the pressure their source states.** Read against its PDF, Molstad and Dodge (1935,
  `10.1021-ie50302a005`) state one testing pressure for their tests in their Experimental Procedure (178
  atmospheres absolute). The six runs of the high-temperature resistance test and the three Zn50Cr50 catalysts
  (dry-process, Groger) had it as not stated; they now carry it, citing that passage (a quote already withheld
  under the cap, so no quoted text is added), as another run of the paper did. Checklist violations: 121 → 112; the
  graph stays valid (0 errors) and every query answers as before. The other gaps were checked and are the sources'
  own: no temperature for the maxima of Frolich et al. (1928), no pressure for the Fig. 7 and 8 runs of
  `10.1246-bcsj.31.45`, and patent examples that only say "similar conditions".
- **Queries reuse what does not depend on the plan.** Every query used to hash the whole document, read its access and
  the publication status of its sources, and gather its evidence quotes, about 100 ms on the methanol graph whatever
  the plan. `pgraph_query.Graph` now computes each once, when first needed, and `run(..., graph=)` reuses it: the
  agent tools keep a document loaded by path with its graph and evidence index until the file changes, and the
  competency questions and proposal checks build one per document. A repeat query on the methanol graph takes 2-15
  ms; the answers are identical.
- **Text queries and search build the evidence index when none is saved.** `scale graph query` (a plan with `text`),
  `scale graph search`, the agent tools `scale_query` and `scale_search`, the competency questions and `scale proposal
  check` used to fail when no index lay beside the document (three of the methanol example's seven plans stopped with
  a missing-file error). The index is derived from the document alone, so they now build it in memory, deterministically
  and writing nothing, as `scale graph index` would save it; a saved index is still used only for its own document.
  The index stays uncommitted: about 30 MB for the methanol graph, and stale after any edit of a quote.
- **Evidence search for large graphs.** The search scored every quote in Python loops; at 930,000 quotes a query took
  2.6-3.5 s and 3.8 GB. It now reads an inverted index (only the postings of the query's words; saved beside the
  index as `<graph>.evidence.terms`, checked against the items it was saved with), computes the int8 cosine in exact
  float32 blocks over norms computed once (the float32 vectors kept in memory after a first query when they fit 2 GB)
  and sorts only the best candidates: about 20 ms (keyword) to 70 ms (hybrid) a query at 930,000 quotes once loaded.
  Results are unchanged: the same hits, scores and order as before in hybrid, vector and keyword mode (checked on the
  methanol graph; ties go by item id as before), so plans and their `min_score` keep their answers. Building the
  index hashes each feature once. A new mode, `rrf` (reciprocal rank fusion of the keyword and vector rankings, scores
  up to 2/61), is opt-in; `hybrid` stays the default.
- **People and agents open pull requests; one person approves and merges** (review policy version 3). An agent may now
  open a pull request ready for review, no longer only a draft; one person other than its author approves it and
  merges it, and agents still never approve, merge or apply. An agent opens its pull request under its own GitHub
  identity (the Claude GitHub App in the scale-agent workflow, or a bot account), never a person's, since GitHub does
  not let an author approve their own pull request (governance/repository-settings.md, "The agent"). The scale-agent
  workflow may run `gh pr create` without `--draft`.
- **The methanol-synthesis example is public** (`examples/methanol-synthesis-pre1966/`), a small benchmark for the
  repository. The curated graph of the historical methanol-synthesis literature published before 1966 was cleared
  for publication; the example keeps its CO and CO2 hydrogenation scope (105 sources, 4,868
  records, 16,586 links, 684 catalytic tests). It was moved from the consortium schema repository's 0.1.0 to its 0.5.0
  with that repository's tools and re-pinned to 0.1.0 (valid, 0 errors), and its quoted text was capped (`scale
  evidence cap`, which applies to the 50 in-copyright sources only; the 55 public-domain sources, the US patents
  and works published before 1931, keep every quote: 6,920 of 25,230 evidence items, all from in-copyright sources,
  carry withheld text). With it: the corpus (`corpus/sources.json`:
  the 105 sources and each PDF's sha256; the PDFs are local), the rights file, the frozen corpus manifest, the curation
  guide and assembly report, the manuscript's seven query plans and the curation tools. Its first release,
  `releases/v1.0.0/` (2026-10-09), is an immutable snapshot: the graph (sha256 `0dfc8c1c…ed13f`), the corpus list,
  the rights file and the plans, with `RELEASE.yaml` (schema 0.1.0 and its spec digest, counts, each plan's answer)
  and `SHA256SUMS`, built and verified by `tools/release_graph.py`. Its kg-bundle,
  `methanol-synthesis-pre1966_v1.0.0`, passes the format's validator (0 errors, 0 warnings): 4,850 nodes, 14,107
  edges; the 3,277 links whose quotes are withheld under the cap are left out, since format 1.0.0 has no place for
  withheld-quote evidence. The fragments, page
  texts, OCR and the earlier private kg-bundles stay in the restricted copy; the evidence index is built locally. New tests,
  `tools/tests/test_example_methanol.py`, run on the public files.
- **One approval for every change (review policy version 2).** A pull request to `main` now merges with one approving
  review from any reviewer other than its author, instead of two; a reviewer who disagrees with a merged change
  corrects it with a pull request of their own. `governance/review-policy.yaml` sets `approvals.required: 1`, and the
  `main` ruleset (`governance/github/ruleset-main.json`) requires one approving review and no longer a code owner's,
  so that any reviewer, not only the owner, can approve; CODEOWNERS still routes review requests. The owner is a reviewer and
  approves other people's pull requests; the bootstrap rule covers only the owner's own pull requests (GitHub does not
  let an author approve) and ends as soon as a second reviewer joins: `scale proposal decide --bootstrap-bypass` is refused
  once another reviewer can approve (`policy.approvable`), not only once every seat is filled. No schema change.

## 0.1.0 — 2026-10-08

The first version of SCALE — Shared Concepts, Attributes, and Links with Evidence — in `github.com/hlxin/scale`:
one shared framework for evidence-backed scientific knowledge graphs across domains, with the science kernel and
catalysis as the first domain ([decision record 0001](docs/decisions/0001-scale-0.1.0.md)). It continues the work
developed in the SCALE Consortium's schema repository (the consortium schema repository, up to commit 79b4fe4),
whose earlier versions, releases, proposals and decision records stay there. No release has been built yet; the
first will be `v0.1.0`.

- **Schema 0.1.0, one version for the whole schema.** The science kernel (`core/graph/kernel.yaml`) and the catalysis
  file (`domain/graph/catalysis.yaml`), assembled by `domain/graph/scale-graph.yaml`, at **scale-graph 0.1.0**.
  The spec digest of scale-graph 0.1.0 (sha256 of its spec document, `scale graph spec`): `3c2fa7205a7bae5e0bbfa7d87826ff7ab7803e78536129064101c7d5a2c02006`.
  The content is that of the
  catalysis graph schema the work had reached (catalysis 0.5.0 on kernel 0.2.0 in the consortium schema
  repository's numbering): the
  method of science, what is studied and done with and who does it, the value object, evidence, record references,
  stewardship and the source lifecycle in the kernel; catalysis as a whole, the terms of every driving force and one
  checklist whose cases follow a test's `driving_forces` in the catalysis file. The kernel and the catalysis file
  carry no version of their own; `core/CORE.yaml`, `domain/DOMAIN.yaml`, `scale-release.yaml` (`schema_version`) and
  the kernel-only example manifest state the one version, `scale domains check` requires them to agree, and every
  applied proposal raises it whichever file it changes, freezing the version it replaces (its kernel as
  `core/graph/frozen/kernel-<version>.yaml`). Concepts carry no `added_in` or proposal id of the earlier numbering;
  every concept is provisional. The kernel, the catalysis manifest and the kernel-only example manifest say
  `status: candidate` (`scale domains check` requires the kernel's and the kernel-only manifest's status to be the
  manifest's); status is not part of the spec document, so the digest above holds.
- **Schema texts.** Apart from the version metadata, no schema text changed: normalized for the version fields,
  `lineage`, the manifest's `proposals` list and the `added_in` and `proposal` stamps, the spec document of
  scale-graph 0.1.0 equals that of the content it was taken from. Two texts therefore still use the consortium
  schema repository's earlier numbering. The example in the kernel's `graph.follows_domains` description names
  `thermocatalysis@0.1.0`, a frozen driving-force profile of that numbering that this repository does not hold (a
  document that follows it gets an unknown-domain error here; follow `catalysis` or `catalysis@0.1.0`). The
  checklist's `basis` in `domain/graph/catalysis.yaml` cites "the adopted catalysis schema 0.1.0", the catalysis
  schema 0.1.0 of that numbering (the profiles the checklist was first built from), not this repository's
  scale-graph 0.1.0. Changing either text changes the schema's content and needs a proposal; both rewordings are
  open work ([domain/ROADMAP.md](domain/ROADMAP.md), "The schema's wording").
- **Identity by digest.** Spec documents say `lineage: scale`. `scale graph spec --expect <sha256>` (and
  `pgraph.identify`) says whether a version and digest are this repository's; a document pinning a version these
  tools do not hold is reported as such, never read under another version of the same number.
- **Examples and fixtures at 0.1.0.** The public synthetic catalysis examples (the worked example, one document per
  driving force and combination, the source-lifecycle example), the invalid fixtures and the synthetic test proposal
  were moved to today's content with `scale graph migrate` and re-pinned to 0.1.0 (the test proposal's fixtures to
  its target, 0.2.0); the source-lifecycle fixtures already pinned today's content and were re-pinned to 0.1.0. The
  five science-kernel cases already pinned 0.1.0 and are unchanged. The public synthetic fixtures of the catalyst
  states and contexts (two passing documents and eight counterexamples, each failing with exactly its stated error)
  were moved the same way and are kept, re-pinned to 0.1.0, in
  [tools/tests/fixtures/catalyst-states/](tools/tests/fixtures/catalyst-states/README.md) and tested
  (`tools/tests/test_catalyst_states.py`), as the source-lifecycle fixtures are.
- **Tools.** The general tools stay: the validator and checklists, curation with evidence and the copyright cap,
  graph queries with typed absences and the unit rule, evidence search, the source lifecycle, schema proposals (check,
  decide, apply, the version bump after a merge), releases, the kg-bundle export, competency questions, coverage and
  conflict skills, access rules and viewer filters, the agent tools over the command line, HTTP, MCP and Python, and
  the skills (curate-source, query-graph, evolve-schema, triage-feedback, scan-conflicts, map-coverage,
  curate-dataset, export-graph). `scale proposal check` warns while a proposal's migration step (base version to
  target) is not registered in `tools/scale/pgraph_migrate.py`, and `scale proposal new`, `build`, `decide` and
  `apply` refuse the data bundled in an installed package, so that they never write into it when run outside a
  checkout. With no release built, `scale skills install` installs the head's skills and
  `scale release verify` has nothing to verify. The tools may read inputs that may not be committed from an optional
  restricted copy that only an environment variable names. The skills restart their numbering with this
  repository, as the schema does: every skill is at version 0.1.0 (their earlier versions belong to the consortium
  schema repository), and a later change to a skill's text raises its version.
- **Scanned pages read by two readers: `scale pages`.** The check the consortium schema repository's methanol
  corpus tool applied to scanned sources is now a general command for any curated document and source
  ([tools/pagereading.py](tools/pagereading.py); `render`, `region`, `agree`, `check`, `pending`,
  `merge-second`, `import`): a reading of a page image carries its region and transcription; the tool computes its
  agreement with the OCR words in that region and records the OCR engines; a reading OCR does not confirm needs a
  matching, independent second reading; every value of a record read from an image is in a transcription or quote.
  Its tests on synthetic pages came with it, and its guide is in [docs/curation.md](docs/curation.md#reading-scanned-pages-two-readers).
  The page images and OCR words stay local, since they reproduce the source. CI does not cover the real-PDF path:
  `test_render_and_region_read_a_pdf` needs pymupdf (the `pdf` extra) and tesseract, which CI's `dev` install does
  not have, so it is skipped there; run it locally with `uv run --extra dev --extra pdf pytest
  domain/tests/test_vision_ocr.py` where tesseract is installed.
- **Not carried.** The tools that served only the consortium schema repository's two restricted example corpora
  (the methanol-synthesis corpus's brief, fragment check, assembly, scoping and bundle commands, corpus freezer,
  converters of another group's dataset and bundle into the retired record format, workbook comparison and export,
  value census and one-off revision script; another corpus's curation library and source tools), their query plans and
  READMEs, the tests that needed their data, and two unapplied proposals (stability maps and the order of phenomena;
  activity in a catalyst state and reaction pathways). They served project data that may not be published, which is
  kept in a separate private data repository; the tooling stays in the consortium schema repository at 79b4fe4
  ([decision record 0001](docs/decisions/0001-scale-0.1.0.md), item 4). The two proposals' themes are in
  [domain/ROADMAP.md](domain/ROADMAP.md).
- **A personal repository.** The owner, Hongliang Xin (@hlxin), owns every path in `.github/CODEOWNERS`; two reviewer
  seats are placeholders, two approvals are required once they are filled, and the owner merges under the bootstrap
  rule until then. The `ci` and `proposal-check` workflows run on pull requests without secrets; `apply-proposals` is
  started by hand and needs a token configured for this repository (`APPLY_TOKEN`); `scale-agent` is off unless started
  by hand; `publish` is inert until the PyPI trusted publisher is configured.
