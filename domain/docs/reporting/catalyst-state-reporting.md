# Minimum information about a catalyst state and its reaction pathways

**Draft 0.2 (2026-10-20), for expert review. Not endorsed by any journal or society.** It is the
reporting companion to the catalysis schema's catalyst states. Since scale-catal 0.6.0 a state has its own site
populations (`HAS_SITE` from the `CatalystState`, with a share, a density, the exposed atoms counted and the sites a
rate is divided by), a turnover frequency is kept as reported and says how it was calculated, operando means
characterized while the kinetics are measured (an observation states whether they were), and a fit to a spectrum is
an analysis of its own. Which component is active is a
`Claim` with named `ABOUT` roles and its evidence, not a new link: draft 0.1 planned a link `ACTIVE_FOR` for it, which
the claim replaces. Items whose fields the schema does not have yet are marked *(planned)* in the SCALE column: the
label `ReactionPathway`, the test property `product_distribution`, the properties `order` and `intermediate_role` on
`PROCEEDS_VIA` (the link itself exists, from a Reaction to a species or a reaction), `in_state` on `LOCATED_ON` and
`kinetic_role` on `HAS_ELEMENTARY_STEP` (pathways and their steps, [ROADMAP](../../ROADMAP.md)). Item numbers are
stable across drafts; wording is not.

## Why a checklist

The catalyst that turns over is often not the catalyst that was loaded. It forms under reaction
conditions after an action history, may be a minority of what is present, may include adsorbates,
and is usually identified by an argument rather than observed directly. Papers report these
elements unevenly, so states and pathways cannot be compared across studies. This checklist asks
authors to report what was done, what was observed and how an assignment was argued. It does not
ask for more experiments.

Minimum-information checklists that worked in other fields (MIAME for microarrays, STRENDA for
enzymology) stayed short, separate from the full data model, and were backed by a validator.
This follows that pattern: **R** = required for the record to be comparable, **E** = expected when
it was measured. Each item names the SCALE field that holds it. For the items whose fields the schema
has, `scale graph validate` can check a curated paper against the list; the fields marked *(planned)* wait for
a later change, and until then such an item is recorded in the record's `note` or `unmodeled` list.

## A. Starting point and action history

| # | Item | | SCALE |
|---|---|---|---|
| A1 | The as-prepared state: phases and how they were identified | R | `CatalystState` (`state_kind: as_prepared`), `HAS_PHASE`, `DETERMINED_BY` |
| A2 | Every action from the as-prepared state to the observation, in order (pretreatment, gas switches, pressure, temperature or potential steps), with its conditions and duration | R | `Treatment` / `CatalyticTest` / `Operation`, `PRECEDES`, `REACHED_BY {timing, elapsed}` |
| A3 | Whether the sample was exposed to air or transferred between actions | E | `Characterization.transfer` |

## B. Conditions at the observation

| # | Item | | SCALE |
|---|---|---|---|
| B1 | Temperature and where it was measured | R | `CatalyticTest.temperature`, `temperature_measured_at` (catalysis checklist, thermal case) |
| B2 | Total pressure and the partial pressure (or fraction) of every reactant and product present | R | `CatalystState.conditions`, `Feed` |
| B3 | Electrode potential with its reference scale and iR compensation; irradiance and wavelength; plasma power | R when applicable | properties the catalysis domain adds to `Experiment` (so a `CatalyticTest` has them): `electrode_potential`, `reference_scale`, `ir_compensation`; `irradiance`, `wavelength`; `discharge_power` (required by the checklist's electro, photo and plasma cases) |
| B4 | Evidence that rates are free of heat and mass transport limits, and how it was obtained (stated, calculated, or tested by varying particle size, flow or stirring) | E | an `Analysis` with `analysis_kind: transport_check` that `HAS_INPUT` the test, with `evaluation_basis` (`asserted`, `numerical`, `experimental`), `method`, `verdict` and the `temperature` it applies to; a test read as `intrinsic_kinetics` is checked for one (scale-catal 0.5.0) |

## C. The catalyst state

| # | Item | | SCALE |
|---|---|---|---|
| C1 | The phases present, where they are (surface, overlayer, bulk, interface) and their abundance, with the basis of the abundance | R | `HAS_PHASE {location, dominance, fraction}` |
| C2 | Adsorbates and surface complexes identified, with coverage when measured | E | `HAS_COMPONENT {role: adsorbate, coverage, bound_to}` |
| C3 | The site populations proposed in the state, the material they sit on and their share, density or count, each with how it was obtained (measured, derived, computed, assumed; a bound when only a limit is known), its uncertainty and what it assumes (an adsorption stoichiometry, a particle shape) | E | `HAS_SITE` from the `CatalystState`, its `population_fraction` (a share of a stated whole), `site_density`, `exposed_metal_count` and `site_inventory`, each a value with `origin`, `uncertainty` or `bound`, `produced_by` (the counting measurement, or an `Analysis` that `USES_MODEL` a `Model` with its `assumptions`) and `evidence_ids`; `LOCATED_ON` (scale-catal 0.6.0); *(planned)* `LOCATED_ON {in_state}` |
| C4 | How the state was observed: technique, in situ, operando or ex situ as the source reports it, information depth, time after the action | R | `DETERMINED_BY`, `Characterization.observation_mode` (the source's label, kept as reported), `information_depth` |
| C5 | Whether the state was still changing when observed (steady, drifting, oscillating) | E | `CatalystState.regime` |
| C6 | For an observation reported as operando (characterized while the kinetics are measured): which specimen was observed, whether the kinetics were measured while it was made, what of them (activity or selectivity measured quantitatively in the cell), and the conventional reactor or cell they were compared with, if any | R when the observation is called operando | `DURING {specimen, timing, kinetics, benchmark}` (scale-catal 0.6.0); the checklist's operando case looks for the kinetics measured on the same specimen at the same time |
| C7 | For a fit to an ensemble measurement (linear combination fitting, EXAFS shell fitting, principal component analysis): the data fitted, the references, the fitted parameters with their uncertainties and those held fixed, the models it was preferred to and what it cannot tell apart | E | an `Analysis` with `analysis_kind: spectral_fit`, its `method`, `results` (origin fitted), `limitations`, and the `Dataset` of spectra and the references it `HAS_INPUT`; an alternative model is another Analysis (scale-catal 0.6.0) |

## D. Transitions between states

| # | Item | | SCALE |
|---|---|---|---|
| D1 | The state before and after, and the kind of change (oxidation, carburization, encapsulation, redispersion, …) | R | `StateTransition`, `FROM_STATE`, `TO_STATE` |
| D2 | The action that triggered it and the delay to onset | R | `TRIGGERED_BY {onset_delay}` |
| D3 | Its duration and whether it reverses | E | `duration`, `reversibility` |
| D4 | What promotes or suppresses it (a product, an adsorbate, water), under which conditions | E | `DRIVES_TRANSITION` |

## E. The pathway outcome measured in the state

| # | Item | | SCALE |
|---|---|---|---|
| E1 | Which state the measurement was made in | R | `IN_STATE` |
| E2 | Every product detected, with its selectivity or rate and the basis (carbon, molar, Faradaic), and the balance closure | R | `result_values`, one entry per product, analysis, phase and time, with its `basis`, and a `balance` result produced by an `Analysis` (`analysis_kind: balance`) over the analyses it adds up (scale-catal 0.4.0); *(planned)* `CatalyticTest.product_distribution` as a whole |
| E3 | Conversion, and whether it was kept low enough for kinetic analysis | R | `conversion` |
| E4 | Rates normalized as reported (per mass, area or site); for a turnover frequency, the site count it is divided by, how the sites were counted and in which state | E | `production_rate`; a turnover frequency in `result_values`, as reported, says how it was calculated (scale-catal 0.6.0): it names its site count with `normalized_by` (a `HAS_SITE`'s `exposed_metal_count` or `site_inventory`, in the state the sites were counted in, beside the `IN_STATE` of the test) and states what was counted and how in its `basis` or `definition`; rates calculated on different counts are compared as reported, each shown with its count |
| E5 | Change of activity or selectivity with time on stream | E | `time_on_stream`, `deactivation_rate` |

## F. Which component is active, and why the authors think so

| # | Item | | SCALE |
|---|---|---|---|
| F1 | The component assigned (phase, site, surface species), the state, and the reaction or product it is assigned to | R when an assignment is made | a `Claim` `ABOUT` the component, the state (role `state`), the reaction or product (`reaction`, `product`) and the test it concerns (`test`) |
| F2 | Its function: active, spectator, precursor, inhibiting | R | the role of the claim's `ABOUT` link to the component: `active`, `spectator`, `precursor`, `inhibitor` (co-active: an open point) |
| F3 | The kinds of evidence behind the assignment: correlation across samples or conditions, operando presence, time-resolved participation, isotopic or transient kinetics, site titration, selective poisoning, model system, computation | R | `SUPPORTS` and `CONTRADICTS` from the tests, characterizations, analyses and claims it rests on, with `premise_refs` to the results and a `warrant`; the kind of evidence is the kind of record that supports it |
| F4 | Whether a spectator role was ruled out, and how | E | a spectator interpretation is a claim of its own (role `spectator`), with its evidence; competing assignments are claims of their own, never merged |
| F5 | The proposed route: intermediates in order, rate-determining step, and the state it runs on | E | `PROCEEDS_VIA`, `Mechanism` `HAS_ELEMENTARY_STEP {order}`; *(planned)* `ReactionPathway`, `PROCEEDS_VIA {order, intermediate_role}`, `HAS_ELEMENTARY_STEP {kinetic_role}` |
| F6 | Which transition switches the pathway | E | `AFFECTS_PATHWAY` (to a `Reaction`, optionally scoped to a `site`); *(planned)* to the `ReactionPathway` |

Abundance is not activity: a majority phase is not reported as active unless the paper argues it, and a minority one
can be. An observation that overlaps a run, or changes in step with the activity, does not by itself show that what
changed is active: the activity measured on the same specimen at a stated time, and evidence that perturbs the sites
(their share varied on purpose, a titration, a transient or modulation experiment), carry the argument. A population
counted in one state is not carried to another: sites change with the conditions.

## G. Computation of states and pathways

| # | Item | | SCALE |
|---|---|---|---|
| G1 | The structural model of the state and the conditions it represents (temperature, chemical potentials or pressures, potential) | R | `CatalystState` with `origin: computed`, `STATE_OF` a `StructureModel` |
| G2 | Method and level of theory | R | `Computation` |
| G3 | Which observed state or rate the computation is compared with, and whether it agrees | E | `PREDICTS {agreement, compared_with}` |

## H. Data

| # | Item | | SCALE |
|---|---|---|---|
| H1 | Where the raw spectra, diffraction patterns, kinetic data and structures are deposited, with identifiers | E | `Dataset`, `evidence.source` |

## Open points for reviewers

- **Named roles.** The `ABOUT` roles of an assignment (`active`, `spectator`, `precursor`, `inhibitor`, `state`,
  `reaction`, `product`, `test`, `step`, `mechanism`) are a convention of the catalysis guidance: `ABOUT.role` is free
  text in the science kernel, so the validator does not check them, and the checklist cannot narrow text. Draft 0.1
  listed co-active too (a component active only together with another); review left it out until a case shows it is
  needed and how it differs from two components each `active` in one claim.
  Whether to make them a closed list (a kernel change), or to add a claim specialization, waits for curations that show
  the convention drifting; the example records and queries them without one.
- **Kinds of evidence (F3).** An assignment's evidence is typed by the records that support it, not by a field of its
  own. Whether a `SUPPORTS` link should name the kind of evidence it is (site variation, titration, transient,
  operando presence) is open.
- **Agreement with a conventional reactor (C6).** Operando asks for the kinetics measured while characterizing, not
  for a match to a conventional reactor or cell; a match is recorded when the source gives one (`kinetics:
  matched_to_benchmark`, its test in `benchmark`). No reference gives a tolerance for that agreement, and the checklist
  sets no number.

- **Strength of evidence.** The F3 list names the kinds of evidence; it does not rank them. Should a
  recommended minimum (for example operando presence plus one kinetic criterion) be stated for the
  word "active" in a title or abstract?
- **Transport limits (B4)** and **balance closure (E2)** have typed fields now (a transport check with its
  `evaluation_basis`, scale-catal 0.5.0; result entries and balances, 0.4.0). Whether a minimum basis (a calculation
  or a test, not a statement) should be required for the word "intrinsic" is open; the checklist asks for it
  provisionally, as a should item, and sets no criterion value.
- **Definitions** should cite the IUPAC Gold Book (active site, turnover frequency, selectivity) and
  representative literature. The references are to be pinned from primary sources before the draft
  circulates, not written from memory.
- **Mapping of F3 to the Evidence & Conclusion Ontology (ECO)** is open, to be checked against the
  current ECO release.

## References

- Wrasman et al., Recommendations for improving rigor and reproducibility in site specific characterization, J. Catal.
  2024, 433, 115451, doi:10.1016/j.jcat.2024.115451 (C3, E4, F3: sites counted with an assumed or determined
  stoichiometry, every assumption reported; site quantification under conditions relevant to the reaction, since the
  number and nature of sites change with them; the activity often dominated by a small fraction of the accessible
  sites; varying the site concentration on purpose as the strongest evidence).
- Meyer et al., Recommendations to standardize reporting, execution, and interpretation of X-ray Absorption
  Spectroscopy measurements, J. Catal. 2024, 432, 115369, doi:10.1016/j.jcat.2024.115369 (C6, C7: a bulk-averaging
  technique in which minority species may escape detection; linear combination fits depend on the references assumed;
  fitted parameters with their uncertainties and constraints, contrasted with poorer models; in situ unless the
  kinetics at the beamline match the laboratory reactor's).
- Tackett et al., Rigor and Reproducibility in Electrocatalysis, Best Practices for Operando Studies, ACS Catal. 2026,
  16, 13861, doi:10.1021/acscatal.6c01946 (C4, C6: operando as working conditions with quantitative activity or
  selectivity; the synchronization protocol reported; performance benchmarked against conventional cells; spectators
  may mask transient species unless the system is perturbed).
