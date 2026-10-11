"""Build one synthetic document per driving force (and per combination of forces) for the catalysis domain's scale-catal
schema (all values invented). Every document follows the one catalysis checklist (follows_domains: [catalysis]); its
items for a catalytic test apply by the driving forces the test lists.

    python build_examples.py

  electro.json             nitrate reduction on a Cu electrode: electrodes in their roles, reference scale, electrolyte, FE
  electro-dynamic.json     the same reaction under square potential pulses (a dynamic Operation), with its static control
  electrothermo.json       ammonia decomposition on a Joule-heated Ru/carbon felt, with a furnace-heated control
  photo.json               CO2 photoreduction on TiO2 with its dark control
  plasma.json              DBD ammonia synthesis over Ni/Al2O3 with plasma-only and catalyst-only controls
  photothermo.json         CO2 methanation on Ru/TiO2 under light and heat, dark control at the same catalyst temperature
  photothermo-dynamic.json CO2 hydrogenation on Ni/CeO2 under chopped light (a dynamic Operation), steady-light control
  photoelectro.json        water oxidation on a BiVO4 photoanode: dark and open-circuit controls
  electrophoto.json        C-H amination with an electrochemically turned-over molecular photocatalyst, dark control
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
REPO = _repo_root(HERE, Path.cwd())        # the cwd too: the tests run a copy of this script from a temporary directory
sys.path.insert(0, str(REPO / "tools"))
from scale import layout  # noqa: E402
from scale.pgraph import derive_reported_in  # noqa: E402
from scale.util import write_canonical  # noqa: E402

SYN = "synthetic"


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


# the documents pin the catalysis domain's schema version they are built for
_HEAD = REPO / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST
HEAD_VERSION = __import__("yaml").safe_load(_HEAD.read_text())["version"]


class Doc:
    def __init__(self, key: str, title: str):
        self.p = f"ex:df-{key}"
        self.doc = {"directed": True, "multigraph": True,
                    "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{self.p}/graph", "title": title,
                              "data_status": "synthetic_example", "follows_domains": ["catalysis"],
                              "stewardship": {"access": "public"}},      # committed documents say so (scale check)
                    "nodes": [], "links": []}
        self.n = 0
        self.src = self.node("source/paper", "Source", "Invented paper", kind="article", title=title + " (invented)", year=2026)

    def node(self, rid, label, name, **props):
        nid = f"{self.p}/{rid}"
        self.doc["nodes"].append({"id": nid, "label": label, "props": {"name": name, "origin": SYN, **props}})
        return nid

    def link(self, typ, s, t, **props):
        self.n += 1
        lid = f"{self.p}/link/{self.n}"
        self.doc["links"].append({"id": lid, "source": s, "target": t, "type": typ, "props": {"origin": SYN, **props}})
        return lid

    def ev(self, locator, kind="table"):
        return [{"source": self.src, "locator": locator, "kind": kind}]

    def species(self, key, formula, comp, charge=0):
        return self.node(f"species/{key}", "ChemicalSpecies", formula, formula=formula, elemental_composition=comp, charge=charge)

    def reaction(self, key, equation, parts):
        r = self.node(f"reaction/{key}", "Reaction", equation, equation=equation, balance_status="balanced", direction="forward")
        for sp, coef in parts:
            self.link("HAS_PARTICIPANT", r, sp, role="reactant" if coef < 0 else "product", coefficient=abs(coef))
        return r

    def catalyst(self, key, name, formula):
        c = self.node(f"catalyst/{key}", "Catalyst", name, nominal_formula=formula, catalyst_family="oxide", evidence=self.ev("Table 1"))
        s = self.node(f"sample/{key}", "CatalystSample", f"{name}, batch 1", sample_kind="powder", evidence=self.ev("Table 1"))
        self.link("HAS_FORMULATION", s, c)
        return c, s

    def write(self, name):
        for e in derive_reported_in(self.doc):
            e["props"]["origin"] = SYN
            self.doc["links"].append(e)
        write_canonical(HERE / name, self.doc)


def electrocatalysis() -> None:
    d = Doc("electro", "Nitrate electroreduction to ammonia on a Cu electrode")
    no3, nh3 = d.species("nitrate", "NO3-", {"N": 1, "O": 3}, -1), d.species("ammonia", "NH3", {"N": 1, "H": 3})
    h2o, oh, e = d.species("water", "H2O", {"H": 2, "O": 1}), d.species("hydroxide", "OH-", {"O": 1, "H": 1}, -1), \
        d.species("electron", "e-", {}, -1)
    rxn = d.reaction("no3rr", "NO3- + 6 H2O + 8 e- -> NH3 + 9 OH-", [(no3, -1), (h2o, -6), (e, -8), (nh3, 1), (oh, 9)])
    _, sample = d.catalyst("cu", "Cu nanoparticles", "Cu")
    electrode = d.node("electrode/cu-on-cp", "Electrode", "Cu on carbon paper", substrate="carbon paper",
                       geometric_area=V(1.0, "cm2"), catalyst_loading=V(0.2, "mg/cm2"), evidence=d.ev("Methods", "text"))
    d.link("HAS_PART", electrode, sample, role="catalyst layer")
    ref = d.node("instrument/ref", "ReferenceElectrode", "Ag/AgCl reference", reference_type="ag_agcl", filling="saturated KCl")
    counter = d.node("electrode/pt", "Electrode", "Pt foil counter electrode", substrate="Pt foil")
    k2so4 = d.species("k2so4", "K2SO4", {"K": 2, "S": 1, "O": 4})
    el = d.node("electrolyte/k2so4-kno3", "Electrolyte", "0.5 M K2SO4 + 0.1 M KNO3", pH=V(7.0, "1"), evidence=d.ev("Methods", "text"))
    d.link("HAS_COMPONENT", el, k2so4, role="inert", fraction=V(0.5, "mol/L"), fraction_basis="not_reported")
    d.link("HAS_COMPONENT", el, no3, role="reactant", fraction=V(0.1, "mol/L"), fraction_basis="not_reported")
    cell = d.node("instrument/h-cell", "ElectrochemicalCell", "H-cell", cell_kind="h_cell", separator="Nafion 117", compartments=2)
    t = d.node("test/m03", "CatalyticTest", "Electrolysis at -0.3 V vs RHE", test_kind="activity", driving_forces=["electro"],
               experiment_kind="physical", control_mode="potentiostatic",
               electrode_potential=V(-0.3, "V", as_reported="-0.3 V vs RHE (converted by the authors from Ag/AgCl)"),
               reference_scale="rhe", ir_compensation="partial", ir_compensation_fraction=0.85, temperature=V(298, "K"),
               current_density=V(-120, "mA/cm2", basis="geometric area"), current_normalization="geometric_area", charge_passed=V(-50, "C"),
               faradaic_efficiency=[V(92, "%", target=nh3, uncertainty=3, uncertainty_kind="standard_deviation", replicates=3)],
               evidence=d.ev("Figure 2", "figure"))
    d.link("USES_CATALYST", t, sample, state="as_prepared")
    d.link("USES_ELECTRODE", t, electrode, role="working")
    d.link("USES_ELECTRODE", t, counter, role="counter")
    d.link("USES_ELECTRODE", t, ref, role="reference")
    d.link("IN_ELECTROLYTE", t, el)
    d.link("IN_CELL", t, cell)
    d.link("OF_REACTION", t, rxn)
    d.write("electro.json")


def photocatalysis() -> None:
    d = Doc("photo", "CO2 photoreduction on TiO2 with its dark control")
    co2, co, h2o = d.species("co2", "CO2", {"C": 1, "O": 2}), d.species("co", "CO", {"C": 1, "O": 1}), d.species("water", "H2O", {"H": 2, "O": 1})
    o2 = d.species("o2", "O2", {"O": 2})
    rxn = d.reaction("co2-to-co", "2 CO2 -> 2 CO + O2", [(co2, -2), (co, 2), (o2, 1)])
    _, sample = d.catalyst("tio2", "TiO2 (P25)", "TiO2")
    lamp = d.node("instrument/xe", "LightSource", "300 W Xe lamp", source_kind="xenon_lamp", spectrum="full arc, AM1.5G filter",
                  nominal_power=V(300, "W"))
    illum = d.node("variable/illumination", "Variable", "Illumination", scale="nominal", categories=["light", "dark"])
    tests = {}
    for mode in ("light", "dark"):
        props = dict(test_kind="activity" if mode == "light" else "control", driving_forces=["photo"], experiment_kind="physical",
                     illumination=mode, temperature=V(298, "K"), evidence=d.ev("Table 2"),
                     results={"co_rate": V(12.0 if mode == "light" else 0.2, "umol/(g*h)", target=co)})
        if mode == "light":
            props.update(irradiance=V(100, "mW/cm2"), illuminated_area=V(3.1, "cm2"), optical_path="AM1.5G filter, quartz window, 10 cm to the slurry",
                         wavelength={"status": "present", "lower": 300, "upper": 800, "unit": "nm"},
                         apparent_quantum_yield=[V(0.6, "%", target=co, as_reported="AQY at 365 nm")])
        t = d.node(f"test/{mode}", "CatalyticTest", f"TiO2, {mode}", **props)
        d.link("USES_CATALYST", t, sample, state="as_prepared")
        d.link("ILLUMINATED_BY", t, lamp, geometry="front")
        d.link("OF_REACTION", t, rxn)
        d.link("HAS_VARIABLE", t, illum, role="factor", level={"status": "present", "text_value": mode, "variable": illum})
        d.link("HAS_INPUT", t, h2o, role="reagent")
        tests[mode] = t
    d.link("CONTROL_FOR", tests["dark"], tests["light"], control_kind="negative", differs_in=[illum])
    d.write("photo.json")


def plasma() -> None:
    d = Doc("plasma", "DBD plasma-catalytic ammonia synthesis over Ni/Al2O3 with its controls")
    n2, h2, nh3 = d.species("n2", "N2", {"N": 2}), d.species("h2", "H2", {"H": 2}), d.species("nh3", "NH3", {"N": 1, "H": 3})
    rxn = d.reaction("nh3", "N2 + 3 H2 -> 2 NH3", [(n2, -1), (h2, -3), (nh3, 2)])
    _, sample = d.catalyst("ni", "Ni/Al2O3", "Ni/Al2O3")
    dbd = d.node("instrument/dbd", "PlasmaSource", "Coaxial DBD reactor", discharge_kind="dielectric_barrier", configuration="in_plasma",
                 discharge_gap=V(3, "mm"), dielectric="quartz")
    feed = d.node("feed/n2-h2", "Feed", "N2/H2 = 1/3", evidence=d.ev("Methods", "text"))
    d.link("HAS_COMPONENT", feed, n2, role="reactant", fraction=V(25, "%"), fraction_basis="mole")
    d.link("HAS_COMPONENT", feed, h2, role="reactant", fraction=V(75, "%"), fraction_basis="mole")
    vplasma = d.node("variable/plasma", "Variable", "Plasma on", scale="boolean")
    vcat = d.node("variable/catalyst", "Variable", "Catalyst present", scale="boolean")
    base = dict(driving_forces=["plasma"], experiment_kind="physical", temperature=V(423, "K", as_reported="bed at about 150 °C"),
                pressure=V(1, "atm"), evidence=d.ev("Table 1"))
    both = d.node("test/plasma-catalyst", "CatalyticTest", "Plasma + Ni/Al2O3", test_kind="activity", discharge_power=V(15, "W"),
                  specific_energy_input=V(9, "kJ/L"), applied_voltage=V(8, "kV"), excitation_frequency=V(20, "kHz"),
                  energy_yield=[V(1.2, "g/kWh", target=nh3)], **base)
    # a plasma-only control has no catalyst, so it is an Experiment, not a CatalyticTest (the plasma vocabulary
    # is available on every Experiment)
    plasma_only = d.node("test/plasma-only", "Experiment", "Plasma, no catalyst", experiment_kind="physical", goal="investigate",
                         discharge_power=V(15, "W"), specific_energy_input=V(9, "kJ/L"), energy_yield=[V(0.4, "g/kWh", target=nh3)],
                         conditions={"temperature": V(423, "K"), "pressure": V(1, "atm")}, evidence=d.ev("Table 1"))
    cat_only = d.node("test/catalyst-only", "CatalyticTest", "Ni/Al2O3 without plasma", test_kind="control",
                      **{**base, "driving_forces": ["thermo"]}, results={"nh3_yield": {"status": "below_detection_limit", "value": 1, "unit": "ppm", "target": nh3}})
    for t in (both, cat_only):
        d.link("FED_WITH", t, feed)
        d.link("OF_REACTION", t, rxn)
    d.link("HAS_INPUT", plasma_only, feed, role="reagent")
    d.link("EXAMINES", plasma_only, rxn, role="reaction studied")
    for t in (both, plasma_only):
        d.link("USES_PLASMA", t, dbd)
    d.link("USES_CATALYST", both, sample, state="reduced")
    d.link("USES_CATALYST", cat_only, sample, state="reduced")
    d.link("CONTROL_FOR", plasma_only, both, control_kind="negative", differs_in=[vcat])
    d.link("CONTROL_FOR", cat_only, both, control_kind="negative", differs_in=[vplasma])
    d.write("plasma.json")


def photoelectrocatalysis() -> None:
    d = Doc("photoelectro", "Water oxidation on a BiVO4 photoanode: light and potential together")
    h2o, o2 = d.species("water", "H2O", {"H": 2, "O": 1}), d.species("o2", "O2", {"O": 2})
    hp, e = d.species("proton", "H+", {"H": 1}, 1), d.species("electron", "e-", {}, -1)
    rxn = d.reaction("oer", "2 H2O -> O2 + 4 H+ + 4 e-", [(h2o, -2), (o2, 1), (hp, 4), (e, 4)])
    _, sample = d.catalyst("bivo4", "BiVO4 film", "BiVO4")
    anode = d.node("electrode/bivo4-fto", "Electrode", "BiVO4 on FTO", substrate="FTO glass", geometric_area=V(0.5, "cm2"))
    d.link("HAS_PART", anode, sample, role="photoabsorber and catalyst")
    ref = d.node("instrument/ref", "ReferenceElectrode", "Ag/AgCl reference", reference_type="ag_agcl", filling="3 M KCl")
    el = d.node("electrolyte/kpi", "Electrolyte", "0.5 M potassium phosphate", pH=V(7.0, "1"))
    kpi = d.species("phosphate", "KH2PO4", {"K": 1, "H": 2, "P": 1, "O": 4})
    d.link("HAS_COMPONENT", el, kpi, role="inert", fraction=V(0.5, "mol/L"), fraction_basis="not_reported")
    lamp = d.node("instrument/sim", "LightSource", "Solar simulator", source_kind="solar_simulator", spectrum="AM1.5G")
    villum = d.node("variable/illumination", "Variable", "Illumination", scale="nominal", categories=["light", "dark"])
    vpot = d.node("variable/potential", "Variable", "Electrode potential", scale="quantitative", quantity_kind="electric_potential", unit="V")
    both_forces = ["photo", "electro"]
    common = dict(test_kind="activity", experiment_kind="physical", control_mode="potentiostatic", reference_scale="rhe",
                  ir_compensation="not_applied", temperature=V(298, "K"), evidence=d.ev("Figure 3", "figure"))
    main = d.node("test/light-1v23", "CatalyticTest", "Light, 1.23 V vs RHE", driving_forces=both_forces, illumination="light",
                  light_absorber="photoelectrode",
                  irradiance=V(100, "mW/cm2"), illuminated_area=V(0.5, "cm2"), electrode_potential=V(1.23, "V"),
                  current_density=V(3.5, "mA/cm2", basis="geometric area"), cell_voltage=V(1.9, "V"),
                  photocurrent_density=V(3.5, "mA/cm2"), abpe=V(1.1, "%"),
                  faradaic_efficiency=[V(95, "%", target=o2)], **common)
    dark = d.node("test/dark-1v23", "CatalyticTest", "Dark, 1.23 V vs RHE", driving_forces=["electro"], illumination="dark",
                  electrode_potential=V(1.23, "V"), current_density=V(0.01, "mA/cm2"),
                  **{**common, "test_kind": "control"})
    ocp = d.node("test/light-ocp", "CatalyticTest", "Light, open circuit", driving_forces=["photo"], illumination="light",
                 irradiance=V(100, "mW/cm2"), results={"photovoltage": V(0.45, "V")},
                 **{**common, "test_kind": "control", "control_mode": "open_circuit"})
    for t in (main, dark, ocp):
        d.link("USES_CATALYST", t, sample, state="as_prepared")
        d.link("USES_ELECTRODE", t, anode, role="working")
        d.link("USES_ELECTRODE", t, ref, role="reference")
        d.link("IN_ELECTROLYTE", t, el)
        d.link("OF_REACTION", t, rxn)
    for t in (main, ocp):
        d.link("ILLUMINATED_BY", t, lamp, geometry="front")
    d.link("CONTROL_FOR", dark, main, control_kind="negative", differs_in=[villum])
    d.link("CONTROL_FOR", ocp, main, control_kind="negative", differs_in=[vpot])
    d.write("photoelectro.json")


def photothermal() -> None:
    d = Doc("photothermal", "CO2 methanation on Ru/TiO2 under light and heat")
    co2, h2 = d.species("co2", "CO2", {"C": 1, "O": 2}), d.species("h2", "H2", {"H": 2})
    ch4, h2o = d.species("ch4", "CH4", {"C": 1, "H": 4}), d.species("water", "H2O", {"H": 2, "O": 1})
    rxn = d.reaction("sabatier", "CO2 + 4 H2 -> CH4 + 2 H2O", [(co2, -1), (h2, -4), (ch4, 1), (h2o, 2)])
    _, sample = d.catalyst("ru", "Ru/TiO2", "Ru/TiO2")
    feed = d.node("feed/co2-h2", "Feed", "CO2/H2 = 1/4")
    d.link("HAS_COMPONENT", feed, co2, role="reactant", fraction=V(20, "%"), fraction_basis="mole")
    d.link("HAS_COMPONENT", feed, h2, role="reactant", fraction=V(80, "%"), fraction_basis="mole")
    lamp = d.node("instrument/xe", "LightSource", "Xe lamp", source_kind="xenon_lamp")
    reactor = d.node("instrument/reactor", "Reactor", "Flow reactor with quartz window", reactor_kind="flow")
    villum = d.node("variable/illumination", "Variable", "Illumination", scale="nominal", categories=["light", "dark"])
    common = dict(experiment_kind="physical", temperature=V(473, "K"), temperature_measured_at="catalyst_bed", pressure=V(1, "atm"),
                  heating_mode="external_furnace", space_velocity=V(12000, "mL/(g*h)"), evidence=d.ev("Table 3"))
    light = d.node("test/light", "CatalyticTest", "Light + 473 K", test_kind="activity", driving_forces=["photo", "thermo"],
                   illumination="light", irradiance=V(2.0, "W/cm2"), illuminated_area=V(1.2, "cm2"),
                   conversion=V(18, "%", target=co2), selectivity=V(99, "%", target=ch4),
                   light_induced_temperature_rise=V(0, "K", note="bed temperature held at 473 K by the furnace controller"),
                   heat_source="light_and_external", **common)
    dark = d.node("test/dark", "CatalyticTest", "Dark, 473 K (same bed temperature)", test_kind="control", driving_forces=["thermo"],
                  illumination="dark", conversion=V(9, "%", target=co2), **common)
    for t in (light, dark):
        d.link("USES_CATALYST", t, sample, state="reduced")
        d.link("FED_WITH", t, feed)
        d.link("OF_REACTION", t, rxn)
        d.link("IN_REACTOR", t, reactor)
    d.link("ILLUMINATED_BY", light, lamp, geometry="front")
    d.link("CONTROL_FOR", dark, light, control_kind="negative", differs_in=[villum])
    d.write("photothermo.json")


def electrified_thermal() -> None:
    d = Doc("electrothermal", "Ammonia decomposition on a Joule-heated Ru/carbon felt")
    nh3, n2, h2 = d.species("nh3", "NH3", {"N": 1, "H": 3}), d.species("n2", "N2", {"N": 2}), d.species("h2", "H2", {"H": 2})
    rxn = d.reaction("nh3-decomposition", "2 NH3 -> N2 + 3 H2", [(nh3, -2), (n2, 1), (h2, 3)])
    _, sample = d.catalyst("ru-cf", "Ru on carbon felt", "Ru/C")
    feed = d.node("feed/nh3", "Feed", "pure NH3")
    d.link("HAS_COMPONENT", feed, nh3, role="reactant", fraction=V(100, "%"), fraction_basis="mole")
    vheat = d.node("variable/heating", "Variable", "Heating mode", scale="nominal", categories=["resistive", "external_furnace"])
    common = dict(experiment_kind="physical", driving_forces=["thermo"], temperature=V(723, "K"), temperature_measured_at="catalyst_bed",
                  pressure=V(1, "atm"), space_velocity=V(30000, "mL/(g*h)"), evidence=d.ev("Table 1"))
    joule = d.node("test/joule", "CatalyticTest", "Joule heating, 450 °C at the felt", test_kind="activity", heating_mode="resistive",
                   heating_power=V(12, "W"), heating_current=V(4.2, "A"), heated_element="the Ru-loaded carbon felt",
                   heating_rate=V(50, "K/s"), conversion=V(85, "%", target=nh3), **{**common, "driving_forces": ["electrothermo"]})
    furnace = d.node("test/furnace", "CatalyticTest", "Furnace heating, 450 °C in the bed", test_kind="control",
                     heating_mode="external_furnace", conversion=V(60, "%", target=nh3), **common)
    for t in (joule, furnace):
        d.link("USES_CATALYST", t, sample, state="reduced")
        d.link("FED_WITH", t, feed)
        d.link("OF_REACTION", t, rxn)
    d.link("CONTROL_FOR", furnace, joule, control_kind="baseline", differs_in=[vheat])
    d.write("electrothermo.json")


def dynamic_electrocatalysis() -> None:
    d = Doc("dynelectro", "Pulsed nitrate electroreduction on Cu with a square potential waveform")
    no3, nh3 = d.species("nitrate", "NO3-", {"N": 1, "O": 3}, -1), d.species("ammonia", "NH3", {"N": 1, "H": 3})
    h2o, oh, e = d.species("water", "H2O", {"H": 2, "O": 1}), d.species("hydroxide", "OH-", {"O": 1, "H": 1}, -1), \
        d.species("electron", "e-", {}, -1)
    rxn = d.reaction("no3rr", "NO3- + 6 H2O + 8 e- -> NH3 + 9 OH-", [(no3, -1), (h2o, -6), (e, -8), (nh3, 1), (oh, 9)])
    _, sample = d.catalyst("cu", "Cu nanoparticles", "Cu")
    electrode = d.node("electrode/cu", "Electrode", "Cu on carbon paper", substrate="carbon paper", geometric_area=V(1.0, "cm2"))
    d.link("HAS_PART", electrode, sample, role="catalyst layer")
    ref = d.node("instrument/ref", "ReferenceElectrode", "Ag/AgCl reference", reference_type="ag_agcl", filling="saturated KCl")
    el = d.node("electrolyte/k2so4-kno3", "Electrolyte", "0.5 M K2SO4 + 0.01 M KNO3", pH=V(7.0, "1"))
    d.link("HAS_COMPONENT", el, no3, role="reactant", fraction=V(0.01, "mol/L"), fraction_basis="not_reported")
    pulsed_op = d.node("operation/square-pulse", "Operation", "Square potential pulses", operation_mode="dynamic", time_pattern="periodic",
                       varied_quantities=["electrode_potential"], total_duration=V(1, "h"),
                       segments=[{"electrode_potential": V(0.2, "V"), "duration": V(2, "s")},
                                 {"electrode_potential": V(-1.4, "V"), "duration": V(50, "s")}],
                       description="potentials vs Ag/AgCl (saturated KCl)")
    steady_op = d.node("operation/static", "Operation", "Held at -1.4 V", operation_mode="static", time_pattern="constant",
                       total_duration=V(1, "h"))
    vmode = d.node("variable/control-mode", "Variable", "Control mode", scale="nominal", categories=["pulsed", "potentiostatic"])
    common = dict(experiment_kind="physical", driving_forces=["electro"], reference_scale="ag_agcl", ir_compensation="not_applied",
                  temperature=V(298, "K"), evidence=d.ev("Figure 1", "figure"))
    pulsed = d.node("test/pulsed", "CatalyticTest", "Pulsed, 0.2 V / -1.4 V vs Ag/AgCl", test_kind="activity", control_mode="pulsed",
                    faradaic_efficiency=[V(94, "%", target=nh3)], **common)
    steady = d.node("test/steady", "CatalyticTest", "Potentiostatic, -1.4 V vs Ag/AgCl", test_kind="control", control_mode="potentiostatic",
                    electrode_potential=V(-1.4, "V"), faradaic_efficiency=[V(57, "%", target=nh3)], **common)
    for t in (pulsed, steady):
        d.link("USES_CATALYST", t, sample, state="as_prepared")
        d.link("USES_ELECTRODE", t, electrode, role="working")
        d.link("USES_ELECTRODE", t, ref, role="reference")
        d.link("IN_ELECTROLYTE", t, el)
        d.link("OF_REACTION", t, rxn)
    d.link("HAS_OPERATION", pulsed, pulsed_op)
    d.link("HAS_OPERATION", steady, steady_op)
    d.link("CONTROL_FOR", steady, pulsed, control_kind="baseline", differs_in=[vmode])
    d.write("electro-dynamic.json")


def electrophotocatalysis() -> None:
    d = Doc("electrophoto", "C-H amination with an electrochemically turned-over molecular photocatalyst")
    sub, prod = d.species("benzene", "C6H6", {"C": 6, "H": 6}), d.species("phenyltriazole", "C8H7N3", {"C": 8, "H": 7, "N": 3})
    az, h2 = d.species("triazole", "C2H3N3", {"C": 2, "H": 3, "N": 3}), d.species("h2", "H2", {"H": 2})
    rxn = d.reaction("amination", "C6H6 + C2H3N3 -> C8H7N3 + H2", [(sub, -1), (az, -1), (prod, 1), (h2, 1)])
    cat, sample = d.catalyst("tac", "Trisaminocyclopropenium photocatalyst", "C21H36N3+")
    anode = d.node("electrode/rvc", "Electrode", "Reticulated vitreous carbon anode", substrate="RVC")
    ref = d.node("instrument/ref", "ReferenceElectrode", "Ag/AgNO3 reference", reference_type="pseudo_reference")
    el = d.node("electrolyte/mecn", "Electrolyte", "0.1 M Et4NBF4 in MeCN")
    salt = d.species("et4nbf4", "C8H20NBF4", {"C": 8, "H": 20, "N": 1, "B": 1, "F": 4})
    d.link("HAS_COMPONENT", el, salt, role="inert", fraction=V(0.1, "mol/L"), fraction_basis="not_reported")
    lamp = d.node("instrument/cfl", "LightSource", "Compact fluorescent lamp", source_kind="other", spectrum="white light")
    villum = d.node("variable/illumination", "Variable", "Illumination", scale="nominal", categories=["light", "dark"])
    common = dict(experiment_kind="physical", test_kind="activity", driving_forces=["electro", "photo"],
                  light_absorber="molecular_photocatalyst", excited_species="electrogenerated radical dication of the photocatalyst",
                  control_mode="galvanostatic", current=V(1.5, "mA"),
                  reference_scale="other", temperature=V(298, "K"), evidence=d.ev("Table 1"))
    light = d.node("test/light", "CatalyticTest", "Light + 1.5 mA", illumination="light", results={"yield": V(72, "%", target=prod)}, **common)
    dark = d.node("test/dark", "CatalyticTest", "Dark + 1.5 mA", illumination="dark", results={"yield": V(3, "%", target=prod)},
                  **{**common, "test_kind": "control"})
    for t in (light, dark):
        d.link("USES_CATALYST", t, sample, state="as_prepared")
        d.link("USES_ELECTRODE", t, anode, role="working")
        d.link("USES_ELECTRODE", t, ref, role="reference")
        d.link("IN_ELECTROLYTE", t, el)
        d.link("OF_REACTION", t, rxn)
        d.link("ILLUMINATED_BY", t, lamp, geometry="side")
    d.link("CONTROL_FOR", dark, light, control_kind="negative", differs_in=[villum])
    d.write("electrophoto.json")


def dynamic_photothermal() -> None:
    d = Doc("dynphotothermal", "CO2 hydrogenation on Ni/CeO2 under chopped light and heat")
    co2, h2 = d.species("co2", "CO2", {"C": 1, "O": 2}), d.species("h2", "H2", {"H": 2})
    co, h2o = d.species("co", "CO", {"C": 1, "O": 1}), d.species("water", "H2O", {"H": 2, "O": 1})
    rxn = d.reaction("rwgs", "CO2 + H2 -> CO + H2O", [(co2, -1), (h2, -1), (co, 1), (h2o, 1)])
    _, sample = d.catalyst("ni-ceo2", "Ni/CeO2", "Ni/CeO2")
    feed = d.node("feed/co2-h2", "Feed", "CO2/H2 = 1/1")
    d.link("HAS_COMPONENT", feed, co2, role="reactant", fraction=V(50, "%"), fraction_basis="mole")
    d.link("HAS_COMPONENT", feed, h2, role="reactant", fraction=V(50, "%"), fraction_basis="mole")
    lamp = d.node("instrument/xe", "LightSource", "Xe lamp with chopper", source_kind="xenon_lamp")
    chopped_op = d.node("operation/chopped", "Operation", "Chopped light", operation_mode="dynamic", time_pattern="periodic",
                        varied_quantities=["irradiance"], period=V(20, "s"), duty_cycle=V(50, "%"),
                        segments=[{"irradiance": V(2.0, "W/cm2"), "duration": V(10, "s")}, {"irradiance": V(0, "W/cm2"), "duration": V(10, "s")}])
    steady_op = d.node("operation/steady", "Operation", "Steady light", operation_mode="static", time_pattern="constant")
    vmod = d.node("variable/modulation", "Variable", "Light modulation", scale="nominal", categories=["chopped", "steady"])
    common = dict(experiment_kind="physical", driving_forces=["photo", "thermo"], illumination="light", temperature=V(523, "K"),
                  temperature_measured_at="catalyst_bed", pressure=V(1, "atm"), heating_mode="external_furnace",
                  space_velocity=V(24000, "mL/(g*h)"), evidence=d.ev("Figure 4", "figure"))
    chopped = d.node("test/chopped", "CatalyticTest", "Chopped light, 20 s period", test_kind="activity", irradiance=V(1.0, "W/cm2",
                     as_reported="1.0 W cm-2 time-averaged"), conversion=V(14, "%", target=co2), **common)
    steady = d.node("test/steady", "CatalyticTest", "Steady light, same average irradiance", test_kind="control",
                    irradiance=V(1.0, "W/cm2"), conversion=V(11, "%", target=co2), **common)
    for t in (chopped, steady):
        d.link("USES_CATALYST", t, sample, state="reduced")
        d.link("FED_WITH", t, feed)
        d.link("OF_REACTION", t, rxn)
        d.link("ILLUMINATED_BY", t, lamp, geometry="front")
    d.link("HAS_OPERATION", chopped, chopped_op)
    d.link("HAS_OPERATION", steady, steady_op)
    d.link("CONTROL_FOR", steady, chopped, control_kind="baseline", differs_in=[vmod])
    d.write("photothermo-dynamic.json")


if __name__ == "__main__":
    for f in (electrocatalysis, photocatalysis, plasma, photoelectrocatalysis, photothermal, electrified_thermal,
              dynamic_electrocatalysis, electrophotocatalysis, dynamic_photothermal):
        f()
    print("wrote 9 documents")
