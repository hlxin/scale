"""Source lifecycle (in the science kernel, and the tooling that ships with it): a source's publication status derived
from notice links, the records that rest on retracted sources flagged by the validator, left out of query answers by
default and marked in the kg-bundle export; never rewritten, never deleted. Documents without notices are unchanged.
Documents are checked under the version they pin; the synthetic lifecycle fixtures (tools/tests/fixtures/source-lifecycle/)
under the head."""

import json
import shutil

import pytest

from conftest import COMPETENCY, REPO, spec_of
from scale import kgbundle, lifecycle, pgraph, pgraph_query
from scale.competency import run, run_question
from scale.util import ScaleError, dump_yaml, load_doc, load_yaml
from test_graph_search_query import _bundle_validator

P9 = REPO / "tools/tests/fixtures/source-lifecycle"            # the fixtures/ of the lifecycle's examples
FIXTURES_PIN = P9 / "pass-retraction-scope.json"                  # the lifecycle fixtures all pin one version
X = REPO / "domain/examples/scale-graph"
EXAMPLE = X / "source-lifecycle/retracted-source.json"
Y = "ex:exmpl/lifecycle-example"
PAPER_A, PAPER_B, NOTICE = f"{Y}/source/paper-a", f"{Y}/source/paper-b", f"{Y}/source/retraction-notice-b"
TEST_A, TEST_B = f"{Y}/test/zno", f"{Y}/test/zncr"


@pytest.fixture(scope="module")
def spec():
    """The schema the lifecycle example pins."""
    return spec_of(load_doc(EXAMPLE))


@pytest.fixture(scope="module")
def cand():
    """The schema the lifecycle fixtures pin (the head while they pin it, else its frozen copy)."""
    return spec_of(load_doc(FIXTURES_PIN))


@pytest.fixture()
def doc():
    return load_doc(EXAMPLE)


def _warnings(rep, code: str) -> dict[str, str]:
    return {w["record"]: w["message"] for w in rep.warnings if w["message"].startswith(code + ":")}


def _link(lid, t, a, b, **p):
    return {"id": lid, "type": t, "source": a, "target": b, "props": {"origin": "synthetic", **p}}


# ------------------------------------------------------------------------------------------ derived status
def test_publication_status_is_derived_from_notice_links(cand):
    st = lifecycle.statuses(load_doc(P9 / "pass-retraction-scope.json"), cand)
    x = "ex:exmpl/lifecycle"
    assert lifecycle.status_of(st, f"{x}/source/paper-a") == "retracted"
    assert lifecycle.status_of(st, f"{x}/source/paper-b") == "partially_retracted"       # scope partial
    assert lifecycle.status_of(st, f"{x}/dataset/b-table-2") == "retracted"              # the retracted part, as a dataset
    assert st[f"{x}/source/paper-a"]["notices"] == [f"{x}/link/retracts-a"]
    assert lifecycle.status_of(st, f"{x}/source/retraction-notice-a") == lifecycle.UNKNOWN   # a notice has no status itself
    corrected = lifecycle.statuses(load_doc(P9 / "pass-correction.json"))
    assert lifecycle.status_of(corrected, f"{x}/source/paper-a") == "corrected"
    concern = lifecycle.statuses(load_doc(P9 / "pass-expression-of-concern.json"))
    assert lifecycle.status_of(concern, f"{x}/source/paper-b") == "expression_of_concern"
    checked = lifecycle.statuses(load_doc(P9 / "pass-status-check.json"), cand)
    assert checked[f"{x}/source/paper-a"] == {"status": lifecycle.UNKNOWN, "notices": [], "status_check": {
        "checked_on": "2026-10-06", "checked_via": "the publisher's article page, read by a curator (invented)",
        "result": "no_notice_found"}}
    assert f"{x}/dataset/rates" in checked                                              # a dataset can be checked too
    # the most serious notice decides; a withdrawal counts as retracted; a status is never read from a property
    d = load_doc(P9 / "pass-correction.json")
    d["links"].append(_link(f"{x}/link/withdrawn", "UPDATES", f"{x}/source/correction", f"{x}/source/paper-a",
                            update_type="withdrawal"))
    d["nodes"][0]["props"]["publication_status"] = "current"
    st = lifecycle.statuses(d)
    assert lifecycle.status_of(st, f"{x}/source/paper-a") == "withdrawn" and "withdrawn" in lifecycle.RETRACTED
    assert lifecycle.statuses(load_doc(X / "example.json")) == {}


def test_documents_without_notices_validate_as_before():
    for f in [X / "example.json", *sorted((X / "driving-force-examples").glob("*.json"))]:
        d = load_doc(f)
        rep = pgraph.validate(d, spec_of(d))
        out = rep.as_dict()
        assert rep.lifecycle is None and set(out["summary"]) == {"error", "warning"}, f
        assert "source_lifecycle" not in (out.get("conformance") or {}), f
        assert not any(w["message"].split(":")[0] in ("rests_on_retracted_source", "partially_rests_on_retracted_source",
                                                       "retraction_undated", "retracted_without_notice") for w in rep.warnings)


# ------------------------------------------------------------------------------------------ validator (SL-2)
def test_the_validator_flags_what_rests_on_retracted_sources(doc, spec):
    rep = pgraph.validate(doc, spec)
    assert rep.ok
    flagged = _warnings(rep, "rests_on_retracted_source")
    assert set(flagged) == {TEST_B, f"{Y}/catalyst/zncr", f"{Y}/catalyst-sample/zncr", f"{Y}/link/zncr/catalyst"}
    assert all("flagged, not rewritten" in m and PAPER_B in m for m in flagged.values())
    assert not _warnings(rep, "partially_rests_on_retracted_source")
    assert rep.lifecycle == {"sources_by_status": {"retracted": 1}, "sources_checked": 0,
                             "rests_on_retracted_source": 4, "partially_rests_on_retracted_source": 0}
    out = rep.as_dict()
    assert out["summary"]["source_lifecycle"] == rep.lifecycle and out["conformance"]["source_lifecycle"] == rep.lifecycle
    assert {n["id"] for n in doc["nodes"]} == {n["id"] for n in load_doc(EXAMPLE)["nodes"]}   # nothing removed or rewritten
    assert doc == load_doc(EXAMPLE)


def test_resting_follows_one_hop_along_inputs_and_produced_by(doc, spec):
    # test A is fed with a feed only the retracted paper reports, and a value of it was produced by test B
    feed = next(n for n in doc["nodes"] if n["id"] == f"{Y}/feed/co-2h2")
    feed["props"]["evidence"] = [{"source": PAPER_B, "locator": "Table 2", "kind": "table"}]
    doc["links"].append(_link(f"{Y}/feed/co-2h2/reported-in/paper-b", "REPORTED_IN", feed["id"], PAPER_B, locators=["Table 2"]))
    rep = pgraph.validate(doc, spec)
    part = _warnings(rep, "partially_rests_on_retracted_source")
    assert TEST_A in part and PAPER_B in part[TEST_A]                               # FED_WITH specializes HAS_INPUT
    assert feed["id"] in _warnings(rep, "rests_on_retracted_source")
    d2 = load_doc(EXAMPLE)
    a = next(n for n in d2["nodes"] if n["id"] == TEST_A)
    a["props"]["results"]["methanol_production"].update(origin="derived", produced_by=TEST_B)
    assert TEST_A in _warnings(pgraph.validate(d2, spec), "partially_rests_on_retracted_source")
    # a record that uses an input a retracted dataset includes is told so: the input is included, not the record
    d3 = load_doc(EXAMPLE)
    table, notice_t, feed_id = f"{Y}/dataset/feed-table", f"{Y}/source/notice-t", f"{Y}/feed/co-2h2"
    ev = [{"kind": "table", "locator": "Table 1", "source": PAPER_A, "note": "feed composition (invented)"}]
    next(n for n in d3["nodes"] if n["id"] == feed_id)["props"]["evidence"] = ev
    d3["nodes"] += [{"id": table, "label": "Dataset", "props": {"name": "Table 1 of paper A (invented)", "data_kind": "table",
                                                                "availability": "not_reported", "origin": "synthetic", "evidence": ev}},
                    {"id": notice_t, "label": "Source", "props": {"name": "Notice T (invented)", "title": "Notice T (invented)",
                                                                  "kind": "retraction_notice", "year": 2024, "origin": "synthetic"}}]
    d3["links"] += [_link(f"{feed_id}/reported-in/paper-a", "REPORTED_IN", feed_id, PAPER_A),
                    _link(f"{table}/reported-in/paper-a", "REPORTED_IN", table, PAPER_A),
                    _link(f"{Y}/link/retracts-t", "RETRACTS", notice_t, table, retracted_on="2024-01-01"),
                    _link(f"{table}/includes/feed", "INCLUDES", table, feed_id)]
    rep = pgraph.validate(d3, spec)
    assert rep.ok, rep.errors[:3]
    assert lifecycle.resting(d3, spec)[TEST_A]["dataset_records"] == {table: [feed_id]}
    msg = _warnings(rep, "partially_rests_on_retracted_source")[TEST_A]
    assert f"uses {feed_id}, included in the retracted dataset {table}, which retracts its evidence from {PAPER_A}" in msg
    assert f"included in the retracted dataset {table}, which retracts" in _warnings(rep, "rests_on_retracted_source")[feed_id]
    assert "uses" not in _warnings(rep, "rests_on_retracted_source")[feed_id]
    assert lifecycle.input_edges(spec) >= {"HAS_INPUT", "FED_WITH", "USES_ELECTRODE", "IN_ELECTROLYTE"}


def test_claims_retractions_without_notices_and_undated_retractions_are_flagged(doc, spec):
    claim = lambda cid, status, src: {"id": cid, "label": "Claim", "props": {  # noqa: E731
        "name": cid, "statement": "ZnCr2O4 is more active than ZnO (invented).", "claim_kind": "comparison",
        "claim_status": status, "origin": "synthetic", "evidence": [{"source": src, "locator": "Table 2", "kind": "table"}]}}
    doc["nodes"] += [claim(f"{Y}/claim/supported", "supported", PAPER_B), claim(f"{Y}/claim/retracted", "retracted", PAPER_A),
                     claim(f"{Y}/claim/noticed", "retracted", PAPER_B)]
    for c in ("supported", "retracted", "noticed"):
        src = PAPER_A if c == "retracted" else PAPER_B
        doc["links"].append(_link(f"{Y}/claim/{c}/reported-in", "REPORTED_IN", f"{Y}/claim/{c}", src, locators=["Table 2"]))
    retracts = next(e for e in doc["links"] if e["type"] == "RETRACTS")
    del retracts["props"]["retracted_on"]
    rep = pgraph.validate(doc, spec)
    assert rep.ok
    assert set(_warnings(rep, "supported_on_retracted_sources")) == {f"{Y}/claim/supported"}
    assert set(_warnings(rep, "retracted_without_notice")) == {f"{Y}/claim/retracted"}     # its source is not retracted
    assert set(_warnings(rep, "retraction_undated")) == {retracts["id"]}
    doc["links"].append(_link(f"{Y}/link/retracts-claim", "RETRACTS", NOTICE, f"{Y}/claim/retracted", retracted_on="2022-02-01"))
    assert not _warnings(pgraph.validate(doc, spec), "retracted_without_notice")         # now a notice reaches it


def test_the_candidate_types_the_new_fields_and_checks_scope_locators(cand):
    for f in ("pass-retraction-scope", "pass-correction", "pass-expression-of-concern", "pass-preprint-of", "pass-status-check"):
        rep = pgraph.validate(load_doc(P9 / f"{f}.json"), cand)
        assert rep.ok, (f, rep.errors)
    rep = pgraph.validate(load_doc(P9 / "pass-retraction-scope.json"), cand)
    via = _warnings(rep, "rests_on_retracted_source")
    assert "included in the retracted dataset ex:exmpl/lifecycle/dataset/b-table-2" in via["ex:exmpl/lifecycle/claim/b-table-2"]
    msgs = {f: [e["message"] for e in pgraph.validate(load_doc(P9 / f"{f}.json"), cand).errors]
            for f in ("fail-update-type", "fail-updates-without-evidence", "fail-status-check-date", "fail-scope-locators-full")}
    assert any("update_type: 'retraction' is not one of" in m for m in msgs["fail-update-type"])
    assert msgs["fail-updates-without-evidence"] == ["missing required property 'evidence'"]
    assert msgs["fail-status-check-date"] == ["status_check.checked_on: expected an ISO date: YYYY, YYYY-MM or YYYY-MM-DD"]
    assert any(m.startswith("scope_locators go only with a partial retraction") for m in msgs["fail-scope-locators-full"])
    d = load_doc(P9 / "pass-status-check.json")
    del d["nodes"][0]["props"]["status_check"]["result"]
    d["nodes"][0]["props"]["status_check"]["by"] = "someone"
    errs = [e["message"] for e in pgraph.validate(d, cand).errors]
    assert "status_check: unknown field 'by'" in errs and "status_check: a status_check needs result" in errs


def test_describe_shows_the_new_fields(cand):
    out = pgraph.describe(cand, ["Source", "Dataset", "UPDATES", "SAME_WORK_AS", "RETRACTS"])
    src = out["labels"]["Source"]["properties"]
    assert src["status_check"].startswith("status_check{checked_on: date, checked_via: text, result: enum[no_notice_found|notice_found]}")
    assert {"text_version", "text_sha256", "retrieved_from", "retrieved_on", "published_on", "date_basis", "priority_date"} <= set(src)
    assert "withdrawal_notice" in src["kind"] and "issued" in out["labels"]["Dataset"]["properties"]
    assert out["edges"]["UPDATES"]["properties"]["update_type"].startswith("enum[correction|")
    assert set(out["edges"]["RETRACTS"]["properties"]) >= {"scope", "scope_locators", "retracted_on"}
    assert out["edges"]["SAME_WORK_AS"]["properties"]["relation"].startswith("enum[preprint_of|")
    assert pgraph.describe(cand)["status_check_fields"] == ["checked_on", "checked_via", "result"]


# ------------------------------------------------------------------------------------------ queries (SL-3)
PLAN = {"match": {"label": "CatalyticTest", "as": "test"}, "return": ["test.name"], "evidence": True}


def test_queries_label_retracted_evidence_and_leave_out_what_rests_only_on_it(doc, spec):
    res = pgraph_query.run(doc, spec, PLAN)
    assert res["status"] == "answered" and [r["bound"]["test"] for r in res["rows"]] == [TEST_A]
    assert res["excluded"] == [{"record": TEST_B, "reason": "rests_on_retracted_source", "sources": [PAPER_B]}]
    assert any("rest only on retracted or withdrawn sources" in x for x in res["limitations"])
    assert {e["source_status"] for r in res["rows"] for e in r["evidence"]} == {"current_or_unknown"}
    kept = pgraph_query.run(doc, spec, {**PLAN, "include_retracted": True})
    assert kept["row_count"] == 2 and kept["excluded"] == []
    by = {r["bound"]["test"]: {e["source_status"] for e in r["evidence"]} for r in kept["rows"]}
    assert by == {TEST_A: {"current_or_unknown"}, TEST_B: {"retracted"}}
    only_b = {**PLAN, "match": {**PLAN["match"], "where": [{"prop": "name", "op": "eq", "value": "ZnCr2O4, run 1"}]}}
    assert pgraph_query.run(doc, spec, only_b)["status"] == "no_matching_record"         # left out, not missing context
    # without evidence in the answer the row is still judged by its evidence
    assert pgraph_query.run(doc, spec, {**PLAN, "evidence": False})["row_count"] == 1


def test_a_retracted_dataset_leaves_out_the_records_it_includes(cand):
    d = load_doc(P9 / "pass-retraction-scope.json")
    plan = {"match": {"label": "Claim", "as": "claim"}, "return": ["claim.statement"], "evidence": True}
    res = pgraph_query.run(d, cand, plan)
    assert res["row_count"] == 0 and res["excluded"][0]["reason"] == "rests_on_retracted_source"
    ev = pgraph_query.run(d, cand, {**plan, "include_retracted": True})["rows"][0]["evidence"][0]
    assert ev["source_status"] == "partially_retracted" and ev["retracted_in_dataset"] == "ex:exmpl/lifecycle/dataset/b-table-2"
    # the excluded row names no retracted source (the paper is only partly retracted), and the dataset apart
    assert res["excluded"] == [{"record": f"{Z}/claim/b-table-2", "reason": "rests_on_retracted_source", "sources": [],
                                "datasets": [TABLE]}]
    msg = _warnings(pgraph.validate(d, cand), "rests_on_retracted_source")[f"{Z}/claim/b-table-2"]
    assert "retracted sources" not in msg and f"which retracts its evidence from {Z}/source/paper-b" in msg


def test_a_retracted_dataset_reported_in_its_own_notice_still_comes_from_the_paper(cand):
    """A dataset that cites (and is REPORTED_IN) the notice retracting it: the notice is not where its data came
    from, so the partial retraction still names the paper and the claim is still left out by default."""
    d = load_doc(P9 / "pass-retraction-scope.json")
    notice = f"{Z}/source/retraction-notice-b"
    table = next(n for n in d["nodes"] if n["id"] == TABLE)
    table["props"]["evidence"] = [{"kind": "text", "locator": "notice, paragraph 2", "source": notice,
                                   "note": "Table 2 is retracted (invented)"}]
    d["links"].append({"id": f"{TABLE}/reported-in/notice", "type": "REPORTED_IN", "source": TABLE, "target": notice,
                       "props": {"origin": "synthetic", "locators": ["paragraph 2"]}})
    assert pgraph.validate(d, cand).ok
    st = lifecycle.statuses(d, cand)
    assert lifecycle.dataset_sources(d, st, cand) == {TABLE: [f"{Z}/source/paper-b"]}
    plan = {"match": {"label": "Claim", "as": "claim"}, "return": ["claim.statement"], "evidence": True}
    res = pgraph_query.run(d, cand, plan)
    assert res["row_count"] == 0 and res["excluded"][0]["reason"] == "rests_on_retracted_source"
    assert f"{Z}/claim/b-table-2" in _warnings(pgraph.validate(d, cand), "rests_on_retracted_source")


Z = "ex:exmpl/lifecycle"
TABLE = f"{Z}/dataset/b-table-2"


def _with_current_source(d: dict) -> dict:
    """pass-retraction-scope with an independent, current source that also supports the claim of Table 2."""
    d["nodes"].append({"id": f"{Z}/source/paper-c", "label": "Source", "props": {
        "name": "A replication over the invented alloy (invented)", "title": "A replication over the invented alloy (invented)",
        "kind": "article", "year": 2023, "origin": "synthetic"}})
    claim = next(n for n in d["nodes"] if n["id"] == f"{Z}/claim/b-table-2")
    claim["props"]["evidence"].append({"kind": "table", "locator": "Table 1", "source": f"{Z}/source/paper-c",
                                       "note": "first order in hydrogen again (invented)"})
    return d


def test_a_retracted_dataset_retracts_only_the_evidence_from_its_own_sources(cand):
    """A record a retracted dataset includes loses the evidence that came from the dataset's source, not the
    support of an independent current source: it partially rests on retracted evidence and stays in answers."""
    d = _with_current_source(load_doc(P9 / "pass-retraction-scope.json"))
    claim = f"{Z}/claim/b-table-2"
    st = lifecycle.statuses(d, cand)
    # the graph says neither where the table is reported nor whose evidence it cites: the notice that retracts it
    # retracts one source in part, paper B, which is the table's source
    assert lifecycle.dataset_sources(d, st, cand) == {TABLE: [f"{Z}/source/paper-b"]}
    assert lifecycle.resting(d, cand, st)[claim] == {"rests": "some", "sources": [], "datasets": [TABLE],
                                                      "dataset_sources": {TABLE: [f"{Z}/source/paper-b"]},
                                                      "dataset_records": {TABLE: [claim]}}
    rep = pgraph.validate(d, cand)
    assert claim not in _warnings(rep, "rests_on_retracted_source")
    part = _warnings(rep, "partially_rests_on_retracted_source")[claim]
    assert "paper-c" not in part and "retracted sources" not in part and TABLE in part
    plan = {"match": {"label": "Claim", "as": "claim"}, "return": ["claim.statement"], "evidence": True}
    res = pgraph_query.run(d, cand, plan)
    assert res["status"] == "answered" and res["row_count"] == 1 and res["excluded"] == []
    by = {e["source"]: e for e in res["rows"][0]["evidence"]}
    assert by[f"{Z}/source/paper-b"]["retracted_in_dataset"] == TABLE
    assert "retracted_in_dataset" not in by[f"{Z}/source/paper-c"] and by[f"{Z}/source/paper-c"]["source_status"] == "current_or_unknown"
    # the dataset's source can also be the Source it is REPORTED_IN (no notice reaching the paper)
    d2 = _with_current_source(load_doc(P9 / "pass-retraction-scope.json"))
    d2["links"] = [e for e in d2["links"] if e["id"] != f"{Z}/link/retracts-b"]
    d2["links"].append(_link(f"{TABLE}/reported-in/paper-b", "REPORTED_IN", TABLE, f"{Z}/source/paper-b", locators=["Table 2"]))
    st2 = lifecycle.statuses(d2, cand)
    assert lifecycle.dataset_sources(d2, st2, cand) == {TABLE: [f"{Z}/source/paper-b"]}
    assert lifecycle.resting(d2, cand, st2)[claim]["rests"] == "some"
    # a dataset whose source the graph does not name, including a record of the current source alone: the record
    # rests on the dataset as one more item, so partially; the current source is never named as retracted
    d3 = _with_current_source(load_doc(P9 / "pass-retraction-scope.json"))
    d3["links"] = [e for e in d3["links"] if e["id"] != f"{Z}/link/retracts-b"]
    next(n for n in d3["nodes"] if n["id"] == claim)["props"]["evidence"].pop(0)
    r = lifecycle.resting(d3, cand)[claim]
    assert r == {"rests": "some", "sources": [], "datasets": [TABLE], "dataset_sources": {TABLE: []},
                 "dataset_records": {TABLE: [claim]}}
    assert pgraph_query.run(d3, cand, plan)["row_count"] == 1
    # a fully retracted source is named as such, beside the dataset
    d4 = load_doc(P9 / "pass-retraction-scope.json")
    next(n for n in d4["nodes"] if n["id"] == claim)["props"]["evidence"].append(
        {"kind": "text", "locator": "section 2", "source": f"{Z}/source/paper-a"})
    r = lifecycle.resting(d4, cand)[claim]
    assert r == {"rests": "all", "sources": [f"{Z}/source/paper-a"], "datasets": [TABLE],
                 "dataset_sources": {TABLE: [f"{Z}/source/paper-b"]}, "dataset_records": {TABLE: [claim]}}
    ex = pgraph_query.run(d4, cand, plan)["excluded"]
    assert ex == [{"record": claim, "reason": "rests_on_retracted_source", "sources": [f"{Z}/source/paper-a"], "datasets": [TABLE]}]


def test_a_notice_that_also_reaches_an_independent_source_does_not_retract_its_evidence(cand):
    """The notice that retracts a dataset may also correct, or retract in part, another source that supports the
    same record independently: that source's evidence still stands, the record at most partially rests on
    retracted evidence and stays in answers, and no warning or exclusion names that source."""
    claim, paper_b, paper_c, notice = (f"{Z}/claim/b-table-2", f"{Z}/source/paper-b", f"{Z}/source/paper-c",
                                       f"{Z}/source/retraction-notice-b")
    plan = {"match": {"label": "Claim", "as": "claim"}, "return": ["claim.statement"], "evidence": True}
    ev = [{"kind": "text", "locator": "notice", "source": notice, "note": "the notice (invented)"}]
    corrects = _link(f"{Z}/link/corrects-c", "UPDATES", notice, paper_c, update_type="correction",
                     updated_on="2022-02-01", evidence=ev)
    retracts = _link(f"{Z}/link/retracts-c", "RETRACTS", notice, paper_c, scope="partial", scope_locators=["Figure 9"],
                     retracted_on="2022-02-01", evidence=ev)

    def variant(extra: dict, reported: bool) -> dict:
        d = _with_current_source(load_doc(P9 / "pass-retraction-scope.json"))
        d["links"] += [extra, _link(f"{claim}/reported-in/paper-c", "REPORTED_IN", claim, paper_c, locators=["Table 1"])]
        if reported:                       # the table is REPORTED_IN paper B and cites it: the graph names its source
            d["links"].append(_link(f"{TABLE}/reported-in/paper-b", "REPORTED_IN", TABLE, paper_b, locators=["Table 2"]))
            next(n for n in d["nodes"] if n["id"] == TABLE)["props"]["evidence"] = [
                {"kind": "table", "locator": "Table 2", "source": paper_b, "note": "the table (invented)"}]
        return d

    for extra in (corrects, retracts):
        for reported in (True, False):
            d = variant(extra, reported)
            st = lifecycle.statuses(d, cand)
            assert lifecycle.status_of(st, paper_c) in ("corrected", "partially_retracted")
            rep = pgraph.validate(d, cand)
            assert rep.ok, rep.errors[:3]
            assert claim not in _warnings(rep, "rests_on_retracted_source"), (extra["id"], reported)
            part = _warnings(rep, "partially_rests_on_retracted_source")[claim]
            assert "paper-c" not in part and "retracted sources" not in part
            res = pgraph_query.run(d, cand, plan)
            assert res["row_count"] == 1 and res["excluded"] == [], (extra["id"], reported)
            by = {e["source"]: e for e in pgraph_query.run(d, cand, {**plan, "include_retracted": True})["rows"][0]["evidence"]}
            assert "retracted_in_dataset" not in by[paper_c]
            r = lifecycle.resting(d, cand, st)[claim]
            if reported or extra is corrects:
                # the table's own source is paper B (REPORTED_IN, its evidence, or the one source the notice
                # retracts in part; a correction says nothing about where a table came from)
                assert lifecycle.dataset_sources(d, st, cand) == {TABLE: [paper_b]}
                assert r["dataset_sources"] == {TABLE: [paper_b]} and by[paper_b]["retracted_in_dataset"] == TABLE
            else:
                # the notice retracts two sources in part and the graph names neither as the table's: the table is
                # one item of support of its own, and no source's evidence is taken away with it
                assert lifecycle.dataset_sources(d, st, cand) == {TABLE: []}
                assert r["dataset_sources"] == {TABLE: []} and "retracted_in_dataset" not in by[paper_b]
            assert r["rests"] == "some" and r["sources"] == []


def test_two_retracted_datasets_each_retract_only_their_own_sources_evidence(cand):
    """A record two retracted datasets include: each dataset retracts only the evidence from its own sources, so
    the evidence from paper B is attributed to the table of paper B, never to the other dataset."""
    d = _with_current_source(load_doc(P9 / "pass-retraction-scope.json"))
    claim, other = f"{Z}/claim/b-table-2", f"{Z}/dataset/a-q"
    d["nodes"] += [{"id": f"{Z}/source/paper-q", "label": "Source", "props": {
                       "name": "Another invented paper (invented)", "title": "Another invented paper (invented)",
                       "kind": "article", "year": 2021, "origin": "synthetic"}},
                   {"id": f"{Z}/source/notice-q", "label": "Source", "props": {
                       "name": "Retraction of another invented paper (invented)",
                       "title": "Retraction of another invented paper (invented)", "kind": "retraction_notice",
                       "year": 2024, "origin": "synthetic"}},
                   {"id": other, "label": "Dataset", "props": {"name": "Table 1 of paper Q (invented)"}}]
    d["links"] += [_link(f"{other}/reported-in/paper-q", "REPORTED_IN", other, f"{Z}/source/paper-q", locators=["Table 1"]),
                   _link(f"{Z}/link/retracts-q", "RETRACTS", f"{Z}/source/notice-q", other, retracted_on="2024-05-01"),
                   _link(f"{other}/includes/b-table-2", "INCLUDES", other, claim)]
    st = lifecycle.statuses(d, cand)
    incl = lifecycle.retracted_inclusions(d, st, cand)
    assert incl[claim] == {other: [f"{Z}/source/paper-q"], TABLE: [f"{Z}/source/paper-b"]}
    assert lifecycle.retracted_by(st, incl, claim, f"{Z}/source/paper-b") == [TABLE]
    assert lifecycle.retracted_by(st, incl, claim, f"{Z}/source/paper-c") == []
    assert lifecycle.unsourced_inclusions(incl, claim, {f"{Z}/source/paper-b", f"{Z}/source/paper-c"}) == [other]
    r = lifecycle.resting(d, cand, st)[claim]
    assert r == {"rests": "some", "sources": [], "datasets": [other, TABLE],
                 "dataset_sources": {other: [], TABLE: [f"{Z}/source/paper-b"]},
                 "dataset_records": {other: [claim], TABLE: [claim]}}
    msg = _warnings(pgraph.validate(d, cand), "partially_rests_on_retracted_source")[claim]
    assert f"included in the retracted dataset {other}; included in the retracted dataset {TABLE}, which retracts its " \
           f"evidence from {Z}/source/paper-b" in msg and "paper-c" not in msg and "paper-q" not in msg
    plan = {"match": {"label": "Claim", "as": "claim"}, "return": ["claim.statement"], "evidence": True}
    res = pgraph_query.run(d, cand, {**plan, "include_retracted": True})
    by = {e["source"]: e for e in res["rows"][0]["evidence"]}
    assert by[f"{Z}/source/paper-b"]["retracted_in_dataset"] == TABLE
    assert "retracted_in_dataset" not in by[f"{Z}/source/paper-c"]
    assert pgraph_query.run(d, cand, plan)["row_count"] == 1           # paper C still supports it
    # without paper C, both datasets are named in the exclusion, each for its own reason
    d["nodes"] = [n for n in d["nodes"] if n["id"] != f"{Z}/source/paper-c"]
    c = next(n for n in d["nodes"] if n["id"] == claim)
    c["props"]["evidence"] = [ev for ev in c["props"]["evidence"] if ev["source"] != f"{Z}/source/paper-c"]
    assert lifecycle.resting(d, cand)[claim]["rests"] == "all"
    assert pgraph_query.run(d, cand, plan)["excluded"] == [{"record": claim, "reason": "rests_on_retracted_source",
                                                             "sources": [], "datasets": [other, TABLE]}]


def test_missing_and_exists_hold_on_an_unbound_optional_variable(doc, spec):
    """A filter on an optional variable that found nothing: missing holds, every other op fails (it used to drop
    every row, so "no notice reaches it" answered no_matching_record)."""
    plan = {"match": {"label": "Source", "as": "src", "where": [{"prop": "kind", "op": "eq", "value": "article"}]},
            "steps": [{"from": "src", "edge": "RETRACTS", "direction": "in", "to": "Source", "as": "notice", "optional": True}],
            "return": ["src.name"]}
    missing = pgraph_query.run(doc, spec, {**plan, "where": [{"var": "notice", "prop": "id", "op": "missing"}]})
    assert missing["status"] == "answered" and [r["bound"]["src"] for r in missing["rows"]] == [PAPER_A]
    exists = pgraph_query.run(doc, spec, {**plan, "where": [{"var": "notice", "prop": "id", "op": "exists"}]})
    assert [r["bound"]["src"] for r in exists["rows"]] == [PAPER_B]
    other = pgraph_query.run(doc, spec, {**plan, "where": [{"var": "notice", "prop": "kind", "op": "eq", "value": "retraction_notice"}]})
    assert [r["bound"]["src"] for r in other["rows"]] == [PAPER_B]


def test_a_where_filter_on_an_undeclared_variable_is_an_error(doc, spec):
    """The unbound shortcut of missing holds only for a variable an optional step declares: a misspelled variable
    is an error, never a filter that every row passes."""
    plan = {"match": {"label": "Source", "as": "src"},
            "steps": [{"from": "src", "edge": "RETRACTS", "direction": "in", "to": "Source", "as": "notice", "optional": True}],
            "return": ["src.name"]}
    with pytest.raises(ScaleError, match="where names the variable 'notcie', which neither match nor a step declares"):
        pgraph_query.run(doc, spec, {**plan, "where": [{"var": "notcie", "prop": "id", "op": "missing"}]})
    with pytest.raises(ScaleError, match="neither match nor a step declares"):
        pgraph_query.run(doc, spec, {"match": {"label": "Source", "as": "src"}, "return": ["src.name"],
                                     "where": [{"var": "notice", "prop": "id", "op": "exists"}]})
    # an edge variable (edge_as) is declared: the filter applies to the link it binds, and an optional step's
    # link left unbound is missing, as its record is
    edge = {**plan, "steps": [{**plan["steps"][0], "edge_as": "r"}]}
    bound = lambda p: sorted(r["bound"]["src"] for r in pgraph_query.run(doc, spec, p)["rows"])   # noqa: E731
    for op in ("missing", "exists"):
        by_link = bound({**edge, "where": [{"var": "r", "prop": "id", "op": op}]})
        assert by_link == bound({**edge, "where": [{"var": "notice", "prop": "id", "op": op}]}) and by_link
    assert PAPER_B in bound({**edge, "where": [{"var": "r", "prop": "id", "op": "exists"}]})
    assert PAPER_A in bound({**edge, "where": [{"var": "r", "prop": "id", "op": "missing"}]})
    assert bound({**edge, "where": [{"var": "r", "prop": "type", "op": "eq", "value": "RETRACTS"}]}) == [PAPER_B]
    assert bound({**edge, "where": [{"var": "r", "prop": "retracted_on", "op": "exists"}]}) == [PAPER_B]
    gap = pgraph_query.run(doc, spec, {**edge, "where": [{"var": "r", "prop": "no_such_prop", "op": "exists"}]})
    assert gap["status"] == "schema_gap" and gap["schema_gaps"] == ["RETRACTS.no_such_prop is not declared"]


def test_the_competency_question_shows_the_exclusion_and_the_opt_in(tmp_path):
    res = run(REPO, ["catalysis"])
    cq5 = next(q for q in res["questions"] if q["id"] == "CQ-05")
    assert cq5["ok"] and cq5["answer"]["rows"] == 1 and cq5["variants"][0]["answer"]["rows"] == 2
    # a variant's unmet expectation fails the question and says which variant
    repo = tmp_path / "repo"
    shutil.copytree(REPO / "domain", repo / "domain",
                    ignore=shutil.ignore_patterns("__pycache__", "proposals", "tests"))
    for d in ("core", "governance"):
        shutil.copytree(REPO / d, repo / d, ignore=shutil.ignore_patterns("__pycache__", "proposals"))
    shutil.copy2(REPO / "scale-release.yaml", repo / "scale-release.yaml")
    (repo / "releases").mkdir()
    q = load_yaml(COMPETENCY / "cq-05-retracted-sources.yaml")
    q["variants"][0]["expect"]["excluded"]["rests_on_retracted_source"] = 1
    q["expect"]["source_statuses"] = ["retracted"]
    p = repo / "domain/competency/cq-05-retracted-sources.yaml"
    p.write_text(dump_yaml(q))
    out = run_question(repo, "catalysis", p)
    assert not out["ok"]
    assert "the evidence never carries source_status ['retracted'] (carried: ['current_or_unknown'])" in out["problems"]
    assert "variant 0 (include_retracted: True): 0 rows excluded for rests_on_retracted_source, expected 1" in out["problems"]
    q["variants"] = [{"expect": {"status": "answered"}}]
    p.write_text(dump_yaml(q))
    assert "variants[0]: a variant names the plan keys it changes (plan)" in run_question(repo, "catalysis", p)["problems"]


# ------------------------------------------------------------------------------------------ kg-bundle export (SL-11, PROV-DATA-04)
def test_the_bundle_export_keeps_lifecycle_links_and_marks_what_rests_on_them(tmp_path, doc, spec):
    m = kgbundle.export(doc, spec, tmp_path / "b", "lifecycle", created="2026-10-06T00:00:00Z")
    g = json.loads((tmp_path / "b/kg/graph.json").read_text())
    nodes = {n["props"].get("scale_id"): n for n in g["nodes"]}
    assert nodes[PAPER_B]["props"]["source_status"] == "retracted" and "source_status" not in nodes[PAPER_A]["props"]
    assert nodes[TEST_B]["props"]["source_status"] == "rests_on_retracted_source" and "source_status" not in nodes[TEST_A]["props"]
    ret = [e for e in g["links"] if e["type"] == "RETRACTS"]
    notice = nodes[NOTICE]["props"]
    # the format wants a quote on every substantive edge: a notice link without one cites the notice's title
    assert len(ret) == 1 and ret[0]["props"]["metadata_only"] is True
    assert ret[0]["props"]["_evidence"] == [{"quote": notice["title"], "source_id": notice["source_id"], "locator": {"section": "title"}}]
    assert ret[0]["props"]["source_paper_ids"] == [notice["source_id"]]
    assert ret[0]["source"] == nodes[NOTICE]["id"] and ret[0]["target"] == nodes[PAPER_B]["id"]
    # the derived properties are declared, as the format asks (it reserves names that begin with an underscore)
    schema = json.loads((tmp_path / "b/kg/schema.json").read_text())
    assert schema["node_types"]["Publication"]["properties"]["source_status"]["type"] == "enum"
    assert schema["edge_types"]["RETRACTS"]["properties"]["metadata_only"]["type"] == "boolean"
    assert "_source_status" not in (tmp_path / "b/kg/graph.json").read_text()
    rep = m["export_report"]
    assert rep["lifecycle_links_metadata_only"] == 1 and "RETRACTS" not in rep["not_exported_links"]
    # the counts are of the records the bundle holds: the link to test B's catalyst has no quote, so it is not
    # exported, and only three of the four records the validator flags are in the bundle
    flagged = {x["props"]["scale_id"] for x in g["nodes"] + g["links"]
               if x["props"].get("source_status") == "rests_on_retracted_source"}
    assert len(flagged) == 3 and rep["source_lifecycle"]["rests_on_retracted_source"] == len(flagged)
    assert rep["source_lifecycle"]["sources_by_status"] == {"retracted": 1}
    v = _bundle_validator()
    if v:
        kgbundle.seal(tmp_path / "b")
        res = v.validate_bundle(tmp_path / "b")
        assert res.ok, [f.message for f in res.errors][:5]
    # a notice without a title cannot be cited: its link is not exported, and the report says so
    untitled = load_doc(EXAMPLE)
    for n in untitled["nodes"]:
        if n["id"] == NOTICE:
            n["props"].pop("title"), n["props"].pop("name")
    rep = kgbundle.export(untitled, spec, tmp_path / "u", "untitled", created="2026-10-06T00:00:00Z")["export_report"]
    assert rep["not_exported_links"]["RETRACTS"] == 1 and "lifecycle_links_metadata_only" not in rep
    # a notice link to a Dataset keeps both ends: the dataset is reported in the notice, and the report counts only
    # the notice links the bundle holds
    cand = spec_of(load_doc(FIXTURES_PIN))
    m = kgbundle.export(load_doc(P9 / "pass-retraction-scope.json"), cand, tmp_path / "r", "scope",
                      created="2026-10-06T00:00:00Z")
    g = json.loads((tmp_path / "r/kg/graph.json").read_text())
    by_scale = {n["props"].get("scale_id"): n for n in g["nodes"]}
    table = by_scale[TABLE]
    assert table["props"]["source_status"] == "retracted"
    to_table = [e for e in g["links"] if e["type"] == "RETRACTS" and e["target"] == table["id"]]
    assert len(to_table) == 1 and to_table[0]["props"]["metadata_only"] is True
    assert to_table[0]["source"] == by_scale[f"{Z}/source/retraction-notice-b"]["id"]
    rep = m["export_report"]
    held = {e["props"]["scale_id"] for e in g["links"] if e["props"].get("metadata_only")}
    assert rep["lifecycle_links_metadata_only"] == len(held) == 3 and "RETRACTS" not in rep["not_exported_links"]
    assert {e["source"] for e in g["links"]} | {e["target"] for e in g["links"]} <= {n["id"] for n in g["nodes"]}
    if v:
        kgbundle.seal(tmp_path / "r")
        res = v.validate_bundle(tmp_path / "r")
        assert res.ok, [f.message for f in res.errors][:5]
    plain = kgbundle.export(load_doc(X / "example.json"), spec, tmp_path / "p", "plain",
                          created="2026-10-06T00:00:00Z")
    assert "source_lifecycle" not in plain["export_report"] and "source_status" not in (tmp_path / "p/kg/graph.json").read_text()


def test_the_bundle_export_keeps_bases_apart_and_says_what_it_converted(tmp_path, doc, spec):
    V = lambda value, unit, **k: {"status": "present", "value": value, "unit": unit, **k}  # noqa: E731
    assert kgbundle.target("pressure", V(100, "psig")) == "pressure_gauge"
    assert kgbundle.quantity("pressure", V(100, "psig"))[0]["value"] == pytest.approx(0.689476)      # in its unit, not + 1 atm
    assert kgbundle.target("pressure", V(100, "lbf/in2 (gauge)")) == "pressure_gauge"
    assert kgbundle.target("pressure", V(100, "atm", as_reported="100 atm. gauge")) == "pressure_gauge"
    assert kgbundle.target("pressure", V(150, "atm", note="absolute")) == "pressure"
    assert kgbundle.target("pressure", V(100, "atm", note="absolute, not gauge")) == "pressure"
    # the value's own basis wins over a gauge equivalent given in parentheses
    absolute = V(178, "atm", basis="absolute", as_reported="178 atmospheres absolute (2600 pounds per square inch gage)")
    assert kgbundle.target("pressure", absolute) == "pressure"
    assert kgbundle.quantity("pressure", absolute)[0]["value"] == pytest.approx(18.03585)
    assert kgbundle.target("pressure", V(178, "atm", as_reported="178 atmospheres absolute (2600 pounds per square inch gage)")) \
        == "pressure"
    assert kgbundle.target("pressure", V(2600, "psi", basis="gauge")) == "pressure_gauge"
    assert kgbundle.target("pressure", V(2600, "psia", as_reported="2600 psia (gauge reading 2585)")) == "pressure"
    assert kgbundle.target("pressure", V(4850, "psi", as_reported="4850 p.s.i.g.")) == "pressure_gauge"
    assert kgbundle.target("pressure", V(2600, "psi", as_reported="2600 pounds per square inch gage (178 atm abs.)")) \
        == "pressure_gauge"
    # a parenthetical that holds only a basis is the value's own: "20 bar (gauge)", "20 bar(g)" are gauge
    for reported in ("20 bar (gauge)", "20 bar(g)", "20 bar (g)", "20 bar (gage)"):
        assert kgbundle.target("pressure", V(20, "bar", as_reported=reported)) == "pressure_gauge", reported
        assert kgbundle.quantity("pressure", V(20, "bar", as_reported=reported))[0]["value"] == pytest.approx(2.0)
    assert kgbundle.target("pressure", V(20, "bar(g)")) == "pressure_gauge"
    assert kgbundle.quantity("pressure", V(20, "bar (g)"))[0]["unit"] == "MPa"
    assert kgbundle.target("pressure", V(20, "bar(a)")) == "pressure" and kgbundle.pressure_basis(V(20, "bar(a)")) == "absolute"
    assert kgbundle.pressure_basis(V(20, "bar", as_reported="20 bar (abs)")) == "absolute"
    assert kgbundle.pressure_basis(V(20, "bar", as_reported="20 bar")) == "unstated"
    # a text that names both bases outside parentheses, with no basis stated, is not converted either way
    mixed = V(2600, "psi", as_reported="2600 psi gauge, i.e. 178 atm absolute")
    assert kgbundle.pressure_basis(mixed) == "unclear" and kgbundle.target("pressure", mixed) == "pressure"
    assert kgbundle.quantity("pressure", mixed) == (None, "2600 psi gauge, i.e. 178 atm absolute")
    assert kgbundle.target("pressure", {**mixed, "basis": "gauge"}) == "pressure_gauge"            # a stated basis decides
    assert kgbundle.target("space_velocity", V(5000, "vol H2/vol catalyst/h")) == "space_velocity_h2"
    assert kgbundle.target("space_velocity", V(5000, "L exit gas (std. cond.) per L catalyst per h")) == "space_velocity_exit_gas"
    assert kgbundle.target("space_velocity", V(5000, "h-1")) == "space_velocity"
    assert kgbundle.quantity("space_velocity", V(50, "cc/cc/min"))[0]["value"] == 3000.0              # time unit only
    q, _ = kgbundle.quantity("temperature", V(380, "°C", uncertainty=2, uncertainty_kind="standard_deviation"))
    assert q["uncertainty"] == {"kind": "std", "plus_minus": 2.0}                                    # the offset cancels
    t = next(n for n in doc["nodes"] if n["id"] == TEST_A)
    t["props"]["pressure"] = V(100, "psig")
    t["props"]["space_velocity"] = V(5000, "vol H2/vol catalyst/h", basis="H2 fed per volume of catalyst")
    t["props"]["temperature"] = {"status": "present", "lower": 350, "upper": 370, "unit": "°C"}
    next(n for n in doc["nodes"] if n["id"] == TEST_B)["props"]["pressure"] = mixed
    m = kgbundle.export(doc, spec, tmp_path / "b", "bases", created="2026-10-06T00:00:00Z")
    g = json.loads((tmp_path / "b/kg/graph.json").read_text())
    p = next(n for n in g["nodes"] if n["props"].get("scale_id") == TEST_A)["props"]
    assert p["pressure_gauge"]["unit"] == "MPa" and "pressure" not in p
    assert p["space_velocity_h2"]["value"] == 5000.0 and p["space_velocity_h2_basis"] == "H2 fed per volume of catalyst"
    assert p["temperature"]["uncertainty"] == {"kind": "range", "low": 623.15, "high": 643.15}
    pb = next(n for n in g["nodes"] if n["props"].get("scale_id") == TEST_B)["props"]
    assert pb["pressure_as_reported"] == mixed["as_reported"] and pb["pressure_note"] == kgbundle.UNCLEAR_PRESSURE
    assert "pressure" not in pb and "pressure_gauge" not in pb and m["export_report"]["pressure_basis_unclear"] == 1
    schema = json.loads((tmp_path / "b/kg/schema.json").read_text())["node_types"]["CatalyticTest"]["properties"]
    assert "never an absolute pressure" in schema["pressure_gauge"]["description"]
    assert "midpoint" in schema["temperature"]["description"]
    assert m["export_report"]["ranges_as_midpoint"] == {"temperature": 1}
    assert m["export_report"]["kept_apart_by_basis"] == {"pressure_gauge": 1, "space_velocity_h2": 1}


def test_the_bundle_export_report_counts_only_the_conversions_the_bundle_holds(tmp_path, doc, spec):
    """A record no source reports is not exported: what converting its values did is not counted either."""
    base = kgbundle.export(json.loads(json.dumps(doc)), spec, tmp_path / "a", "base", created="2026-10-06T00:00:00Z")["export_report"]
    orphan = json.loads(json.dumps(next(n for n in doc["nodes"] if n["id"] == TEST_A)))
    orphan["id"] += "-unreported"
    orphan["props"].pop("evidence", None)
    orphan["props"].update(temperature={"status": "present", "lower": 200, "upper": 250, "unit": "°C"},
                           pressure={"status": "present", "value": 20, "unit": "barg"},
                           space_velocity={"status": "present", "value": 5, "unit": "vol/vol/h"})
    doc["nodes"].append(orphan)
    rep = kgbundle.export(doc, spec, tmp_path / "b", "orphan", created="2026-10-06T00:00:00Z")["export_report"]
    g = json.loads((tmp_path / "b/kg/graph.json").read_text())
    assert orphan["id"] not in {n["props"].get("scale_id") for n in g["nodes"]}
    assert rep["nodes_not_exported_no_source"] == base.get("nodes_not_exported_no_source", 0) + 1
    for k in ("ranges_as_midpoint", "kept_apart_by_basis", "values_as_text", "split_links", "pressure_basis_unclear"):
        assert rep.get(k) == base.get(k), k
    # the same record, reported, is counted
    orphan["props"]["evidence"] = next(n for n in doc["nodes"] if n["id"] == TEST_A)["props"]["evidence"]
    rep = kgbundle.export(doc, spec, tmp_path / "c", "reported", created="2026-10-06T00:00:00Z")["export_report"]
    assert rep["ranges_as_midpoint"]["temperature"] == (base.get("ranges_as_midpoint") or {}).get("temperature", 0) + 1
    assert rep["kept_apart_by_basis"]["pressure_gauge"] == (base.get("kept_apart_by_basis") or {}).get("pressure_gauge", 0) + 1
    assert rep["values_as_text"]["space_velocity"] == base["values_as_text"].get("space_velocity", 0) + 1


@pytest.mark.parametrize("fixture", sorted(p.name for p in P9.glob("pass-*.json")))
def test_the_bundle_export_of_every_pass_fixture_is_a_valid_bundle(tmp_path, fixture):
    """A document of sources and notices alone reports nothing: the bundle declares no REPORTED_IN (the format
    rejects an edge type with an empty from), and it validates."""
    d = load_doc(P9 / fixture)
    m = kgbundle.export(d, spec_of(d), tmp_path / "b", "fx", created="2026-10-06T00:00:00Z")
    schema = json.loads((tmp_path / "b/kg/schema.json").read_text())
    assert all(t["from"] and t["to"] for t in schema["edge_types"].values())
    g = json.loads((tmp_path / "b/kg/graph.json").read_text())
    if all(n["label"] == "Source" for n in d["nodes"]):
        assert "REPORTED_IN" not in schema["edge_types"]
    held = {e["props"]["scale_id"] for e in g["links"] if e["props"].get("metadata_only")}
    assert m["export_report"].get("lifecycle_links_metadata_only", 0) == len(held)
    v = _bundle_validator()
    if v:
        kgbundle.seal(tmp_path / "b")
        res = v.validate_bundle(tmp_path / "b")
        assert res.ok, [f.message for f in res.errors][:5]
