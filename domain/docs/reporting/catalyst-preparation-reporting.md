# Minimum information about a catalyst's preparation and characterization

**Draft 0.1 (2026-10-20), for expert review. Not endorsed by any journal or society.** It is the reporting companion
to the recording recipes for preparations and characterizations
([skills/curate-corpus/references/recipes.md](../../../skills/curate-corpus/references/recipes.md), "Preparation
recipes" and "Characterization recipes") and to the [catalyst-state checklist](catalyst-state-reporting.md), whose
section A (the action history) it details. It adds no field to the schema: every item names what SCALE already has
(scale-catal 0.6.0), and the preparation examples (domain/examples/scale-catal/preparation-examples/) record each.

## Why a checklist

Two catalysts with one nominal formula can differ in everything that was not reported: the precursor lot, which
solution was added to which, the ramp of the calcination, how long the powder sat in a vial and in what gas. A size
from microscopy, one from diffraction and one from light scattering are three quantities; a coordination number means
little without the model it was fitted with. This checklist asks authors to report what was done and how each number
was obtained. It does not ask for more experiments: an item the source does not report is recorded as not stated,
never filled in.

**R** = required for the record to be repeatable or comparable, **E** = expected when it was done or measured. Each
item names the SCALE field that holds it, and the last column says where the recommendation comes from (the
references at the end; "report" is the workshop report, with its section).

## P. Materials and their identity

| # | Item | | SCALE | From |
|---|---|---|---|---|
| P1 | Every chemical used: its identity with its water of hydration, the manufacturer, the purity or grade as stated, the lot, and any purification before use | R | a `ChemicalSpecies` whose `formula` includes the water (`·xH2O` with a `note` when the source gives no number); `PREPARED_FROM {supplier, grade, amount}`; a purchased lot a `Sample` (`preparation_status: purchased`) with its `batch_identifier`; a purification a `Treatment` or `note` | report §3.A, §3.D ("source, purity, and lot numbers of all reagents"); hydration: this checklist |
| P2 | The support: vendor, catalogue number, lot, dates bought and opened, how it was stored and pretreated, and its surface area, pore volume and pore sizes, saying whether measured or from the supplier | R | a `Material`; its lot a `Sample` with `batch_identifier` and `identifiers`; supplier values in its `properties` with a `definition` saying so; a `Treatment` the lot is `TREATED_BY` | report §3.B |
| P3 | The batch a result comes from, how many batches were made and how they compared (or that the material was made once) | R | `CatalystSample.batch_identifier`, `HAS_FORMULATION`; two batches are two samples; a statement of agreement a `Claim` (`claim_kind: data_quality`) | report §3.A |

## S. The synthesis

| # | Item | | SCALE | From |
|---|---|---|---|---|
| S1 | Every step in order, with the scale, the vessel, the amounts, volumes and concentrations used, how it was mixed (stirrer type, size, rate) and what was seen during it | R | `ProcedureStep` `PART_OF {order}` the `Preparation`; `HAS_INPUT {role, amount}`; `HAS_OUTPUT`; a solution a `Sample` with `HAS_COMPONENT.concentration`; mixing in `conditions.stirring_rate` and `method`; observations in `note` | report §3.A, §3.B, §3.C |
| S2 | For impregnation: which method (incipient wetness or wet impregnation); the incipient volume and how and on how much support it was measured; the precursor's solubility; the number of impregnations and the drying between them; for wet impregnation, how support and solution were mixed and how the mixture was dried | R when the catalyst is impregnated | the Preparation's `method`; the incipient-volume step's `conditions.incipient_volume` and inputs; one step per impregnation; the drying step's `method` and `conditions` | report §3.B (incipient wetness and wet impregnation), §3.C |
| S3 | For precipitation: the concentrations and volumes of the solutions and the precipitating agent, which was added to which (or both fed together) and how fast, the target pH with its tolerance and the pH measured, the temperature, the aging time and temperature, and the washing (solvent, volume, number of washes, criterion) | R when the catalyst is precipitated | the precipitation step's two inputs (`role: reagent` the one added, `material` the one it was added to) and its `conditions` (`addition_rate`, `stirring_rate`, `ph`, `final_ph`); the aging and washing steps; for a deposition-precipitation, the pH against time a `Dataset` | report §3.A, §3.B (deposition precipitation), §3.C |
| S4 | Drying and calcination: temperature, ramp, hold time and cooling, gas and whether static or flowing, and how much powder in what vessel | R | `ProcedureStep.temperature`, `ramp_rate`, `duration`, `atmosphere`; the rest in `conditions` | report §3.A, §3.C |
| S5 | A written procedure followed and every deviation from it; the sensitivities found (or "no known sensitivities") | E | `FOLLOWS_PROTOCOL` a `Protocol`, with `deviations`; the Preparation's `note` | report §3.A |

## T. Activation, storage, transfer and reaction history

| # | Item | | SCALE | From |
|---|---|---|---|---|
| T1 | Every treatment after the synthesis, in order (reduction, passivation, re-reduction), with temperature and its gradients, ramp, hold time, cooling, gas and flow (or space velocity), the bed, and the switch from one gas to the next | R | `Treatment` with `treatment_kind`, `TREATED_BY {order}` from the batch, `PRECEDES` from the action before it; flows, ramps and the bed in `conditions` | report §3.B (supported pre-catalyst treatment), §5 |
| T2 | Storage: the form stored in, the container and place (bench, desiccator, glovebox and its O2 and H2O contents), the atmosphere, light, temperature and humidity, and the time stored | E | a `Treatment` with `treatment_kind: exposure`, its `method`, `atmosphere`, `duration`, `temperature` and `conditions`; the form is the state before it | report §3.A, §3.B ("Container", "Atmosphere (air, inert, vacuum)", "Light exposure"), §6 |
| T3 | How and how quickly the sample reached each measurement or test, and whether air reached it | E | `Characterization.transfer` and `observation_mode` (in situ: never exposed to ambient between the action and the measurement; ex situ: exposed); a `CatalystState` `REACHED_BY` the action before it and `DETERMINED_BY` the measurement | report §2, §3.A, §3.B |
| T4 | The tests and treatments the sample went through before a measurement | E | `USES_CATALYST {state}`, `PRECEDES`, the states `REACHED_BY` the test (`timing: during`, `after`) | report §5; Wrasman et al. §3 (catalyst history) |

## K. Composition

| # | Item | | SCALE | From |
|---|---|---|---|---|
| K1 | The target (nominal) composition or loading and how it was set (the amounts weighed) | R | `HAS_COMPONENT` `fraction` or `loading` on the formulation, `origin: assumed`, with its `definition` | report §4.A (target against actual composition) |
| K2 | The measured bulk composition: method, digestion, calibration, amounts, the state of the specimen and the basis (by mass, by atoms, of which elements), with impurities | E | a result entry of the `Characterization` that measured it (`composition_fraction` or `loading`, `target` the element, `basis`), `information_depth: bulk`, `CHARACTERIZES {state}`; the digestion in `conditions`, the value's `calibration` | report §4.A, §3.B |
| K3 | The measured surface composition: method, information depth, state and basis, never read as the bulk one | E | the same, `information_depth: surface`; under reaction conditions, the measurement in that atmosphere and the `CatalystState` it establishes | report §3.B, §3.C, §4.A |

## M. Every characterization

| # | Item | | SCALE | From |
|---|---|---|---|---|
| M1 | The specimen measured, its state and the conditions during the measurement (temperature, atmosphere, in situ or not), and its pretreatment | R | `CHARACTERIZES {state}`, `temperature`, `atmosphere`, `observation_mode`, `information_depth`, `sampling`; the pretreatment in `conditions` or as a `Treatment` | report §3.C, §4.A; Wrasman et al. §3 |
| M2 | The instrument and the acquisition settings, and the purity of the gases used | E | `USES_INSTRUMENT` an `Instrument` with `settings`; the measurement's `conditions` | Wrasman et al. §3 |
| M3 | Standards, calibration, blanks and checks on a known material | E | `HAS_INPUT {role: reference_standard}`; a calibration `Characterization` (`goal: calibrate`), `CALIBRATED_BY`, a value's `calibration`; a blank or a reference measurement `CONTROL_FOR` it | Wrasman et al. §3, §4.2 |
| M4 | Where the raw data are | E | a `Dataset` the measurement `HAS_OUTPUT`, its `availability` and `uri` | report §4.A; Meyer et al. (STEM/TEM) §3; Wrasman et al. §3 |
| M5 | How the data were processed or fitted: software and version, equations or model, what was held fixed, ranges, goodness of fit, uncertainties and how they were derived, and limitations | R when a fitted or derived value is reported | an `Analysis` that `HAS_INPUT` the data and references, `USES_MODEL` (its `assumptions`), `USES_SOFTWARE {version}`, with `method` and `limitations`; values `origin: fitted` or `derived`, `produced_by` it | Wrasman et al. §3; Meyer et al. (XAS) §2 |
| M6 | Each reported quantity named for what it is, and each statistic of a distribution apart, with its replicates and uncertainty | R | one `Variable` per measurand (`quantity_kind`, `definition`); a mean, a standard deviation and a count are three results | Meyer et al. (STEM/TEM) §2; Wrasman et al. §3 |

## X. By technique

| # | Item | | SCALE | From |
|---|---|---|---|---|
| X1 | XAS: the detection mode and channel, the monochromator and harmonic rejection, the beam size; the sample's form and contents; the energy calibration and alignment and the references; the cell, its flows, temperature and pressure (for operando, conversion and selectivity); a check for beam damage; every path with its coordination number, distance and disorder; the k-weight and the k- and R-ranges; the independent points and the parameters fitted; what was fixed and how S0^2 was set; the goodness of fit when models are compared; uncertainties; the data in E, k and R | R when XAS is reported | the characterization's `conditions`; an `Analysis` (`analysis_kind: spectral_fit`) with its model, inputs and results | Meyer et al. (XAS) §2 |
| X2 | Electron microscopy sizes: the number of particles counted, the mean and how it was computed, the standard deviation (and skew when the distribution is not normal), the full distribution; the areas surveyed and how they were chosen; the smallest size the mode resolves and the magnification; the electron dose, dose rate and total dose; the microscope, voltage and detectors; how the sample was prepared and loaded; the image processing; the raw images | R when sizes are reported | the characterization's `conditions` (`lower_size_limit`, `electron_dose`, …); results `microscopy_particle_size`, `microscopy_particle_size_spread`, `count`; the images a `Dataset` | Meyer et al. (STEM/TEM) §2, §3; report §4.A |
| X3 | Chemisorption and titration: the probe, its partial pressure, the adsorption temperature and time, the purge, the pretreatment, the stoichiometry and every other assumption used to turn an uptake into sites, the uptake with its replicates, a blank on the support, and how the result compares with the metal content | R when reported | the characterization's `conditions` and uptake; an `Analysis` that `USES_MODEL` the stoichiometry and takes the measured metal content; a dispersion as `site_fraction`; exposed atoms on the `HAS_SITE` from the state | Wrasman et al. §2.2, §3, §4.2 |
| X4 | Physisorption: the adsorptive and temperature; the amount and form of the sample; the degassing vacuum, temperature and time; the relative-pressure range and number of points of the BET fit; the thickness model or NLDFT kernel of a pore analysis; the isotherm | R when reported | the characterization's `conditions`; an `Analysis` that `USES_MODEL` the BET equation; the isotherm a `Dataset` | report §4.A |
| X5 | Sizes from different techniques reported as different quantities, each with its technique; an XRD size is an average, a missing reflection is not a size | R | `microscopy_particle_size`, `crystallite_size`, `hydrodynamic_size`, `dispersion_equivalent_size`; a missing size `below_detection_limit` or `not_reported`, never another technique's | report §1, §4.A; Meyer et al. (XAS) §1–§2; hydrodynamic size: the request that prompted this draft (no reference covers it) |

## Open points for reviewers

- **Size kinds.** The measurands above are named in each Variable's `quantity_kind` by convention. The kernel does not
  declare them yet, so their units are not checked and a plan selects them through their Variable rather than by
  kind. Declaring `microscopy_particle_size`, `crystallite_size` and `hydrodynamic_size` (all lengths) is a schema change for when
  curated records use the convention.
- **Statistics of a value.** A value has no field for the statistic it is (mean, median) or for how many items it
  summarizes, so each statistic is a result of its own. A value field would be a kernel change.
- **Bulk and surface.** A bulk and a surface fraction share a kind and a basis, so a scientific comparison does not
  keep them apart; a plan names the Variable or the information depth. Making information depth a comparison context
  is a schema change.
- **A preparation checklist.** The catalysis checklist has no case for a Preparation or a Treatment, so `scale graph
  validate` does not check these items yet; whether to add one (should items) waits for curations that follow the
  recipes.
- **Not in the references.** None of the references covers the water of hydration of a precursor, a hydrodynamic
  (light-scattering) size, the median of a size distribution or the BET C constant; the items that name them are this
  draft's.

## References

- Addressing Rigor and Reproducibility in Thermal, Heterogeneous Catalysis, workshop report, v1.00, 2023,
  doi:10.5281/zenodo.8029159 (CC BY 4.0): §2 (in situ and ex situ), §3 (synthesis: §3.A general, §3.B deposited
  catalysts, §3.C supported and bulk metal oxides, §3.D), §4.A (characterization: composition, crystal structure,
  surface area and porosity, particle size distributions), §5 (catalyst testing), §6 (sample storage).
- Alba-Rubio, Christopher, Personick, Stowers, Recommendations to standardize reporting on the synthesis of
  heterogeneous catalysts, J. Catal. 2024, 429, 115259, doi:10.1016/j.jcat.2023.115259: the journal version of the
  report's synthesis section, by four of the committee that wrote it; its text was not read for this draft.
- Meyer et al., Recommendations to standardize reporting, execution and interpretation of STEM/TEM measurements,
  J. Catal. 2024, 433, 115480, doi:10.1016/j.jcat.2024.115480: §2 (best practices), §3 (reporting standards).
- Meyer et al., Recommendations to standardize reporting, execution, and interpretation of X-ray Absorption
  Spectroscopy measurements, J. Catal. 2024, 432, 115369, doi:10.1016/j.jcat.2024.115369: §1, §2 (best practices and
  recommended reporting standards).
- Wrasman et al., Recommendations for improving rigor and reproducibility in site specific characterization, J. Catal.
  2024, 433, 115451, doi:10.1016/j.jcat.2024.115451: §2.2 (uptake of adsorbates), §3 (reporting), §4.2 (comparing
  results with expectations).
