"""Build the synthetic agentic-campaign example of the catalysis domain (all values invented): a campaign in which an
agent chooses the next catalysts to test, recorded with what TRACE-AI asks of its workflow (Xin et al., Chem Catal.
2026, doi:10.1016/j.checat.2026.101755), and the checks a person made of the records' curation.

    python build_examples.py

  self-driving-campaign.json
    the campaign             a Design of kind adaptive: its level of autonomy (A2, a person approves each run), its
                             human oversight and interventions, the agent's policy and objectives, its safety bounds and
                             measures, its stopping criterion and why it stopped, what was done with failed runs and
                             what was excluded
    the runs                 three CO2-to-methanol tests over Cu-Zn-Al catalysts, each PART_OF_DESIGN with its round and
                             PROPOSED_BY the agent with what the operator decided (approved; modified, the temperature
                             lowered; approved, then aborted by a pressure alarm), and a fourth proposal the operator
                             rejected, which never ran
    the surrogate            a Gaussian-process model with its version, architecture, hyperparameters, training
                             objective, uncertainty method (calibrated, used by the acquisition function) and the
                             descriptor it reads; fitted to the campaign's table (located, licensed, assembled by a
                             versioned script), and validated twice: grouped by composition family with the spread of its
                             error, and with random folds, whose lower error the source reports as a single number
                             (random folds mix runs of one family: what a grouped split rules out)
    executable artifacts     the notebook that reruns the fit and the container image it needs
    curation                 the records curated by an extraction agent (autonomy level A3 of the curation) and checked
                             by a person against the source: a sample and the flagged records, with the fields checked,
                             wrong and missed, the outcome, and a warning acknowledged (context the schema cannot express
                             yet, kept in unmodeled)
"""

from __future__ import annotations

import hashlib
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


def sha(name: str) -> str:
    """An invented digest (the files are invented too), stable from build to build."""
    return hashlib.sha256(f"invented file: {name}".encode()).hexdigest()


def self_driving_campaign() -> dict:
    p = "ex:sdl"
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{p}/graph",
                     "title": "An agentic campaign recorded as TRACE-AI asks, and the checks made of its curation "
                              "(synthetic)",
                     "data_status": "synthetic_example", "follows_domains": ["catalysis"]},
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
                 title="Closed-loop optimization of Cu-Zn-Al catalysts for CO2 hydrogenation to methanol (invented)")

    def ev(locator, kind="text", **kw):
        return {"source": paper, "locator": locator, "kind": kind, **kw}

    # ---- the chemistry the runs share
    def species(key, formula, composition):
        return node(f"species/{key}", "ChemicalSpecies", formula, formula=formula, elemental_composition=composition,
                    charge=0)

    co2, h2 = species("co2", "CO2", {"C": 1, "O": 2}), species("h2", "H2", {"H": 2})
    meoh, h2o = species("methanol", "CH3OH", {"C": 1, "H": 4, "O": 1}), species("h2o", "H2O", {"H": 2, "O": 1})
    rxn = node("reaction/co2-to-methanol", "Reaction", "CO2 + 3 H2 -> CH3OH + H2O", equation="CO2 + 3 H2 -> CH3OH + H2O",
               balance_status="balanced", direction="forward")
    for sp, role, coef in ((co2, "reactant", 1), (h2, "reactant", 3), (meoh, "product", 1), (h2o, "product", 1)):
        link("HAS_PARTICIPANT", rxn, sp, role=role, coefficient=coef)
    feed = node("feed/h2-co2", "Feed", "H2/CO2 = 3", ratios={"h2_to_co2": V(3, "1", basis="molar")},
                evidence=[ev("Methods, catalytic testing")])
    for sp in (co2, h2):
        link("HAS_COMPONENT", feed, sp, role="reactant")
    reactor = node("instrument/parallel-reactor", "Reactor", "Parallel fixed-bed reactor, 16 channels",
                   reactor_kind="fixed_bed", evidence=[ev("Methods, catalytic testing")])

    def catalyst(key, cu, zn):
        cat = node(f"catalyst/{key}", "Catalyst", f"Cu{cu}Zn{zn}Al10 (molar, metals basis)",
                   nominal_formula=f"Cu{cu}Zn{zn}Al10Ox", catalyst_family="mixed_oxide", evidence=[ev("Table 1", "table")])
        sample = node(f"sample/{key}", "CatalystSample", f"Cu{cu}Zn{zn}Al10, coprecipitated by the robot",
                      sample_kind="powder", evidence=[ev("Table 1", "table")])
        link("HAS_FORMULATION", sample, cat)
        return sample

    # ---- the agent, its policy and the campaign
    agent = node("software/bo-agent", "Software", "the campaign's optimization agent", software_kind="agent",
                 version="2.1.0", repository="https://example.org/invented/bo-agent", evidence=[ev("Methods, agent")])
    v_temp = node("variable/reactor-temperature", "Variable", "reactor temperature", scale="quantitative", unit="°C",
                  quantity_kind="temperature")
    v_pres = node("variable/reactor-pressure", "Variable", "reactor pressure", scale="quantitative", unit="bar",
                  quantity_kind="pressure")
    v_mae = node("variable/sty-mae", "Variable", "mean absolute error of the predicted space-time yield",
                 scale="quantitative", unit="g/(g h)", quantity_kind="mean_absolute_error")
    design = node(
        "design/campaign", "Design", "Bayesian optimization of Cu-Zn-Al composition and temperature, four rounds",
        design_kind="adaptive", assignment_method="adaptive", autonomy_level="A2",
        human_oversight="An operator approved, changed or rejected every proposed run before the robot made and tested "
                        "it, and could stop the campaign at any round.",
        interventions=["Round 2: the operator lowered a proposed 290 °C to 270 °C, the upper end of the furnace's "
                       "calibrated range; the agent was told the run's actual temperature.",
                       "Round 3: the operator rejected a proposal of 85 % Cu, outside the compositions the robot can "
                       "coprecipitate.",
                       "Round 3: a pressure alarm aborted one run; the operator kept it out of the fit."],
        intervention_count=V(3, "1"),
        agent_policy="Bayesian optimization with a Gaussian-process surrogate and expected improvement, two runs per "
                     "round, the first round chosen by Latin hypercube sampling with seed 5.",
        objectives="Maximize the methanol space-time yield at 30 bar; one objective.",
        safety_bounds=[V(300, "°C", bound="upper", variable=v_temp), V(50, "bar", bound="upper", basis="absolute",
                                                                    variable=v_pres)],
        safety_measures="The robot refuses set points beyond the bounds; a pressure or temperature alarm, a gas leak or a "
                        "lost connection to the agent shuts the reactor down and stops the round.",
        stopping_criterion="Four rounds, or an expected improvement below 0.01 g/(g h) for two rounds.",
        stop_reason="The four rounds the budget allowed were run.",
        negative_results_policy="Every run is reported, the aborted one included, with its reason; aborted runs are "
                                "left out of the surrogate's training data.",
        exclusion_criteria="Runs aborted by an alarm.", excluded_count=V(1, "1"),
        post_hoc_changes="None reported.",
        unmodeled=["the robot's liquid-handling tolerance before each round (2 %, Methods)"],
        evidence=[ev("Methods, agent"), ev("Figure 2", "figure")])

    def run(key, name, rnd, order, sample, temp, sty, decision, status="completed", **kw):
        tid = node(f"test/{key}", "CatalyticTest", name, test_kind="activity", driving_forces=["thermo"],
                   experiment_kind="physical", experiment_status=status, temperature=V(temp, "°C"),
                   pressure=V(30, "bar", basis="absolute"), temperature_measured_at="catalyst_bed",
                   space_velocity=V(12000, "mL/(g h)"),
                   **({"space_time_yield": V(sty, "g/(g h)", target=meoh)} if sty is not None else {}),
                   evidence=[ev("Table 2", "table")], **kw)
        link("USES_CATALYST", tid, sample, state="reduced")
        link("FED_WITH", tid, feed)
        link("IN_REACTOR", tid, reactor)
        link("OF_REACTION", tid, rxn)
        link("PART_OF_DESIGN", tid, design, iteration=rnd, run_order=order)
        link("PROPOSED_BY", tid, agent, human_decision=decision, acquisition_value=round(0.4 / order, 3),
             proposed_at=f"2026-03-{order + 1:02d}T09:00:00Z", evidence=[ev("Supplementary Table 3", "table")])
        return tid

    s1, s2, s3 = catalyst("cu60zn30", 60, 30), catalyst("cu70zn20", 70, 20), catalyst("cu50zn40", 50, 40)
    r1 = run("round-1", "Cu60Zn30Al10, 250 °C (round 1)", 1, 1, s1, 250, 0.42, "approved")
    r2 = run("round-2", "Cu70Zn20Al10, 270 °C (round 2; proposed at 290 °C)", 2, 2, s2, 270, 0.55, "modified")
    r3 = run("round-3", "Cu50Zn40Al10, 260 °C (round 3; aborted)", 3, 3, s3, 260, None, "approved", status="aborted",
             note="A pressure alarm stopped the run after 20 min.")
    rejected = node("experiment/round-3-rejected", "Experiment", "Cu85Zn5Al10, 280 °C (round 3; rejected, never run)",
                    experiment_kind="physical", experiment_status="proposed", evidence=[ev("Supplementary Table 3", "table")])
    link("PART_OF_DESIGN", rejected, design, iteration=3, run_order=4)
    link("PROPOSED_BY", rejected, agent, human_decision="rejected", acquisition_value=0.31,
         rationale="outside the compositions the robot can coprecipitate", proposed_at="2026-03-04T09:00:00Z",
         evidence=[ev("Supplementary Table 3", "table")])

    # ---- the data, the surrogate, its fit and its validations
    table = node("dataset/campaign-runs", "Dataset", "the campaign's runs, one row each", data_kind="table",
                 availability="available", uri="https://example.org/invented/campaign-runs.csv",
                 sha256=sha("campaign-runs.csv"), licence="CC-BY-4.0 (invented)", version="1",
                 evidence=[ev("Data availability")])
    script = node("software/assembly-script", "Software", "the script that assembles the runs into one table",
                  software_kind="application", version="1.0.3", repository="https://example.org/invented/campaign-tools",
                  evidence=[ev("Code availability")])
    env = node("dataset/container", "Dataset", "container image the fit and the notebook run in",
               data_kind="environment", availability="available", uri="https://example.org/invented/container",
               sha256=sha("container"), version="2026.03", evidence=[ev("Code availability")])
    notebook = node("dataset/notebook", "Dataset", "notebook that refits the surrogate and redraws Figure 3",
                    data_kind="notebook", availability="available", uri="https://example.org/invented/refit.ipynb",
                    sha256=sha("refit.ipynb"), version="1.2", evidence=[ev("Code availability")])
    assembly = node("experiment/assembly", "Experiment", "assembling the campaign's runs into one table",
                    experiment_kind="computational", goal="compute", execution_environment=env,
                    evidence=[ev("Methods, data")])
    for r in (r1, r2, r3):
        link("HAS_INPUT", assembly, r, role="data")
    link("HAS_OUTPUT", assembly, table)
    link("USES_SOFTWARE", assembly, script)
    cu_frac = node("descriptor/cu-fraction", "Descriptor", "molar Cu fraction (metals basis)",
                   quantity_kind="composition_fraction", definition="Cu over Cu + Zn + Al, molar",
                   evidence=[ev("Methods, surrogate")])
    gp = node("model/gp-surrogate", "Model", "Gaussian-process surrogate of the space-time yield",
              model_kind="Gaussian-process regression", version="round-3",
              architecture="A Gaussian process with a Matern 5/2 kernel on the Cu and Zn fractions and the temperature, "
                           "scaled to 0-1, and a white-noise term.",
              hyperparameters={"length_scale": V(0.15, "1", definition="the kernel's, on the scaled inputs"),
                               "noise_level": V(0.02, "1", definition="as a share of the yield's range")},
              training_objective="Maximum marginal likelihood of the campaign's completed runs.",
              uncertainty_method="gaussian_process", uncertainty_components="both_separately",
              uncertainty_calibration="91 % of held-out yields fell inside the 95 % predictive interval in the grouped "
                                      "cross-validation.",
              uncertainty_use="Expected improvement chose each round's runs; a proposal whose predictive standard "
                              "deviation exceeded 0.2 g/(g h) was flagged for the operator.",
              validity_domain="Cu 40-80 %, Zn 10-50 %, Al 10 % (molar, metals basis), 230-300 °C, 30 bar, H2/CO2 = 3.",
              evidence=[ev("Methods, surrogate")])
    link("USES_DESCRIPTOR", gp, cu_frac)
    fit = node("experiment/gp-fit", "Experiment", "fitting the surrogate to the completed runs of rounds 1-3",
               experiment_kind="computational", goal="calibrate", execution_environment=env,
               evidence=[ev("Methods, surrogate")])
    link("EVALUATES", fit, gp, evaluation_kind="calibration", evidence=[ev("Methods, surrogate")])
    link("HAS_INPUT", fit, table, role="training_data")

    def validation(key, name, split, mae, **kw):
        unc = {k: kw.pop(k) for k in ("uncertainty", "uncertainty_kind") if k in kw}
        vid = node(f"experiment/{key}", "Experiment", name, experiment_kind="computational", goal="validate",
                   execution_environment=env, evidence=[ev("Table 3", "table", id=f"mae_{key}")],
                   result_values=[{"id": "mae", "status": "present", "value": mae, "unit": "g/(g h)", "variable": v_mae,
                                   "evidence_ids": [f"mae_{key}"], **unc}])
        link("HAS_INPUT", vid, table, role="validation_data")
        link("EVALUATES", vid, gp, evaluation_kind="validation", outcome="passes", criterion="MAE below 0.25 g/(g h)",
             split_strategy=split, result_refs=[{"record": vid, "path": "/result_values/mae"}],
             evidence=[ev("Table 3", "table")], **kw)
        return vid

    validation("gp-grouped-cv", "five-fold cross-validation, one composition family per fold", "grouped", 0.21,
               uncertainty=0.05, uncertainty_kind="standard_deviation",
               grouped_by="composition family (the Cu:Zn ratio)", folds=5, split_seed=11,
               preprocessing_within_split=True, generalization="local_extrapolation")
    validation("gp-random-cv", "five-fold cross-validation with random folds", "random", 0.12, folds=5, split_seed=11)
    pred = node("computation/round-4-predictions", "Computation", "the surrogate's predictions for round 4",
                computation_kind="machine_learned", task="predicting the space-time yield of untested compositions",
                execution_environment=env, evidence=[ev("Figure 3", "figure")])
    link("USES_MODEL", pred, gp)
    link("USES_SOFTWARE", pred, agent)

    # ---- how the records were curated, and the check a person made of them
    extractor = node("software/extraction-agent", "Software", "the agent that extracted these records",
                     software_kind="agent", version="0.4.0")
    checker = node("person/checker", "Person", "Invented checker")
    doc["graph"]["stewardship"] = {"access": "public", "curated_by": [extractor], "autonomy_level": "A3"}
    doc["graph"]["checks"] = [{
        "checked_by": checker, "checked_on": "2026-10-21",
        "records": [design, r1, r2, r3, gp, f"{p}/experiment/gp-grouped-cv"],
        "selection": "sample_and_flagged", "fraction": 0.3, "seed": 3,
        "scope": "each value, unit, locator and quote of the records against the invented paper (Methods, Tables 1-3, "
                 "Supplementary Table 3)",
        "fields_checked": 46, "fields_wrong": 1, "fields_missed": 2, "tolerance": "the digits printed",
        "outcome": "corrected",
        "acknowledged": [{"record": design, "warning": "unmodeled context: the robot's liquid-handling tolerance",
                          "reason": "the source states it, and the schema has no place for a dispensing tolerance yet; "
                                    "kept in unmodeled and raised as a gap"}],
        "note": "Round 2's pressure had been read as gauge; the paper gives absolute pressures, and it was corrected. Two "
                "space velocities were missing and were added."}]
    for e in derive_reported_in(doc):
        e["props"]["origin"] = SYN
        doc["links"].append(e)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "self-driving-campaign.json", self_driving_campaign())
    print("wrote self-driving-campaign.json")
