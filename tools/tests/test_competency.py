"""Competency questions: a graph query plan, the public example documents it runs on and its expected
answer; `scale domains cq` runs them and fails when one does not answer as expected."""

import json
import shutil

import pytest

from conftest import CATALYSIS, REPO, as_project_data
from scale import layout
from scale.cli import main
from scale.competency import meets, run, run_question
from scale.util import ScaleError, dump_yaml, load_doc, load_yaml, write_canonical

CQ = CATALYSIS / layout.DOMAIN_COMPETENCY / "cq-01-faradaic-efficiency.yaml"


def _question(tmp_path, **changes):
    """A copy of CQ-01 in the catalysis competency directory of a copied domain, with changes."""
    repo = tmp_path / "repo"
    shutil.copytree(REPO / "domain", repo / "domain",
                    ignore=shutil.ignore_patterns("__pycache__", "proposals", "tests"))
    for d in ("core", "governance"):
        shutil.copytree(REPO / d, repo / d, ignore=shutil.ignore_patterns("__pycache__", "proposals"))
    shutil.copy2(REPO / layout.RELEASE_MANIFEST, repo / layout.RELEASE_MANIFEST)
    (repo / layout.RELEASES).mkdir()
    q = load_yaml(CQ)
    for k, v in changes.items():
        if v is None:
            q.pop(k)
        else:
            q[k] = v
    p = repo / "domain/competency/cq-09-test.yaml"
    p.write_text(dump_yaml(q))
    return repo, p


def test_every_catalysis_question_answers_as_expected():
    res = run(REPO, ["catalysis"])
    assert res["ok"] and res["answered_as_expected"] == 6 and res["stubs"] == 0
    by_id = {q["id"]: q for q in res["questions"]}
    assert by_id["CQ-01"]["answer"] == {"status": "answered", "rows": 3, "schema_gaps": []}
    assert by_id["CQ-02"]["answer"]["rows"] == 10                       # one row per control of a catalytic test


def test_an_unmet_expectation_fails_with_what_differs(tmp_path):
    repo, p = _question(tmp_path, expect={"status": "answered", "min_rows": 9, "values": {"test.control_mode": ["galvanostatic"]}})
    r = run_question(repo, "catalysis", p)
    assert not r["ok"] and r["answer"]["rows"] == 3
    assert r["problems"] == ["3 rows, expected at least 9",
                             "test.control_mode never returns ['galvanostatic'] (returned: ['potentiostatic', 'pulsed'])"]
    assert not run(repo, ["catalysis"])["ok"]


def test_a_schema_gap_can_be_the_expected_answer(tmp_path):
    plan = {"match": {"label": "CatalyticTest", "as": "t", "where": [{"prop": "site_turnover", "op": "exists"}]}}
    repo, p = _question(tmp_path, plan=plan, expect={"status": "schema_gap", "schema_gaps": ["CatalyticTest.site_turnover is not declared"]})
    assert run_question(repo, "catalysis", p)["ok"]


def test_questions_run_only_on_declared_public_examples(tmp_path):
    repo, p = _question(tmp_path, documents=["examples/scale-catal/example.json"])     # declared, made project data here
    ex = repo / "domain/examples/scale-catal/example.json"
    write_canonical(ex, as_project_data(load_doc(ex)))
    r = run_question(repo, "catalysis", p)
    assert not r["ok"] and "is not public (stewardship access project)" in r["problems"][0]
    doc = load_doc(ex)                                                  # no access stated: not public either
    del doc["graph"]["stewardship"]
    write_canonical(ex, doc)
    r = run_question(repo, "catalysis", p)
    assert not r["ok"] and "is not public (stewardship access not stated)" in r["problems"][0]
    repo, p = _question(tmp_path / "b", documents=["../../core/examples/science-examples/a-designed-series.json"])
    assert "is not one of the domain's example documents" in run_question(repo, "catalysis", p)["problems"][0]


def test_malformed_questions_are_reported(tmp_path):
    repo, p = _question(tmp_path, expect=None)
    assert run_question(repo, "catalysis", p)["problems"] == ["expect.status is required (what the answer must be)"]
    repo, p = _question(tmp_path / "b", expect={"status": "found"})
    assert "is not one of" in run_question(repo, "catalysis", p)["problems"][0]
    repo, p = _question(tmp_path / "c", documents=None)
    assert "documents: name the public example documents" in run_question(repo, "catalysis", p)["problems"][0]
    repo, p = _question(tmp_path / "d", plan={"steps": []})
    assert "the plan does not run: a plan needs match.label or match.id" in run_question(repo, "catalysis", p)["problems"][0]


def test_a_stub_is_listed_not_counted(tmp_path):
    repo, p = _question(tmp_path, plan=None, expect=None, documents=None)
    r = run_question(repo, "catalysis", p)
    assert r["stub"] and not r["ok"] and r["problems"] == []
    res = run(repo, ["catalysis"])
    assert res["ok"] and res["stubs"] == 1


def test_meets_compares_status_rows_values_and_gaps():
    ans = {"status": "answered", "rows": 2, "values": {"t.x": [{"value": 1}, "a"]}, "schema_gaps": []}
    assert meets(ans, {"status": "answered", "min_rows": 2, "max_rows": 2, "values": {"t.x": [1, "a"]}}) == []
    assert meets(ans, {"max_rows": 1}) == ["2 rows, expected at most 1"]


def test_cli_runs_named_domains(capsys):
    assert main(["--repo", str(REPO), "domains", "cq", "catalysis", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["answered_as_expected"] == 6
    with pytest.raises(ScaleError, match="no domain astronomy"):
        run(REPO, ["astronomy"])
