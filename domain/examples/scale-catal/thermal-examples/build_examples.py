"""Build the synthetic example of an analysis that separates the heating a driving force causes from its other effects on
a rate (all values invented): an Analysis of analysis_kind thermal_contribution, for light and for a plasma, with the
shares it attributes as result entries.

    python build_examples.py

  thermal-contribution.json
    light, photothermal    CO2 methanation over Ru/TiO2 under light at five irradiances; the rate follows the catalyst
                           temperature the light raises (partition_method intensity_dependence): 95 % of the CH4 rate
                           from heating, 5 % not
    light, non-thermal     the same reaction under light against a dark control heated to the illuminated surface's
                           temperature (DARK_CONTROL_FOR, matched at the surface); the analysis compares the two rates
                           (control_at_matched_temperature): 60 % from heating, 40 % not
    plasma                 NH3 synthesis in a DBD packed with Ni/Al2O3 against the catalyst without plasma at the same
                           bed temperature (CONTROL_FOR); the analysis compares the two rates: 25 % of the NH3 rate from
                           heating, 75 % from the plasma's other effects
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


def thermal_contribution() -> dict:
    p = "ex:tc"
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{p}/graph",
                     "title": "How much of a rate under light or a plasma is heating, and how a source tells (synthetic)",
                     "data_status": "synthetic_example", "follows_domains": ["catalysis"],
                     "stewardship": {"access": "public"}},
           "nodes": [], "links": []}
    n = [0]

    def node(rid, label, name, **props):
        nid = f"{p}/{rid}"
        doc["nodes"].append({"id": nid, "label": label, "props": {"name": name, "origin": SYN, **props}})
        return nid

    def link(typ, s, t, **props):
        n[0] += 1
        lid = f"{p}/link/{n[0]}"
        doc["links"].append({"id": lid, "source": s, "target": t, "type": typ, "props": {"origin": SYN, **props}})
        return lid

    paper = node("source/paper", "Source", "Invented paper", kind="article", year=2026,
                 title="Heat or something else? Rates under light and in a plasma (invented)")

    def ev(locator, kind="table", **kw):
        return {"source": paper, "locator": locator, "kind": kind, **kw}

    def species(key, formula, composition):
        return node(f"species/{key}", "ChemicalSpecies", formula, formula=formula, elemental_composition=composition, charge=0)

    co2, h2, ch4, h2o = species("co2", "CO2", {"C": 1, "O": 2}), species("h2", "H2", {"H": 2}), \
        species("ch4", "CH4", {"C": 1, "H": 4}), species("h2o", "H2O", {"H": 2, "O": 1})
    n2, nh3 = species("n2", "N2", {"N": 2}), species("nh3", "NH3", {"N": 1, "H": 3})

    def reaction(key, equation, parts):
        rid = node(f"reaction/{key}", "Reaction", equation, equation=equation, balance_status="balanced",
                   direction="forward", evidence=[ev("Methods", "text")])
        for sp, role, coef in parts:
            link("HAS_PARTICIPANT", rid, sp, role=role, coefficient=coef)
        return rid

    methanation = reaction("co2-methanation", "CO2 + 4 H2 -> CH4 + 2 H2O",
                           [(co2, "reactant", 1), (h2, "reactant", 4), (ch4, "product", 1), (h2o, "product", 2)])
    ammonia = reaction("ammonia", "N2 + 3 H2 -> 2 NH3", [(n2, "reactant", 1), (h2, "reactant", 3), (nh3, "product", 2)])

    def variable(key, name):
        return node(f"variable/{key}", "Variable", name, scale="quantitative", quantity_kind="species_fraction", unit="%")

    v_heat = variable("thermal-share", "share of the rate due to heating")
    v_other = variable("nonthermal-share", "share of the rate due to the driving force's other effects")
    v_light = node("variable/illumination", "Variable", "illumination", scale="nominal", categories=["light", "dark"])
    v_plasma = node("variable/plasma", "Variable", "plasma", scale="nominal", categories=["on", "off"])

    def feed(key, name, components):
        fid = node(f"feed/{key}", "Feed", name, evidence=[ev("Methods", "text")])
        for sp in components:
            link("HAS_COMPONENT", fid, sp, role="reactant")
        return fid

    def sample(key, name, formula, form):
        cat = node(f"catalyst/{key}", "Catalyst", name, nominal_formula=formula, catalyst_family="metal", evidence=[ev("Table 1")])
        s = node(f"sample/{key}", "CatalystSample", f"{name}, {form}", sample_kind="film" if form == "film" else "pellet",
                 evidence=[ev("Table 1")])
        link("HAS_FORMULATION", s, cat)
        return s

    def separation(key, name, inputs, method, limitations, partition, product, heat, other, locator):
        aid = node(f"analysis/{key}", "Analysis", name, analysis_kind="thermal_contribution", partition_method=partition,
                   method=method, limitations=limitations,
                   evidence=[ev(locator, "figure", id="f")],
                   result_values=[{"id": "thermal_share", "status": "present", "value": heat, "unit": "%", "variable": v_heat,
                                   "target": product, "evidence_ids": ["f"]},
                                  {"id": "nonthermal_share", "status": "present", "value": other, "unit": "%",
                                   "variable": v_other, "target": product, "evidence_ids": ["f"]}])
        for x in inputs:
            link("HAS_INPUT", aid, x, role="data")
        return aid

    # ---- light: CO2 methanation over Ru/TiO2
    ru = sample("ru-tio2", "2 wt% Ru/TiO2", "Ru/TiO2", "film")
    co2_h2 = feed("co2-h2", "CO2/H2 = 1/4", [co2, h2])
    cell = node("instrument/photoreactor", "Reactor", "Flow photoreactor with a quartz window", reactor_kind="flow",
                evidence=[ev("Methods", "text")])
    lamp = node("instrument/xe-lamp", "LightSource", "300 W Xe lamp, AM1.5G filter", source_kind="xenon_lamp",
                spectrum="AM1.5G-filtered xenon", evidence=[ev("Methods", "text")])

    def light_test(key, name, claim, rise, locator):
        tid = node(f"test/{key}", "CatalyticTest", name, test_kind="activity", driving_forces=["photo", "thermo"],
                   experiment_kind="physical", illumination="light", heat_source="light_and_external",
                   temperature=V(250, "°C"), pressure=V(1, "bar", basis="absolute"), temperature_measured_at="catalyst_bed",
                   light_induced_temperature_rise=V(rise, "K"), irradiance=V(2.0, "W/cm2"), illuminated_area=V(1.0, "cm2"),
                   interpretations=[claim], evidence=[ev(locator, "figure")])
        link("USES_CATALYST", tid, ru, state="reduced")
        link("FED_WITH", tid, co2_h2)
        link("IN_REACTOR", tid, cell)
        link("ILLUMINATED_BY", tid, lamp, geometry="front")
        link("OF_REACTION", tid, methanation)
        return tid

    photo = light_test("light-five-irradiances", "Methanation under light at five irradiances", "photothermal_effect",
                       55, "Figure 2")
    separation("irradiance-dependence", "Rate against irradiance and catalyst temperature", [photo],
               "the rates at five irradiances against a thermal baseline, the dark rate at each light-induced catalyst "
               "temperature from an Arrhenius fit of dark rates; the rate above the baseline is the light's other effects",
               "the baseline assumes that the bed temperature the thermocouple reads is the temperature of the reacting "
               "surface; a hotter surface would put more of the rate on heating",
               "intensity_dependence", ch4, 95, 5, "Figure 2")
    nonthermal = light_test("light-surface-matched", "Methanation under light, against a surface-matched dark control",
                            "nonthermal_light_effect", 40, "Figure 3")
    dark = node("test/dark-surface-matched", "CatalyticTest", "Dark, heated to the illuminated surface temperature",
                test_kind="control", driving_forces=["thermo"], experiment_kind="physical", illumination="dark",
                temperature=V(250, "°C"), pressure=V(1, "bar", basis="absolute"), temperature_measured_at="catalyst_bed",
                evidence=[ev("Figure 3", "figure")])
    link("USES_CATALYST", dark, ru, state="reduced")
    link("FED_WITH", dark, co2_h2)
    link("IN_REACTOR", dark, cell)
    link("OF_REACTION", dark, methanation)
    link("DARK_CONTROL_FOR", dark, nonthermal, control_kind="negative", differs_in=[v_light],
         temperature_matched_by="external_heating", temperature_matched_at="illuminated_surface",
         temperature_matched_over="steady_state", temperature_difference=V(3, "K"))
    separation("dark-control-comparison", "Rate under light against the surface-matched dark rate", [nonthermal, dark],
               "the dark rate at the illuminated surface temperature, as the share of the rate under light it accounts for",
               "assumes that the surface temperature the thermal camera reads is that of the reacting surface and that the "
               "dark rate at it is the whole thermal part",
               "control_at_matched_temperature", ch4, 60, 40, "Figure 3")

    # ---- a plasma: NH3 synthesis in a packed-bed DBD
    ni = sample("ni-al2o3", "10 wt% Ni/Al2O3 beads", "Ni/Al2O3", "beads, 1-2 mm")
    n2_h2 = feed("n2-h2", "N2/H2 = 1/3", [n2, h2])
    dbd = node("instrument/dbd", "PlasmaSource", "Coaxial DBD, 3 mm gap, packed with the beads",
               discharge_kind="dielectric_barrier", configuration="in_plasma", evidence=[ev("Methods", "text")])
    beads = node("material/al2o3-beads", "Material", "Bare Al2O3 beads, 1-2 mm (the packing without Ni)",
                 evidence=[ev("Methods", "text")])
    v_active = node("variable/active-phase", "Variable", "active phase on the packing", scale="nominal", categories=["Ni", "none"])
    plasma = node("test/plasma-catalyst", "CatalyticTest", "NH3 synthesis, DBD packed with Ni/Al2O3, bed at 200 °C",
                  test_kind="activity", driving_forces=["plasma"], experiment_kind="physical",
                  interpretations=["plasma_catalyst_synergy"], temperature=V(200, "°C"),
                  pressure=V(1, "bar", basis="absolute"), excitation_frequency=V(23, "kHz"),
                  discharge_power=V(18, "W", definition="from the charge-voltage Lissajous figure"),
                  specific_energy_input=V(10.8, "kJ/L", definition="plasma power over the total flow"),
                  evidence=[ev("Table 3")])
    link("USES_CATALYST", plasma, ni, state="reduced")
    link("FED_WITH", plasma, n2_h2)
    link("USES_PLASMA", plasma, dbd)
    link("OF_REACTION", plasma, ammonia)
    bare = node("experiment/plasma-bare-packing", "Experiment", "DBD packed with bare Al2O3 beads, bed at 200 °C",
                experiment_kind="physical", goal="investigate", discharge_power=V(18, "W"),
                conditions={"temperature": V(200, "°C"), "pressure": V(1, "bar", basis="absolute")}, evidence=[ev("Table 3")])
    link("USES_PLASMA", bare, dbd)
    link("HAS_INPUT", bare, n2_h2, role="material")
    link("HAS_INPUT", bare, beads, role="material")
    link("EXAMINES", bare, ammonia)
    link("CONTROL_FOR", bare, plasma, control_kind="negative", differs_in=[v_active])
    thermal = node("test/thermal-alone", "CatalyticTest", "NH3 synthesis over Ni/Al2O3 without plasma, bed at 200 °C",
                   test_kind="control", driving_forces=["thermo"], experiment_kind="physical", temperature=V(200, "°C"),
                   pressure=V(1, "bar", basis="absolute"), temperature_measured_at="catalyst_bed", evidence=[ev("Table 3")])
    link("USES_CATALYST", thermal, ni, state="reduced")
    link("FED_WITH", thermal, n2_h2)
    link("OF_REACTION", thermal, ammonia)
    link("CONTROL_FOR", thermal, plasma, control_kind="negative", differs_in=[v_plasma])
    separation("plasma-heating", "NH3 rate in the plasma against the catalyst at the same bed temperature", [plasma, thermal],
               "the rate without plasma at the bed temperature the plasma reached, as the share of the rate in the plasma "
               "it accounts for",
               "assumes that the catalyst in the discharge is at the measured bed temperature; local heating in the "
               "filaments is not resolved, so the thermal share is a lower bound",
               "control_at_matched_temperature", nh3, 25, 75, "Table 3")

    for e in derive_reported_in(doc):
        e["props"]["origin"] = SYN
        doc["links"].append(e)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "thermal-contribution.json", thermal_contribution())
    print("wrote thermal-contribution.json")
