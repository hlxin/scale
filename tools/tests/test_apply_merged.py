"""The operating model's automation, offline: a merged proposal applied from its recorded GitHub reviews
(`scale proposal apply-merged`, all or nothing), the placeholder warning of `scale check`, the proposals a push
changed (`scale ci proposals`) and the update of a data repository's documents (`scale kg update`)."""

import copy
import hashlib
import json
import shutil
import subprocess

import pytest

from conftest import REPO, kernel_of, schema_at
from scale.apply_merged import apply_merged
from scale.util import ScaleError, dump_yaml, load_doc, load_yaml, write_canonical
from test_proposal_graph import BASE, G, _mini_repo, gh_review

HEAD = "f00dfeed"
OK = lambda repo: (True, "all checks passed")          # noqa: E731  (the full check, stubbed)


def tree(repo):
    """Every file's digest: what 'nothing written' means."""
    return {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(repo.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def checked(tmp_path):
    from scale.pgraph_proposal import check
    repo, cs = _mini_repo(tmp_path)
    assert check(cs, repo)["ok"]
    return repo, cs


def reviews(*who, commit=HEAD):
    return [gh_review(w, rid=100 + i, commit=commit) for i, w in enumerate(who)]


def test_two_approvals_apply_the_proposal_and_bump_the_version(tmp_path):
    repo, cs = checked(tmp_path)
    res = apply_merged(repo, cs, 42, reviews("ada", "ben"), author="hlxin", head_sha=HEAD,
                       pr_url="https://github.com/hlxin/scale/pull/42", check=OK)
    assert res["status"] == "applied" and res["approved_by"] == ["ada", "ben"]
    assert res["commit_message"] == f"Apply proposal 009001 (catalysis): schema {BASE} → 0.2.0 (PR #42)"
    assert load_yaml(repo / G / "scale-graph.yaml")["version"] == "0.2.0"
    assert load_yaml(repo / "core/CORE.yaml")["version"] == load_yaml(repo / "scale-release.yaml")["schema_version"] == "0.2.0"
    assert load_yaml(cs / "proposal.yaml")["status"] == "applied"
    assert (repo / G / f"frozen/scale-graph-{BASE}.yaml").is_file()
    assert (repo / f"core/graph/frozen/kernel-{BASE}.yaml").is_file()
    rec = (repo / res["decision_record"]).read_text()
    assert "approved in pull request [#42](https://github.com/hlxin/scale/pull/42)" in rec
    assert "**Approved by:** ada, ben" in rec and "**Author:** hlxin" in rec
    assert sorted(p.name for p in (cs / "approvals").iterdir()) == ["github-ada-100.json", "github-ben-101.json"]
    assert load_doc(repo / "docs/decisions/log.json")["decisions"][0]["pr"] == 42


def test_one_approval_by_any_reviewer_applies_it(tmp_path):
    repo, cs = checked(tmp_path)
    res = apply_merged(repo, cs, 42, reviews("ben"), author="hlxin", head_sha=HEAD, check=OK)
    assert res["status"] == "applied" and "**Approved by:** ben" in (repo / res["decision_record"]).read_text()


def test_no_approval_writes_nothing(tmp_path):
    repo, cs = checked(tmp_path)
    before = tree(repo)
    with pytest.raises(ScaleError, match=r"#42 does not satisfy .*1 more approving review"):
        apply_merged(repo, cs, 42, reviews("hlxin"), author="hlxin", head_sha=HEAD, check=OK)
    assert tree(repo) == before


def test_the_authors_own_approval_is_ignored(tmp_path):
    repo, cs = checked(tmp_path)
    before = tree(repo)
    with pytest.raises(ScaleError, match=r"not counted: ada \(the author of the change\)"):
        apply_merged(repo, cs, 42, reviews("ada"), author="ada", head_sha=HEAD, check=OK)
    assert tree(repo) == before


def test_a_placeholder_is_ignored(tmp_path):
    repo, cs = checked(tmp_path)
    pol = load_yaml(repo / "governance/review-policy.yaml")
    pol["reviewers"]["members"].append({"name": "TODO-reviewer-2", "github": "TODO-reviewer-2", "placeholder": True})
    (repo / "governance/review-policy.yaml").write_text(dump_yaml(pol))
    before = tree(repo)
    with pytest.raises(ScaleError, match=r"not counted: TODO-reviewer-2 \(a placeholder seat, not a person\)"):
        apply_merged(repo, cs, 42, reviews("TODO-reviewer-2"), author="hlxin", head_sha=HEAD, check=OK)
    assert tree(repo) == before


def test_approvals_of_an_older_commit_do_not_count(tmp_path):
    repo, cs = checked(tmp_path)
    with pytest.raises(ScaleError, match="1 more approving review"):
        apply_merged(repo, cs, 42, reviews("ben", commit="older"), author="hlxin", head_sha=HEAD, check=OK)


def test_an_applied_proposal_is_left_alone(tmp_path):
    repo, cs = checked(tmp_path)
    apply_merged(repo, cs, 42, reviews("ada", "ben"), author="hlxin", head_sha=HEAD, check=OK)
    after = tree(repo)
    res = apply_merged(repo, cs, 42, reviews("ada", "ben"), author="hlxin", head_sha=HEAD, check=OK)
    assert res == {"proposal": "009001", "status": "already applied", "changed": False}
    assert tree(repo) == after


def test_a_failing_check_puts_every_file_back(tmp_path):
    repo, cs = checked(tmp_path)
    before = tree(repo)
    with pytest.raises(ScaleError, match="`scale check` failed after the apply:\nFAIL unit tests"):
        apply_merged(repo, cs, 42, reviews("ada", "ben"), author="hlxin", head_sha=HEAD,
                     check=lambda r: (False, "FAIL unit tests\nsome checks failed"))
    assert tree(repo) == before
    assert not (repo / G / "frozen").exists() and not (cs / "approvals").exists()


def test_the_bot_runs_the_full_check_with_the_unit_tests(tmp_path, monkeypatch):
    """A version bump that breaks a unit test must fail the apply, not main: the check after the apply is the full
    `scale check` (the unit tests included), not `--fast`."""
    import inspect
    from scale import apply_merged as am, devcheck
    seen = []
    monkeypatch.setattr(devcheck, "run_checks", lambda repo, fast=False, out=None: seen.append(fast) or True)
    assert am.full_check(tmp_path) == (True, "") and seen == [False]
    assert inspect.signature(am.apply_merged).parameters["check"].default is am.full_check
    monkeypatch.undo()
    assert "unit tests" in [s["name"] for s in devcheck.check_steps(REPO, fast=False)]
    assert "unit tests" not in [s["name"] for s in devcheck.check_steps(REPO, fast=True)]


@pytest.mark.parametrize("committed", [
    {"reviewer": "ada", "decision": "approve", "at": "2026-10-05T09:00:00Z"},     # stands in for a second approval
    {"reviewer": "ada", "decision": "approve", "at": "2999-01-01T00:00:00Z"},     # would outrank ada's real request
])
def test_approval_files_committed_in_the_pull_request_never_count(tmp_path, committed):
    """Only GitHub reviews approve: a file the pull request put in approvals/ is refused, whatever it says."""
    repo, cs = checked(tmp_path)
    write_canonical(cs / "approvals/github-ada-999.json", {"proposal": "009001", **committed})
    before = tree(repo)
    gh = reviews("ben") + [gh_review("ada", state="CHANGES_REQUESTED", rid=7, commit=HEAD)]
    for given in (reviews("ben"), gh, reviews("ada", "ben")):
        with pytest.raises(ScaleError, match=r"approvals/ already holds 1 file\(s\)"):
            apply_merged(repo, cs, 42, given, author="hlxin", head_sha=HEAD, check=OK)
        assert tree(repo) == before


def test_the_decision_record_lists_only_the_github_reviews(tmp_path):
    repo, cs = checked(tmp_path)
    res = apply_merged(repo, cs, 42, reviews("ada", "ben") + [gh_review("cy", state="COMMENTED", rid=9, commit=HEAD)],
                       author="hlxin", head_sha=HEAD, check=OK)
    rec = (repo / res["decision_record"]).read_text().split("## Reviews", 1)[1]
    assert "ada (pull request #42, review 100)" in rec and "ben (pull request #42, review 101)" in rec
    assert "cy" not in rec


def test_only_the_counted_approvals_are_recorded(tmp_path):
    """The author's own approval and one by somebody outside the policy are not written to approvals/ and are
    not listed as reviews in the decision record; the record names them under 'Reviews not counted'."""
    repo, cs = checked(tmp_path)
    res = apply_merged(repo, cs, 42, reviews("ada", "ben", "hlxin", "zed"), author="hlxin", head_sha=HEAD, check=OK)
    assert sorted(p.name for p in (cs / "approvals").iterdir()) == ["github-ada-100.json", "github-ben-101.json"]
    reviewed, not_counted = (repo / res["decision_record"]).read_text().split("## Reviews", 1)[1].split("## Reviews not counted")
    assert "ada (pull request #42" in reviewed and "ben (pull request #42" in reviewed
    assert "hlxin" not in reviewed and "zed" not in reviewed
    assert "hlxin: the author of the change" in not_counted and "zed: not a reviewer in the review policy" in not_counted


def test_review_status_takes_the_proposal_as_an_argument_or_an_option(tmp_path, capsys):
    from scale.cli import main
    repo, cs = checked(tmp_path)
    for args in (["009001"], ["--proposal", "009001"]):
        main(["--repo", str(repo), "review", "status", *args, "--format", "json"])
        assert json.loads(capsys.readouterr().out)["proposal"] == "009001"
    assert main(["--repo", str(repo), "review", "status", "009001", "--proposal", "009002"]) == 2
    assert "two different proposals" in capsys.readouterr().err


def test_a_pull_request_adding_approval_files_fails_its_check(tmp_path):
    from scale.ci import proposal_checks
    repo, cs = _mini_repo(tmp_path)
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout  # noqa: E731
    git("init", "-q", "-b", "main")
    git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "--allow-empty", "-m", "start")
    git("branch", "base")
    write_canonical(cs / "approvals/github-ada-1.json", {"proposal": "009001", "reviewer": "ada", "decision": "approve"})
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-m", "proposal")
    res = proposal_checks(repo, "base")
    assert not res["ok"]
    row = res["proposals"][0]
    assert row["result"] == "failed" and "approvals/ holds github-ada-1.json" in row["why"]


def test_a_draft_is_not_applied(tmp_path):
    from scale.pgraph_proposal import set_status
    repo, cs = checked(tmp_path)
    set_status(cs, "draft")
    with pytest.raises(ScaleError, match="status 'draft'; only a merged proposal with status 'proposed'"):
        apply_merged(repo, cs, 42, reviews("ada", "ben"), author="hlxin", check=OK)


def test_the_cli_runs_the_real_check_and_rolls_back(tmp_path, capsys):
    """Through the CLI the full check always runs; the mini repository cannot pass it, so nothing is written."""
    from scale.cli import main
    repo, cs = checked(tmp_path)
    (tmp_path / "reviews.json").write_text(json.dumps(reviews("ada", "ben")))
    before = tree(repo)
    assert main(["--repo", str(repo), "proposal", "apply-merged", "009001", "--pr", "42", "--author", "hlxin",
                 "--head-sha", HEAD, "--reviews", str(tmp_path / "reviews.json")]) == 2
    assert tree(repo) == before


def test_a_bootstrap_bypass_is_recorded_as_such_and_only_while_no_other_reviewer_has_joined(tmp_path):
    """Until a second reviewer joins, the owner's own change cannot be approved: the owner, who merged under the
    ruleset's bootstrap bypass, records the decision by hand, and the record says it was not approved."""
    from scale.pgraph_proposal import apply, decide
    repo, cs = checked(tmp_path)
    with pytest.raises(ScaleError, match="besides hlxin can approve"):
        decide(cs, repo, bootstrap_bypass="reviewers not yet added", by="hlxin")
    pol = load_yaml(repo / "governance/review-policy.yaml")
    pol["reviewers"]["members"] = [pol["reviewers"]["members"][0], pol["reviewers"]["members"][1],
                                   {"name": "TODO-reviewer-2", "github": "TODO-reviewer-2", "placeholder": True}]
    (repo / "governance/review-policy.yaml").write_text(dump_yaml(pol))
    with pytest.raises(ScaleError, match="besides hlxin can approve"):     # one expert has joined: no bypass
        decide(cs, repo, bootstrap_bypass="reviewers not yet added", by="hlxin")
    pol["reviewers"]["members"] = [pol["reviewers"]["members"][0],
                                   {"name": "TODO-reviewer-2", "github": "TODO-reviewer-2", "placeholder": True}]
    (repo / "governance/review-policy.yaml").write_text(dump_yaml(pol))
    with pytest.raises(ScaleError, match="not approved"):
        decide(cs, repo)
    with pytest.raises(ScaleError, match="needs a reason"):
        decide(cs, repo, bootstrap_bypass=" ", by="hlxin")
    with pytest.raises(ScaleError, match="TODO-reviewer-2 is not a reviewer"):
        decide(cs, repo, bootstrap_bypass="reviewers not yet added", by="TODO-reviewer-2")
    rec = decide(cs, repo, pr=3, bootstrap_bypass="reviewers not yet added", by="hlxin").read_text()
    assert "merged under the bootstrap bypass by hlxin, without an approval" in rec
    assert "Bootstrap bypass by hlxin: reviewers not yet added" in rec
    assert load_doc(repo / "docs/decisions/log.json")["decisions"][0]["bootstrap_bypass"] == "reviewers not yet added"
    assert apply(cs, repo, confirm=True)["dry_run"] is False


def test_check_warns_about_placeholder_reviewers(tmp_path):
    import io
    from scale import devcheck
    assert devcheck.reviewer_warnings(REPO) == ["reviewers: 2 placeholders to fill (governance/review-policy.yaml)"]
    repo, _ = _mini_repo(tmp_path)                     # its policy has three people and no placeholder
    assert devcheck.reviewer_warnings(repo) == []
    step = devcheck.check_steps(REPO, fast=True)[0]
    assert step["cmds"] == [] and step["warning"] is devcheck.reviewer_warnings
    out = io.StringIO()
    steps = [step]
    import unittest.mock as mock
    with mock.patch.object(devcheck, "check_steps", lambda *a, **k: steps):
        assert devcheck.run_checks(REPO, fast=True, out=out)          # a warning never fails the check
    assert out.getvalue().splitlines()[0] == "warn reviewers: 2 placeholders to fill (governance/review-policy.yaml)"


def test_changed_proposals_lists_what_a_push_changed(tmp_path):
    from scale.ci import changed_proposals
    repo, cs = _mini_repo(tmp_path)
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout  # noqa: E731
    git("init", "-q", "-b", "main")
    git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "--allow-empty", "-m", "start")
    before = git("rev-parse", "HEAD").strip()
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-m", "proposal")
    got = changed_proposals(repo, before, "HEAD")
    assert got == [{"proposal": "009001", "path": "domain/proposals/009001", "status": "proposed"}]
    assert changed_proposals(repo, before, "HEAD", status="applied") == []
    with pytest.raises(ScaleError, match="no commit"):
        changed_proposals(repo, "0" * 40)


def test_a_pull_request_gets_its_proposals_checked_in_one_comment(tmp_path):
    from scale.ci import COMMENT_MARK, proposal_checks, proposal_comment
    repo, cs = _mini_repo(tmp_path)
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout  # noqa: E731
    git("init", "-q", "-b", "main")
    git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "--allow-empty", "-m", "start")
    git("branch", "base")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-m", "proposal")
    res = proposal_checks(repo, "base")
    assert res["ok"] and [(r["proposal"], r["result"]) for r in res["proposals"]] == [("009001", "ok")]
    text = proposal_comment(res)
    assert text.startswith(COMMENT_MARK) and "**009001**" in text and "- tier 2; schema diff: 1 added" in text
    assert "- fixtures 2/2 as expected" in text and "migration: meaning_preserving" in text
    # a proposal that reads restricted inputs is not checked without them, and does not fail
    row = {"proposal": "000007", "path": "domain/proposals/000007", "status": "proposed",
           "result": "needs restricted data", "why": "x", "committed": {"checked_at": "2026-10-05", "tier": 2, "ok": True}}
    text = proposal_comment({"repo": str(repo), "proposals": [row], "ok": True})
    assert "not checked here: its inputs are restricted data (a restricted copy, SCALE_RESTRICTED_DATA)" in text
    assert "tier 2, ok True" in text


def _pull_request(repo):
    """A git repository whose branch ``base`` is empty: everything in the working tree is the pull request."""
    def git(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *a], cwd=repo, check=True,
                              capture_output=True, text=True).stdout
    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "start")
    git("branch", "base")
    return lambda: (git("add", "-A"), git("commit", "-q", "-m", "proposal"))


def _restricted_gap_source(tmp_path, repo, cs, monkeypatch):
    """The proposal's gap source moved to the restricted copy and checked with it, as its author does: the
    public validation_report.json records the gap source as a restricted input. Returns the gap source."""
    from scale.pgraph_proposal import check
    restricted, gaps = tmp_path / "restricted", "domain/examples/secret/curation/fragments"
    write_canonical(restricted / gaps / "src1.json", {"gaps": [{"kind": "missing_concept", "text": "a gap"}]})
    p = load_yaml(cs / "proposal.yaml")
    p.update(gap_sources=[gaps], gap_themes=[{"id": "TH-01", "title": "A deferred theme", "resolution": "deferred",
                                              "reason": "later", "instances": ["src1#gap/0"]}])
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    monkeypatch.setenv("SCALE_RESTRICTED_DATA", str(restricted))
    assert check(cs, repo)["ok"]
    assert load_doc(cs / "validation_report.json")["restricted"]["inputs"] == [gaps]
    return gaps


def _set_gap_source(cs, src):
    p = load_yaml(cs / "proposal.yaml")
    p["gap_sources"] = [src]
    (cs / "proposal.yaml").write_text(dump_yaml(p))


def test_a_wrong_input_path_fails_the_pull_request_check_with_the_data_here(tmp_path, monkeypatch):
    """With the restricted data present, a proposal is checked in full: a typo in an input path fails, whatever
    its error message says about restricted data."""
    from scale.ci import proposal_checks
    repo, cs = _mini_repo(tmp_path)
    gaps = _restricted_gap_source(tmp_path, repo, cs, monkeypatch)
    _set_gap_source(cs, gaps.replace("fragments", "fragmnets"))
    _pull_request(repo)()
    res = proposal_checks(repo, "base")
    row = res["proposals"][0]
    assert not res["ok"] and row["result"] == "failed" and "fragmnets does not exist" in row["why"]


def test_without_the_data_only_a_recorded_restricted_input_with_a_passing_report_is_let_through(tmp_path, monkeypatch):
    """Without the restricted data (CI), "needs restricted data" is earned, not read from an error message: every
    input missing from the repository must be one the committed report (from a check with the data) records as
    restricted, and that report must have passed. A typo, a missing report or a failed one fails the check."""
    from scale.ci import proposal_checks, proposal_comment
    repo, cs = _mini_repo(tmp_path)
    gaps = _restricted_gap_source(tmp_path, repo, cs, monkeypatch)
    commit = _pull_request(repo)
    monkeypatch.setenv("SCALE_RESTRICTED_DATA", str(tmp_path / "absent"))
    report = load_doc(cs / "validation_report.json")

    def row():
        commit()
        res = proposal_checks(repo, "base")
        assert res["ok"] is (res["proposals"][0]["result"] != "failed")
        return res["proposals"][0]

    r = row()                                       # a genuinely restricted input, a passing committed report
    assert r["result"] == "needs restricted data" and r["committed"]["ok"] is True
    assert "not checked here: its inputs are restricted data" in proposal_comment(
        {"repo": str(repo), "proposals": [r], "ok": True})
    write_canonical(cs / "validation_report.json", {**report, "ok": False})          # the report did not pass
    r = row()
    assert r["result"] == "failed" and "did not pass" in r["why"]
    (cs / "validation_report.json").unlink()                                       # no committed report
    r = row()
    assert r["result"] == "failed" and "no committed validation_report.json" in r["why"]
    write_canonical(cs / "validation_report.json", report)
    _set_gap_source(cs, gaps.replace("fragments", "fragmnets"))                     # a typo in the public tree
    r = row()
    assert r["result"] == "failed" and "does not record it as restricted data" in r["why"]
    _set_gap_source(cs, gaps)                                                       # with the data, the check runs
    monkeypatch.setenv("SCALE_RESTRICTED_DATA", str(tmp_path / "restricted"))
    assert row()["result"] == "ok"


def test_without_the_data_a_proposal_changed_after_its_passing_report_fails(tmp_path, monkeypatch):
    """Without the restricted data, a passing committed report lets a proposal through only while it is current:
    the proposal must still build (which needs no restricted data) to the committed candidate, tier and schema
    diff. A proposal.yaml edited after the report (an operation that no longer builds, a different concept, a
    changed definition) fails the check."""
    from scale.ci import proposal_checks
    repo, cs = _mini_repo(tmp_path)
    _restricted_gap_source(tmp_path, repo, cs, monkeypatch)
    commit = _pull_request(repo)
    monkeypatch.setenv("SCALE_RESTRICTED_DATA", str(tmp_path / "absent"))
    good = load_yaml(cs / "proposal.yaml")

    def row(edit=None):
        p = load_yaml(cs / "proposal.yaml") if edit is None else edit(copy.deepcopy(good))
        (cs / "proposal.yaml").write_text(dump_yaml(p))
        if subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout:
            commit()
        res = proposal_checks(repo, "base")
        assert res["ok"] is (res["proposals"][0]["result"] != "failed")
        return res["proposals"][0]

    def op(**kw):
        def edit(p):
            p["operations"][0].update(kw)
            return p
        return edit

    def described(p):
        p["operations"][0]["value"] = {**p["operations"][0]["value"], "description": "edited after the report"}
        return p

    assert row()["result"] == "needs restricted data"                                # current: let through
    r = row(op(file="domain/graph/nonexistent.yaml", op="frobnicate"))   # no longer builds
    assert r["result"] == "failed" and "no longer builds" in r["why"] and "nonexistent.yaml" in r["why"]
    r = row(op(key="PressureSensor"))                                               # another concept: another diff
    assert r["result"] == "failed" and "schema diff" in r["why"] and "out of date" in r["why"]
    r = row(described)                                                              # same diff, other candidate
    assert r["result"] == "failed" and "committed candidate/" in r["why"]
    assert row(lambda p: p)["result"] == "needs restricted data"                    # restored
    assert (cs / "candidate").is_dir() and not subprocess.run(
        ["git", "status", "--porcelain", "--", "."], cwd=cs, capture_output=True, text=True).stdout   # left as committed


# ------------------------------------------------------------------------------------------ scale kg update
def _two_versions(tmp_path):
    """A schema repository whose head is 0.2.0 (0.1.0 with one synthetic property added to the catalysis file) with
    0.1.0 frozen beside it, as `scale proposal apply` leaves them; and a data repository with synthetic documents
    pinning 0.1.0. Version 0.1.0 is BASE, read from the head while the head is at it, else from its frozen copies."""
    import os
    from scale.pgraph_proposal import append_frozen_sums
    repo = tmp_path / "schema"
    for d in ("core", "domain/graph", "governance", "tools/skills"):
        shutil.copytree(REPO / d, repo / d, ignore=shutil.ignore_patterns("__pycache__", "proposals", "frozen"))
    for f in ("scale-release.yaml", "domain/DOMAIN.yaml"):
        shutil.copy2(REPO / f, repo / f)
    src = schema_at(BASE)
    shutil.copy2(kernel_of(src), repo / "core/graph/kernel.yaml")
    shutil.copy2(src.parent / load_yaml(src)["domains"][0], repo / G / "catalysis.yaml")
    (repo / "releases").mkdir()
    v, kfz, fz = BASE, repo / "core/graph/frozen", repo / G / "frozen"
    (fz / f"v{v}").mkdir(parents=True)
    kfz.mkdir(parents=True)
    shutil.copy2(repo / "core/graph/kernel.yaml", kfz / f"kernel-{v}.yaml")
    shutil.copy2(repo / G / "catalysis.yaml", fz / f"v{v}/catalysis.yaml")
    man = {**{k: x for k, x in load_yaml(repo / G / "scale-graph.yaml").items() if k != "proposals"}, "version": v}
    (fz / f"scale-graph-{v}.yaml").write_text(dump_yaml({**man, "status": "frozen", "domains": [f"v{v}/catalysis.yaml"],
                                                         "kernel": os.path.relpath(kfz / f"kernel-{v}.yaml", fz)}))
    append_frozen_sums(kfz, [kfz / f"kernel-{v}.yaml"])
    append_frozen_sums(fz, [fz / f"scale-graph-{v}.yaml", fz / f"v{v}/catalysis.yaml"])
    cat = load_yaml(repo / G / "catalysis.yaml")
    cat["nodes"]["CatalyticTest"]["properties"]["test_only_note"] = {"type": "text", "maturity": "provisional"}
    (repo / G / "catalysis.yaml").write_text(dump_yaml(cat))
    (repo / G / "scale-graph.yaml").write_text(dump_yaml({**man, "version": "0.2.0", "proposals": ["009001"]}))
    data = tmp_path / "kg"
    ex = data / "examples/demo"
    ex.mkdir(parents=True)
    src = REPO / "domain/examples/scale-graph/driving-force-examples"
    shutil.copy2(src / "electro.json", ex / "electro.graph.json")
    shutil.copy2(src / "electro.json", ex / f"electro.scale-graph-{v}.graph.json")        # a copy kept at its version
    bad = load_doc(src / "photo.json")
    bad["graph"]["follows_domains"] = ["no-such-checklist"]
    write_canonical(ex / "odd.graph.json", bad)
    shutil.copytree(src, data / "sealed")                                   # a sealed package is not read
    (data / "sealed/.scale-verbatim").write_text("")
    kept = data / "proposals/000001/before-apply"                           # a proposal's input: not read
    kept.mkdir(parents=True)
    shutil.copy2(src / "electro.json", kept / "electro.graph.json")
    from scale.passages import Index, evidence_items
    Index.build(evidence_items(load_doc(ex / "electro.graph.json"))).save(ex / "electro.evidence")
    return repo, data, ex


@pytest.fixture()
def step(monkeypatch):
    """The step 0.1.0 -> 0.2.0 registered as its proposal registers it, with a rule that stops on a document it cannot
    map (a checklist the schema does not have)."""
    from scale import pgraph_migrate

    def rule(doc, spec):
        if doc["graph"].get("follows_domains") != ["catalysis"]:
            raise ScaleError(f"follows_domains {doc['graph'].get('follows_domains')} cannot be mapped")
        return []
    monkeypatch.setitem(pgraph_migrate.STEPS, BASE, ("0.2.0", "009001"))
    monkeypatch.setitem(pgraph_migrate.STEP_RULES, BASE, ("checklists checked", rule))


def test_kg_update_dry_run_writes_nothing(tmp_path, step):
    from scale.kg import update
    repo, data, _ = _two_versions(tmp_path)
    before = tree(data)
    res = update(repo, data, dry_run=True)
    assert tree(data) == before and not res["ok"]
    by = {r["document"].rsplit("/", 1)[-1]: r for r in res["documents"]}
    assert set(by) == {"electro.graph.json", f"electro.scale-graph-{BASE}.graph.json", "odd.graph.json"}
    assert by["electro.graph.json"]["status"] == "would update" and by["electro.graph.json"]["steps"] == [
        f"{BASE} → 0.2.0 (009001)"]
    assert by[f"electro.scale-graph-{BASE}.graph.json"]["status"] == "kept"
    assert by["odd.graph.json"]["status"] == "refused" and "a step rule cannot migrate it" in by["odd.graph.json"]["why"]


def test_kg_update_migrates_validates_and_reindexes(tmp_path, capsys, step):
    from scale.cli import main
    repo, data, ex = _two_versions(tmp_path)
    odd, kept = (ex / "odd.graph.json").read_bytes(), (ex / f"electro.scale-graph-{BASE}.graph.json").read_bytes()
    proposal_input = data / "proposals/000001/before-apply/electro.graph.json"
    index = (ex / "electro.evidence.jsonl").stat().st_mtime_ns
    assert main(["--repo", str(repo), "kg", "update", "--data", str(data), "--out", str(tmp_path / "r.json")]) == 1   # one refused
    res = load_doc(tmp_path / "r.json")
    row = next(r for r in res["documents"] if r["document"].endswith("/electro.graph.json"))
    assert row["status"] == "updated" and row["after"]["errors"] == 0 and row["index"].endswith("electro.evidence.jsonl")
    doc = load_doc(ex / "electro.graph.json")
    assert doc["graph"]["schema_version"] == "0.2.0" and doc["graph"]["follows_domains"] == ["catalysis"]
    assert (ex / "odd.graph.json").read_bytes() == odd and (ex / f"electro.scale-graph-{BASE}.graph.json").read_bytes() == kept
    assert (ex / "electro.evidence.jsonl").stat().st_mtime_ns != index
    assert load_doc(proposal_input)["graph"]["schema_version"] == BASE          # proposal folders are not read
    assert "refused" in capsys.readouterr().out
    assert res["counts"] == {"kept": 1, "refused": 1, "updated": 1}
    # a second run finds it current
    from scale.kg import update
    again = update(repo, data)
    assert next(r for r in again["documents"] if r["document"].endswith("/electro.graph.json"))["status"] == "current"


def test_the_apply_workflow_is_manual_and_pushes_only_with_its_own_token():
    """The apply-proposals workflow runs only when a person starts it (workflow_dispatch, from main) and pushes with the
    repository secret APPLY_TOKEN, never with the workflow token, which stays read-only; without the secret it stops at
    its first step. No workflow asks for contents: write. The main ruleset lets the repository admin (the owner) bypass
    it (the bootstrap rule), and no organization actor."""
    rules = json.loads((REPO / "governance/github/ruleset-main.json").read_text())
    actors = {(a["actor_type"], a["actor_id"], a["bypass_mode"]) for a in rules["bypass_actors"]}
    assert actors == {("RepositoryRole", 5, "always")}
    pr = next(r for r in rules["rules"] if r["type"] == "pull_request")["parameters"]
    assert pr["required_approving_review_count"] == 1 and not pr["require_code_owner_review"]   # any one reviewer
    wf = load_yaml(REPO / ".github/workflows/apply-proposals.yml")
    assert set(wf["on"]) == {"workflow_dispatch"} and set(wf["on"]["workflow_dispatch"]["inputs"]) == {"proposal", "pr"}
    job = wf["jobs"]["apply"]
    assert job["if"] == "github.ref == 'refs/heads/main'" and job["permissions"]["contents"] == "read"
    assert "environment" not in job and "APPLY_TOKEN" in (REPO / ".github/workflows/apply-proposals.yml").read_text()
    first = job["steps"][0]
    assert first["if"] == "env.HAS_APPLY_TOKEN != 'true'" and "exit 1" in first["run"]
    checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["token"] == "${{ secrets.APPLY_TOKEN }}"
    agent = load_yaml(REPO / ".github/workflows/scale-agent.yml")
    assert set(agent["on"]) == {"workflow_dispatch"}                       # off unless a person starts it
    for f in sorted((REPO / ".github/workflows").glob("*.yml")):
        perms = [load_yaml(f).get("permissions") or {}] + [j.get("permissions") or {} for j in load_yaml(f)["jobs"].values()]
        assert all(p.get("contents") != "write" for p in perms), f.name
