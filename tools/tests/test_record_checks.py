"""A person's checks of curated records (graph.checks, the kernel's record_check, scale-catal 0.7.2 on): what a check
covers, the counts that give the extraction's precision and recall, the warnings it acknowledges (listed apart, never
silently dropped) and what a filtered view or a graph of some sources keeps of it."""

import copy
import json

from conftest import EXAMPLES, REPO, spec_of
from scale import graphparts, pgraph
from scale.cli import main
from scale.recordchecks import prune, quality
from scale.util import load_doc

CAMPAIGN = EXAMPLES / "scale-catal/agentic-examples/self-driving-campaign.json"
DESIGN = "ex:sdl/design/campaign"


def campaign() -> dict:
    return copy.deepcopy(load_doc(CAMPAIGN))


def report(doc: dict) -> dict:
    return pgraph.validate(doc, spec_of(doc)).as_dict()


def test_an_acknowledged_warning_is_listed_apart():
    rep = report(campaign())
    assert rep["valid"] and rep["summary"]["warning"] == 0 and rep["summary"]["acknowledged"] == 1
    ack = rep["acknowledged"][0]
    assert ack["record"] == DESIGN and ack["message"].startswith("unmodeled context: the robot's liquid-handling")
    assert ack["checked_by"] == "ex:sdl/person/checker" and ack["checked_on"] == "2026-10-21" and ack["reason"]
    # without the check, the same warning is open
    doc = campaign()
    del doc["graph"]["checks"]
    rep = report(doc)
    assert [w["record"] for w in rep["warnings"]] == [DESIGN] and "acknowledged" not in rep


def test_an_acknowledgement_no_warning_matches_is_reported():
    doc = campaign()
    design = next(n for n in doc["nodes"] if n["id"] == DESIGN)
    del design["props"]["unmodeled"]                       # the context was modelled: nothing left to acknowledge
    rep = report(doc)
    assert rep["valid"] and "acknowledged" not in rep
    assert [w["message"] for w in rep["warnings"]] == [
        "checks[0].acknowledged[0]: no warning on ex:sdl/design/campaign contains \"unmodeled context: the robot's "
        "liquid-handling tolerance\" any more; remove the acknowledgement or update it"]


def test_a_check_of_a_revised_record_does_not_cover_the_newer_one():
    doc = campaign()
    old = next(n for n in doc["nodes"] if n["id"] == "ex:sdl/test/round-1")
    new = copy.deepcopy(old)
    new["id"], new["props"]["record_version"] = "ex:sdl/test/round-1-v2", 2
    doc["nodes"].append(new)
    doc["links"].append({"id": "ex:sdl/link/revises", "type": "REVISES", "source": new["id"], "target": old["id"],
                         "props": {"origin": "synthetic"}})
    doc["links"] += [dict(e, id=e["id"] + "-v2", source=new["id"]) for e in doc["links"]
                     if e["source"] == old["id"] and e["type"] == "REPORTED_IN"]
    rep = report(doc)
    assert any("ex:sdl/test/round-1 was checked, and ex:sdl/test/round-1-v2 REVISES it" in w["message"]
               for w in rep["warnings"]), rep["warnings"]


def test_a_sample_states_its_fraction_and_seed():
    doc = campaign()
    del doc["graph"]["checks"][0]["seed"]
    rep = report(doc)
    assert rep["valid"] and any("a sample states its fraction and seed" in w["message"] for w in rep["warnings"])


def test_precision_and_recall_come_from_the_counts():
    q = quality({"fields_checked": 46, "fields_wrong": 1, "fields_missed": 2})
    assert q == {"precision": round(45 / 46, 4), "recall": round(45 / 47, 4)}
    assert quality({"fields_checked": 10}) == {"precision": None, "recall": None}
    assert quality({"fields_checked": 10, "fields_wrong": 0}) == {"precision": 1.0, "recall": None}
    assert quality({"fields_checked": 3, "fields_wrong": 5}) == {"precision": None, "recall": None}   # reported apart


def test_prune_keeps_a_check_to_the_records_held():
    g = campaign()["graph"]
    kept, removed = prune(g, {"ex:sdl/test/round-1", "ex:sdl/person/checker"})
    assert kept["checks"][0]["records"] == ["ex:sdl/test/round-1"] and "acknowledged" not in kept["checks"][0]
    assert removed == 6                                    # five records and one acknowledgement
    gone, removed = prune(g, {"ex:sdl/test/round-1"})       # its checker left out: the check goes
    assert "checks" not in gone and removed == 6
    assert g["checks"][0]["records"][0] == DESIGN          # the graph given is not changed


def test_a_filtered_view_keeps_only_the_checks_of_its_records():
    doc = campaign()
    for n in doc["nodes"]:
        if n["id"] in (DESIGN, "ex:sdl/test/round-2"):
            n["props"]["stewardship"] = {"access": "institution", "contributed_by": []}
    view = pgraph.filter_for(doc, [], "2026-10-21")
    recs = view["graph"]["checks"][0]["records"]
    assert DESIGN not in recs and "ex:sdl/test/round-2" not in recs and "ex:sdl/test/round-1" in recs
    assert "acknowledged" not in view["graph"]["checks"][0]        # it acknowledged a warning on a record withheld
    assert not [e for e in report(view)["errors"] if "checks" in e["message"]]


def test_a_subset_of_sources_keeps_its_checks():
    def rec(rid, label="Experiment"):
        return {"id": rid, "label": label, "props": {"name": rid, "origin": "synthetic"}}
    checks = [{"checked_by": "ex:a/person/p", "checked_on": "2026-10-21", "records": ["ex:a/s1/x", "ex:a/s2/y"],
               "scope": "each value against the source", "outcome": "passed",
               "acknowledged": [{"record": "ex:a/s2/y", "warning": "w", "reason": "as the source states it"}]},
              {"checked_by": "ex:a/person/q", "checked_on": "2026-10-22", "records": ["ex:a/s2/y"],
               "scope": "each value against the source", "outcome": "passed"}]
    parts = {"header": {"directed": True, "multigraph": True, "graph": {"graph_id": "ex:a/graph", "checks": checks}},
             "shared": {"nodes": [rec("ex:a/person/p", "Person"), rec("ex:a/person/q", "Person")], "links": []},
             "sources": {s: {"source": f"ex:a/source/{s}", "nodes": [rec(f"ex:a/source/{s}", "Source"), rec(r)],
                             "links": []} for s, r in (("s1", "ex:a/s1/x"), ("s2", "ex:a/s2/y"))}}
    sub = graphparts.subset(parts, ["s1"])
    assert [c["records"] for c in sub["header"]["graph"]["checks"]] == [["ex:a/s1/x"]]
    assert "acknowledged" not in sub["header"]["graph"]["checks"][0]           # it was on a record left out
    assert [n["id"] for n in sub["shared"]["nodes"]] == ["ex:a/person/p"]      # the checker of the check kept, not q
    sub2 = graphparts.subset(parts, ["s2"])
    assert [c["records"] for c in sub2["header"]["graph"]["checks"]] == [["ex:a/s2/y"], ["ex:a/s2/y"]]
    assert sorted(n["id"] for n in sub2["shared"]["nodes"]) == ["ex:a/person/p", "ex:a/person/q"]


def test_review_sample_returns_the_check_to_fill_in(capsys):
    assert main(["--repo", str(REPO), "review", "sample", str(CAMPAIGN), "--fraction", "0.3", "--seed", "3",
                 "--include-flagged"]) == 0
    out = json.loads(capsys.readouterr().out)
    check = out["check"]
    assert check["selection"] == "sample_and_flagged" and check["fraction"] == 0.3 and check["seed"] == 3
    assert check["records"] == [r["id"] for r in out["sample"]] and "checked_by" in out["to_record"]
