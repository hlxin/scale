# Minimum information about a catalyst state and its reaction pathways

**Draft 0.1 (2026-10-03), for expert review. Not endorsed by any journal or society.** It is the
reporting companion to a planned catalysis proposal (activity in a catalyst state, reaction pathways, product
distributions; [ROADMAP](../../ROADMAP.md)). Some items name fields that schema 0.1.0 does not have yet, marked
*(planned)* in the SCALE column: the link `ACTIVE_FOR` (with its `in_state`, `product`, `function`,
`assignment_basis` and `turnover_frequency`), the label `ReactionPathway`, the test property `product_distribution`,
the properties `order` and `intermediate_role` on `PROCEEDS_VIA` (the link itself exists, from a Reaction to a species
or a reaction), `population` and `dominance` on `HAS_SITE`, `in_state` on `LOCATED_ON` and `kinetic_role` on
`HAS_ELEMENTARY_STEP`. They are what that proposal would add. Item numbers are stable across drafts; wording is not.

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
it was measured. Each item names the SCALE field that holds it. For the items whose fields schema 0.1.0
has, `scale graph validate` can check a curated paper against the list; the fields marked *(planned)* wait for
the proposal, and until then such an item is recorded in the record's `note` or `unmodeled` list.

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
| B4 | Evidence that rates are free of heat and mass transport limits | E | not yet modelled (record in the test's `note`) |

## C. The catalyst state

| # | Item | | SCALE |
|---|---|---|---|
| C1 | The phases present, where they are (surface, overlayer, bulk, interface) and their abundance, with the basis of the abundance | R | `HAS_PHASE {location, dominance, fraction}` |
| C2 | Adsorbates and surface complexes identified, with coverage when measured | E | `HAS_COMPONENT {role: adsorbate, coverage, bound_to}` |
| C3 | The site populations proposed, the material they sit on and their share | E | `HAS_SITE`, `LOCATED_ON`; *(planned)* `HAS_SITE {population, dominance}`, `LOCATED_ON {in_state}` |
| C4 | How the state was observed: technique, in situ, operando or ex situ, information depth, time after the action | R | `DETERMINED_BY`, `Characterization.observation_mode`, `information_depth` |
| C5 | Whether the state was still changing when observed (steady, drifting, oscillating) | E | `CatalystState.regime` |

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
| E2 | Every product detected, with its selectivity or rate and the basis (carbon, molar, Faradaic), and the balance closure | R | *(planned)* `CatalyticTest.product_distribution` |
| E3 | Conversion, and whether it was kept low enough for kinetic analysis | R | `conversion` |
| E4 | Rates normalized as reported (per mass, area or site); for a turnover frequency, how the sites were counted | E | `production_rate`; *(planned)* `ACTIVE_FOR.turnover_frequency` |
| E5 | Change of activity or selectivity with time on stream | E | `time_on_stream`, `deactivation_rate` |

## F. Which component is active, and why the authors think so

| # | Item | | SCALE |
|---|---|---|---|
| F1 | The component assigned (phase, site, surface species), the state, and the reaction or product it is assigned to | R when an assignment is made | *(planned)* `ACTIVE_FOR {in_state, product}` |
| F2 | Its function: active, co-active, spectator, precursor, inhibiting | R | *(planned)* `ACTIVE_FOR.function` |
| F3 | The kinds of evidence behind the assignment: correlation across samples or conditions, operando presence, time-resolved participation, isotopic or transient kinetics, site titration, selective poisoning, model system, computation | R | *(planned)* `ACTIVE_FOR.assignment_basis` |
| F4 | Whether a spectator role was ruled out, and how | E | `Claim`; *(planned)* `function: spectator` on the alternatives |
| F5 | The proposed route: intermediates in order, rate-determining step, and the state it runs on | E | `PROCEEDS_VIA`, `Mechanism` `HAS_ELEMENTARY_STEP {order}`; *(planned)* `ReactionPathway`, `PROCEEDS_VIA {order, intermediate_role}`, `HAS_ELEMENTARY_STEP {kinetic_role}` |
| F6 | Which transition switches the pathway | E | `AFFECTS_PATHWAY` (to a `Reaction` in 0.1.0); *(planned)* to the `ReactionPathway` |

Abundance is not activity: a majority phase is not reported as active unless the paper argues it.

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

- **Strength of evidence.** The F3 list names the kinds of evidence; it does not rank them. Should a
  recommended minimum (for example operando presence plus one kinetic criterion) be stated for the
  word "active" in a title or abstract?
- **Transport limits (B4)** and **balance closure (E2)** have no typed field yet; they would be a
  later proposal.
- **Definitions** should cite the IUPAC Gold Book (active site, turnover frequency, selectivity) and
  representative literature. The references are to be pinned from primary sources before the draft
  circulates, not written from memory.
- **Mapping of F3 to the Evidence & Conclusion Ontology (ECO)** is open, to be checked against the
  current ECO release.
