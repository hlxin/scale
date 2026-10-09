"""Build the five worked cases of the science kernel (synthetic; all values invented).

    python build_examples.py            # writes the five JSON documents beside this file

Each case exercises one part of the kernel:
  a  a designed series with a control, a tested hypothesis and prediction, and an independent reproduction;
  b  a computed prediction validated against a calibrated measurement (verification vs validation);
  c  a value the source states inconsistently, and its correction as a new record version;
  d  a meta-analysis with inclusion criteria, pinned input versions and a pooled estimate;
  e  an autonomous campaign: an agent proposes the next experiment from a model it re-fitted.
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
from scale.pgraph import derive_reported_in  # noqa: E402
from scale.util import write_canonical  # noqa: E402

SYN = "synthetic"
# the documents pin the schema version of the kernel-only manifest they are validated against (the schema's one version)
KERNEL_ONLY = REPO / "core/examples/science-kernel-only.yaml"
VERSION = str(__import__("yaml").safe_load(KERNEL_ONLY.read_text())["version"])


def V(value=None, unit=None, **kw) -> dict:
    v = {"status": "present", **({"value": value} if value is not None else {}), **({"unit": unit} if unit else {})}
    v.update(kw)
    return v


class Doc:
    def __init__(self, gid: str, title: str):
        self.p = gid
        self.doc = {"directed": True, "multigraph": True,
                    "graph": {"schema": "scale-graph", "schema_version": VERSION, "graph_id": f"{gid}/graph",
                              "title": title, "data_status": "synthetic_example",
                              "stewardship": {"access": "public"}},      # committed documents say so (scale check)
                    "nodes": [], "links": []}
        self.n = 0

    def node(self, rid: str, label: str, name: str, **props) -> str:
        nid = f"{self.p}/{rid}"
        self.doc["nodes"].append({"id": nid, "label": label, "props": {"name": name, "origin": SYN, **props}})
        return nid

    def link(self, typ: str, s: str, t: str, **props) -> str:
        self.n += 1
        lid = f"{self.p}/link/{self.n}"
        self.doc["links"].append({"id": lid, "source": s, "target": t, "type": typ, "props": {"origin": SYN, **props}})
        return lid

    def ev(self, src: str, locator: str, **kw) -> dict:
        return {"source": src, "locator": locator, "kind": kw.pop("kind", "text"), **kw}

    def write(self, name: str) -> None:
        for e in derive_reported_in(self.doc):
            e["props"]["origin"] = SYN
            self.doc["links"].append(e)
        write_canonical(HERE / name, self.doc)


# ---------------------------------------------------------------------------- (a)
def case_a() -> None:
    d = Doc("ex:sk-a", "Synthetic case (a): Zn-loading series with a control, a tested hypothesis and an independent reproduction")
    srcA = d.node("source/lab-a", "Source", "Lab A paper (invented)", kind="article", title="Zn loading and methanol activity (invented)", year=2021)
    srcB = d.node("source/lab-b", "Source", "Lab B paper (invented)", kind="article", title="Reproducing the Zn effect (invented)", year=2023)
    labA = d.node("org/lab-a", "Institution", "Lab A", institution_kind="university")
    labB = d.node("org/lab-b", "Institution", "Lab B", institution_kind="government_laboratory")
    rxn = d.node("object/methanol-synthesis", "ObjectOfStudy", "Methanol synthesis over Cu–Zn catalysts", object_kind="phenomenon",
                 generality="kind", scope="CO/CO2 hydrogenation at 523 K")
    q = d.node("question/zn", "Question", "Zn and activity", statement="Does Zn at Cu–Zn interfaces set the methanol-synthesis activity of Cu catalysts?")
    h1 = d.node("hypothesis/interface", "Hypothesis", "Interface sites", statement="Cu–Zn interface sites are the active sites; the rate scales with interface area.",
                hypothesis_kind="mechanistic", statistical_role="not_applicable", proposed_at="2019", hypothesis_status="supported",
                refuted_if="The space-time yield does not rise with Zn loading at constant Cu surface area.",
                evidence=[d.ev(srcA, "Introduction")])
    h2 = d.node("hypothesis/dispersion", "Hypothesis", "Dispersion only", statement="Zn only raises Cu dispersion; interface sites play no special role.",
                hypothesis_kind="competing", statistical_role="not_applicable", hypothesis_status="proposed", evidence=[d.ev(srcA, "Discussion")])
    d.link("COMPETES_WITH", h1, h2)
    d.link("ABOUT", h1, rxn)
    d.link("ABOUT", q, rxn)
    d.link("ADDRESSES", h1, q)
    vzn = d.node("variable/zn", "Variable", "Zn fraction", scale="quantitative", quantity_kind="mole_fraction", unit="mol%")
    vsty = d.node("variable/sty", "Variable", "Space-time yield", scale="quantitative", quantity_kind="space_time_yield", unit="g/(kg*h)")
    vT = d.node("variable/t", "Variable", "Temperature", scale="quantitative", quantity_kind="temperature", unit="K")
    p1 = d.node("prediction/rise", "Prediction", "STY rises with Zn", statement="The space-time yield rises with Zn loading up to about 30 mol%.",
                variable=vsty, direction="increase", proposed_at="2020-01")
    d.link("DERIVES", h1, p1)
    design = d.node("design/series", "Design", "Zn series", design_kind="one_factor", assignment_method="systematic", planned_replicates=2,
                    evidence=[d.ev(srcA, "Experimental, Table 1", kind="table")])
    d.link("ADDRESSES", design, q)
    d.link("AIMS_TO_TEST", design, h1)
    d.link("HAS_VARIABLE", design, vzn, role="factor", levels=[V(0, "mol%"), V(10, "mol%"), V(30, "mol%")])
    d.link("HAS_VARIABLE", design, vsty, role="target")
    d.link("HAS_VARIABLE", design, vT, role="controlled", levels=[V(523, "K")])
    prot = d.node("protocol/coprecipitation", "Protocol", "Co-precipitation", protocol_kind="synthesis",
                  steps=["co-precipitate nitrates with Na2CO3 at pH 7", "age 1 h", "calcine at 623 K"])
    exps = {}
    for i, zn in enumerate((0, 10, 30)):
        s = d.node(f"object/catalyst-zn{zn}", "ObjectOfStudy", f"Catalyst batch, {zn} mol% Zn", object_kind="thing",
                   generality="particular", evidence=[d.ev(srcA, "Table 1", kind="table")])
        prep = d.node(f"procedure/prep-zn{zn}", "Procedure", f"Preparation, {zn} mol% Zn", method="co-precipitation", procedure_status="completed",
                      performed_on="2021-02", evidence=[d.ev(srcA, "Experimental")])
        d.link("FOLLOWS_PROTOCOL", prep, prot)
        d.link("HAS_OUTPUT", prep, s)
        e = d.node(f"experiment/zn{zn}", "Experiment", f"Test at {zn} mol% Zn", experiment_kind="physical", manipulation="interventional",
                   approach="hypothesis_driven", goal="confirm", experiment_status="completed", performed_on="2021-03",
                   conditions={"temperature": V(523, "K", variable=vT)},
                   results={"space_time_yield": V([0.21, 0.48, 0.66][i], "g/(kg*h)", variable=vsty, uncertainty=0.02,
                                                  uncertainty_kind="standard_deviation", uncertainty_evaluation="type_a", replicates=2)},
                   evidence=[d.ev(srcA, "Table 2", kind="table")])
        d.link("PART_OF_DESIGN", e, design, experimental_unit=s, arm="control" if zn == 0 else "treatment", run_order=i + 1)
        d.link("HAS_VARIABLE", e, vzn, role="factor", level=V(zn, "mol%"))
        d.link("EXAMINES", e, s, role="catalyst", state="reduced")
        d.link("EXAMINES", e, rxn, role="reaction studied")
        d.link("PERFORMED_BY", e, labA)
        d.link("AIMS_TO_TEST", e, h1)
        exps[zn] = e
    d.link("CONTROL_FOR", exps[0], exps[30], control_kind="baseline", differs_in=[vzn])
    d.link("TESTS", exps[30], p1, outcome="supports", statistical_decision="not_applicable",
           result_refs=[{"record": exps[30], "path": "/results/space_time_yield"}, {"record": exps[0], "path": "/results/space_time_yield"}],
           warrant="The yield triples from 0 to 30 mol% Zn with temperature held at 523 K.", evidence=[d.ev(srcA, "Table 2", kind="table")])
    d.link("TESTS", exps[30], h1, outcome="supports", result_refs=[{"record": exps[30], "path": "/results/space_time_yield"}],
           warrant="The predicted rise is observed.", evidence=[d.ev(srcA, "Discussion")])
    c1 = d.node("claim/rise", "Claim", "Yield rises with Zn", statement="The space-time yield rose threefold from 0 to 30 mol% Zn at 523 K.",
                claim_kind="finding", claim_status="supported", inference_type="interventional", evidence=[d.ev(srcA, "Table 2", kind="table")])
    d.link("CONCLUDES", exps[30], c1)
    d.link("ABOUT", c1, h1)
    eB = d.node("experiment/lab-b-zn30", "Experiment", "Lab B test at 30 mol% Zn", experiment_kind="physical", manipulation="interventional",
                approach="hypothesis_driven", goal="confirm", experiment_status="completed", performed_on="2023-05",
                conditions={"temperature": V(523, "K", variable=vT)},
                results={"space_time_yield": V(0.62, "g/(kg*h)", variable=vsty, uncertainty=0.03, uncertainty_kind="standard_deviation", replicates=3)},
                evidence=[d.ev(srcB, "Table 1", kind="table")])
    d.link("PERFORMED_BY", eB, labB)
    d.link("TESTS", eB, h1, outcome="supports", result_refs=[{"record": eB, "path": "/results/space_time_yield"}], evidence=[d.ev(srcB, "Results")])
    d.link("REPLICATES", eB, exps[30], level="reproduce", changed=["sample", "team", "site"], agreement="agrees",
           criterion="Within two standard deviations.", evidence=[d.ev(srcB, "Results")])
    d.write("a-designed-series.json")


# ---------------------------------------------------------------------------- (b)
def case_b() -> None:
    d = Doc("ex:sk-b", "Synthetic case (b): a computed adsorption energy validated against a calibrated measurement")
    src = d.node("source/paper", "Source", "Invented paper", kind="article", title="Computed and measured CO adsorption (invented)", year=2024)
    ads = d.node("object/co-adsorption", "ObjectOfStudy", "CO adsorption on the close-packed facet", object_kind="phenomenon",
                 generality="kind", scope="low coverage")
    ve = d.node("variable/e-ads", "Variable", "CO adsorption energy", scale="quantitative", quantity_kind="adsorption_energy", unit="eV",
                definition="E(CO*) − E(*) − E(CO, gas), at low coverage", of=ads)
    model = d.node("model/dft", "Model", "DFT (GGA, invented)", model_kind="electronic_structure",
                   assumptions=["low coverage", "no zero-point correction"], validity_domain="low coverage on close-packed facets")
    code = d.node("software/dft-code", "Software", "a DFT code", software_kind="application", version="6.4")
    cfg = d.node("dataset/inputs", "Dataset", "Calculation inputs", data_kind="configuration", availability="available", sha256="0" * 64)
    env = d.node("dataset/environment", "Dataset", "Environment", data_kind="environment", availability="available")
    comp = d.node("experiment/dft", "Experiment", "DFT calculation", experiment_kind="computational", manipulation="interventional",
                  goal="compute", experiment_status="completed", finished_at="2024-01-10T09:00:00Z",
                  configuration=cfg, execution_environment=env, random_seed=7,
                  results={"adsorption_energy": V(-1.20, "eV", variable=ve)}, evidence=[d.ev(src, "Table 1", kind="table")])
    d.link("USES_MODEL", comp, model)
    d.link("REPRESENTS", model, ads)
    d.link("USES_SOFTWARE", comp, code, version="6.4")
    conv = d.node("experiment/convergence", "Experiment", "Convergence check", experiment_kind="computational", goal="validate",
                  experiment_status="completed", results={"energy_change": V(0.008, "eV")}, evidence=[d.ev(src, "SI, Table S2", kind="table")])
    d.link("EVALUATES", conv, comp, evaluation_kind="verification", criterion="energies change < 0.01 eV with a denser k-point mesh",
           outcome="passes", result_refs=[{"record": conv, "path": "/results/energy_change"}])
    pred = d.node("prediction/e-ads", "Prediction", "Predicted adsorption energy", variable=ve,
                  expected=V(-1.20, "eV", variable=ve, uncertainty=0.2, uncertainty_kind="plus_minus_unspecified"),
                  direction="value", proposed_at="2024-01")
    d.link("DERIVES", model, pred)
    std = d.node("object/reference-standard", "ObjectOfStudy", "Calibration standard (certified heat of reaction)", object_kind="thing",
                 generality="particular", description="A reference material with a certified enthalpy of -0.500 ± 0.002 kJ.")
    cal = d.node("experiment/calibration", "Experiment", "Calorimeter calibration", experiment_kind="physical", goal="calibrate",
                 experiment_status="completed", performed_on="2024-02")
    d.link("HAS_INPUT", cal, std, role="reference_standard")
    calorimeter = d.node("instrument/calorimeter", "Instrument", "Microcalorimeter", instrument_kind="microcalorimeter")
    d.link("CALIBRATED_BY", calorimeter, cal, valid_until="2024-12")
    meas = d.node("experiment/calorimetry", "Experiment", "Adsorption calorimetry", experiment_kind="physical", manipulation="interventional",
                  approach="hypothesis_driven", goal="validate", experiment_status="completed", started_at="2024-03-01T08:00:00Z",
                  results={"adsorption_energy": V(-1.05, "eV", variable=ve, uncertainty=0.05, uncertainty_kind="standard_uncertainty",
                                                  uncertainty_evaluation="type_a_and_b", replicates=3, calibration=cal)},
                  evidence=[d.ev(src, "Figure 3", kind="figure")])
    d.link("USES_INSTRUMENT", meas, calorimeter, role="measurement")
    d.link("EXAMINES", meas, ads, role="phenomenon measured")
    d.link("TESTS", meas, pred, outcome="supports", result_refs=[{"record": meas, "path": "/results/adsorption_energy"}],
           warrant="The measured value lies within the predicted ±0.2 eV.", evidence=[d.ev(src, "Figure 3", kind="figure")])
    d.link("EVALUATES", meas, model, evaluation_kind="validation", criterion="|ΔE| ≤ 0.2 eV", outcome="passes", scope="CO on the close-packed facet",
           result_refs=[{"record": meas, "path": "/results/adsorption_energy"}, {"record": comp, "path": "/results/adsorption_energy"}])
    d.write("b-computation-validated.json")


# ---------------------------------------------------------------------------- (c)
def case_c() -> None:
    d = Doc("ex:sk-c", "Synthetic case (c): a reference electrode stated inconsistently, then corrected")
    src = d.node("source/paper", "Source", "Invented electrochemistry paper", kind="article", title="Nitrate electrolysis on copper foil (invented)", year=2025)
    corr = d.node("source/correction", "Source", "Correction notice (invented)", kind="correction", title="Correction to: Nitrate electrolysis on copper foil", year=2026)
    obj = d.node("object/nitrate-reduction", "ObjectOfStudy", "Nitrate electroreduction on Cu", object_kind="phenomenon", generality="kind")
    vref = d.node("variable/reference", "Variable", "Reference electrode", scale="nominal",
                  categories=["Ag/AgCl, saturated KCl", "Ag/AgCl, 3 M KCl", "RHE", "SCE"])
    vpot = d.node("variable/potential", "Variable", "Applied potential", scale="quantitative", quantity_kind="electric_potential", unit="V")
    v1 = d.node("experiment/electrolysis", "Experiment", "Electrolysis at −0.9 V", experiment_kind="physical", manipulation="interventional",
                goal="investigate", experiment_status="completed", record_version=1,
                conditions={"potential": V(-0.9, "V", variable=vpot, as_reported="−0.9 V vs Ag/AgCl", evidence_ids=["methods"]),
                            "reference_electrode": {"status": "not_reported", "missing_reason": "ambiguous_in_source", "variable": vref,
                                                    "note": "‘Ag/AgCl (3 M KCl)’ (Methods) and ‘Ag/AgCl (saturated KCl)’ (Results)",
                                                    "evidence_ids": ["methods", "results"]}},
                evidence=[d.ev(src, "Methods", id="methods", quote="all potentials were read against an Ag/AgCl (3 M KCl) electrode"),
                          d.ev(src, "Results", id="results", quote="versus the Ag/AgCl (saturated KCl) reference")])
    v2 = d.node("experiment/electrolysis-v2", "Experiment", "Electrolysis at −0.9 V (corrected)", experiment_kind="physical",
                manipulation="interventional", goal="investigate", experiment_status="completed", record_version=2,
                conditions={"potential": V(-0.9, "V", variable=vpot, as_reported="−0.9 V vs Ag/AgCl"),
                            "reference_electrode": {"status": "present", "text_value": "Ag/AgCl, saturated KCl", "variable": vref,
                                                    "evidence_ids": ["correction"]}},
                evidence=[d.ev(corr, "Correction notice", id="correction", quote="every experiment used the Ag/AgCl reference filled with saturated KCl")])
    d.link("REVISES", v2, v1)
    d.link("EXAMINES", v1, obj)
    d.link("EXAMINES", v2, obj)
    c = d.node("claim/inconsistent", "Claim", "Inconsistent reference", statement="The original paper names the reference electrode inconsistently.",
               claim_kind="data_quality", claim_status="superseded", inference_type="expert_opinion", evidence=[d.ev(src, "Methods; Results")])
    d.link("ABOUT", c, v1, role="reference electrode")
    d.write("c-inconsistent-reference.json")


# ---------------------------------------------------------------------------- (d)
def case_d() -> None:
    d = Doc("ex:sk-d", "Synthetic case (d): a meta-analysis of reported turnover frequencies")
    q = d.node("question/tof", "Question", "Reported TOF", statement="What turnover frequency is reported for Cu/ZnO at 523 K?")
    pop = d.node("object/cu-zno", "ObjectOfStudy", "Cu/ZnO catalysts reported at 523 K", object_kind="population", generality="kind")
    d.link("ABOUT", q, pop)
    vtof = d.node("variable/tof", "Variable", "Turnover frequency", scale="quantitative", quantity_kind="turnover_frequency", unit="1/s", of=pop)
    design = d.node("design/meta", "Design", "Meta-analysis", design_kind="meta_analysis",
                    inclusion_criteria="Cu/ZnO catalysts; 523 K; site count by N2O titration", exclusion_criteria="conversion above 10 %")
    d.link("ADDRESSES", design, q)
    ma = d.node("experiment/meta-analysis", "Experiment", "Random-effects pooling", experiment_kind="computational", manipulation="observational",
                approach="exploratory", goal="benchmark", experiment_status="completed", method_id="STATO:0000429",
                results={"pooled_tof": V(0.012, "1/s", variable=vtof, interval_lower=0.009, interval_upper=0.016,
                                          uncertainty_kind="confidence_interval", confidence_level=0.95),
                         "heterogeneity_i2": V(41, "%")})
    d.link("PART_OF_DESIGN", ma, design)
    for i, tof in enumerate((0.010, 0.015, 0.011), start=1):
        s = d.node(f"source/s{i}", "Source", f"Study {i} (invented)", kind="article", title=f"Study {i} (invented)", year=2010 + i)
        x = d.node(f"experiment/s{i}", "Experiment", f"Reported test, study {i}", experiment_kind="physical", experiment_status="completed",
                   record_version=1, results={"tof": V(tof, "1/s", variable=vtof)}, evidence=[d.ev(s, "Table 2", kind="table")])
        d.link("HAS_INPUT", ma, x, role="data", input_version=1)
        d.link("INCLUDES", design, x)
    c = d.node("claim/pooled", "Claim", "Pooled TOF", statement="Across three studies the pooled TOF is 0.012 s⁻¹ (95 % CI 0.009–0.016).",
               claim_kind="generalization", claim_status="supported", inference_type="meta_analysis", scope="Cu/ZnO at 523 K, N2O site counting")
    d.link("CONCLUDES", ma, c)
    d.link("ABOUT", c, pop)
    d.link("SUPPORTS", ma, c, premise_refs=[{"record": ma, "path": "/results/pooled_tof"}], warrant="Pooled estimate with its interval.")
    d.write("d-meta-analysis.json")


# ---------------------------------------------------------------------------- (e)
def case_e() -> None:
    d = Doc("ex:sk-e", "Synthetic case (e): an autonomous campaign proposing its next experiment")
    q = d.node("question/optimum", "Question", "Best loading", statement="Which Zn loading maximizes the space-time yield at 523 K?")
    fam = d.node("object/cu-zn-family", "ObjectOfStudy", "Cu–Zn catalysts of varying Zn loading", object_kind="population", generality="kind")
    vzn = d.node("variable/zn", "Variable", "Zn fraction", scale="quantitative", quantity_kind="mole_fraction", unit="mol%", of=fam)
    vsty = d.node("variable/sty", "Variable", "Space-time yield", scale="quantitative", quantity_kind="space_time_yield", unit="g/(kg*h)", of=fam)
    design = d.node("design/campaign", "Design", "Adaptive campaign", design_kind="adaptive", assignment_method="adaptive",
                    stopping_criterion="STY above 1.5 g/(kg*h), or 20 iterations")
    d.link("ADDRESSES", design, q)
    d.link("HAS_VARIABLE", design, vzn, role="factor")
    d.link("HAS_VARIABLE", design, vsty, role="target")
    agent = d.node("software/planner", "Software", "Campaign planner", software_kind="agent", version="0.3")
    robot = d.node("instrument/robot", "Instrument", "Synthesis and test robot", instrument_kind="robotic platform")
    m1 = d.node("model/surrogate-v1", "Model", "Surrogate (v1)", model_kind="gaussian_process", record_version=1)
    e1 = d.node("experiment/iter1", "Experiment", "Iteration 1", experiment_kind="physical", manipulation="interventional", approach="exploratory",
                goal="investigate", experiment_status="completed", finished_at="2026-05-01T12:00:00Z",
                results={"space_time_yield": V(0.9, "g/(kg*h)", variable=vsty)})
    d.link("PART_OF_DESIGN", e1, design, iteration=1)
    d.link("HAS_VARIABLE", e1, vzn, role="factor", level=V(15, "mol%"))
    d.link("USES_INSTRUMENT", e1, robot, role="actuator")
    d.link("EXAMINES", e1, fam)
    data1 = d.node("dataset/iter1", "Dataset", "Iteration 1 data", data_kind="processed", availability="available", record_version=1)
    d.link("HAS_OUTPUT", e1, data1)
    fit = d.node("experiment/refit", "Experiment", "Re-fit surrogate", experiment_kind="computational", goal="compute",
                 experiment_status="completed", finished_at="2026-05-01T12:05:00Z")
    d.link("HAS_INPUT", fit, data1, role="training_data", input_version=1)
    d.link("HAS_INPUT", fit, m1, role="parameter", input_version=1)
    m2 = d.node("model/surrogate-v2", "Model", "Surrogate (v2)", model_kind="gaussian_process", record_version=2)
    d.link("HAS_OUTPUT", fit, m2)
    d.link("REVISES", m2, m1)
    d.link("PERFORMED_BY", fit, agent)
    pred = d.node("prediction/iter2", "Prediction", "Expected yield at 22 mol%", variable=vsty,
                  expected=V(1.3, "g/(kg*h)", variable=vsty, interval_lower=1.1, interval_upper=1.5,
                             uncertainty_kind="confidence_interval", confidence_level=0.9),
                  direction="value", proposed_at="2026-05-01")
    d.link("DERIVES", m2, pred)
    e2 = d.node("experiment/iter2", "Experiment", "Iteration 2 (planned)", experiment_kind="physical", manipulation="interventional",
                approach="hypothesis_driven", goal="investigate", experiment_status="planned")
    d.link("PART_OF_DESIGN", e2, design, iteration=2)
    d.link("HAS_VARIABLE", e2, vzn, role="factor", level=V(22, "mol%"))
    d.link("PROPOSED_BY", e2, agent, rationale="Highest expected improvement under the v2 surrogate.", acquisition_value=0.8,
           proposed_at="2026-05-01T12:06:00Z")
    d.link("AIMS_TO_TEST", e2, pred)
    d.write("e-autonomous-campaign.json")


if __name__ == "__main__":
    for f in (case_a, case_b, case_c, case_d, case_e):
        f()
    print("wrote 5 documents")
