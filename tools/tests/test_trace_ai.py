"""TRACE-AI read on scale-catal records (`scale trace-ai`, docs/trace-ai.md): every item of the checklist once, a
status the records decide (never satisfied by default, never not applicable without the condition that says so), the
flags worth a second look, and how the records were curated."""

import copy
import json

import pytest

from conftest import EXAMPLES, REPO, spec_of
from scale.api import ScaleToolkit
from scale.cli import main
from scale.pgraph_query import schema_gaps
from scale.traceai import ITEM_IDS, assess, load_crosswalk, problems, render_markdown, restrict
from scale.util import ScaleError, load_doc

CAMPAIGN = EXAMPLES / "scale-catal/agentic-examples/self-driving-campaign.json"
ENERGIES = EXAMPLES / "scale-catal/computation-examples/computed-energies.json"


@pytest.fixture(scope="module")
def cw():
    return load_crosswalk(REPO)


def run(path, cw, source=None) -> dict:
    doc = load_doc(path)
    return assess(doc, spec_of(doc), cw, source)


def status(rep: dict) -> dict:
    return {i["id"]: i["status"] for i in rep["items"]}


def campaign() -> dict:
    return copy.deepcopy(load_doc(CAMPAIGN))


def node(doc: dict, rid: str) -> dict:
    return next(n for n in doc["nodes"] if n["id"] == rid)


def item(rep: dict, iid: str) -> dict:
    return next(i for i in rep["items"] if i["id"] == iid)


def test_the_crosswalk_covers_every_item_once(cw):
    assert problems(cw) == []
    assert [i["id"] for i in cw["items"]] == list(ITEM_IDS)
    assert cw["checklist_version"] == "2.2.0" and "10.1016/j.checat.2026.101755" in cw["reference"]
    doc = (REPO / "docs/trace-ai.md").read_text(encoding="utf-8")
    assert all(f"| {i} |" in doc for i in ITEM_IDS)                     # the documentation lists every item


def test_a_malformed_crosswalk_is_refused(cw):
    bad = copy.deepcopy(cw)
    bad["items"] = bad["items"][1:] + [dict(bad["items"][1], applies="nowhere")]
    bad["items"][2]["needs"][0]["check"] = "metric_uncertainty"            # plans and a check on one need
    probs = problems(bad)
    assert any("missing ['A1']" in p and "twice ['A2']" in p for p in probs)
    assert any("unknown condition 'nowhere'" in p for p in probs)
    assert any("give plans or a check, one of the two" in p for p in probs)
    with pytest.raises(ScaleError, match="malformed"):
        assess(load_doc(CAMPAIGN), spec_of(load_doc(CAMPAIGN)), bad)


def test_an_agentic_campaign_supports_the_workflow_items(cw):
    rep = run(CAMPAIGN, cw)
    st = status(rep)
    assert {i for i, s in st.items() if s == "supported"} == {
        "A2", "A3", "A4", "A5", "B1", "B2", "B5", "C1", "C2", "C3", "C4", "C5", "D1", "D3"}
    assert st["B3"] == "partial" and {st[i] for i in ("A1", "B4", "D2")} == {"by_hand"}
    c2 = next(i for i in rep["items"] if i["id"] == "C2")
    level = next(n for n in c2["needs"] if n["name"] == "autonomy_level")
    assert level["records"] == ["ex:sdl/design/campaign"] and level["rows"][0]["design.autonomy_level"] == "A2"
    assert level["evidence"] and level["evidence"][0]["source"] == "ex:sdl/source/paper"
    cur = rep["curation"]
    assert cur["autonomy_level"] == "A3" and cur["curated_by"] == ["ex:sdl/software/extraction-agent"]
    assert cur["checks"] == [{"checked_by": "ex:sdl/person/checker", "checked_on": "2026-10-21", "records": 6,
                              "selection": "sample_and_flagged", "outcome": "corrected",
                              "precision": round(45 / 46, 4), "recall": round(45 / 47, 4)}]
    assert cur["evidenced_records_checked"] == 6 < cur["evidenced_records"]


def test_a_random_split_and_a_bare_metric_are_flagged(cw):
    rep = run(CAMPAIGN, cw)
    flags = {f["name"]: f for i in rep["items"] for f in i.get("flags") or []}
    assert flags["random_split"]["records"] == ["ex:sdl/experiment/gp-random-cv", "ex:sdl/model/gp-surrogate"]
    assert flags["metric_without_uncertainty"]["records"] == ["ex:sdl/experiment/gp-random-cv/result_values/mae"]
    # stated with its spread, the metric is no longer flagged and B3 is supported
    doc = copy.deepcopy(load_doc(CAMPAIGN))
    v = next(n for n in doc["nodes"] if n["id"] == "ex:sdl/experiment/gp-random-cv")["props"]["result_values"][0]
    v.update(uncertainty=0.03, uncertainty_kind="standard_deviation")
    rep = assess(doc, spec_of(doc), cw)
    assert status(rep)["B3"] == "supported" and "metric_without_uncertainty" not in str(rep)


def test_a_metric_named_by_its_whole_record_is_read_and_one_that_names_none_is_not_passed_over(cw):
    """A reference without a path names every result of its record; a reference that names no metric keeps B3 from
    being supported (it cannot be assessed), never passed over."""
    doc = campaign()
    ev = next(e for e in doc["links"] if e["source"] == "ex:sdl/experiment/gp-random-cv" and e["type"] == "EVALUATES")
    del ev["props"]["result_refs"][0]["path"]
    rep = assess(doc, spec_of(doc), cw)
    assert status(rep)["B3"] == "partial"                                   # its bare metric is found all the same
    assert item(rep, "B3")["flags"][0]["records"] == ["ex:sdl/experiment/gp-random-cv/result_values/mae"]
    ev["props"]["result_refs"] = [{"record": "ex:sdl/design/campaign"}]   # a record with no result
    rep = assess(doc, spec_of(doc), cw)
    b3 = item(rep, "B3")
    assert b3["status"] == "partial" and "flags" not in b3
    assert b3["needs"][0]["note"] == "a reference that names no metric: ex:sdl/design/campaign"


def test_a_model_is_read_with_its_own_records_never_with_anothers(cw):
    """B5 asks each model how its uncertainty was quantified, calibrated and used: one model's method and another's
    calibration do not make the item supported."""
    doc = campaign()
    gp = node(doc, "ex:sdl/model/gp-surrogate")
    calibration, use = gp["props"].pop("uncertainty_calibration"), gp["props"].pop("uncertainty_use")
    other = copy.deepcopy(gp)
    other["id"] = "ex:sdl/model/forest"
    other["props"].update(name="a random forest of the yields", architecture="A random forest of 200 trees",
                          uncertainty_calibration=calibration, uncertainty_use=use)
    del other["props"]["uncertainty_method"]
    doc["nodes"].append(other)
    rep = assess(doc, spec_of(doc), cw)
    b5 = item(rep, "B5")
    assert b5["status"] == "partial" and all(n["found"] for n in b5["needs"])
    assert b5["coverage"] == {"subject": "model", "records": 2, "complete": 0, "incomplete": [
        {"record": "ex:sdl/model/forest", "lacks": ["method"]},
        {"record": "ex:sdl/model/gp-surrogate", "lacks": ["calibration", "use"]}]}
    assert "ex:sdl/model/forest lacks method" in render_markdown(rep)
    gp["props"].update(uncertainty_calibration=calibration, uncertainty_use=use)
    b5 = item(assess(doc, spec_of(doc), cw), "B5")
    assert b5["status"] == "partial" and b5["coverage"]["complete"] == 1     # the other model still lacks its method


def test_failed_runs_without_a_policy_only_partly_support_a5(cw):
    doc = campaign()
    del node(doc, "ex:sdl/design/campaign")["props"]["negative_results_policy"]
    assert status(assess(doc, spec_of(doc), cw))["A5"] == "partial"        # failed runs and exclusions, no policy
    for k in ("exclusion_criteria", "excluded_count"):
        del node(doc, "ex:sdl/design/campaign")["props"][k]
    for n in doc["nodes"]:
        if n["props"].get("experiment_status") in ("failed", "aborted"):
            n["props"]["experiment_status"] = "completed"
    assert status(assess(doc, spec_of(doc), cw))["A5"] == "gap"


def test_c4_applies_to_a_campaign_with_a_physical_run(cw):
    """Safety applies to a campaign whose runs are physical: an experiment that states it, a characterization, or a
    catalytic test that is not an equilibrium estimate; whether the campaign is adaptive or only states its autonomy."""
    runs = ["ex:sdl/test/round-1", "ex:sdl/test/round-2", "ex:sdl/test/round-3", "ex:sdl/experiment/round-3-rejected"]
    doc = campaign()
    node(doc, "ex:sdl/design/campaign")["props"]["design_kind"] = "screening"      # its autonomy level makes it one
    assert status(assess(doc, spec_of(doc), cw))["C4"] == "supported"
    for r in runs:                                                       # catalytic tests stating no kind: physical
        node(doc, r)["props"].pop("experiment_kind")
    assert status(assess(doc, spec_of(doc), cw))["C4"] == "supported"
    for r in runs:                                                       # equilibrium estimates: computed
        node(doc, r)["props"]["experiment_kind"] = "computational"
        if node(doc, r)["label"] == "CatalyticTest":
            node(doc, r)["props"]["test_kind"] = "equilibrium_estimate"
    rep = assess(doc, spec_of(doc), cw)
    assert status(rep)["C4"] == "not_applicable" and status(rep)["C2"] == "supported"
    node(doc, "ex:sdl/experiment/round-3-rejected")["props"]["experiment_kind"] = "physical"
    assert status(assess(doc, spec_of(doc), cw))["C4"] == "supported"   # a generic experiment that states it


def test_an_item_without_its_condition_is_not_applicable_with_the_reason(cw):
    rep = run(ENERGIES, cw)
    c = {i["id"]: i for i in rep["items"]}
    assert {c[i]["status"] for i in ("C1", "C2", "C3", "C4", "C5")} == {"not_applicable"}
    assert c["C2"]["reason"].startswith("no record of an adaptive or autonomous campaign")
    assert c["B3"]["status"] == "gap"                                       # two metrics, neither with its spread
    assert len(c["B3"]["flags"][0]["records"]) == 2


def test_a_need_the_pinned_schema_cannot_express_is_not_assessed(cw):
    rep = run(ENERGIES, cw)                                                 # pinned 0.7.1: no split, no UQ fields
    assert rep["schema_version"] == "0.7.1"
    st = status(rep)
    assert st["B2"] == "not_assessed" and st["B5"] == "not_assessed"
    b2 = next(i for i in rep["items"] if i["id"] == "B2")
    assert "EVALUATES.split_strategy is not declared" in b2["needs"][0]["schema_gap"]
    assert "not expressible in scale-catal 0.7.1" in render_markdown(rep)
    # a value the vocabulary of 0.7.1 does not hold is a gap of the schema too, not an absence from the records
    assert st["D1"] == "not_assessed"
    assert item(rep, "D1")["needs"][0]["schema_gap"] == ["Dataset.data_kind has no value notebook"]
    plan = cw["items"][ITEM_IDS.index("D1")]["needs"][0]["plans"][0]
    old = spec_of(load_doc(ENERGIES))
    assert schema_gaps(plan, old, values=True) == ["Dataset.data_kind has no value notebook"]
    assert schema_gaps(plan, old) == []                                  # a query's own answer is unchanged


def test_one_sources_records_are_read_as_that_source_states_them(cw):
    """--source keeps a shared record's evidence and values of that source alone, and the checks of the records it
    holds."""
    doc = campaign()
    doc["nodes"].append({"id": "ex:sdl/source/second", "label": "Source",
                         "props": {"name": "a second invented paper", "origin": "synthetic", "source_kind": "article"}})
    cv = node(doc, "ex:sdl/experiment/gp-grouped-cv")
    cv["props"]["evidence"].append({"id": "rmse-second", "kind": "table", "locator": "Table 1",
                                    "source": "ex:sdl/source/second"})
    cv["props"]["result_values"].append({"id": "rmse", "status": "present", "value": 0.3, "unit": "g/(g h)",
                                         "variable": "ex:sdl/variable/sty-mae", "evidence_ids": ["rmse-second"]})
    other = copy.deepcopy(node(doc, "ex:sdl/test/round-1"))
    other["id"] = "ex:sdl/test/second-run"
    for e in other["props"]["evidence"]:
        e["source"] = "ex:sdl/source/second"
    doc["nodes"].append(other)
    doc["links"] += [{"id": f"ex:sdl/link/second-{i}", "type": "REPORTED_IN", "source": s,
                      "target": "ex:sdl/source/second", "props": {"origin": "synthetic"}}
                     for i, s in enumerate((cv["id"], other["id"]))]
    doc["graph"]["checks"].append({"checked_by": "ex:sdl/person/checker", "checked_on": "2026-10-22",
                                   "records": [other["id"]], "scope": "the second paper's run", "outcome": "passed"})
    view = restrict(doc, "ex:sdl/source/paper")
    kept = node(view, cv["id"])
    assert [v["id"] for v in kept["props"]["result_values"]] == ["mae"]
    assert {e["source"] for e in kept["props"]["evidence"]} == {"ex:sdl/source/paper"}
    assert other["id"] not in {n["id"] for n in view["nodes"]} and len(view["graph"]["checks"]) == 1
    rep = assess(doc, spec_of(doc), cw, "ex:sdl/source/paper")
    assert len(rep["curation"]["checks"]) == 1 and rep["curation"]["checks"][0]["precision"] == round(45 / 46, 4)
    second = restrict(doc, "ex:sdl/source/second")
    assert [v["id"] for v in node(second, cv["id"])["props"]["result_values"]] == ["rmse"]
    first, own = second["graph"]["checks"]                 # the record both report keeps its check, not its counts
    assert first["records"] == [cv["id"]] and "fields_checked" not in first and own["records"] == [other["id"]]


def test_one_sources_records(cw):
    doc = load_doc(CAMPAIGN)
    view = restrict(doc, "ex:sdl/source/paper")
    assert {n["id"] for n in view["nodes"]} >= {"ex:sdl/design/campaign", "ex:sdl/person/checker"}
    rep = run(CAMPAIGN, cw, "ex:sdl/source/paper")
    assert rep["source"] == "ex:sdl/source/paper" and status(rep) == status(run(CAMPAIGN, cw))
    with pytest.raises(ScaleError, match="is not a Source"):
        restrict(doc, "ex:sdl/design/campaign")


def test_the_command_and_the_agent_tool_give_the_report(capsys):
    assert main(["--repo", str(REPO), "trace-ai", str(CAMPAIGN)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# TRACE-AI 2.2.0 on ex:sdl/graph") and "| C2 | supported |" in out
    assert "precision 0.9783, recall 0.9574" in out
    res = ScaleToolkit(repo=REPO).call("trace_ai", {"path": str(CAMPAIGN), "format": "markdown"})
    assert "error" not in res and res["summary"]["supported"] == 14 and res["markdown"].startswith("# TRACE-AI")
    assert json.dumps(res)                                                   # JSON all the way down
