"""Gap reports: what a scale-catal query could not answer becomes a classified gap; only a missing
concept leads to a schema change proposal, and a GitHub issue is filed only by a person."""

import json

from conftest import DRIVING_FORCE_EXAMPLES, GRAPH_MANIFEST
from scale import pgraph, pgraph_query
from scale.cli import main
from scale.gaps import gaps_from_query, make_gap, render_issue, submit_issue
from scale.util import load_doc


def test_issue_rendering_and_dry_run():
    gap = make_gap("missing_concept", record="ex:c", about="operating program", detected_by="curation",
                   schema="scale-catal 0.4.0", evidence=["ex:ev/1"])
    body = render_issue(gap)
    assert "`missing_concept`" in body and "ex:ev/1" in body and "schema change request" in body.lower()
    assert "**Schema:** `scale-catal 0.4.0`" in body
    dry = submit_issue(gap)
    assert dry["dry_run"] and "gap:missing-concept" in dry["command"]
    cmd = dry["command"]                                       # the title stays; only the body is elided
    assert cmd[3:7] == ["--title", gap["title"], "--body", "<body>"] and body not in cmd
    assert "(skills/evolve-schema/SKILL.md)" in body     # the skill paths of the repository layout


def _run(plan: dict) -> dict:
    doc = load_doc(DRIVING_FORCE_EXAMPLES / "electro-dynamic.json")
    return pgraph_query.run(doc, pgraph.load_spec(GRAPH_MANIFEST), plan)


def test_query_absences_route_to_gap_kinds():
    gap = gaps_from_query(_run({"match": {"label": "CatalyticTest", "as": "t", "where": [{"prop": "site_turnover", "op": "exists"}]}}))
    assert [(g["kind"], g["about"]) for g in gap] == [("missing_concept", "CatalyticTest.site_turnover is not declared")]
    assert gap[0]["schema"] == f"scale-catal {load_doc(DRIVING_FORCE_EXAMPLES / 'electro-dynamic.json')['graph']['schema_version']}"
    none = gaps_from_query(_run({"match": {"label": "CatalyticTest", "as": "t", "where": [{"prop": "control_mode", "op": "eq",
                                                                                         "value": "galvanostatic"}]}}))
    assert [g["kind"] for g in none] == ["missing_source_coverage"]
    # a pulsed test states no single potential: reported as not reported, so source review, not a schema change
    res = _run({"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.electrode_potential"]})
    assert res["status"] == "answered"
    synthetic = {**res, "missing_context": [{"record": "ex:r1", "field": "t.ph", "reason": "not_reported"},
                                            {"record": "ex:r2", "field": "t.charge", "reason": "not_curated"}]}
    assert {g["kind"] for g in gaps_from_query(synthetic)} == {"absent_source_information"}   # not_curated is backlog


def test_a_gap_keeps_the_access_of_the_answer_it_was_made_from(tmp_path, capsys, monkeypatch):
    """Every gap made from a query result carries the result's access; one that is not public says so in its issue
    body and on stderr, and `scale gap issue --submit` refuses it before anything is sent. A result that states no
    access is read as institution."""
    import pytest

    from scale.util import ScaleError

    res = _run({"match": {"label": "CatalyticTest", "as": "t", "where": [{"prop": "site_turnover", "op": "exists"}]}})
    assert res["access"]["level"] == "public"
    assert all(g["access"] == res["access"] for g in gaps_from_query(res))
    closed = {**res, "access": {"level": "project", "note": "not all public"}}
    gap = gaps_from_query(closed)[0]
    assert gap["access"] == {"level": "project", "note": "not all public"}
    assert "Not for a public tracker" in render_issue(gap) and "access project" in render_issue(gap)
    assert "Not for a public tracker" not in render_issue(gaps_from_query(res)[0])
    assert submit_issue(gap)["dry_run"]                                        # a dry run sends nothing
    with pytest.raises(ScaleError, match="files only public gaps"):
        submit_issue(gap, dry_run=False)
    unstated = gaps_from_query({k: v for k, v in res.items() if k != "access"})[0]
    assert unstated["access"]["level"] == "institution"
    # a gap that states no access (written by hand, or by an older from-query) is not public either: it warns and
    # --submit refuses it before anything is sent (gh is never run here); it states access.level public to be filed
    import scale.gaps

    def no_gh(*args, **kwargs):
        raise AssertionError("gh must not be run")
    monkeypatch.setattr(scale.gaps.subprocess, "run", no_gh)
    for bare in (make_gap("missing_concept", record="ex:c", about="operating program", detected_by="curation", schema=None),
                 {**make_gap("missing_concept", record="ex:c", about="x", detected_by="curation", schema=None), "access": None}):
        assert "Not for a public tracker" in render_issue(bare) and "access not stated" in render_issue(bare)
        with pytest.raises(ScaleError, match="files only public gaps"):
            submit_issue(bare, dry_run=False)
        f = tmp_path / "bare.json"
        f.write_text(json.dumps(bare))
        assert main(["gap", "issue", str(f), "--submit"]) == 2
        assert "not for a public tracker" in capsys.readouterr().err
    public = make_gap("missing_concept", record="ex:c", about="x", detected_by="curation", schema=None,
                      access={"level": "public", "note": ""})
    assert "Not for a public tracker" not in render_issue(public)
    f = tmp_path / "gap.json"
    f.write_text(json.dumps(gap))
    assert main(["gap", "issue", str(f), "--submit"]) == 2
    assert "not for a public tracker" in capsys.readouterr().err
    assert main(["gap", "issue", str(f)]) in (0, None)
    out = capsys.readouterr()
    assert "Not for a public tracker" in out.out and "not for a public tracker" in out.err


def test_cli_turns_a_query_result_into_gap_files(tmp_path, capsys):
    res = tmp_path / "result.json"
    res.write_text(json.dumps(_run({"match": {"label": "Catalyst", "as": "c", "where": [{"prop": "tof", "op": "exists"}]}})))
    assert main(["gap", "from-query", str(res), "--out-dir", str(tmp_path / "gaps")]) in (0, None)
    out = json.loads(capsys.readouterr().out)
    assert [g["kind"] for g in out["gaps"]] == ["missing_concept"] and len(out["written"]) == 1
    assert main(["gap", "list", str(tmp_path / "gaps")]) in (0, None)
    assert "missing_concept" in capsys.readouterr().out
