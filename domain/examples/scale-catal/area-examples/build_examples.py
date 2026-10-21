"""Build the synthetic examples of four areas of catalysis research (all values invented): an enzyme test, a homogeneous
test, two transport checks and two electrolysis tests, each recording what the areas need that the catalysis vocabulary
lacked before 0.7.1 (Ontologies4Cat's areas; docs/mappings.md).

    python build_examples.py

  catalysis-areas.json
    biocatalysis          an alcohol dehydrogenase (EC 1.1.1.1) immobilized on silica: a Catalyst of family enzyme, the
                          enzyme a macromolecule; the reaction mixture with its substrate, its cofactor (NAD+) and its
                          solvent (a phosphate buffer in water), at a stated pH; the specific activity (U/mg) and the
                          activity of the whole charge (U), and a Michaelis constant for ethanol from a fit of rates
    homogeneous           1-octene hydrogenation by a rhodium phosphine complex in toluene, with added triphenylphosphine
                          (ligand): a turnover number, apart from a turnover frequency
    transport checks      ethylene hydrogenation over Pd/Al2O3, two checks: a Weisz-Prater and a Mears criterion, an
                          effectiveness factor and a Thiele modulus (one check finds no limitation, the other a
                          limitation in larger particles); a criterion whose definition names none (left out of a
                          comparison as missing_context)
    energy                CO2 electrolysis to CO in a flow cell: the electrical energy per mole of CO and per kilogram of
                          CO (two quantities, kept apart by their units), and the cell's energy efficiency
    how the source says it   every test states catalysis_mode as its source describes it
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


def T(text, **kw) -> dict:
    return {"status": "present", "text_value": text, **kw}


def catalysis_areas() -> dict:
    p = "ex:ca"
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{p}/graph",
                     "title": "An enzyme, a homogeneous catalyst, transport checks and the energy of an electrolysis, each "
                              "with what its area of catalysis needs (synthetic)",
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

    def source(key, title):
        return node(f"source/{key}", "Source", f"Invented paper ({key})", kind="article", year=2026, title=title)

    bio = source("enzyme", "Ethanol oxidation by an alcohol dehydrogenase immobilized on silica (invented)")
    homog = source("homogeneous", "Hydrogenation of 1-octene with a rhodium phosphine complex (invented)")
    transport = source("transport", "Ethylene hydrogenation over Pd/Al2O3, with and without transport limitation (invented)")
    energy = source("energy", "CO2 electrolysis to CO in a flow cell, and the energy it takes (invented)")

    def ev(source_id, locator, kind="table", **kw):
        return {"source": source_id, "locator": locator, "kind": kind, **kw}

    def species(key, formula, composition, charge, name=None, **props):
        stated = {k: v for k, v in (("formula", formula), ("elemental_composition", composition), ("charge", charge))
                  if v is not None}
        return node(f"species/{key}", "ChemicalSpecies", name or formula, **stated, **props)

    def variable(key, name, kind, unit, **props):
        return node(f"variable/{key}", "Variable", name, scale="quantitative", quantity_kind=kind, unit=unit, **props)

    def reaction(key, equation, src, *items):
        r = node(f"reaction/{key}", "Reaction", equation, equation=equation, balance_status="balanced", direction="forward",
                 evidence=[ev(src, "Scheme 1", "figure")])
        for sp, role, coef, phase in items:
            link("HAS_PARTICIPANT", r, sp, role=role, coefficient=coef, phase=phase)
        return r

    # ---- biocatalysis: an immobilized enzyme, its cofactor and solvent, its activity and a Michaelis constant
    ethanol = species("ethanol", "C2H6O", {"C": 2, "H": 6, "O": 1}, 0, name="ethanol")
    acetaldehyde = species("acetaldehyde", "C2H4O", {"C": 2, "H": 4, "O": 1}, 0, name="acetaldehyde")
    nad = species("nad", "C21H28N7O14P2", {"C": 21, "H": 28, "N": 7, "O": 14, "P": 2}, 1, name="NAD+", species_kind="ion")
    nadh = species("nadh", "C21H29N7O14P2", {"C": 21, "H": 29, "N": 7, "O": 14, "P": 2}, 0, name="NADH")
    proton = species("proton", "H+", {"H": 1}, 1, species_kind="ion")
    water = species("water", "H2O", {"H": 2, "O": 1}, 0, name="water")
    adh = species("adh", None, None, None, name="alcohol dehydrogenase (yeast)", species_kind="macromolecule",
                  identifiers={"ec": "1.1.1.1"})
    silica = node("material/silica", "Material", "mesoporous silica", formula="SiO2", material_family="oxide",
                  crystallinity="amorphous")
    adh_cat = node("catalyst/adh-silica", "Catalyst", "ADH immobilized on mesoporous silica", catalyst_family="enzyme",
                   nominal_formula="ADH/SiO2", evidence=[ev(bio, "Section 2.1", "text")])
    link("HAS_COMPONENT", adh_cat, adh, role="active_component", loading=V(48, "mg/g"))
    link("HAS_COMPONENT", adh_cat, silica, role="support")
    adh_sample = node("sample/adh-silica-batch", "CatalystSample", "ADH/SiO2 batch", sample_kind="batch",
                      batch_identifier="B-1")
    link("HAS_FORMULATION", adh_sample, adh_cat)
    ox = reaction("ethanol-oxidation", "C2H6O + NAD+ -> C2H4O + NADH + H+", bio, (ethanol, "reactant", 1, "liquid"),
                  (nad, "reactant", 1, "liquid"), (acetaldehyde, "product", 1, "liquid"), (nadh, "product", 1, "liquid"),
                  (proton, "product", 1, "liquid"))
    mixture = node("feed/assay-mixture", "Feed", "assay mixture: ethanol and NAD+ in phosphate buffer",
                   evidence=[ev(bio, "Section 2.3", "text")])
    link("HAS_COMPONENT", mixture, ethanol, role="reactant", concentration=V(50, "mmol/L"))
    link("HAS_COMPONENT", mixture, nad, role="cofactor", concentration=V(2, "mmol/L"))
    link("HAS_COMPONENT", mixture, water, role="solvent", role_detail="phosphate buffer, 50 mM")
    stirred = node("reactor/stirred-vial", "Reactor", "stirred glass vial", reactor_kind="batch", volume=V(5, "mL"))
    v_sa = variable("specific-activity", "specific activity of the immobilized ADH", "enzyme_activity", "U/mg")
    v_ua = variable("activity", "activity of the immobilized ADH in the assay", "enzyme_activity", "U")
    v_km = variable("km-ethanol", "Michaelis constant for ethanol", "michaelis_constant", "mmol/L")
    assay = node("test/adh-assay", "CatalyticTest", "ADH/SiO2 activity assay at 30 °C", test_kind="activity",
                 catalysis_mode="biocatalytic", driving_forces=["thermo"], experiment_kind="physical",
                 temperature=V(30, "°C"), pressure=V(1, "atm", basis="absolute"), duration=V(10, "min"),
                 conditions={"pH": V(7.5, "1", definition="pH of the assay mixture (phosphate buffer)",
                                     evidence_ids=["s23"])},
                 result_values=[V(12.5, "U/mg", id="specific_activity", variable=v_sa, target=ethanol,
                                  definition="micromoles of ethanol oxidized per minute per milligram of immobilized enzyme",
                                  evidence_ids=["t1_activity"]),
                                V(0.6, "U", id="activity", variable=v_ua, target=ethanol, evidence_ids=["t1_activity"])],
                 evidence=[ev(bio, "Section 2.3", "text", id="s23"), ev(bio, "Table 1", id="t1_activity")])
    link("USES_CATALYST", assay, adh_sample, amount=V(48, "µg"))
    link("FED_WITH", assay, mixture)
    link("IN_REACTOR", assay, stirred)
    link("OF_REACTION", assay, ox)
    mm = node("model/michaelis-menten", "Model", "Michaelis-Menten rate law", model_kind="rate law",
              equations=["r = r_max c / (Km + c)"], evidence=[ev(bio, "Figure 3", "figure")])
    km_fit = node("analysis/michaelis-menten-fit", "Analysis", "Michaelis-Menten fit of initial rates against ethanol",
                  analysis_kind="kinetic_fit", method="non-linear least squares of initial rates, 0.5-50 mM ethanol",
                  temperature=V(30, "°C"),
                  result_values=[V(1.8, "mmol/L", id="km_ethanol", variable=v_km, target=ethanol, uncertainty=0.2,
                                   uncertainty_kind="standard_error", evidence_ids=["f3_fit"])],
                  evidence=[ev(bio, "Figure 3", "figure", id="f3_fit")])
    link("USES_MODEL", km_fit, mm)
    link("HAS_INPUT", km_fit, assay, role="data")
    link("OF_REACTION", km_fit, ox)

    # ---- homogeneous catalysis: a complex, an added ligand, a solvent, a turnover number
    octene = species("1-octene", "C8H16", {"C": 8, "H": 16}, 0, name="1-octene")
    octane = species("octane", "C8H18", {"C": 8, "H": 18}, 0, name="octane")
    h2 = species("h2", "H2", {"H": 2}, 0, name="hydrogen")
    toluene = species("toluene", "C7H8", {"C": 7, "H": 8}, 0, name="toluene")
    pph3 = species("pph3", "C18H15P", {"C": 18, "H": 15, "P": 1}, 0, name="triphenylphosphine")
    rh_complex = species("rh-complex", "C54H45ClP3Rh", {"C": 54, "H": 45, "Cl": 1, "P": 3, "Rh": 1}, 0,
                         name="chloridotris(triphenylphosphine)rhodium(I)")
    rh_cat = node("catalyst/rh-pph3", "Catalyst", "RhCl(PPh3)3 with added PPh3", catalyst_family="molecular_complex",
                  nominal_formula="RhCl(PPh3)3 + 2 PPh3", evidence=[ev(homog, "Section 2", "text")])
    link("HAS_COMPONENT", rh_cat, rh_complex, role="active_component")
    link("HAS_COMPONENT", rh_cat, pph3, role="ligand", fraction=V(2, "1", basis="relative_to_component",
                                                                     definition="mol PPh3 added per mol Rh"),
         relative_to=rh_complex)
    rh_sample = node("sample/rh-pph3-batch", "CatalystSample", "RhCl(PPh3)3 as received", sample_kind="powder")
    link("HAS_FORMULATION", rh_sample, rh_cat)
    hyd = reaction("octene-hydrogenation", "C8H16 + H2 -> C8H18", homog, (octene, "reactant", 1, "liquid"),
                   (h2, "reactant", 1, "gas"), (octane, "product", 1, "liquid"))
    homog_feed = node("feed/octene-in-toluene", "Feed", "1-octene in toluene under hydrogen")
    link("HAS_COMPONENT", homog_feed, octene, role="reactant", concentration=V(0.5, "mol/L"))
    link("HAS_COMPONENT", homog_feed, toluene, role="solvent")
    link("HAS_COMPONENT", homog_feed, h2, role="reactant")
    autoclave = node("reactor/autoclave", "Reactor", "glass autoclave", reactor_kind="stirred_tank")
    v_ton = variable("ton-octane", "turnover number to octane", "turnover_number", "1")
    v_conv = variable("octene-conversion", "conversion of 1-octene", "conversion", "%")
    rh_test = node("test/rh-hydrogenation", "CatalyticTest", "1-octene hydrogenation, 25 °C, 1 bar H2", test_kind="activity",
                   catalysis_mode="homogeneous", driving_forces=["thermo"], experiment_kind="physical",
                   temperature=V(25, "°C"), pressure=V(1, "bar", basis="absolute"), duration=V(2, "h"),
                   result_values=[V(950, "1", id="ton", variable=v_ton, target=octane,
                                    definition="mol octane formed per mol Rh charged, after 2 h", evidence_ids=["t2"]),
                                  V(95, "%", id="conversion", variable=v_conv, target=octene, evidence_ids=["t2"])],
                   evidence=[ev(homog, "Table 2", id="t2")])
    link("USES_CATALYST", rh_test, rh_sample, amount=V(0.1, "mol%"))
    link("FED_WITH", rh_test, homog_feed)
    link("IN_REACTOR", rh_test, autoclave)
    link("OF_REACTION", rh_test, hyd)

    # ---- heat, transport and kinetic data: criteria, an effectiveness factor and a Thiele modulus
    ethylene = species("ethylene", "C2H4", {"C": 2, "H": 4}, 0, name="ethylene")
    ethane = species("ethane", "C2H6", {"C": 2, "H": 6}, 0, name="ethane")
    eh = reaction("ethylene-hydrogenation", "C2H4 + H2 -> C2H6", transport, (ethylene, "reactant", 1, "gas"),
                  (h2, "reactant", 1, "gas"), (ethane, "product", 1, "gas"))
    pd = node("catalyst/pd-alumina", "Catalyst", "1 wt% Pd/Al2O3", catalyst_family="metal", nominal_formula="Pd/Al2O3")
    eh_feed = node("feed/ethylene-hydrogen", "Feed", "2% ethylene and 20% hydrogen in helium")
    link("HAS_COMPONENT", eh_feed, ethylene, role="reactant", fraction=V(2, "mol%"))
    link("HAS_COMPONENT", eh_feed, h2, role="reactant", fraction=V(20, "mol%"))
    helium = species("helium", "He", {"He": 1}, 0, name="helium", species_kind="atom")
    link("HAS_COMPONENT", eh_feed, helium, role="diluent")
    v_crit = variable("transport-criterion", "transport criterion", "transport_criterion", "1")
    v_eta = variable("effectiveness-factor", "effectiveness factor", "effectiveness_factor", "1")
    v_phi = variable("thiele-modulus", "Thiele modulus", "thiele_modulus", "1")
    v_rate = variable("ethane-rate", "rate of ethane formation", "production_rate", "µmol/(g s)")
    checks = []
    for key, size, rate, wp, mears, eta, phi, verdict in (
            ("fine", "75-150 µm", 3.2, 0.04, 0.002, 0.99, 0.2, "no transport limitation"),
            ("coarse", "1-2 mm", 2.1, 2.6, 0.03, 0.62, 2.3, "pore diffusion limits the rate in the larger particles")):
        sample = node(f"sample/pd-alumina-{key}", "CatalystSample", f"Pd/Al2O3, {size} particles", sample_kind="granules")
        link("HAS_FORMULATION", sample, pd)
        t = node(f"test/ethylene-hydrogenation-{key}", "CatalyticTest", f"ethylene hydrogenation at 350 K, {size}",
                 test_kind="kinetics", catalysis_mode="heterogeneous", driving_forces=["thermo"],
                 experiment_kind="physical", temperature=V(350, "K"), pressure=V(1, "bar", basis="absolute"),
                 result_values=[V(rate, "µmol/(g s)", id="ethane_rate", variable=v_rate, target=ethane,
                                  evidence_ids=[f"t1_{key}"])],
                 evidence=[ev(transport, "Table 1", id=f"t1_{key}")])
        link("USES_CATALYST", t, sample)
        link("FED_WITH", t, eh_feed)
        link("OF_REACTION", t, eh)
        check = node(f"analysis/transport-{key}", "Analysis", f"transport check, {size}", analysis_kind="transport_check",
                     evaluation_basis="numerical", method="Weisz-Prater and Mears criteria from the rate at 350 K",
                     verdict=verdict, temperature=V(350, "K"),
                     result_values=[V(wp, "1", id="weisz_prater", variable=v_crit, definition="Weisz-Prater criterion",
                                      evidence_ids=[f"s4_{key}"]),
                                    V(mears, "1", id="mears", variable=v_crit, definition="Mears criterion",
                                      evidence_ids=[f"s4_{key}"]),
                                    V(eta, "1", id="effectiveness_factor", variable=v_eta, evidence_ids=[f"s4_{key}"]),
                                    V(phi, "1", id="thiele_modulus", variable=v_phi,
                                      definition="generalized Thiele modulus", evidence_ids=[f"s4_{key}"])],
                     evidence=[ev(transport, "Supporting information, Section S4", "text", id=f"s4_{key}")])
        link("HAS_INPUT", check, t, role="data")
        checks.append(check)
    # a criterion its source does not name: kept, but no comparison can place it
    unnamed = node("analysis/transport-unnamed", "Analysis", "transport check whose criterion is not named",
                   analysis_kind="transport_check", evaluation_basis="numerical", verdict="no transport limitation",
                   result_values=[V(0.1, "1", id="criterion", variable=v_crit, evidence_ids=["s5"])],
                   evidence=[ev(transport, "Supporting information, Section S5", "text", id="s5")])
    link("HAS_INPUT", unnamed, checks[0], role="data")

    # ---- process design, energy: the electrical energy per product, per mole and per kilogram
    co2 = species("co2", "CO2", {"C": 1, "O": 2}, 0, name="carbon dioxide")
    co = species("co", "CO", {"C": 1, "O": 1}, 0, name="carbon monoxide")
    o2 = species("o2", "O2", {"O": 2}, 0, name="oxygen")
    co2rr = reaction("co2-to-co", "2 CO2 -> 2 CO + O2", energy, (co2, "reactant", 2, "gas"), (co, "product", 2, "gas"),
                     (o2, "product", 1, "gas"))
    ag = node("catalyst/ag-gde", "Catalyst", "Ag on a gas-diffusion electrode", catalyst_family="metal", nominal_formula="Ag")
    koh = species("koh", "KOH", {"K": 1, "O": 1, "H": 1}, 0, name="potassium hydroxide")
    anolyte = node("electrolyte/koh", "Electrolyte", "1 M KOH", pH=V(14, "1"))
    link("HAS_COMPONENT", anolyte, koh, role="other", role_detail="electrolyte salt", concentration=V(1, "mol/L"))
    link("HAS_COMPONENT", anolyte, water, role="solvent")
    v_e_mol = variable("energy-per-mol-co", "electrical energy per mole of CO", "energy_consumption", "kJ/mol")
    v_e_kg = variable("energy-per-kg-co", "electrical energy per kilogram of CO", "energy_consumption", "kWh/kg")
    v_eff = variable("energy-efficiency", "energy efficiency of the cell", "efficiency", "%")
    for key, current, e_mol, e_kg, eff in (("100", 100, 420, 4.2, 59), ("300", 300, 510, 5.1, 48)):
        t = node(f"test/co2-electrolysis-{key}", "CatalyticTest", f"CO2 electrolysis at {current} mA/cm2",
                 test_kind="activity", catalysis_mode="heterogeneous", driving_forces=["electro"],
                 experiment_kind="physical", temperature=V(25, "°C"), control_mode="galvanostatic",
                 result_values=[V(e_mol, "kJ/mol", id="energy_per_mol", variable=v_e_mol, target=co,
                                  definition="electrical energy into the cell per mole of CO formed",
                                  evidence_ids=[f"t3_{key}"]),
                                V(e_kg, "kWh/kg", id="energy_per_kg", variable=v_e_kg, target=co,
                                  definition="electrical energy into the cell per kilogram of CO formed",
                                  evidence_ids=[f"t3_{key}"]),
                                V(eff, "%", id="energy_efficiency", variable=v_eff, target=co,
                                  definition="energy efficiency of CO formation (thermodynamic potential times Faradaic "
                                             "efficiency over cell voltage)", evidence_ids=[f"t3_{key}"])],
                 evidence=[ev(energy, "Table 3", id=f"t3_{key}")])
        link("OF_REACTION", t, co2rr)
        link("IN_ELECTROLYTE", t, anolyte)
        sample = node(f"sample/ag-gde-{key}", "CatalystSample", f"Ag gas-diffusion electrode, run at {current} mA/cm2",
                      sample_kind="electrode")
        link("HAS_FORMULATION", sample, ag)
        link("USES_CATALYST", t, sample)

    for e in derive_reported_in(doc):
        e["props"]["origin"] = SYN
        doc["links"].append(e)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "catalysis-areas.json", catalysis_areas())
