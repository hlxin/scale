"""On-demand upgrades of a curated graph to a newer schema version (tools/upgrade.py; `scale graph upgrade`; the
upgrade-curation skill): a report first, the mechanical upgrade only with --write, re-reading only from a worklist."""

import json
import subprocess
import sys
from collections import Counter

import pytest

from conftest import REPO, RUN_SCALE
from scale import graphparts as gp
from scale.upgrade import plan, render, step_impact
from scale.util import ScaleError, load_doc

EX = REPO / "examples/methanol-synthesis-public"


@pytest.fixture(scope="module")
def doc():
    return load_doc(EX)


@pytest.fixture(scope="module")
def up(doc):
    return plan(doc, REPO)


def test_the_public_example_upgrades_cleanly_and_ids_are_kept(doc, up):
    res, new = up
    assert (res["from"], res["blocked"], res["after"]["errors"]) == ("0.2.0", None, 0)
    assert new["graph"]["schema_version"] == res["to"] and doc["graph"]["schema_version"] == "0.2.0"   # input untouched
    assert {n["id"] for n in new["nodes"]} == {n["id"] for n in doc["nodes"]}
    assert sum(len(s.get("rewrites") or []) for s in res["steps"]) == 39


def test_each_step_gets_a_verdict_for_this_graph(up):
    v = {s["from"]: s["verdict"] for s in up[0]["steps"]}
    assert v["0.2.0"] == "nothing to do"                   # a description changed
    assert v["0.2.1"] == "needs attention"                 # quantity contracts: 39 rewrites
    assert v["0.7.1"] == "optional"                        # TRACE-AI properties: available, never needed
    assert set(v.values()) <= {"needs attention", "optional", "checked automatically", "nothing to do"}


def test_comparisons_that_now_need_a_context_make_the_worklist(up):
    res = up[0]
    ctx = {(x["kind"], x["context"]): x for x in res["comparability"]["by_context"]}
    assert ctx[("pressure", "pressure_convention")]["values"] > 300      # "150 atmospheres": gauge or absolute?
    w = res["worklist"]
    assert 0 < w["records"] < 1000 and w["sources"] <= 55
    item = next(i for i in w["items"] if any("pressure_convention" in a for a in i["asks"]))
    assert item["sources"] and item["locators"]           # what to re-read, and where


def test_optional_properties_join_the_worklist_only_when_named(doc, up):
    base = up[0]["worklist"]["records"]
    res, _ = plan(doc, REPO, enrich=["CatalyticTest.catalysis_mode"])
    assert res["worklist"]["records"] > base and res["enrich"] == ["CatalyticTest.catalysis_mode"]
    with pytest.raises(ScaleError, match="--enrich names no property"):
        plan(doc, REPO, enrich=["CatalyticTest.no_such_property"])


def test_the_report_says_what_to_decide(up):
    md = render(up[0])
    for part in ("## Summary", "Stay at 0.2.0", "Upgrade mechanically", "## Step by step",
                 "## Comparisons that now need a context", "## Re-reading worklist, by source",
                 "## New properties available (optional)"):
        assert part in md


def test_step_impact_reads_a_diff_against_what_the_graph_uses():
    diff = {"added": ["nodes.CatalyticTest.new_thing", "nodes.Unused.other", "nodes.NewLabel"],
            "removed": [], "changed": [],
            "narrowed": ["quantities.kinds.selectivity is compared by selectivity_whole",
                         "nodes.CatalyticTest.temperature holds quantity temperature (its unit must be of that kind's dimensions)",
                         "profiles.catalysis CatalyticTest requires driving_forces"],
            "loosened": []}
    imp = step_impact(diff, Counter(CatalyticTest=5), Counter(), 10, Counter(), Counter(selectivity=3))
    assert imp["verdict"] == "needs attention" and imp["new_comparisons"][0]["values"] == 3
    assert imp["new_properties"][0]["property"] == "new_thing" and imp["unit_contracts"] == 1
    quiet = step_impact({"added": ["nodes.Unused.x"], "removed": [], "changed": [], "narrowed": [], "loosened": []},
                        Counter(CatalyticTest=5), Counter(), 10)
    assert quiet["verdict"] == "nothing to do"


def test_the_command_writes_the_report_and_upgrades_only_with_write(tmp_path):
    g = tmp_path / "one"
    gp.write_parts(gp.subset(gp.read_parts(EX), ["10.1021-ie50226a034"]), g)
    # the tools of the repository under test (RUN_SCALE), not an installed package: the version-bump test runs this
    # suite on a copy whose schema is one version ahead
    cmd = [sys.executable, "-c", RUN_SCALE, str(REPO / "tools"), "--repo", str(REPO), "graph", "upgrade", str(g),
           "--report-dir", str(tmp_path)]
    run = subprocess.run(cmd, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)
    assert out["report"].endswith(f"upgrade-one-0.2.0-to-{out['to']}.md") and "written" not in out
    assert (tmp_path / f"upgrade-one-0.2.0-to-{out['to']}.json").is_file()
    assert load_doc(g)["graph"]["schema_version"] == "0.2.0"                        # a report changes nothing
    run = subprocess.run(cmd + ["--write"], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert load_doc(g)["graph"]["schema_version"] == out["to"]
    again = subprocess.run(cmd, capture_output=True, text=True)
    assert again.returncode != 0 and "already at" in again.stderr
