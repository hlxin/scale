"""The science kernel: loading, the five worked cases, and a counterexample per rule."""

import copy
import json

import pytest

from conftest import CORE, EXAMPLES, REPO, spec_of
from scale.pgraph import kernel_only_spec, load_spec, validate
from scale.util import ScaleError

G = CORE / "graph"
X = CORE / "examples"
EX = X / "science-examples"
CASES = sorted(EX.glob("*.json"))
assert len(CASES) == 5, f"the five worked cases are missing from {EX}"


@pytest.fixture(scope="module")
def spec():
    return load_spec(X / "science-kernel-only.yaml")


def doc(name):
    return json.loads((EX / name).read_text())


def node(d, suffix):
    return next(n for n in d["nodes"] if n["id"].endswith(suffix))


def link(d, typ, src_suffix=None):
    return next(e for e in d["links"] if e["type"] == typ and (src_suffix is None or e["source"].endswith(src_suffix)))


def msgs(d, spec, kind="errors"):
    return [m["message"] for m in getattr(validate(d, spec), kind)]


def test_kernel_declares_the_science_labels(spec):
    assert {"Question", "Hypothesis", "Prediction", "Experiment", "Procedure", "Protocol", "Design", "Variable",
            "Claim", "ObjectOfStudy", "Operation", "Instrument", "Model", "Source", "Dataset", "Person", "Institution",
            "Project", "Software", "Method"} == set(spec["nodes"])
    assert "Activity" not in spec["nodes"] and "Activity" not in (spec.get("abstract") or {})
    assert "Sample" not in spec["nodes"]                       # physical specimens belong to the domains
    assert spec["nodes"]["ObjectOfStudy"]["properties"]["object_kind"]["values"] == ["thing", "system", "phenomenon", "population"]
    assert spec["edges"]["EXAMINES"]["to"] == ["ObjectOfStudy"]
    assert {"TESTS", "CONTROL_FOR", "REPLICATES", "EVALUATES", "HAS_VARIABLE", "PART_OF_DESIGN"} <= set(spec["edges"])
    assert all(e["module"] == "kernel" for e in spec["edges"].values())


def test_every_kernel_term_names_its_closest_external_terms():
    import yaml
    k = yaml.safe_load((G / "kernel.yaml").read_text())
    science = ("Question", "Hypothesis", "Prediction", "Experiment", "Procedure", "Protocol", "Design", "Variable", "Claim",
               "ObjectOfStudy")
    assert all(k["nodes"][lab].get("maps_to") for lab in science)


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_worked_cases_are_valid_without_warnings(path):
    """Each case under the kernel of the version it pins (the head's kernel-only manifest while it pins the head, else
    the frozen kernel of that version)."""
    d = json.loads(path.read_text())
    rep = validate(d, kernel_only_spec(REPO, d["graph"]["schema_version"]))
    assert rep.errors == [] and rep.warnings == [], (rep.errors, rep.warnings)


def test_examples_are_built_reproducibly(tmp_path):
    import shutil
    import subprocess
    import sys
    work = tmp_path / "ex"
    shutil.copytree(EX, work)
    subprocess.run([sys.executable, str(work / "build_examples.py")], check=True, capture_output=True,
                   cwd=REPO)
    # the script writes beside itself, i.e. into the copy, for the head version; the committed cases, moved to the head
    # along the registered steps (nothing, while they pin it), are what it writes
    from scale.pgraph_migrate import raise_version
    from scale.util import write_canonical
    head = load_spec(X / "science-kernel-only.yaml")
    for p in CASES:
        d = json.loads(p.read_text())
        if d["graph"]["schema_version"] != head["version"]:
            d = raise_version(d, head["version"], head)[0]
        write_canonical(tmp_path / "want.json", d)
        assert (work / p.name).read_bytes() == (tmp_path / "want.json").read_bytes(), p.name


# ---------------------------------------------------------------- loader
def test_any_inside_a_list_is_rejected(tmp_path):
    import yaml
    k = yaml.safe_load((G / "kernel.yaml").read_text())
    k["edges"]["EXAMINES"]["to"] = ["ANY"]
    (tmp_path / "k.yaml").write_text(yaml.safe_dump(k))
    man = yaml.safe_load((X / "science-kernel-only.yaml").read_text())
    man["kernel"] = "k.yaml"
    (tmp_path / "m.yaml").write_text(yaml.safe_dump(man))
    with pytest.raises(ScaleError, match="ANY must stand alone"):
        load_spec(tmp_path / "m.yaml")


def test_ref_targets_accept_subtypes_everywhere(spec):
    # value.produced_by names Experiment; after expansion it lists every label that is_a Experiment
    assert "Experiment" in spec["value"]["fields"]["produced_by"]["targets"]


# ---------------------------------------------------------------- value object
@pytest.mark.parametrize("bad,expect", [
    ({"status": "present"}, "exactly one of"),
    ({"status": "present", "value": 1, "text_value": "x", "unit": "K"}, "exactly one of"),
    ({"status": "present", "value": 1}, "needs a unit"),
    ({"status": "present", "lower": 1, "unit": "K"}, "lower and upper come together"),
    ({"status": "present", "value": 1, "lower": 0, "upper": 2, "unit": "K"}, "not both"),
    ({"status": "not_reported", "value": 1}, "carries no value"),
    ({"status": "present", "value": 1, "unit": "K", "missing_reason": "not_curated"}, "missing_reason goes only"),
    ({"status": "present", "value": 1, "unit": "K", "uncertainty": 0.1}, "needs uncertainty_kind"),
    ({"status": "present", "value": 1, "unit": "K", "uncertainty": -1, "uncertainty_kind": "standard_deviation"}, "negative"),
    ({"status": "present", "value": 1, "unit": "K", "interval_lower": 0, "uncertainty_kind": "confidence_interval",
      "confidence_level": 0.9}, "come together"),
    ({"status": "present", "value": 1, "unit": "K", "interval_lower": 0, "interval_upper": 2,
      "uncertainty_kind": "confidence_interval"}, "needs confidence_level"),
    ({"status": "present", "value": 1, "unit": "K", "uncertainty": 0.2, "uncertainty_kind": "expanded_uncertainty"},
     "coverage_factor or confidence_level"),
    ({"status": "present", "value": 1, "unit": "K", "interval_lower": 0, "interval_upper": 2,
      "uncertainty_kind": "confidence_interval", "confidence_level": 95}, "between 0 and 1"),
    ({"status": "present", "value": 1, "unit": "K", "replicates": 0}, "at least 1"),
    ({"status": "present", "value": 1, "unit": "K", "origin": "fitted"}, "produced_by"),
    ({"status": "below_quantification_limit", "unit": "K"}, "needs the limit"),
])
def test_value_object_rules(spec, bad, expect):
    d = doc("d-meta-analysis.json")
    node(d, "experiment/meta-analysis")["props"]["results"]["extra"] = bad
    assert any(expect in m for m in msgs(d, spec)), msgs(d, spec)


def test_categorical_values(spec):
    d = doc("c-inconsistent-reference.json")
    ref = node(d, "experiment/electrolysis-v2")["props"]["conditions"]["reference_electrode"]
    ref.pop("text_value")
    ref.update(value=1, unit="1")
    assert any("is a text_value" in m for m in msgs(d, spec))
    d = doc("c-inconsistent-reference.json")
    node(d, "experiment/electrolysis-v2")["props"]["conditions"]["reference_electrode"]["text_value"] = "Hg/HgO"
    assert any("not one of the categories" in m for m in msgs(d, spec, "warnings"))


def test_partial_dates_are_iso(spec):
    d = doc("a-designed-series.json")
    node(d, "hypothesis/interface")["props"]["proposed_at"] = "2019-13-45x"
    assert any("ISO date" in m for m in msgs(d, spec))


# ---------------------------------------------------------------- references and evidence ids
def test_record_refs_and_evidence_ids_resolve(spec):
    d = doc("a-designed-series.json")
    link(d, "TESTS")["props"]["result_refs"][0]["path"] = "/results/nope"
    assert any("does not resolve to a property" in m for m in msgs(d, spec))
    d = doc("a-designed-series.json")
    link(d, "TESTS")["props"]["result_refs"][0]["record"] = "ex:sk-a/experiment/missing"
    assert any("does not resolve to a node or link" in m for m in msgs(d, spec))
    d = doc("c-inconsistent-reference.json")
    node(d, "experiment/electrolysis")["props"]["conditions"]["potential"]["evidence_ids"] = ["abstract"]
    assert any("not an evidence item of this record" in m for m in msgs(d, spec))


# ---------------------------------------------------------------- method-of-science rules
def test_polar_test_outcome_needs_what_it_rests_on(spec):
    d = doc("a-designed-series.json")
    t = link(d, "TESTS")["props"]
    t.pop("result_refs"), t.pop("evidence")
    assert any("cites evidence or result_refs" in m for m in msgs(d, spec))


def test_post_hoc_prediction_is_flagged(spec):
    d = doc("b-computation-validated.json")
    node(d, "prediction/e-ads")["props"]["proposed_at"] = "2024-06"          # after the measurement (2024-03)
    assert any("post hoc" in m for m in msgs(d, spec, "warnings"))


def test_fit_does_not_confirm_its_own_data(spec):
    d = doc("b-computation-validated.json")
    r = node(d, "experiment/calorimetry")["props"]["results"]["adsorption_energy"]
    r.update(origin="fitted", produced_by=node(d, "experiment/dft")["id"])
    assert any("fitted value" in m for m in msgs(d, spec, "warnings"))


def test_hypothesis_status_needs_matching_evidence(spec):
    d = doc("a-designed-series.json")
    node(d, "hypothesis/dispersion")["props"]["hypothesis_status"] = "refuted"
    assert any("hypothesis_status refuted" in m for m in msgs(d, spec))
    d = doc("a-designed-series.json")
    for e in d["links"]:
        if e["type"] == "TESTS":
            e["props"]["outcome"] = "inconclusive"
    assert any("hypothesis_status supported" in m for m in msgs(d, spec))


def test_hypothesis_driven_experiment_names_what_it_tests(spec):
    d = doc("d-meta-analysis.json")
    node(d, "experiment/meta-analysis")["props"]["approach"] = "hypothesis_driven"
    assert any("names no hypothesis" in m for m in msgs(d, spec, "warnings"))


def test_prediction_and_variable_rules(spec):
    d = doc("e-autonomous-campaign.json")
    p = node(d, "prediction/iter2")["props"]
    p["expected"]["variable"] = node(d, "variable/zn")["id"]
    assert any("disagree" in m for m in msgs(d, spec))
    d = doc("e-autonomous-campaign.json")
    node(d, "variable/sty")["props"].pop("quantity_kind")
    assert any("names its quantity_kind" in m for m in msgs(d, spec))


def test_controls_and_reproductions_are_recorded_not_judged(spec):
    d = doc("a-designed-series.json")
    link(d, "CONTROL_FOR")["props"]["differs_in"] = []
    link(d, "REPLICATES")["props"].pop("changed")
    w = msgs(d, spec, "warnings")
    assert any("differs_in" in m for m in w) and any("lists what changed" in m for m in w)
    d = doc("a-designed-series.json")                                     # several differences: no confounding verdict
    link(d, "CONTROL_FOR")["props"]["differs_in"].append(node(d, "variable/t")["id"])
    assert not any("confound" in m for m in msgs(d, spec, "warnings") + msgs(d, spec))


def test_structure_rules(spec):
    d = doc("e-autonomous-campaign.json")
    m1, m2 = node(d, "model/surrogate-v1")["id"], node(d, "model/surrogate-v2")["id"]
    d["links"].append({"id": "ex:sk-e/link/cycle", "source": m1, "target": m2, "type": "REVISES", "props": {"origin": "synthetic"}})
    assert any("REVISES forms a cycle" in m for m in msgs(d, spec))
    d = doc("e-autonomous-campaign.json")
    link(d, "REVISES")["target"] = node(d, "dataset/iter1")["id"]
    assert any("same label" in m for m in msgs(d, spec))
    d = doc("e-autonomous-campaign.json")
    e1 = node(d, "experiment/iter1")["id"]
    d["links"].append({"id": "ex:sk-e/link/self", "source": e1, "target": e1, "type": "PRECEDES", "props": {"origin": "synthetic"}})
    assert any("joins a record to itself" in m for m in msgs(d, spec))


def test_inputs_used_at_an_old_version_are_flagged(spec):
    d = doc("d-meta-analysis.json")
    node(d, "experiment/s2")["props"]["record_version"] = 2
    assert any("inputs revised" in m for m in msgs(d, spec, "warnings"))
    node(d, "experiment/meta-analysis")["props"]["freshness_status"] = "inputs_revised"
    assert not any("inputs revised" in m for m in msgs(d, spec, "warnings"))


def test_existing_schema_versions_are_unaffected():
    ex = json.loads((EXAMPLES / "scale-catal/example.json").read_text())
    assert validate(copy.deepcopy(ex), spec_of(ex)).errors == []          # under the version it pins, head or frozen


def test_objects_of_study_and_their_parts(spec):
    d = doc("a-designed-series.json")
    rxn = node(d, "object/methanol-synthesis")
    assert rxn["props"]["object_kind"] == "phenomenon"
    e0 = node(d, "experiment/zn0")["id"]
    d["links"].append({"id": "ex:sk-a/link/bad-examines", "source": e0, "target": node(d, "variable/zn")["id"],
                       "type": "EXAMINES", "props": {"origin": "synthetic"}})
    assert any("EXAMINES target must be" in m for m in msgs(d, spec))
    d = doc("a-designed-series.json")
    cat = node(d, "object/catalyst-zn0")["id"]
    d["links"] += [{"id": "ex:sk-a/link/p1", "source": rxn["id"], "target": cat, "type": "HAS_PART", "props": {"origin": "synthetic"}},
                   {"id": "ex:sk-a/link/p2", "source": cat, "target": rxn["id"], "type": "HAS_PART", "props": {"origin": "synthetic"}}]
    assert any("HAS_PART forms a cycle" in m for m in msgs(d, spec))


def test_operations_are_static_or_dynamic(spec):
    d = doc("a-designed-series.json")
    e = node(d, "experiment/zn30")["id"]
    d["nodes"].append({"id": "ex:sk-a/operation/pulsed", "label": "Operation", "props": {"name": "pulsed", "origin": "synthetic",
                                                                                         "operation_mode": "dynamic"}})
    d["links"].append({"id": "ex:sk-a/link/op", "source": e, "target": "ex:sk-a/operation/pulsed", "type": "HAS_OPERATION",
                       "props": {"origin": "synthetic"}})
    assert any("names its varied_quantities" in m for m in msgs(d, spec))
    assert any("says how it varies" in m for m in msgs(d, spec, "warnings"))
    op = node(d, "operation/pulsed")["props"]
    op.update(varied_quantities=["temperature"], period={"status": "present", "value": 60, "unit": "s"})
    assert not [m for m in msgs(d, spec) + msgs(d, spec, "warnings") if "operation" in m]
    op.update(operation_mode="static", time_pattern="periodic")
    assert any("a static operation has time_pattern constant" in m for m in msgs(d, spec))

