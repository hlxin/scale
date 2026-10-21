"""TRACE-AI read on scale-catal records (`scale trace-ai`, docs/trace-ai.md): every item of the checklist once, a
status the records decide (never satisfied by default, never not applicable without the condition that says so), the
flags worth a second look, and how the records were curated."""

import copy
import json

import pytest

from conftest import EXAMPLES, REPO, spec_of
from scale.api import ScaleToolkit
from scale.cli import main
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
