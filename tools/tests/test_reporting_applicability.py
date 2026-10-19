"""Reporting applicability and connected evidence (scale-catal 0.5.0 on): the catalysis checklist applies a test's cases
by its driving forces, so that a test listing none has unknown applicability and is never complete; and it looks for
the evidence a reading of the test needs (CatalyticTest.interpretations) in the records connected to it, at most two
links away, incoming or outgoing. Validity, completeness and comparability stay three answers. Exercised on the
evidence examples (domain/examples/scale-catal/evidence-examples/), the reporting-applicability fixtures
(tools/tests/fixtures/reporting-applicability/) and variants of the head's checklist written outside the repository."""

import copy
import shutil
import subprocess
import sys

import pytest
import yaml

from conftest import DRIVING_FORCE_EXAMPLES, EXAMPLES, GRAPH_MANIFEST, HEAD_VERSION, REPO, spec_at, spec_of
from scale import layout, pgraph, pgraph_migrate, pgraph_query
from scale.pgraph_profiles import conformance
from scale.schema_change import diff_specs
from scale.util import ScaleError, load_doc, write_canonical

EV = EXAMPLES / "scale-catal/evidence-examples"
FX = REPO / "tools/tests/fixtures/reporting-applicability"
EXPECT = yaml.safe_load((FX / "expect.yaml").read_text())


def _records(doc: dict, spec: dict | None = None) -> dict:
    c = conformance(doc, spec or spec_of(doc), by_record=True)["profiles"]["catalysis"]
    return c, c["records"]


def _id(doc: dict, local: str) -> str:
    return next(n["id"] for n in doc["nodes"] if n["id"].endswith("/" + local))


def _node(doc: dict, local: str) -> dict:
    return next(n for n in doc["nodes"] if n["id"].endswith("/" + local))


def _found(rec: dict, name: str) -> bool:
    return rec["evidence"][name]["found"]


# ---------------------------------------------------------------- the fixtures report what expect.yaml states
@pytest.mark.parametrize("case", EXPECT["pass"] + EXPECT["fail"], ids=lambda c: c["file"].removesuffix(".json"))
def test_each_fixture_reports_what_expect_yaml_states(case):
    doc = load_doc(FX / case["file"])
    spec = spec_of(doc)
    rep = pgraph.validate(doc, spec)
    assert rep.errors == [], rep.errors                         # every fixture is valid: completeness is not validity
    c, recs = _records(doc, spec)
    for k, n in case["applicability"].items():
        assert c["applicability"][k] == n, (k, c["applicability"])
    for state in ("unknown", "exempt"):
        want = {_id(doc, x) for x in case.get(state) or []}
        assert {r for r, x in recs.items() if x["applicability"] == state} == want or state not in case, state
    assert c["missing_evidence"] == case.get("missing_evidence", {})
    if "complete" in case:
        assert c["complete"] is case["complete"]


def test_the_fixtures_are_built_reproducibly(tmp_path):
    work = tmp_path / "fx"
    shutil.copytree(FX, work)
    subprocess.run([sys.executable, str(work / "build_fixtures.py")], check=True, capture_output=True, cwd=REPO)
    for case in EXPECT["pass"] + EXPECT["fail"]:
        doc = load_doc(FX / case["file"])
        built = load_doc(work / case["file"])
        if doc["graph"]["schema_version"] != built["graph"]["schema_version"]:     # the head moved on after they were built
            built["graph"]["schema_version"] = doc["graph"]["schema_version"]
        assert built == doc, case["file"]


# ---------------------------------------------------------------- applicability: known, unknown, exempt
def test_removing_driving_forces_makes_applicability_unknown_and_never_complete():
    doc = load_doc(DRIVING_FORCE_EXAMPLES / "electro.json")
    spec = spec_of(doc)
    tid = _id(doc, "test/m03")
    c, recs = _records(doc, spec)
    assert recs[tid]["applicability"] == "known" and recs[tid]["expected"] == 10 and not c["applicability"]["unknown"]
    for forces in (None, []):
        d = copy.deepcopy(doc)
        t = next(n for n in d["nodes"] if n["id"] == tid)
        if forces is None:
            t["props"].pop("driving_forces")
        else:
            t["props"]["driving_forces"] = forces
        c, recs = _records(d, spec)
        r = recs[tid]
        assert r["applicability"] == "unknown" and r["unknown_for"] == ["driving_forces"]
        assert r["expected"] == 0 and r["violations"] == []          # its driving-force items are neither checked nor met
        assert c["applicability"]["unknown"] == 1 and c["complete"] is False and c["conformant"]
        assert c["unknown"] == [{"record": tid, "label": "CatalyticTest", "properties": ["driving_forces"]}]
        assert pgraph.validate(d, spec).errors == []                 # still valid: an incomplete historical record stays
    d = copy.deepcopy(doc)
    next(n for n in d["nodes"] if n["id"] == tid)["props"]["driving_forces"] = ["other"]
    assert _records(d, spec)[1][tid]["applicability"] == "known"      # "other" is a stated force with no case of its own
    d = copy.deepcopy(doc)
    t = next(n for n in d["nodes"] if n["id"] == tid)
    t["props"].pop("driving_forces")
    t["props"]["test_kind"] = "equilibrium_estimate"
    c, recs = _records(d, spec)
    assert recs[tid]["applicability"] == "exempt" and c["applicability"]["exempt"] == 1 and not c["applicability"]["unknown"]


def test_a_stripped_electrochemical_test_is_no_longer_complete():
    """The earlier review's case: a test stripped of its driving forces and of every electrochemical item looked complete
    over the items that were left."""
    doc = load_doc(DRIVING_FORCE_EXAMPLES / "electro.json")
    spec = spec_of(doc)
    t = _node(doc, "test/m03")
    for k in ("driving_forces", "control_mode", "electrode_potential", "reference_scale", "ir_compensation",
              "current_density", "current_normalization", "charge_passed", "faradaic_efficiency"):
        t["props"].pop(k, None)
    doc["links"] = [e for e in doc["links"] if not (e["source"] == t["id"] and e["type"] in ("IN_ELECTROLYTE", "USES_ELECTRODE",
                                                                                            "IN_CELL"))]
    assert pgraph.validate(doc, spec).errors == []
    c, recs = _records(doc, spec)
    assert recs[t["id"]]["applicability"] == "unknown" and c["complete"] is False


def test_a_checklist_without_applies_by_reads_an_absent_force_as_before():
    """Frozen versions keep their semantics: under 0.4.0 (no applies_by) an absent driving force matches no case, as it
    did; only a document moved to 0.5.0 on reads it as unknown. No version silently reinterprets the records it holds."""
    old = spec_at("0.4.0")
    assert "applies_by" not in old["profiles"]["catalysis"]["effective"]["constraints"]["CatalyticTest"]
    doc = load_doc(DRIVING_FORCE_EXAMPLES / "electro.json")
    _node(doc, "test/m03")["props"].pop("driving_forces")
    c = conformance(doc, old)["profiles"]["catalysis"]
    assert c["applicability"]["unknown"] == 0 and c["applicability"]["known"] >= 1


# ---------------------------------------------------------------- connected evidence
def test_an_incoming_transport_analysis_satisfies_the_pattern():
    doc = load_doc(EV / "kinetic-evidence.json")
    spec = spec_of(doc)
    tid, aid = _id(doc, "test/rates-numerical"), _id(doc, "analysis/weisz-prater")
    rec = _records(doc, spec)[1][tid]
    assert rec["evidence"]["transport_assessment"] == {"level": "should", "found": True, "records": [aid],
                                                        "report": {"evaluation_basis": ["numerical"]}}
    reversed_ = copy.deepcopy(doc)                     # the test HAS_INPUT the analysis: the wrong direction is not evidence
    for e in reversed_["links"]:
        if e["type"] == "HAS_INPUT" and e["source"] == aid and e["target"] == tid:
            e["source"], e["target"] = tid, aid
    assert not _found(_records(reversed_, spec)[1][tid], "transport_assessment")
    other = copy.deepcopy(doc)                          # an analysis of another kind is not a transport assessment
    _node(other, "analysis/weisz-prater")["props"]["analysis_kind"] = "kinetic_fit"
    assert not _found(_records(other, spec)[1][tid], "transport_assessment")


def test_asserted_numerical_and_experimental_assessments_are_told_apart():
    doc = load_doc(EV / "kinetic-evidence.json")
    recs = _records(doc)[1]
    basis = {k: recs[_id(doc, f"test/{k}")]["evidence"] for k in ("rates-numerical", "rates-experimental", "rates-asserted")}
    assert {k: v["transport_assessment"]["report"]["evaluation_basis"] for k, v in basis.items()} == {
        "rates-numerical": ["numerical"], "rates-experimental": ["experimental"], "rates-asserted": ["asserted"]}
    assert {k: v["transport_evidence"]["found"] for k, v in basis.items()} == {
        "rates-numerical": True, "rates-experimental": True, "rates-asserted": False}
    assert recs[_id(doc, "analysis/particle-and-flow")]["evidence"]["compared_runs"]["records"] == sorted(
        _id(doc, f"test/{k}") for k in ("rates-experimental", "rates-fine-particles", "rates-double-flow"))
    short = copy.deepcopy(doc)                          # an experimental basis that names no varied run is reported
    aid = _id(short, "analysis/particle-and-flow")
    short["links"] = [e for e in short["links"] if not (e["source"] == aid and e["type"] == "HAS_INPUT"
                                                       and not e["target"].endswith("/test/rates-experimental"))]
    assert not _found(_records(short)[1][aid], "compared_runs")


def test_missing_light_heat_and_synergy_evidence_is_reported_by_name():
    doc = load_doc(EV / "kinetic-evidence.json")
    c, recs = _records(doc)
    surface, bulk = (recs[_id(doc, f"test/{k}")]["evidence"] for k in ("light-surface-matched", "light-bulk-matched"))
    assert surface["local_temperature_match"]["found"] and surface["light_heat_separation"]["found"]
    assert bulk["light_heat_separation"]["found"] and not bulk["local_temperature_match"]["found"]   # a bulk match only
    assert c["missing_evidence"] == {"transport_evidence": 1, "local_temperature_match": 1}
    bare = copy.deepcopy(doc)                           # without its controls, each missing one is named
    plasma = _id(bare, "test/plasma-catalyst")
    bare["links"] = [e for e in bare["links"] if not (e["type"] == "CONTROL_FOR" and e["target"] == plasma)]
    sep = _id(bare, "analysis/irradiance-dependence")              # and without the analysis that separates light from heat
    bare["links"] = [e for e in bare["links"] if e["source"] != sep]
    c = _records(bare)[0]
    assert {k: c["missing_evidence"].get(k) for k in ("plasma_alone_control", "catalyst_alone_control",
                                                       "light_heat_separation")} == dict.fromkeys(
        ("plasma_alone_control", "catalyst_alone_control", "light_heat_separation"), 1)


def test_ramps_and_pulses_keep_their_time_dependent_context(tmp_path):
    doc = load_doc(EV / "dynamic-and-stability.json")
    spec = spec_of(doc)
    op = _node(doc, "operation/ramp-and-hold")
    rec = _records(doc, spec)[1][op["id"]]
    assert rec["expected"] == 3 and rec["filled"] == 3                # time_pattern, varied_quantities, segments
    bare = copy.deepcopy(doc)
    _node(bare, "operation/ramp-and-hold")["props"].pop("segments")
    assert _records(bare, spec)[1][op["id"]]["missing"] == {"Operation.segments": 1}
    plan = {"match": {"label": "CatalyticTest", "as": "test"},
            "steps": [{"from": "test", "edge": "HAS_OPERATION", "to": "Operation", "as": "operation"}],
            "return": ["test.name", "operation.time_pattern", "operation.segments"]}
    row = pgraph_query.run(doc, spec, plan)["rows"][0]["values"]
    assert row["operation.time_pattern"] == "ramp" and [s.get("heating_rate", {}).get("value") for s in
                                                        row["operation.segments"]] == [None, 10, None]
    pulsed = load_doc(DRIVING_FORCE_EXAMPLES / "electro-dynamic.json")
    rows = pgraph_query.run(pulsed, spec_of(pulsed), plan)["rows"]
    assert "periodic" in {r["values"]["operation.time_pattern"] for r in rows}
    write_canonical(tmp_path / "rt.json", doc)                         # the native format keeps every segment
    assert load_doc(tmp_path / "rt.json") == doc


def test_a_constant_performance_trace_alone_does_not_establish_material_stability():
    doc = load_doc(EV / "dynamic-and-stability.json")
    recs = _records(doc)[1]
    first, trace_only = recs[_id(doc, "test/oer-electrode-1")], recs[_id(doc, "test/oer-trace-only")]
    assert first["evidence"]["performance_over_time"]["found"] and first["evidence"]["material_after_test"]["found"]
    assert set(trace_only["evidence"]) == {"material_after_test"} and not trace_only["evidence"]["material_after_test"]["found"]
    trace = _id(doc, "dataset/potential-oer-trace-only")
    assert any(e["type"] == "HAS_OUTPUT" and e["target"] == trace for e in doc["links"])     # the trace is there, and is not enough
    cut = copy.deepcopy(doc)                                            # electrode 1 without its post-test characterization
    state = _id(cut, "state/nife-after-24h")
    cut["links"] = [e for e in cut["links"] if not (e["type"] == "REACHED_BY" and e["source"] == state)]
    assert not _found(_records(cut)[1][_id(cut, "test/oer-electrode-1")], "material_after_test")


def test_no_cutoff_threshold_or_blanket_control_is_required():
    head = pgraph.load_spec(GRAPH_MANIFEST)
    ct = head["profiles"]["catalysis"]["effective"]["constraints"]["CatalyticTest"]
    assert not (ct.get("evidence") or {}).get("required") and not (ct.get("evidence") or {}).get("recommended")
    for case in ct["when"]:                             # evidence is asked only of a reading the source makes
        if case.get("evidence"):
            assert set(case["if"]) == {"interpretations"} and case.get("maturity") == "provisional" and case.get("basis")
            assert not case["evidence"].get("required")                # provisional: should, never must
    fx = load_doc(FX / "pass-evidence-found.json")
    recs = _records(fx)[1]
    high = recs[_id(fx, "test/intrinsic-high-conversion")]              # 60 % conversion, a Weisz-Prater number of 4
    assert high["evidence"]["transport_evidence"]["found"] and not high["violations"]
    doc = load_doc(EV / "kinetic-evidence.json")                        # tests read as nothing are asked for no evidence
    for k in ("rates-fine-particles", "rates-double-flow", "dark-surface-matched", "thermal-alone"):
        assert "evidence" not in _records(doc)[1][_id(doc, f"test/{k}")], k


def test_validity_completeness_and_comparison_stay_apart():
    doc = load_doc(EV / "kinetic-evidence.json")
    spec = spec_of(doc)
    t = _node(doc, "test/rates-asserted")
    t["props"].pop("driving_forces")                    # unknown applicability and an unsupported reading: still valid,
    rep = pgraph.validate(doc, spec)                    # and still answered by a query
    assert rep.errors == [] and rep.conformance["profiles"]["catalysis"]["complete"] is False
    rows = pgraph_query.run(doc, spec, {"match": {"label": "CatalyticTest", "as": "test",
                                                   "where": [{"prop": "interpretations", "op": "contains",
                                                              "value": "intrinsic_kinetics"}]},
                                        "return": ["test.name", "test.conversion"]})["rows"]
    assert t["props"]["name"] in {r["values"]["test.name"] for r in rows}


# ---------------------------------------------------------------- the dark control and the query (issue #41)
def test_a_dark_control_states_what_a_control_states():
    head = pgraph.load_spec(GRAPH_MANIFEST)
    dark, ctl = head["edges"]["DARK_CONTROL_FOR"], head["edges"]["CONTROL_FOR"]
    assert dark["specializes"] == "CONTROL_FOR"
    for k in ("control_kind", "differs_in"):            # the same property as CONTROL_FOR's, so the two never drift apart
        assert {x: v for x, v in dark["properties"][k].items() if x not in ("description", "maturity")} == \
            {x: v for x, v in ctl["properties"][k].items() if x not in ("description", "maturity")}, k
    doc = load_doc(EV / "kinetic-evidence.json")
    link = next(e for e in doc["links"] if e["type"] == "DARK_CONTROL_FOR")
    assert link["props"]["control_kind"] == "negative" and link["props"]["differs_in"]
    assert pgraph.validate(doc, spec_of(doc)).errors == []


def test_a_control_for_step_follows_a_dark_control_for():
    doc = load_doc(EV / "kinetic-evidence.json")
    spec = spec_of(doc)

    def controls(edge):
        plan = {"match": {"label": "CatalyticTest", "as": "test"},
                "steps": [{"from": "test", "edge": edge, "direction": "in", "to": "Experiment", "as": "control",
                           "edge_as": "link"}],
                "return": ["test.name", "control.name", "link.control_kind"]}
        return {r["values"]["control.name"] for r in pgraph_query.run(doc, spec, plan)["rows"]}
    dark = controls("DARK_CONTROL_FOR")
    every = controls("CONTROL_FOR")
    assert len(dark) == 2 and dark < every                       # every dark control is a control, not the other way
    assert "NH3 synthesis over Ni/Al2O3 without plasma, 200 °C" in every - dark


# ---------------------------------------------------------------- the checklist grammar, the diff and describe
def _variant(tmp_path, mutate):
    root = tmp_path / "cand"
    (root / "core/graph").mkdir(parents=True)
    shutil.copy2(REPO / layout.KERNEL, root / layout.KERNEL)
    shutil.copytree(GRAPH_MANIFEST.parent, root / "domain/graph", ignore=shutil.ignore_patterns("frozen"))
    cat = root / "domain/graph/catalysis.yaml"
    m = yaml.safe_load(cat.read_text())
    mutate(m["checklist"])
    cat.write_text(yaml.safe_dump(m, sort_keys=False, allow_unicode=True))
    return root / "domain/graph/scale-catal.yaml"


def _pattern(ck, i=0):
    """The first evidence pattern of the checklist (the intrinsic-kinetics case's transport_assessment)."""
    case = next(x for x in ck["labels"]["CatalyticTest"]["when"] if x.get("evidence"))
    return case["evidence"]["should"][i]


@pytest.mark.parametrize("mutate, match", [
    (lambda ck: _pattern(ck)["path"].extend([{"edge": "HAS_INPUT"}, {"edge": "HAS_INPUT"}]), "at most 2 links"),
    (lambda ck: _pattern(ck)["path"][0].__setitem__("edge", "HAS_OPINION"), "unknown edge type HAS_OPINION"),
    (lambda ck: _pattern(ck)["path"][0].__setitem__("label", "Reactor"), "Reactor is never at the other end of HAS_INPUT"),
    (lambda ck: _pattern(ck)["path"][0].__setitem__("direction", "sideways"), "direction is in or out"),
    (lambda ck: _pattern(ck)["path"][0]["where"].__setitem__("colour", {"any_of": ["red"]}), "no property 'colour'"),
    (lambda ck: _pattern(ck)["path"][0]["where"]["analysis_kind"].__setitem__("any_of", ["guess"]),
     "must name values of its enum"),
    (lambda ck: _pattern(ck)["path"][0]["where"].__setitem__("method", {"any_of": ["x"]}), "test it with present: true"),
    (lambda ck: _pattern(ck).__setitem__("any_of", [{"path": [{"edge": "HAS_INPUT"}]}]), "takes a path or any_of"),
    (lambda ck: _pattern(ck, 1).__setitem__("name", "transport_assessment"), "names two patterns"),
    (lambda ck: _pattern(ck).__setitem__("min", 0), "min is a whole number of at least 1"),
    (lambda ck: _pattern(ck).__setitem__("report", "colour"), "report names 'colour'"),
    (lambda ck: _pattern(ck).__setitem__("look_for", "x"), "unknown keys"),
    (lambda ck: ck["labels"]["CatalyticTest"].__setitem__("applies_by", ["temperature"]), "not an enum or a list of enum"),
    (lambda ck: ck["labels"]["CatalyticTest"].__setitem__("applies_by", ["interpretations", "test_kind"]),
     "applies_by names 'test_kind', which no case"),
    (lambda ck: ck["edges"]["USES_ELECTRODE"].__setitem__("evidence", {"should": []}), "which a label's block takes"),
])
def test_malformed_patterns_and_applies_by_are_refused(tmp_path, mutate, match):
    with pytest.raises(ScaleError, match=match):
        pgraph.load_spec(_variant(tmp_path, mutate))


def test_the_schema_diff_reads_applies_by_and_required_evidence_as_narrowing(tmp_path):
    head = pgraph.load_spec(GRAPH_MANIFEST)

    def loosen(ck):
        ck["labels"]["CatalyticTest"].pop("applies_by")
    d = diff_specs(head, pgraph.load_spec(_variant(tmp_path / "a", loosen)))
    assert d["loosened"] == ["profiles.catalysis CatalyticTest no longer applies its cases by driving_forces"]

    def require(ck):
        case = next(x for x in ck["labels"]["CatalyticTest"]["when"] if x.get("evidence"))
        case["evidence"]["must"] = case["evidence"].pop("should")
    d = diff_specs(head, pgraph.load_spec(_variant(tmp_path / "b", require)))
    assert "profiles.catalysis CatalyticTest when interpretations any_of [intrinsic_kinetics] requires evidence " \
           "transport_assessment" in d["narrowed"]


def test_describe_prints_applies_by_and_the_evidence_of_each_case():
    out = pgraph.describe(pgraph.load_spec(GRAPH_MANIFEST), ["CatalyticTest"], "catalysis")
    ck = out["checklist"]["labels"]["CatalyticTest"]
    assert ck["applies_by"] == ["driving_forces"]
    kin = next(x for x in ck["when"] if x.get("interpretations") == {"any_of": ["intrinsic_kinetics"]})
    assert [p["name"] for p in kin["evidence"]["should"]] == ["transport_assessment", "transport_evidence"]
    assert kin["maturity"] == "provisional" and kin["basis"]


# ---------------------------------------------------------------- examples and migration
def test_the_evidence_examples_are_built_reproducibly(tmp_path):
    work = tmp_path / "ev"
    shutil.copytree(EV, work)
    subprocess.run([sys.executable, str(work / "build_examples.py")], check=True, capture_output=True, cwd=REPO)
    for name in ("kinetic-evidence.json", "dynamic-and-stability.json"):
        doc = load_doc(EV / name)
        if doc["graph"]["schema_version"] != HEAD_VERSION:
            doc = pgraph_migrate.raise_version(doc, HEAD_VERSION, pgraph.load_spec(GRAPH_MANIFEST))[0]
        write_canonical(tmp_path / name, doc)
        assert (work / name).read_bytes() == (tmp_path / name).read_bytes(), name


@pytest.mark.parametrize("name", ["kinetic-evidence.json", "dynamic-and-stability.json"])
def test_the_evidence_examples_are_valid_and_show_only_the_gaps_they_were_built_to_show(name):
    doc = load_doc(EV / name)
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.errors == [] and rep.warnings == [], (rep.errors, rep.warnings)
    c = rep.conformance["profiles"]["catalysis"]
    assert c["conformant"] and c["missing_evidence"] == (
        {"transport_evidence": 1, "local_temperature_match": 1} if name.startswith("kinetic") else {"material_after_test": 1})


def test_the_step_to_reporting_applicability_rewrites_nothing():
    doc = load_doc(DRIVING_FORCE_EXAMPLES / "electro.json")
    doc["graph"]["schema_version"] = "0.4.0"
    new, log = pgraph_migrate.raise_version(doc, "0.5.0", spec_at("0.5.0"))
    step = next(s for s in log["steps"] if s["from"] == "0.4.0")
    assert step["to"] == "0.5.0" and not step.get("changes")
    assert {k: v for k, v in new.items() if k != "graph"} == {k: v for k, v in doc.items() if k != "graph"}
