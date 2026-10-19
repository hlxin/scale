"""Build the synthetic product-measurement example of the catalysis domain (all values invented): results that the
metric, the product, the assay, the phase and the interval identify, recorded in result_values.

    python build_examples.py

  product-measurements.json
    CO2 hydrogenation over Cu/ZnO/Al2O3       conversion 50 %, methanol yield 40 % and selectivity 80 %: three kinds that a
                                              query never mixes; a second methanol yield (38 %) by NMR of the condensate,
                                              told apart by its assay and phase; methane below the GC's detection limit;
                                              2 % of the carbon in oxygenates the source does not identify; a carbon balance
                                              of 103 ± 4 % (an analysis over both assays), kept as reported
    CO2 electroreduction on Cu, -1.0 V vs RHE  Faradaic efficiencies by GC of the headspace gas and NMR of the catholyte:
                                              CO at 30 and at 60 min (two assays, two intervals), ethanol in the liquid and
                                              in the gas (two phases), methane below the detection limit, 5 % that no
                                              product accounts for, and a charge balance of 97 %
    a repeated electrolysis                    two CO efficiencies that nothing tells apart: an ambiguous repetition,
                                              flagged and never averaged
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


def build() -> dict:
    p = "ex:pm"
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{p}/graph",
                     "title": "Product measurements: results identified by metric, product, assay, phase and interval",
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

    src = node("source/paper", "Source", "Invented paper", kind="article", year=2026,
               title="Product measurements of CO2 hydrogenation and CO2 electroreduction (invented)")

    def ev(locator, kind="table", **kw):
        return {"source": src, "locator": locator, "kind": kind, **kw}

    def species(key, formula, composition, charge=0, name=None):
        return node(f"species/{key}", "ChemicalSpecies", name or formula, formula=formula, elemental_composition=composition,
                    charge=charge)

    co2 = species("co2", "CO2", {"C": 1, "O": 2})
    h2 = species("h2", "H2", {"H": 2})
    meoh = species("methanol", "CH3OH", {"C": 1, "H": 4, "O": 1}, name="methanol")
    co = species("co", "CO", {"C": 1, "O": 1})
    ch4 = species("ch4", "CH4", {"C": 1, "H": 4})
    h2o = species("water", "H2O", {"H": 2, "O": 1})
    formate = species("formate", "HCOO-", {"C": 1, "H": 1, "O": 2}, charge=-1, name="formate")
    etoh = species("ethanol", "C2H5OH", {"C": 2, "H": 6, "O": 1}, name="ethanol")
    hp = species("proton", "H+", {"H": 1}, charge=1)
    e = species("electron", "e-", {}, charge=-1)
    dmso = species("dmso", "C2H6OS", {"C": 2, "H": 6, "O": 1, "S": 1}, name="DMSO")
    khco3 = species("khco3", "KHCO3", {"K": 1, "H": 1, "C": 1, "O": 3})

    def variable(key, name, kind):
        return node(f"variable/{key}", "Variable", name, scale="quantitative", quantity_kind=kind, unit="%")

    v_conv = variable("conversion", "CO2 conversion", "conversion")
    v_yield = variable("yield", "product yield", "product_yield")
    v_sel = variable("selectivity", "product selectivity", "selectivity")
    v_fe = variable("faradaic-efficiency", "Faradaic efficiency", "faradaic_efficiency")
    v_cb = variable("carbon-balance", "carbon balance", "balance")
    v_qb = variable("charge-balance", "charge balance", "balance")

    # ---- CO2 hydrogenation to methanol: three kinds of share, two assays, a balance
    rxn_t = node("reaction/co2-meoh", "Reaction", "CO2 + 3 H2 -> CH3OH + H2O", equation="CO2 + 3 H2 -> CH3OH + H2O",
                 balance_status="balanced", direction="reversible")
    for sp, role, coef in ((co2, "reactant", 1), (h2, "reactant", 3), (meoh, "product", 1), (h2o, "product", 1)):
        link("HAS_PARTICIPANT", rxn_t, sp, role=role, coefficient=coef)
    cat_t = node("catalyst/cu-zno", "Catalyst", "Cu/ZnO/Al2O3", nominal_formula="Cu/ZnO/Al2O3", catalyst_family="metal",
                 evidence=[ev("Table 1")])
    sample_t = node("sample/cu-zno", "CatalystSample", "Cu/ZnO/Al2O3, batch 1", sample_kind="pellet", evidence=[ev("Table 1")])
    link("HAS_FORMULATION", sample_t, cat_t)
    feed = node("feed/co2-h2", "Feed", "CO2/H2 = 1/3", evidence=[ev("Methods", "text")])
    link("HAS_COMPONENT", feed, co2, role="reactant")
    link("HAS_COMPONENT", feed, h2, role="reactant")
    reactor = node("instrument/reactor", "Reactor", "Fixed-bed flow reactor", reactor_kind="flow")

    calib = node("experiment/gc-calibration", "Characterization", "GC calibration with a certified gas mixture",
                 technique="gas chromatography", goal="calibrate", evidence=[ev("Methods", "text")])
    std_gas = node("material/calibration-gas", "Material", "Certified gas mixture: CO2, CO, CH4 and H2 in Ar",
                   evidence=[ev("Methods", "text")])
    link("HAS_INPUT", calib, std_gas, role="reference_standard")
    gc = node("assay/gc-outlet", "Characterization", "Online GC of the outlet gas, 5 h on stream",
              technique="gas chromatography (TCD and FID)", conditions={"time_on_stream": V(5, "h")},
              evidence=[ev("Methods", "text")])
    nmr = node("assay/nmr-condensate", "Characterization", "1H NMR of the condensate collected over 4-5 h on stream",
               technique="1H NMR, DMSO internal standard", conditions={"time_on_stream": V(5, "h")},
               evidence=[ev("Methods", "text")])
    link("HAS_INPUT", nmr, dmso, role="reference_standard")
    raw_gc = node("dataset/chromatograms", "Dataset", "Chromatograms of the outlet gas", data_kind="raw",
                  availability="not_reported")
    raw_nmr = node("dataset/nmr-spectra", "Dataset", "NMR spectra of the condensate", data_kind="spectrum",
                   availability="not_reported")
    link("HAS_OUTPUT", gc, raw_gc)
    link("HAS_OUTPUT", nmr, raw_nmr)
    balance_t = node("analysis/carbon-balance", "Analysis", "Carbon balance over the outlet gas and the condensate",
                     analysis_kind="balance", method="carbon in the outlet gas (GC) and in the condensate (NMR), 4-5 h on "
                     "stream, over the carbon fed", evidence=[ev("Table 2")])
    link("HAS_INPUT", balance_t, gc, role="data")
    link("HAS_INPUT", balance_t, nmr, role="data")

    gas = dict(phase="gas", stream="outlet gas", produced_by=gc, calibration=calib)
    liquid = dict(phase="liquid", stream="condensate", produced_by=nmr)
    test_t = node("test/co2-hydrogenation", "CatalyticTest", "CO2 hydrogenation at 250 °C and 3 MPa, 5 h on stream",
                  test_kind="activity", driving_forces=["thermo"], experiment_kind="physical", temperature=V(250, "°C"),
                  pressure=V(3, "MPa", basis="absolute"), time_on_stream=V(5, "h"), temperature_measured_at="catalyst_bed",
                  evidence=[ev("Table 2", id="t2_conversion"), ev("Table 2", id="t2_yield_gc"),
                            ev("Table 2", id="t2_yield_nmr"), ev("Table 2", id="t2_selectivity"),
                            ev("Table 2", id="t2_detection_limit"), ev("Table 2", id="t2_unidentified"),
                            ev("Table 2", id="t2_balance"), ev("Methods", "text", id="methods")],
                  result_values=[
                      V(50, "%", id="co2_conversion", variable=v_conv, target=co2, basis="carbon", evidence_ids=["t2_conversion"], **gas),
                      V(40, "%", id="methanol_yield_gc", variable=v_yield, target=meoh, basis="carbon",
                        evidence_ids=["t2_yield_gc"], **gas),
                      V(38, "%", id="methanol_yield_nmr", variable=v_yield, target=meoh, basis="carbon",
                        evidence_ids=["t2_yield_nmr"], **liquid),
                      V(80, "%", id="methanol_selectivity", variable=v_sel, target=meoh, basis="carbon",
                        evidence_ids=["t2_selectivity"], **gas),
                      V(18, "%", id="co_selectivity", variable=v_sel, target=co, basis="carbon", evidence_ids=["t2_selectivity"],
                        **gas),
                      {"status": "below_detection_limit", "value": 0.1, "unit": "%", "id": "ch4_selectivity",
                       "variable": v_sel, "target": ch4, "basis": "carbon", "evidence_ids": ["t2_detection_limit"], **gas},
                      V(2, "%", id="unidentified_selectivity", variable=v_sel, unresolved_target="unidentified oxygenates",
                        basis="carbon", evidence_ids=["t2_unidentified"], **liquid),
                      V(103, "%", id="carbon_balance", variable=v_cb, basis="carbon", uncertainty=4,
                        uncertainty_kind="standard_deviation", replicates=3, produced_by=balance_t,
                        definition="carbon in the outlet gas and the condensate over the carbon fed, 4-5 h on stream",
                        evidence_ids=["t2_balance"]),
                  ])
    link("USES_CATALYST", test_t, sample_t, state="reduced")
    link("FED_WITH", test_t, feed)
    link("IN_REACTOR", test_t, reactor)
    link("OF_REACTION", test_t, rxn_t)
    hyp = node("hypothesis/selective-methanol", "Hypothesis", "Cu/ZnO/Al2O3 forms methanol selectively at 250 °C",
               statement="Cu/ZnO/Al2O3 forms methanol from CO2 with a carbon selectivity above 75 % at 250 °C and 3 MPa.",
               hypothesis_kind="descriptive", evidence=[ev("Introduction", "text")])
    link("TESTS", test_t, hyp, outcome="supports",
         result_refs=[{"record": test_t, "path": "/result_values/methanol_selectivity"}])

    # ---- CO2 electroreduction on Cu: Faradaic efficiencies by phase and interval, a charge balance
    rxn_e = node("reaction/co2rr", "Reaction", "CO2 electroreduction to C1 and C2 products",
                 equation="CO2 + n H+ + n e- -> CO, HCOO-, CH4, C2H5OH", balance_status="not_checked",
                 direction="forward")
    for sp, role in ((co2, "reactant"), (hp, "reactant"), (e, "reactant"), (co, "product"), (formate, "product"),
                     (ch4, "product"), (etoh, "product")):
        link("HAS_PARTICIPANT", rxn_e, sp, role=role)
    cat_e = node("catalyst/cu", "Catalyst", "Polycrystalline Cu", nominal_formula="Cu", catalyst_family="metal",
                 evidence=[ev("Methods", "text")])
    sample_e = node("sample/cu-foil", "CatalystSample", "Cu foil", sample_kind="film", evidence=[ev("Methods", "text")])
    link("HAS_FORMULATION", sample_e, cat_e)
    electrolyte = node("electrolyte/khco3", "Electrolyte", "0.1 M KHCO3", evidence=[ev("Methods", "text")])
    link("HAS_COMPONENT", electrolyte, khco3, role="inert", concentration=V(0.1, "mol/L"))
    gc30 = node("assay/gc-30min", "Characterization", "GC of the headspace gas at 30 min", technique="gas chromatography",
                conditions={"time_on_stream": V(30, "min")}, evidence=[ev("Methods", "text")])
    gc60 = node("assay/gc-60min", "Characterization", "GC of the headspace gas at 60 min", technique="gas chromatography",
                conditions={"time_on_stream": V(60, "min")}, evidence=[ev("Methods", "text")])
    nmr_e = node("assay/nmr-catholyte", "Characterization", "1H NMR of the catholyte after 60 min",
                 technique="1H NMR, DMSO internal standard", conditions={"time_on_stream": V(60, "min")},
                 evidence=[ev("Methods", "text")])
    link("HAS_INPUT", nmr_e, dmso, role="reference_standard")
    balance_e = node("analysis/charge-balance", "Analysis", "Charge balance over the headspace gas and the catholyte",
                     analysis_kind="balance", method="the sum of the Faradaic efficiencies of the products quantified in "
                     "the headspace gas (GC at 60 min) and the catholyte (NMR), 0-60 min", evidence=[ev("Table 3")])
    link("HAS_INPUT", balance_e, gc60, role="data")
    link("HAS_INPUT", balance_e, nmr_e, role="data")
    head = dict(phase="gas", stream="headspace")
    cath = dict(phase="liquid", stream="catholyte", produced_by=nmr_e)
    ids = ["t3_co", "t3_h2", "t3_gas", "t3_liquid", "t3_rest", "t3_balance"]
    test_e = node("test/co2rr", "CatalyticTest", "CO2 electroreduction on Cu at -1.0 V vs RHE, 60 min",
                  test_kind="activity", driving_forces=["electro"], experiment_kind="physical", control_mode="potentiostatic",
                  electrode_potential=V(-1.0, "V"), reference_scale="rhe", ir_compensation="applied",
                  current_density=V(-20, "mA/cm2"), current_normalization="geometric_area", temperature=V(298, "K"),
                  duration=V(60, "min"), evidence=[ev("Table 3", id=i) for i in ids],
                  result_values=[
                      V(26, "%", id="co_fe_30min", variable=v_fe, target=co, produced_by=gc30, evidence_ids=["t3_co"], **head),
                      V(24, "%", id="co_fe_60min", variable=v_fe, target=co, produced_by=gc60, evidence_ids=["t3_co"], **head),
                      V(30, "%", id="h2_fe", variable=v_fe, target=h2, produced_by=gc60, evidence_ids=["t3_h2"], **head),
                      {"status": "below_detection_limit", "value": 0.5, "unit": "%", "id": "ch4_fe", "variable": v_fe,
                       "target": ch4, "produced_by": gc60, "evidence_ids": ["t3_gas"], **head},
                      V(2, "%", id="ethanol_fe_gas", variable=v_fe, target=etoh, produced_by=gc60, evidence_ids=["t3_gas"],
                        **head),
                      V(15, "%", id="formate_fe", variable=v_fe, target=formate, evidence_ids=["t3_liquid"], **cath),
                      V(20, "%", id="ethanol_fe_liquid", variable=v_fe, target=etoh, evidence_ids=["t3_liquid"], **cath),
                      V(5, "%", id="unassigned_fe", variable=v_fe, unresolved_target="charge no quantified product accounts for",
                        produced_by=balance_e, evidence_ids=["t3_rest"]),
                      V(97, "%", id="charge_balance", variable=v_qb, basis="charge", produced_by=balance_e,
                        definition="the sum of the Faradaic efficiencies of the products quantified, 0-60 min",
                        evidence_ids=["t3_balance"]),
                  ])
    link("USES_CATALYST", test_e, sample_e, state="as_prepared")
    link("IN_ELECTROLYTE", test_e, electrolyte)
    link("OF_REACTION", test_e, rxn_e)

    # ---- a repeated electrolysis whose two CO efficiencies nothing tells apart
    test_r = node("test/co2rr-repeat", "CatalyticTest", "CO2 electroreduction on Cu at -1.0 V vs RHE, repeated",
                  test_kind="activity", driving_forces=["electro"], experiment_kind="physical", control_mode="potentiostatic",
                  electrode_potential=V(-1.0, "V"), reference_scale="rhe", current_normalization="geometric_area",
                  evidence=[ev("Table S4", id="s4_first"), ev("Table S4", id="s4_second")],
                  result_values=[
                      V(27, "%", id="co_fe_a", variable=v_fe, target=co, evidence_ids=["s4_first"], **head),
                      V(19, "%", id="co_fe_b", variable=v_fe, target=co, evidence_ids=["s4_second"], **head),
                  ])
    link("USES_CATALYST", test_r, sample_e, state="as_prepared")
    link("IN_ELECTROLYTE", test_r, electrolyte)
    link("OF_REACTION", test_r, rxn_e)
    for e_ in derive_reported_in(doc):
        e_["props"]["origin"] = SYN
        doc["links"].append(e_)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "product-measurements.json", build())
    print("wrote product-measurements.json")
