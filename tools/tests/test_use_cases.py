"""Three use cases for adopting SCALE run as query plans on the public-domain
methanol-synthesis example: catalyst search accounting for conditions, "has this been done?", and negative results.
Their answers are pinned here so that a release that changes them says so."""

import pytest

from conftest import REPO, spec_of
from scale import pgraph_query
from scale.util import load_doc, load_yaml

EX = REPO / "examples/methanol-synthesis-public"
UC = EX / "use-cases"


@pytest.fixture(scope="module")
def doc():
    return load_doc(EX)


@pytest.fixture(scope="module")
def graph(doc):
    return pgraph_query.Graph(doc, spec_of(doc))


@pytest.fixture(scope="module")
def index(doc):
    from scale.passages import Index, evidence_items, graph_sha256
    return Index.build(evidence_items(doc), graph_sha256=graph_sha256(doc))


def _run(doc, graph, index, name):
    plan = load_yaml(UC / f"{name}.yaml")
    return pgraph_query.run(doc, graph.spec, plan, index if plan.get("text") else None, graph)


def test_every_use_case_plan_is_pinned():
    assert sorted(p.stem for p in UC.glob("*.yaml")) == [
        "uc1-catalyst-search-by-conditions", "uc2-has-this-been-done", "uc2b-cu-zn-co2-undecidable",
        "uc3-negative-results", "uc3b-why-it-failed"]


@pytest.mark.parametrize("name, rows", [
    ("uc1-catalyst-search-by-conditions", 1),
    ("uc2-has-this-been-done", 44),
    ("uc3-negative-results", 7),
])
def test_structured_use_cases_keep_their_answers(doc, graph, index, name, rows):
    res = _run(doc, graph, index, name)
    assert res["status"] == "answered" and res["row_count"] == rows
    assert all(r.get("evidence") for r in res["rows"])                      # every row carries its evidence
    assert all((ev.get("source_year") or 0) < 1966 for r in res["rows"] for ev in r["evidence"])


def test_an_undecidable_novelty_question_is_not_reported_as_never_done(doc, graph, index):
    res = _run(doc, graph, index, "uc2b-cu-zn-co2-undecidable")
    assert res["status"] == "missing_context" and res["row_count"] == 0     # never no_matching_record
    assert res["coverage"]["not_evaluated_in_steps"]["by_reason"] == {"not_curated": 17}


def test_negative_results_keep_bounds_and_zeros_distinct(doc, graph, index):
    rows = _run(doc, graph, index, "uc3-negative-results")["rows"]
    conv = [r["values"]["test.conversion"] for r in rows]
    assert any(c.get("bound") == "upper" for c in conv)                     # "less than 2 per cent" stays a bound
    assert any(c.get("value") == 0 and not c.get("bound") for c in conv)    # a measured zero stays a zero


def test_why_it_failed_is_answered_from_claims(doc, graph, index):
    res = _run(doc, graph, index, "uc3b-why-it-failed")
    assert res["status"] == "answered" and res["row_count"] >= 20
