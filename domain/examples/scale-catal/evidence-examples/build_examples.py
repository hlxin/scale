"""Build the synthetic evidence examples of the catalysis domain (all values invented): what a test is read as showing
(CatalyticTest.interpretations) and the records connected to it that the catalysis checklist looks for.

    python build_examples.py

  kinetic-evidence.json
    CO oxidation over Pt/Al2O3, read as intrinsic kinetics   four tests whose transport assessment is numerical
                                              (Weisz-Prater and Mears criteria, at 4 % and at 35 % conversion: no
                                              conversion level is a cutoff), experimental (two runs with finer particles
                                              and twice the flow at the same contact time, each CONTROL_FOR the test and an
                                              input of the check) or only asserted; and a test read as system performance,
                                              which needs no transport assessment
    CO2 methanation over Ru/TiO2 under light  a non-thermal effect claimed against a dark control matched at the
                                              illuminated surface in steady state; one claimed against a dark control
                                              matched at the bed temperature only (a bulk match, which the checklist says
                                              does not show a non-thermal effect); and a photothermal effect read from the
                                              dependence on irradiance (a ThermalContributionAnalysis)
    NH3 synthesis in a packed-bed DBD         plasma-catalyst synergy against the plasma with the bare packing and the
                                              catalyst without plasma at the same temperature, with the plasma power (from
                                              the Lissajous figure) apart from what the supply draws
  dynamic-and-stability.json
    steam reforming on an electrically heated tube   a ramp from 300 to 800 °C at 10 K/s and a hold (an Operation with
                                              its segments), the catalyst temperature and the conversion over time
                                              (TimeSeries), read as system performance
    O2 evolution on NiFe oxide, 24 h at 10 mA/cm2    three replicate electrodes of one Design (REPLICATES, PART_OF_DESIGN);
                                              a constant potential trace (performance stability) and the catalyst after
                                              the test, by ICP-MS of the electrolyte and XPS (material stability); and an
                                              electrode read as materially stable from its potential trace alone, which
                                              the checklist reports as missing its material evidence
"""

from __future__ import annotations

import sys
from pathlib import Path


def _repo_root(*starts: Path) -> Path:
    """The SCALE checkout (scale-release.yaml and releases/), searched upward from each start in turn."""
    for p in (q for s in starts for q in (s, *s.parents)):
        if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
            return p
    raise SystemExit("run inside a SCALE repository checkout: no scale-release.yaml and releases/ above "
                     + ", ".join(map(str, starts)))


HERE = Path(__file__).resolve().parent
REPO = _repo_root(HERE, Path.cwd())
sys.path.insert(0, str(REPO / "tools"))
from scale import layout  # noqa: E402
from scale.pgraph import derive_reported_in  # noqa: E402
from scale.util import write_canonical  # noqa: E402

SYN = "synthetic"
_HEAD = REPO / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST
HEAD_VERSION = __import__("yaml").safe_load(_HEAD.read_text())["version"]


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


class Doc:
    """A document under construction: nodes and links with synthetic ids under one prefix, one invented source."""

    def __init__(self, prefix: str, title: str, source_title: str):
        self.p = prefix
        self.doc = {"directed": True, "multigraph": True,
                    "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{prefix}/graph",
                              "title": title, "data_status": "synthetic_example", "follows_domains": ["catalysis"],
                              "stewardship": {"access": "public"}},
                    "nodes": [], "links": []}
        self.n = 0
        self.src = self.node("source/paper", "Source", "Invented paper", kind="article", year=2026, title=source_title)

    def node(self, rid, label, name, **props):
        nid = f"{self.p}/{rid}"
        self.doc["nodes"].append({"id": nid, "label": label, "props": {"name": name, "origin": SYN, **props}})
        return nid

    def link(self, typ, s, t, **props):
        self.n += 1
        lid = f"{self.p}/link/{self.n}"
        self.doc["links"].append({"id": lid, "source": s, "target": t, "type": typ, "props": {"origin": SYN, **props}})
        return lid

    def ev(self, locator, kind="table", **kw):
        return {"source": self.src, "locator": locator, "kind": kind, **kw}

    def species(self, key, formula, composition, name=None):
        return self.node(f"species/{key}", "ChemicalSpecies", name or formula, formula=formula,
                         elemental_composition=composition, charge=0)

    def reaction(self, key, equation, participants):
        rid = self.node(f"reaction/{key}", "Reaction", equation, equation=equation, balance_status="balanced",
                        direction="forward")
        for sp, role, coef in participants:
            self.link("HAS_PARTICIPANT", rid, sp, role=role, coefficient=coef)
        return rid

    def feed(self, key, name, components):
        fid = self.node(f"feed/{key}", "Feed", name, evidence=[self.ev("Methods", "text")])
        for sp in components:
            self.link("HAS_COMPONENT", fid, sp, role="reactant")
        return fid

    def finish(self) -> dict:
        for e in derive_reported_in(self.doc):
            e["props"]["origin"] = SYN
            self.doc["links"].append(e)
        return self.doc


def kinetic_evidence() -> dict:
    d = Doc("ex:ke", "Connected evidence: transport assessments, light-heat separation and plasma-catalyst synergy",
            "Rates, light and plasma over supported metal catalysts (invented)")
    ev = d.ev
    co, o2, co2 = d.species("co", "CO", {"C": 1, "O": 1}), d.species("o2", "O2", {"O": 2}), d.species("co2", "CO2", {"C": 1, "O": 2})
    h2, ch4 = d.species("h2", "H2", {"H": 2}), d.species("ch4", "CH4", {"C": 1, "H": 4})
    h2o, n2, nh3 = d.species("h2o", "H2O", {"H": 2, "O": 1}), d.species("n2", "N2", {"N": 2}), d.species("nh3", "NH3", {"N": 1, "H": 3})

    def variable(key, name, scale, **kw):
        return d.node(f"variable/{key}", "Variable", name, scale=scale, **kw)

    v_size = variable("particle-size", "catalyst particle size (sieve fraction)", "nominal", categories=["125-250 um", "63-125 um"])
    v_flow = variable("flow-rate", "total flow rate at constant W/F", "quantitative", unit="mL/min", quantity_kind="flow_rate")
    v_light = variable("illumination", "illumination", "nominal", categories=["light", "dark"])
    v_plasma = variable("plasma", "plasma", "nominal", categories=["on", "off"])
    v_active = variable("active-phase", "active phase on the packing", "nominal", categories=["Ni", "none"])

    # ---- CO oxidation over Pt/Al2O3: transport assessments by basis
    rxn = d.reaction("co-oxidation", "2 CO + O2 -> 2 CO2", [(co, "reactant", 2), (o2, "reactant", 1), (co2, "product", 2)])
    pt = d.node("catalyst/pt-al2o3", "Catalyst", "1 wt% Pt/Al2O3", nominal_formula="Pt/Al2O3", catalyst_family="metal",
                evidence=[ev("Table 1")])
    coarse = d.node("sample/pt-125-250", "CatalystSample", "Pt/Al2O3, 125-250 um sieve fraction", sample_kind="granules",
                    evidence=[ev("Table 1")])
    fine = d.node("sample/pt-63-125", "CatalystSample", "Pt/Al2O3, 63-125 um sieve fraction", sample_kind="granules",
                  evidence=[ev("Table 1")])
    for s in (coarse, fine):
        d.link("HAS_FORMULATION", s, pt)
    feed = d.feed("co-o2", "1 % CO, 2 % O2 in He", [co, o2])
    reactor = d.node("instrument/fixed-bed", "Reactor", "Quartz fixed-bed reactor, 4 mm i.d.", reactor_kind="fixed_bed")

    def co_test(key, name, conversion, temp=180, kind="kinetics", sample=coarse, **kw):
        tid = d.node(f"test/{key}", "CatalyticTest", name, test_kind=kind, driving_forces=["thermo"],
                     experiment_kind="physical", temperature=V(temp, "°C"), pressure=V(1, "bar", basis="absolute"),
                     temperature_measured_at="catalyst_bed", conversion=V(conversion, "%", target=co),
                     evidence=[ev("Table 2")], **kw)
        d.link("USES_CATALYST", tid, sample, state="reduced")
        d.link("FED_WITH", tid, feed)
        d.link("IN_REACTOR", tid, reactor)
        d.link("OF_REACTION", tid, rxn)
        return tid

    def transport_check(key, name, test, basis, temp=180, **kw):
        aid = d.node(f"analysis/{key}", "Analysis", name, analysis_kind="transport_check", evaluation_basis=basis,
                     temperature=V(temp, "°C"), evidence=[ev("Supporting Information, Section S3", "text")], **kw)
        d.link("HAS_INPUT", aid, test, role="data")
        return aid

    rate = dict(results={"co2_formation_rate": V(2.1, "umol/(g*s)", target=co2)})
    k1 = co_test("rates-numerical", "CO oxidation rates at 180 °C, 4 % conversion", 4, interpretations=["intrinsic_kinetics"],
                 flow_rate=V(100, "mL/min"), **rate)
    transport_check("weisz-prater", "Weisz-Prater and Mears criteria at 180 °C", k1, "numerical",
                    method="Weisz-Prater criterion (internal diffusion) and Mears criterion (external heat and mass transfer)",
                    verdict="no internal or external transport limitation at 180 °C",
                    results={"weisz_prater_number": V(0.08, "1"), "mears_number": V(0.004, "1")})
    k2 = co_test("rates-integral", "CO oxidation at 200 °C, 35 % conversion, integral analysis", 35, temp=200,
                 interpretations=["intrinsic_kinetics"], flow_rate=V(100, "mL/min"),
                 results={"rate_constant": V(0.9, "1/s", definition="first order in CO, integral plug-flow analysis")})
    transport_check("weisz-prater-200", "Weisz-Prater criterion at 200 °C", k2, "numerical", temp=200,
                    method="Weisz-Prater criterion with the rate constant of the integral analysis",
                    verdict="no internal diffusion limitation at 200 °C", results={"weisz_prater_number": V(0.3, "1")})
    k3 = co_test("rates-experimental", "CO oxidation rates at 180 °C, 6 % conversion, tested by variation", 6,
                 interpretations=["intrinsic_kinetics"], flow_rate=V(100, "mL/min"), **rate)
    k3a = co_test("rates-fine-particles", "The same, 63-125 um particles", 6, sample=fine, flow_rate=V(100, "mL/min"), **rate)
    k3b = co_test("rates-double-flow", "The same, twice the flow and twice the catalyst mass (same W/F)", 6,
                  flow_rate=V(200, "mL/min"), **rate)
    d.link("CONTROL_FOR", k3a, k3, control_kind="reference", differs_in=[v_size])
    d.link("CONTROL_FOR", k3b, k3, control_kind="reference", differs_in=[v_flow])
    exp_check = transport_check("particle-and-flow", "Rates at two particle sizes and at twice the flow, same W/F", k3,
                                "experimental", method="particle size halved; total flow doubled at constant W/F",
                                verdict="rates unchanged within the stated 5 %: no internal or external mass transfer "
                                "limitation")
    d.link("HAS_INPUT", exp_check, k3a, role="data")
    d.link("HAS_INPUT", exp_check, k3b, role="data")
    k4 = co_test("rates-asserted", "CO oxidation rates at 180 °C, transport stated negligible", 5,
                 interpretations=["intrinsic_kinetics"], **rate)
    transport_check("asserted", "Transport effects stated to be negligible", k4, "asserted", method="not stated",
                    verdict="mass transfer limitations were negligible")
    co_test("performance", "CO oxidation at 250 °C, 95 % conversion (system performance)", 95, temp=250, kind="activity",
            interpretations=["system_performance"], space_velocity=V(60000, "1/h", basis="GHSV"))

    # ---- CO2 methanation over Ru/TiO2 under light: separating light from heat
    rxn_m = d.reaction("co2-methanation", "CO2 + 4 H2 -> CH4 + 2 H2O",
                       [(co2, "reactant", 1), (h2, "reactant", 4), (ch4, "product", 1), (h2o, "product", 2)])
    ru = d.node("catalyst/ru-tio2", "Catalyst", "2 wt% Ru/TiO2", nominal_formula="Ru/TiO2", catalyst_family="metal",
                evidence=[ev("Table 1")])
    ru_s = d.node("sample/ru-tio2", "CatalystSample", "Ru/TiO2 film on a glass-fibre disc", sample_kind="film",
                  evidence=[ev("Table 1")])
    d.link("HAS_FORMULATION", ru_s, ru)
    feed_m = d.feed("co2-h2", "CO2/H2 = 1/4", [co2, h2])
    cell = d.node("instrument/photoreactor", "Reactor", "Flow photoreactor with a quartz window", reactor_kind="flow")
    lamp = d.node("instrument/xe-lamp", "LightSource", "300 W Xe lamp, AM1.5G filter", source_kind="xenon_lamp",
                  spectrum="AM1.5G-filtered xenon", evidence=[ev("Methods", "text")])

    def light_test(key, name, claim, rise):
        tid = d.node(f"test/{key}", "CatalyticTest", name, test_kind="activity", driving_forces=["photo", "thermo"],
                     experiment_kind="physical", illumination="light", heat_source="light_and_external",
                     temperature=V(250, "°C"), pressure=V(1, "bar", basis="absolute"), temperature_measured_at="catalyst_bed",
                     light_induced_temperature_rise=V(rise, "K"), irradiance=V(2.0, "W/cm2"), illuminated_area=V(1.0, "cm2"),
                     interpretations=[claim], evidence=[ev("Figure 3")])
        d.link("USES_CATALYST", tid, ru_s, state="reduced")
        d.link("FED_WITH", tid, feed_m)
        d.link("IN_REACTOR", tid, cell)
        d.link("ILLUMINATED_BY", tid, lamp, geometry="front")
        d.link("OF_REACTION", tid, rxn_m)
        return tid

    def dark_control(key, name, light, matched_at):
        tid = d.node(f"test/{key}", "CatalyticTest", name, test_kind="control", driving_forces=["thermo"],
                     experiment_kind="physical", illumination="dark", temperature=V(250, "°C"),
                     pressure=V(1, "bar", basis="absolute"), temperature_measured_at="catalyst_bed", evidence=[ev("Figure 3")])
        d.link("USES_CATALYST", tid, ru_s, state="reduced")
        d.link("FED_WITH", tid, feed_m)
        d.link("IN_REACTOR", tid, cell)
        d.link("OF_REACTION", tid, rxn_m)
        d.link("DARK_CONTROL_FOR", tid, light, control_kind="negative", differs_in=[v_light],
               temperature_matched_by="external_heating", temperature_matched_at=matched_at,
               temperature_matched_over="steady_state", temperature_difference=V(3, "K"))
        return tid

    l1 = light_test("light-surface-matched", "Methanation under light, non-thermal effect, surface-matched control",
                    "nonthermal_light_effect", 40)
    dark_control("dark-surface-matched", "Dark, heated to the illuminated surface temperature (thermal camera)", l1,
                 "illuminated_surface")
    l2 = light_test("light-bulk-matched", "Methanation under light, non-thermal effect, bed-matched control",
                    "nonthermal_light_effect", 40)
    dark_control("dark-bulk-matched", "Dark, heated to the bed temperature (thermocouple in the bed)", l2, "catalyst_bed")
    l3 = light_test("light-photothermal", "Methanation under light at five irradiances, photothermal reading",
                    "photothermal_effect", 55)
    sep = d.node("analysis/irradiance-dependence", "ThermalContributionAnalysis",
                 "Rate against irradiance and catalyst temperature", partition_method="intensity_dependence",
                 method="rates at five irradiances fitted against the measured catalyst temperature (Arrhenius)",
                 verdict="the rate follows the light-induced temperature: a photothermal effect",
                 thermal_contribution=V(95, "%", definition="share of the rate the light-induced heating accounts for"),
                 evidence=[ev("Figure 4")])
    d.link("HAS_INPUT", sep, l3, role="data")

    # ---- NH3 synthesis in a packed-bed DBD: plasma-catalyst synergy
    rxn_a = d.reaction("nh3", "N2 + 3 H2 -> 2 NH3", [(n2, "reactant", 1), (h2, "reactant", 3), (nh3, "product", 2)])
    ni = d.node("catalyst/ni-al2o3", "Catalyst", "10 wt% Ni/Al2O3 beads", nominal_formula="Ni/Al2O3", catalyst_family="metal",
                evidence=[ev("Table 1")])
    ni_s = d.node("sample/ni-beads", "CatalystSample", "Ni/Al2O3 beads, 1-2 mm", sample_kind="pellet", evidence=[ev("Table 1")])
    d.link("HAS_FORMULATION", ni_s, ni)
    feed_a = d.feed("n2-h2", "N2/H2 = 1/3", [n2, h2])
    dbd = d.node("instrument/dbd", "PlasmaSource", "Coaxial DBD, 3 mm gap, packed with the beads",
                 discharge_kind="dielectric_barrier", configuration="in_plasma", evidence=[ev("Methods", "text")])
    beads = d.node("material/al2o3-beads", "Material", "Bare Al2O3 beads, 1-2 mm (the packing without Ni)",
                   evidence=[ev("Methods", "text")])
    plasma_t = d.node("test/plasma-catalyst", "CatalyticTest", "NH3 synthesis, DBD packed with Ni/Al2O3, 200 °C",
                      test_kind="activity", driving_forces=["plasma"], experiment_kind="physical",
                      interpretations=["plasma_catalyst_synergy"], temperature=V(200, "°C"),
                      pressure=V(1, "bar", basis="absolute"), excitation_frequency=V(23, "kHz"),
                      discharge_power=V(18, "W", definition="from the charge-voltage Lissajous figure"),
                      power_supply_input=V(65, "W", definition="power drawn by the high-voltage supply"),
                      specific_energy_input=V(10.8, "kJ/L", definition="plasma power over the total flow"),
                      energy_yield=[V(1.2, "g/kWh", target=nh3, definition="per plasma power")], evidence=[ev("Table 3")])
    d.link("USES_CATALYST", plasma_t, ni_s, state="reduced")
    d.link("FED_WITH", plasma_t, feed_a)
    d.link("USES_PLASMA", plasma_t, dbd)
    d.link("OF_REACTION", plasma_t, rxn_a)
    plasma_only = d.node("experiment/plasma-bare-packing", "Experiment", "DBD packed with bare Al2O3 beads, 200 °C",
                         experiment_kind="physical", goal="investigate", discharge_power=V(18, "W"),
                         conditions={"temperature": V(200, "°C"), "pressure": V(1, "bar", basis="absolute")},
                         evidence=[ev("Table 3")])
    d.link("USES_PLASMA", plasma_only, dbd)
    d.link("HAS_INPUT", plasma_only, feed_a, role="material")
    d.link("HAS_INPUT", plasma_only, beads, role="material")
    d.link("EXAMINES", plasma_only, rxn_a)
    d.link("CONTROL_FOR", plasma_only, plasma_t, control_kind="negative", differs_in=[v_active])
    thermal = d.node("test/thermal-alone", "CatalyticTest", "NH3 synthesis over Ni/Al2O3 without plasma, 200 °C",
                     test_kind="control", driving_forces=["thermo"], experiment_kind="physical", temperature=V(200, "°C"),
                     pressure=V(1, "bar", basis="absolute"), temperature_measured_at="catalyst_bed", evidence=[ev("Table 3")])
    d.link("USES_CATALYST", thermal, ni_s, state="reduced")
    d.link("FED_WITH", thermal, feed_a)
    d.link("OF_REACTION", thermal, rxn_a)
    d.link("CONTROL_FOR", thermal, plasma_t, control_kind="negative", differs_in=[v_plasma])
    return d.finish()


def dynamic_and_stability() -> dict:
    d = Doc("ex:ds", "Dynamic operation and stability: a heating ramp, replicate electrodes and the material after a test",
            "Electrified reforming and O2 evolution over time (invented)")
    ev = d.ev
    ch4, h2o, co, h2 = (d.species("ch4", "CH4", {"C": 1, "H": 4}), d.species("h2o", "H2O", {"H": 2, "O": 1}),
                        d.species("co", "CO", {"C": 1, "O": 1}), d.species("h2", "H2", {"H": 2}))
    o2, oh = d.species("o2", "O2", {"O": 2}), d.species("hydroxide", "OH-", {"O": 1, "H": 1}, name="hydroxide")
    koh = d.species("koh", "KOH", {"K": 1, "O": 1, "H": 1})

    # ---- steam methane reforming on a resistively heated tube: a ramp and a hold
    rxn = d.reaction("smr", "CH4 + H2O -> CO + 3 H2", [(ch4, "reactant", 1), (h2o, "reactant", 1), (co, "product", 1),
                                                         (h2, "product", 3)])
    ni = d.node("catalyst/ni-washcoat", "Catalyst", "Ni/ZrO2 washcoat", nominal_formula="Ni/ZrO2", catalyst_family="metal",
                evidence=[ev("Methods", "text")])
    tube = d.node("sample/ni-washcoat-tube", "CatalystSample", "Ni/ZrO2 washcoat on a FeCrAl tube", sample_kind="film",
                  evidence=[ev("Methods", "text")])
    d.link("HAS_FORMULATION", tube, ni)
    feed = d.feed("ch4-h2o", "CH4/H2O = 1/2", [ch4, h2o])
    reactor = d.node("instrument/heated-tube", "Reactor", "Resistively heated FeCrAl tube reactor", reactor_kind="flow")
    ramp = d.node("operation/ramp-and-hold", "Operation", "Ramp from 300 to 800 °C at 10 K/s, then held for 30 min",
                  operation_mode="dynamic", time_pattern="ramp", varied_quantities=["temperature", "heating_power"],
                  total_duration=V(31, "min"),
                  segments=[{"temperature": V(300, "°C"), "duration": V(60, "s")},
                            {"heating_rate": V(10, "K/s"), "duration": V(50, "s")},
                            {"temperature": V(800, "°C"), "duration": V(30, "min")}],
                  evidence=[ev("Figure 2")])
    t_trace = d.node("dataset/catalyst-temperature", "TimeSeries", "Catalyst temperature, thermocouple in the washcoat",
                     variable="catalyst temperature", unit="°C", series_kind="instantaneous", availability="not_reported",
                     sampling_interval=V(1, "s"), evidence=[ev("Figure 2")])
    x_trace = d.node("dataset/conversion", "TimeSeries", "CH4 conversion by online MS", variable="CH4 conversion", unit="%",
                     series_kind="instantaneous", availability="not_reported", sampling_interval=V(2, "s"),
                     evidence=[ev("Figure 2")])
    smr = d.node("test/ramped-reforming", "CatalyticTest", "Steam reforming during a 300-800 °C ramp and a 30 min hold",
                 test_kind="activity", driving_forces=["electrothermo"], experiment_kind="physical",
                 interpretations=["system_performance"], temperature={"status": "present", "lower": 300, "upper": 800,
                                                                      "unit": "°C"},
                 pressure=V(1, "bar", basis="absolute"), heating_mode="resistive", temperature_measured_at="catalyst_bed",
                 heated_element="the FeCrAl tube", heating_power=V(450, "W", definition="during the hold"),
                 heating_rate=V(10, "K/s"), time_on_stream=V(31, "min"),
                 conversion=V(92, "%", target=ch4, definition="at the end of the hold"), evidence=[ev("Figure 2")])
    d.link("USES_CATALYST", smr, tube, state="reduced")
    d.link("FED_WITH", smr, feed)
    d.link("IN_REACTOR", smr, reactor)
    d.link("OF_REACTION", smr, rxn)
    d.link("HAS_OPERATION", smr, ramp)
    d.link("HAS_OUTPUT", smr, t_trace)
    d.link("HAS_OUTPUT", smr, x_trace)

    # ---- O2 evolution on NiFe oxide: replicates, a performance trace and the material after the test
    rxn_o = d.reaction("oer", "4 OH- -> O2 + 2 H2O + 4 e-", [(oh, "reactant", 4), (o2, "product", 1), (h2o, "product", 2)])
    nife = d.node("catalyst/nife-oxide", "Catalyst", "NiFe oxide (Ni:Fe 3:1)", nominal_formula="Ni0.75Fe0.25Ox",
                  catalyst_family="mixed_oxide", evidence=[ev("Methods", "text")])
    electrolyte = d.node("electrolyte/koh", "Electrolyte", "1 M KOH", pH=V(14, "1"), evidence=[ev("Methods", "text")])
    d.link("HAS_COMPONENT", electrolyte, koh, role="inert", concentration=V(1, "mol/L"))
    cell = d.node("instrument/h-cell", "ElectrochemicalCell", "Three-electrode PTFE cell", cell_kind="single_compartment")
    design = d.node("design/replicate-electrodes", "Design", "Three electrodes from one batch, 24 h at 10 mA/cm2",
                    design_kind="other", planned_replicates=3, strategy="three independently prepared electrodes",
                    evidence=[ev("Methods", "text")])

    def electrode(key):
        sid = d.node(f"sample/nife-{key}", "CatalystSample", f"NiFe oxide on Ni foam, electrode {key}", sample_kind="electrode",
                     evidence=[ev("Methods", "text")])
        d.link("HAS_FORMULATION", sid, nife)
        return sid

    def oer_test(key, name, sample, claims, potential):
        tid = d.node(f"test/{key}", "CatalyticTest", name, test_kind="stability", driving_forces=["electro"],
                     experiment_kind="physical", control_mode="galvanostatic", current_density=V(10, "mA/cm2"),
                     current_normalization="geometric_area", electrode_potential=V(potential, "V"), reference_scale="rhe",
                     ir_compensation="partial", temperature=V(298, "K"), duration=V(24, "h"), interpretations=claims,
                     evidence=[ev("Figure 5")])
        d.link("USES_CATALYST", tid, sample, state="as_prepared")
        d.link("IN_ELECTROLYTE", tid, electrolyte)
        d.link("IN_CELL", tid, cell)
        d.link("OF_REACTION", tid, rxn_o)
        trace = d.node(f"dataset/potential-{key}", "TimeSeries", f"Potential over 24 h, {name}", variable="electrode potential",
                       unit="V", series_kind="instantaneous", availability="not_reported", sampling_interval=V(10, "s"),
                       evidence=[ev("Figure 5")])
        d.link("HAS_OUTPUT", tid, trace)
        return tid

    runs = []
    for i, pot in enumerate((1.53, 1.54, 1.53), start=1):
        claims = ["performance_stability", "material_stability"] if i == 1 else ["performance_stability"]
        runs.append(oer_test(f"oer-electrode-{i}", f"electrode {i}", electrode(str(i)), claims, pot))
        d.link("PART_OF_DESIGN", runs[-1], design, replicate_group="24 h at 10 mA/cm2", run_order=i)
    for r in runs[1:]:
        d.link("REPLICATES", r, runs[0], level="replicate", changed=["sample"], agreement="agrees",
               criterion="potentials within 10 mV over 24 h")
    after = d.node("state/nife-after-24h", "CatalystState", "Electrode 1 after 24 h", state_kind="post_reaction",
                   regime="steady", evidence=[ev("Figure 6")])
    d.link("REACHED_BY", after, runs[0], timing="after", elapsed=V(24, "h"))
    d.link("STATE_OF", after, next(n["id"] for n in d.doc["nodes"] if n["id"].endswith("sample/nife-1")))
    icp = d.node("characterization/icp-ms", "Characterization", "ICP-MS of electrolyte aliquots over 24 h",
                 technique="inductively coupled plasma mass spectrometry", observation_mode="ex_situ",
                 results={"dissolved_fe": V(0.4, "ug", definition="Fe in the electrolyte after 24 h"),
                          "dissolved_ni": V(0.1, "ug", definition="Ni in the electrolyte after 24 h")},
                 evidence=[ev("Figure 6")])
    xps = d.node("characterization/xps-after", "Characterization", "XPS of electrode 1 after 24 h",
                 technique="X-ray photoelectron spectroscopy", observation_mode="ex_situ", evidence=[ev("Figure 6")])
    d.link("DETERMINED_BY", after, icp)
    d.link("DETERMINED_BY", after, xps)
    oer_test("oer-trace-only", "electrode read as stable from its potential trace", electrode("4"), ["material_stability"],
             1.53)
    return d.finish()


if __name__ == "__main__":
    write_canonical(HERE / "kinetic-evidence.json", kinetic_evidence())
    write_canonical(HERE / "dynamic-and-stability.json", dynamic_and_stability())
    print("wrote kinetic-evidence.json and dynamic-and-stability.json")
