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
    # each from its own counts: nothing extracted and two fields missed is a recall of 0, with no precision
    assert quality({"fields_checked": 0, "fields_wrong": 0, "fields_missed": 2}) == {"precision": None, "recall": 0.0}


def test_an_acknowledgement_that_several_warnings_match_acknowledges_none():
    """An acknowledgement names one warning: a text two warnings share is reported and closes neither, whatever the
    order of the acknowledgements."""
    doc = campaign()
    design = next(n for n in doc["nodes"] if n["id"] == DESIGN)
    design["props"]["unmodeled"].append("the order in which the robot dispensed the nitrates (Methods)")
    assert sum(w["record"] == DESIGN for w in report(doc)["warnings"]) == 1       # the first one stays acknowledged
    doc["graph"]["checks"][0]["acknowledged"][0]["warning"] = "unmodeled context:"
    rep = report(doc)
    assert "acknowledged" not in rep and sum(w["record"] == DESIGN for w in rep["warnings"]) == 2
    assert any("2 warnings on ex:sdl/design/campaign contain 'unmodeled context:'" in w["message"]
               for w in rep["warnings"])


def test_an_exact_acknowledgement_beside_an_ambiguous_one_in_either_order():
    """Each acknowledgement is matched against every warning, so their order changes nothing: the exact one closes its
    warning, the ambiguous one closes none (it would close the other if read against what the first left)."""
    for order in (0, 1):
        doc = campaign()
        design = next(n for n in doc["nodes"] if n["id"] == DESIGN)
        design["props"]["unmodeled"].append("the order in which the robot dispensed the nitrates (Methods)")
        exact = doc["graph"]["checks"][0]["acknowledged"][0]
        vague = dict(exact, warning="unmodeled context:")
        doc["graph"]["checks"][0]["acknowledged"] = [exact, vague] if order == 0 else [vague, exact]
        rep = report(doc)
        assert [a["message"] for a in rep["acknowledged"]] == [next(w for w in report(campaign())["acknowledged"])["message"]]
        open_ = [w["message"] for w in rep["warnings"] if w["record"] == DESIGN]
        assert len(open_) == 1 and "dispensed the nitrates" in open_[0]
        assert any("2 warnings on ex:sdl/design/campaign contain 'unmodeled context:'" in w["message"] for w in rep["warnings"])


def test_a_withheld_id_is_matched_as_an_id_not_as_a_prefix():
    """Withholding round-1 keeps an acknowledgement of round-10 and a note that names round-10; a path into round-1 is
    round-1."""
    g = {"checks": [{"checked_by": "p", "checked_on": "2026-10-21", "records": ["ex:a/round-10"], "scope": "s",
                     "outcome": "passed", "note": "ex:a/round-10 was read twice.",
                     "acknowledged": [{"record": "ex:a/round-10", "warning": "w", "reason": "as stated"}]}]}
    kept, _ = prune(g, {"ex:a/round-10", "p"}, {"ex:a/round-1"})
    assert kept["checks"][0]["acknowledged"] and kept["checks"][0]["note"] == "ex:a/round-10 was read twice."
    g["checks"][0]["note"] = "compared with ex:a/round-1/result_values/x."
    assert "checks" not in prune(g, {"ex:a/round-10", "p"}, {"ex:a/round-1"})[0]


def test_a_malformed_check_is_reported_never_a_crash():
    doc = campaign()
    doc["graph"]["checks"][0].update(records=1, acknowledged="all of them", fields_checked="many")
    rep = report(doc)
    assert not rep["valid"] and rep["errors"] and "acknowledged" not in rep


def test_prune_keeps_a_check_to_the_records_held():
    g = campaign()["graph"]
    kept, removed = prune(g, {"ex:sdl/test/round-1", "ex:sdl/person/checker"})
    assert kept["checks"][0]["records"] == ["ex:sdl/test/round-1"] and "acknowledged" not in kept["checks"][0]
    assert removed == 6                                    # five records and one acknowledgement
    gone, removed = prune(g, {"ex:sdl/test/round-1"})       # its checker left out: the check goes
    assert "checks" not in gone and removed == 6
    assert g["checks"][0]["records"][0] == DESIGN          # the graph given is not changed


def test_no_id_of_a_record_left_out_stays_in_the_checks():
    """What a view or a bundle leaves out leaves no id behind: an acknowledgement whose warning names such a record goes,
    and so does a check whose own text names one. A check that loses records loses its counts and its sample, which
    were over all of them."""
    g = campaign()["graph"]
    g["checks"][0]["acknowledged"].append({"record": "ex:sdl/test/round-1", "reason": "as the source states it",
                                           "warning": "inputs revised: ex:sdl/dataset/container"})
    present = set(g["checks"][0]["records"]) | {"ex:sdl/person/checker"}
    kept, _ = prune(g, present, {"ex:sdl/dataset/container"})
    assert [a["record"] for a in kept["checks"][0]["acknowledged"]] == [DESIGN]
    assert kept["checks"][0]["fields_checked"] == 46                   # every record it checked is held: counts stay
    named = copy.deepcopy(g)
    named["checks"][0]["note"] += " The container (ex:sdl/dataset/container) was not checked."
    assert "checks" not in prune(named, present, {"ex:sdl/dataset/container"})[0]
    fewer, _ = prune(g, present - {"ex:sdl/test/round-2"}, {"ex:sdl/test/round-2"})
    c = fewer["checks"][0]
    assert not {"fields_checked", "fields_wrong", "fields_missed", "fraction", "seed", "selection"} & set(c)
    assert "keeps 5 of the 6 records" in c["note"] and quality(c) == {"precision": None, "recall": None}
    # through a filtered view and a bundle
    doc = campaign()
    doc["graph"]["checks"][0]["acknowledged"].append({"record": "ex:sdl/test/round-1", "reason": "as stated",
                                                      "warning": "inputs revised: ex:sdl/dataset/container"})
    container = next(n for n in doc["nodes"] if n["id"] == "ex:sdl/dataset/container")
    container["props"]["stewardship"] = {"access": "institution", "contributed_by": []}
    view = pgraph.filter_for(doc, [], "2026-10-21")
    bundle, _ = pgraph.restrict_to(doc, {"access": "public"}, "2026-10-21")
    for d in (view, bundle):
        assert "ex:sdl/dataset/container" not in {n["id"] for n in d["nodes"]}
        assert "ex:sdl/dataset/container" not in json.dumps(d["graph"])
        c = d["graph"]["checks"][0]
        # every record it checked is there, but the cross-validation without its execution environment (the container):
        # the counts were over what the view no longer shows
        assert len(c["records"]) == 6 and "fields_checked" not in c and "1 of them only in part" in c["note"]


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


def test_a_check_of_a_shared_link_keeps_its_checker_in_a_subset():
    """A check that covers only a link between shared records (reached by the sources kept) keeps its checker, who is
    brought into the subset with it."""
    def rec(rid, label="Experiment"):
        return {"id": rid, "label": label, "props": {"name": rid, "origin": "synthetic"}}
    link = {"id": "ex:a/link/shared", "type": "INCLUDES", "source": "ex:a/data/d1", "target": "ex:a/data/d2",
            "props": {"origin": "synthetic"}}
    checks = [{"checked_by": "ex:a/person/q", "checked_on": "2026-10-22", "records": [link["id"]],
               "scope": "the inclusion against the source", "outcome": "passed"}]
    parts = {"header": {"directed": True, "multigraph": True, "graph": {"graph_id": "ex:a/graph", "checks": checks}},
             "shared": {"nodes": [rec("ex:a/data/d1", "Dataset"), rec("ex:a/data/d2", "Dataset"),
                                  rec("ex:a/person/q", "Person")], "links": [link]},
             "sources": {"s1": {"source": "ex:a/source/s1", "nodes": [rec("ex:a/source/s1", "Source"), rec("ex:a/s1/x")],
                                "links": [{"id": "ex:a/s1/link/1", "type": "HAS_INPUT", "source": "ex:a/s1/x",
                                           "target": "ex:a/data/d1", "props": {"origin": "synthetic"}}]}}}
    sub = graphparts.subset(parts, ["s1"])
    assert [c["records"] for c in sub["header"]["graph"]["checks"]] == [[link["id"]]]
    assert {n["id"] for n in sub["shared"]["nodes"]} == {"ex:a/data/d1", "ex:a/data/d2", "ex:a/person/q"}
    assert [lk["id"] for lk in sub["shared"]["links"]] == [link["id"]]


def test_review_sample_returns_the_check_to_fill_in(capsys):
    assert main(["--repo", str(REPO), "review", "sample", str(CAMPAIGN), "--fraction", "0.3", "--seed", "3",
                 "--include-flagged"]) == 0
    out = json.loads(capsys.readouterr().out)
    check = out["check"]
    assert check["selection"] == "sample_and_flagged" and check["fraction"] == 0.3 and check["seed"] == 3
    assert check["records"] == [r["id"] for r in out["sample"]] and "checked_by" in out["to_record"]
