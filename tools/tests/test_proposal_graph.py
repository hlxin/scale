"""scale-graph proposals: a checked, reviewed and applied schema version (with a synthetic proposal,
proposal 009001, built on 0.1.0); one version for the kernel and the catalysis domain together, raised by
every applied proposal; proposal names (a six-digit number, global) and numbers allocated across owners; and the
review policy (approvals.required approving reviews from reviewers other than the author: one in the
repository, two in the engine tests below)."""

import datetime as dt
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from conftest import EXAMPLES, GRAPH_MANIFEST, REPO, kernel_of, schema_at
from scale import layout, pgraph
from scale.review import from_github, record
from scale.pgraph_proposal import apply, build, check, decide, diff_specs, head_manifest, set_version, tier, verify_frozen
from scale.policy import evaluate, load_policy
from scale.util import ScaleError, dump_yaml, load_doc, load_yaml, write_canonical

CS = REPO / "tools/tests/fixtures/proposals/009001"   # synthetic: adds PressureGauge to the catalysis domain
CS_REL = "domain/proposals/009001"           # where the mini repository holds it
NOW = dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc)
G = "domain/graph"                                   # the mini repository's catalysis graph directory
# an extra domain file of the mini repository (synthetic), for the restructuring operations
EXTRA = {"domain": "extra", "maturity": "provisional", "title": "Extra (test fixture)", "imports": [],
         "nodes": {"Kiln": {"is_a": "Instrument", "fixed": {"instrument_kind": "kiln"},
                            "description": "A synthetic instrument (test fixture)."}}}


BASE = load_yaml(CS / "proposal.yaml")["base"]["version"]   # the version the synthetic proposal is built on (0.1.0)


def _mini_repo(tmp_path, extra: bool = False):
    """A repository whose catalysis schema is scale-graph BASE, the version the synthetic proposal is built on: the
    kernel, the catalysis manifest and file of that version (the head's while the head is at it, else the frozen
    copies the repository keeps once a proposal has moved it on; with ``extra``, a second, synthetic domain file listed
    too), the files that state the one version, one example document pinning it and the proposal. No version is
    frozen yet."""
    repo = tmp_path / "repo"
    src = schema_at(BASE)
    man = load_yaml(src)
    (repo / "core/graph").mkdir(parents=True)
    shutil.copy2(kernel_of(src), repo / "core/graph/kernel.yaml")
    (repo / G).mkdir(parents=True)
    for rel in man["domains"]:
        shutil.copy2(src.parent / rel, repo / G / Path(rel).name)
    man.update(status=load_yaml(GRAPH_MANIFEST)["status"], kernel="../../core/graph/kernel.yaml",
               domains=[Path(rel).name for rel in man["domains"]])
    man.pop("proposals", None)
    if extra:
        (repo / G / "extra.yaml").write_text(dump_yaml(EXTRA))
        man["domains"] = man["domains"] + ["extra.yaml"]
    (repo / G / "scale-graph.yaml").write_text(dump_yaml(man))
    (repo / "domain/DOMAIN.yaml").write_text(dump_yaml({"domain": "catalysis", "status": "stable", "version": BASE,
                                                        "graph": {"manifest": "graph/scale-graph.yaml"}}))
    (repo / "core/examples").mkdir(parents=True)
    for rel, key in (("core/CORE.yaml", "version"), ("core/examples/science-kernel-only.yaml", "version"),
                     ("scale-release.yaml", "schema_version")):
        shutil.copy2(REPO / rel, repo / rel)
        set_version(repo / rel, key, BASE)
    (repo / "domain/examples/scale-graph").mkdir(parents=True)
    ex = load_doc(EXAMPLES / "scale-graph/example.json")
    assert ex["graph"]["schema_version"] == BASE, "the example has moved on: rebase the synthetic proposal 009001"
    write_canonical(repo / "domain/examples/scale-graph/example.json", ex)
    shutil.copytree(REPO / "governance", repo / "governance")
    pol = load_yaml(repo / "governance/review-policy.yaml")        # two filled seats besides hlxin, for the tests
    pol["reviewers"]["members"] = [{"name": "Hongliang Xin", "github": "hlxin", "since": "2026-09-26"},
                                   {"name": "Ada", "github": "ada", "since": "2026-10-05"},
                                   {"name": "Ben", "github": "ben", "since": "2026-10-05"}]
    (repo / "governance/review-policy.yaml").write_text(dump_yaml(pol))
    (repo / "docs/decisions").mkdir(parents=True)
    cs = repo / CS_REL
    shutil.copytree(CS, cs)
    return repo, cs


def gh_review(login, state="APPROVED", rid=1, at="2026-10-05T10:00:00Z", commit="c0ffee"):
    """A review as GET /repos/{o}/{r}/pulls/{n}/reviews returns it."""
    return {"id": rid, "user": {"login": login}, "state": state, "submitted_at": at, "commit_id": commit}


def _approve(cs, *who, pr=1, author="hlxin"):
    """Record approving reviews of the proposal's pull request (by default ada and ben; hlxin authored it)."""
    record(cs, from_github([gh_review(w, rid=i + 1) for i, w in enumerate(who or ("ada", "ben"))], pr, author))


# ------------------------------------------------------------------------------------------ check
def test_check_is_clean(tmp_path):
    repo, cs = _mini_repo(tmp_path)
    res = check(cs, repo, now=NOW)
    assert res["ok"] and not res["problems"] and not res["blocking"], res
    assert res["fixtures"] == res["fixtures_total"] == 2
    mig = load_doc(cs / "migration_assessment.json")
    assert mig["summary"] == "meaning_preserving"


def test_the_target_raises_the_one_version_whichever_file_changes(tmp_path):
    """One version for the kernel and the catalysis domain: the proposal's target must raise it; the parts carry none,
    so no part is asked for a version of its own."""
    repo, cs = _mini_repo(tmp_path)
    res = check(cs, repo, now=NOW)
    assert res["ok"] and not any("keeps version" in o["message"] or "version bump" in o["message"]
                                 for o in load_doc(cs / "critic_report.json")["objections"])
    p = load_yaml(cs / "proposal.yaml")
    p["target_version"] = BASE
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    assert any(f"target_version {BASE} does not raise the base {BASE}" in m
               for m in check(cs, repo, now=NOW)["problems"])
    p["target_version"] = "0.2.0"
    p["operations"].append({"op": "set", "file": f"{G}/catalysis.yaml", "path": "title", "value": "Catalysis (edited)"})
    p["operations"].append({"op": "add", "file": f"{G}/catalysis.yaml", "path": "", "key": "version", "value": "0.2.0"})
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    with pytest.raises(ScaleError, match="carries no version of its own"):       # a part may not name its own version
        check(cs, repo, now=NOW)


def test_new_concepts_enter_as_provisional(tmp_path):
    repo, cs = _mini_repo(tmp_path)
    spec = pgraph.load_spec(build(cs, repo))
    assert spec["version"] == "0.2.0" and "PressureGauge" in spec["nodes"]
    g = load_yaml(cs / "candidate/domain/graph/catalysis.yaml")["nodes"]["PressureGauge"]
    assert g["maturity"] == "provisional" and g["added_in"] == "0.2.0" and g["proposal"] == "009001"
    p = load_yaml(cs / "proposal.yaml")
    p["operations"][0]["value"]["maturity"] = "stable"
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    assert any("enters as stable" in x for x in check(cs, repo, now=NOW)["problems"])


def test_diff_and_tier():
    a = pgraph.load_spec(GRAPH_MANIFEST)
    b = {**a, "nodes": {k: v for k, v in a["nodes"].items() if k != "Descriptor"}}
    d = diff_specs(a, b)
    assert "nodes.Descriptor" in d["removed"] and tier(d) == 3
    assert tier(diff_specs(a, a)) == 0


# ------------------------------------------------------------------------------------------ review policy
POLICY = {"policy_version": 1, "reviewers": {"team": "@example-org/reviewers", "members": [
    {"name": "Ada", "github": "ada"}, {"name": "Ben", "github": "ben"}, {"name": "Cy", "github": "cy"},
    {"name": "TODO-reviewer-4", "github": "TODO-reviewer-4", "placeholder": True}]},
    "approvals": {"required": 2, "author_counts": False, "placeholders_count": False}}


def A(who, decision="approve", at="2026-09-28T00:00:00+00:00"):
    return {"reviewer": who, "decision": decision, "at": at}


def test_two_reviewers_other_than_the_author_approve():
    assert evaluate(POLICY, [A("ada"), A("ben")], author="cy")["satisfied"]
    st = evaluate(POLICY, [A("ada")], author="cy")
    assert not st["satisfied"] and st["missing"] == ["1 more approving review(s) from reviewers other than the author (has 1 of 2)"]
    st = evaluate(POLICY, [A("ada"), A("ben")], author="ada")                  # the author's own review never counts
    assert not st["satisfied"] and st["ignored"] == [{"reviewer": "ada", "why": "the author of the change"}]
    st = evaluate(POLICY, [A("Ada"), A("ADA")], author="cy")                   # one person, two reviews: one approval
    assert st["approved_by"] == ["ada"] and not st["satisfied"]


def test_placeholders_and_people_outside_the_policy_never_count():
    st = evaluate(POLICY, [A("ada"), A("TODO-reviewer-4"), A("eve")], author="cy")
    assert not st["satisfied"] and st["approved_by"] == ["ada"]
    assert {x["reviewer"]: x["why"] for x in st["ignored"]} == {"TODO-reviewer-4": "a placeholder seat, not a person",
                                                                 "eve": "not a reviewer in the review policy"}


def test_the_latest_review_counts_and_requested_changes_block():
    st = evaluate(POLICY, [A("ada"), A("ben"), A("cy", "request_changes", "2026-09-28T01:00:00+00:00")], author="eve")
    assert not st["satisfied"] and st["blocking"] == ["cy"]
    st = evaluate(POLICY, [A("ada"), A("ben"), A("cy", "request_changes", "2026-09-28T01:00:00+00:00"),
                           A("cy", "approve", "2026-09-28T02:00:00+00:00")], author="eve")
    assert st["satisfied"] and st["approved_by"] == ["ada", "ben", "cy"]
    st = evaluate(POLICY, [A("ada"), A("ben"), A("ben", "comment", "2026-09-28T03:00:00+00:00")], author="eve")
    assert st["satisfied"]                                                         # a comment keeps an approval
    st = evaluate(POLICY, [A("ada"), A("ben"), A("ben", "dismissed", "2026-09-28T03:00:00+00:00")], author="eve")
    assert not st["satisfied"]                                                     # a dismissed review does not


def test_the_repository_policy_has_one_reviewer_and_two_placeholders():
    from scale.policy import approvable, placeholders, reviewers
    pol = load_policy(REPO)
    assert pol["policy_version"] == 3 and pol["approvals"]["required"] == 1 and pol["reviewers"]["team"] == "@hlxin"
    assert [m["github"] for m in reviewers(pol)] == ["hlxin"]
    assert [m["github"] for m in placeholders(pol)] == ["TODO-reviewer-2", "TODO-reviewer-3"]
    st = evaluate(pol, [A("hlxin"), A("TODO-reviewer-2"), A("TODO-reviewer-3")], author="someone")
    assert st["satisfied"] and st["approved_by"] == ["hlxin"]          # the owner approves someone else's change
    st = evaluate(pol, [A("TODO-reviewer-2")], author="hlxin")
    assert not st["satisfied"] and st["notes"]                          # the owner's own change: nobody can approve yet
    assert not approvable(pol, "hlxin") and approvable(pol, "someone")
    one = {**pol, "reviewers": {**pol["reviewers"], "members": [*reviewers(pol), {"name": "Ada", "github": "ada"}]}}
    assert approvable(one, "hlxin") and evaluate(one, [A("ada")], author="hlxin")["satisfied"]   # one expert is enough


def test_github_reviews_become_approval_records(tmp_path):
    """GitHub review states map to decisions; an approval of an older commit than the merged head is stale."""
    reviews = [gh_review("ada", rid=11, commit="head"), gh_review("ben", rid=12, commit="old"),
               gh_review("cy", "CHANGES_REQUESTED", rid=13, commit="head"), gh_review("dee", "PENDING", rid=14),
               {"id": 15, "user": None, "state": "APPROVED", "submitted_at": "2026-10-05T10:00:00Z"}]
    recs = from_github(reviews, 7, author="eve", head_sha="head")
    assert [(r["reviewer"], r["decision"]) for r in recs] == [("ada", "approve"), ("ben", "dismissed"), ("cy", "request_changes")]
    assert recs[0] == {"reviewer": "ada", "decision": "approve", "at": "2026-10-05T10:00:00Z", "pr": 7, "review_id": 11,
                       "source": "github", "commit": "head", "pr_author": "eve"}
    repo, cs = _mini_repo(tmp_path)
    assert [p.name for p in record(cs, recs[:1])] == ["github-ada-11.json"]
    assert record(cs, recs[:1]) == []                                              # recorded once
    assert load_doc(cs / "approvals/github-ada-11.json")["proposal"] == "009001"


def test_decide_then_apply_freezes_the_base_and_installs_the_candidate(tmp_path):
    repo, cs = _mini_repo(tmp_path)
    check(cs, repo, now=NOW)
    with pytest.raises(ScaleError, match="not approved"):
        decide(cs, repo, now=NOW)
    _approve(cs)
    rec = decide(cs, repo, now=NOW)
    assert rec.name == "0001-009001.md" and "Approved by:** ada, ben" in rec.read_text()   # NNNN-<id>.md
    assert rec.read_text().startswith("# Decision record 0001 — proposal 009001: ")
    assert load_doc(repo / "docs/decisions/log.json")["decisions"][0]["proposal"] == "009001"
    assert apply(cs, repo)["dry_run"]
    apply(cs, repo, confirm=True)
    fz = repo / G / "frozen"
    head, frozen = pgraph.load_spec(repo / G / "scale-graph.yaml"), pgraph.load_spec(fz / f"scale-graph-{BASE}.yaml")
    assert head["version"] == "0.2.0" and "PressureGauge" in head["nodes"]
    assert frozen["version"] == BASE and "PressureGauge" not in frozen["nodes"]
    assert load_yaml(repo / G / "scale-graph.yaml")["proposals"] == ["009001"]   # the first proposal, no empty entry
    # one version: the kernel of the base version is frozen under it (in the core), the domain's parts beside its manifest
    assert load_yaml(fz / f"scale-graph-{BASE}.yaml")["kernel"] == f"../../../core/graph/frozen/kernel-{BASE}.yaml"
    assert (repo / f"core/graph/frozen/kernel-{BASE}.yaml").read_bytes() == (repo / "core/graph/kernel.yaml").read_bytes()
    assert (fz / f"v{BASE}/catalysis.yaml").exists() and not list(fz.rglob("kernel*"))
    # every file that states the one version follows it; the kernel and the catalysis file carry none
    for rel, key in (("core/CORE.yaml", "version"), ("domain/DOMAIN.yaml", "version"), ("scale-release.yaml", "schema_version"),
                     ("core/examples/science-kernel-only.yaml", "version")):
        assert str(load_yaml(repo / rel)[key]) == "0.2.0", rel
    assert "version" not in load_yaml(repo / "core/graph/kernel.yaml") and "version" not in load_yaml(repo / G / "catalysis.yaml")
    res = verify_frozen(repo)
    assert res["ok"] and res["files"] == 3                      # the kernel; the manifest and its one domain part
    # rebuilding the applied proposal reads the frozen base and keys its parts onto the head paths
    built = build(cs, repo)
    assert built == cs / "candidate" / G / "scale-graph.yaml"
    assert (cs / "candidate" / G / "catalysis.yaml").read_text() == (repo / G / "catalysis.yaml").read_text()
    old = load_doc(repo / "domain/examples/scale-graph/example.json")   # pins the base: validates against the frozen copy
    assert pgraph.validate(old, pgraph.load_spec(pgraph.spec_for(repo, BASE))).errors == []
    with pytest.raises(ScaleError, match=f"built on {BASE}"):
        apply(cs, repo, confirm=True)


def test_apply_refuses_a_base_version_frozen_already(tmp_path):
    repo, cs = _mini_repo(tmp_path)
    check(cs, repo, now=NOW)
    _approve(cs)
    decide(cs, repo, now=NOW)
    kfz = repo / "core/graph/frozen"                             # the base version's kernel frozen before
    kfz.mkdir(parents=True)
    (kfz / f"kernel-{BASE}.yaml").write_text((repo / "core/graph/kernel.yaml").read_text())
    with pytest.raises(ScaleError, match=f"kernel-{BASE}.yaml exists already: version {BASE} was frozen before"):
        apply(cs, repo, confirm=True)
    assert not (repo / G / "frozen").exists()                   # nothing was frozen or installed
    assert load_yaml(repo / G / "scale-graph.yaml")["version"] == BASE


def test_apply_installs_only_the_candidate_its_proposal_builds(tmp_path):
    """A check whose candidate does not load leaves no candidate/ behind; a candidate/ that is not what proposal.yaml
    builds on the head (left by an earlier check, or older than an edit) is refused, in the dry run too, before
    anything is frozen or installed."""
    repo, cs = _mini_repo(tmp_path)
    p = load_yaml(cs / "proposal.yaml")
    versioned = {**p, "operations": p["operations"] + [
        {"op": "add", "file": "core/graph/kernel.yaml", "path": "", "key": "version", "value": "0.2.0"}]}
    (cs / "proposal.yaml").write_text(dump_yaml(versioned))
    with pytest.raises(ScaleError, match="the kernel carries no version of its own"):
        check(cs, repo, now=NOW)
    assert not (cs / "candidate").exists()
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    assert check(cs, repo, now=NOW)["ok"]
    _approve(cs)
    decide(cs, repo, now=NOW)
    k = cs / "candidate/core/graph/kernel.yaml"
    built = k.read_text()
    k.write_text(built.replace("kernel: scale-graph-kernel\n", "kernel: scale-graph-kernel\nversion: 0.2.0\n", 1))
    for confirm in (False, True):
        with pytest.raises(ScaleError, match=r"009001: the committed candidate/ is not what proposal.yaml builds on this "
                                             r"head \(core/graph/kernel.yaml differs\)"):
            apply(cs, repo, confirm=confirm)
    assert not (repo / G / "frozen").exists() and not (repo / "core/graph/frozen").exists()
    assert load_yaml(repo / G / "scale-graph.yaml")["version"] == BASE and "version" not in load_yaml(repo / "core/graph/kernel.yaml")
    k.write_text(built)
    assert apply(cs, repo, confirm=True)["dry_run"] is False
    assert load_yaml(repo / G / "scale-graph.yaml")["version"] == "0.2.0"


def test_a_kernel_and_catalysis_proposal_raises_the_one_version_and_the_next_freezes_its_kernel(tmp_path):
    """A proposal that edits the kernel and the catalysis file raises the one version like any other; the next proposal
    freezes the kernel of its own base version beside that version's catalysis parts."""
    repo, cs = _mini_repo(tmp_path)
    p = load_yaml(cs / "proposal.yaml")
    p["operations"].append({"op": "add", "file": "core/graph/kernel.yaml", "path": "nodes.Source.properties",
                            "key": "gauge_note", "value": {"type": "text", "description": "A synthetic note (test)."}})
    p["areas"] = ["kernel", "catalysis"]
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    res = check(cs, repo, now=NOW)
    assert res["ok"], res
    assert any("touches the science kernel" in o["message"] for o in load_doc(cs / "critic_report.json")["objections"])
    _approve(cs)
    decide(cs, repo, now=NOW)
    plan = apply(cs, repo, confirm=True)
    assert plan["freeze_kernel"] == f"core/graph/frozen/kernel-{BASE}.yaml" and "core/graph/kernel.yaml" in plan["install"]
    assert "gauge_note" in pgraph.load_spec(repo / G / "scale-graph.yaml")["nodes"]["Source"]["properties"]
    assert "gauge_note" not in load_yaml(repo / f"core/graph/frozen/kernel-{BASE}.yaml")["nodes"]["Source"]["properties"]
    assert verify_frozen(repo)["ok"]
    # the next proposal (catalysis only) is built on 0.2.0 and freezes 0.2.0, the kernel with it
    cs2 = repo / "domain/proposals/009002"
    shutil.copytree(CS, cs2)
    p = load_yaml(cs2 / "proposal.yaml")
    p.update({"id": "009002", "base": {**p["base"], "version": "0.2.0"}, "target_version": "0.3.0"})
    p["operations"][0].update(key="FlowGauge", value={**p["operations"][0]["value"], "description": "What measures a reported flow."})
    p["fixtures"] = json.loads(json.dumps(p["fixtures"]).replace("proposals/009001/", "proposals/009002/"))
    (cs2 / "proposal.yaml").write_text(dump_yaml(p))
    for f in (cs2 / "fixtures").glob("*.json"):                 # the fixtures pin the version they are written for
        d = load_doc(f)
        d["graph"]["schema_version"] = "0.3.0"
        write_canonical(f, d)
    assert check(cs2, repo, now=NOW)["ok"]
    _approve(cs2)
    decide(cs2, repo, now=NOW)
    plan = apply(cs2, repo, confirm=True)
    assert plan["freeze_kernel"] == "core/graph/frozen/kernel-0.2.0.yaml" and not any(x.startswith("core/graph/kernel")
                                                                                       for x in plan["install"])
    assert (repo / "core/graph/frozen/kernel-0.2.0.yaml").read_bytes() == (repo / "core/graph/kernel.yaml").read_bytes()
    assert sorted(p.name for p in (repo / "core/graph/frozen").glob("kernel-*.yaml")) == [f"kernel-{BASE}.yaml",
                                                                                          "kernel-0.2.0.yaml"]
    assert verify_frozen(repo)["ok"] and load_yaml(repo / G / "scale-graph.yaml")["proposals"] == ["009001", "009002"]
    assert load_yaml(repo / "core/CORE.yaml")["version"] == "0.3.0"


def test_a_misspelled_base_manifest_fails_loudly():
    cat = REPO / "domain/graph/scale-graph.yaml"
    assert head_manifest(REPO, {"id": "000099", "base": {"manifest": "domain/graph/scale-graph.yaml"}}) == cat
    for rel in ("domain/graph/scale-graph.yml", "domain/catalysis/graph/scale-graph.yaml", "schema/scale-graph.yaml", None):
        with pytest.raises(ScaleError, match="000099: base.manifest .* does not exist; set it to domain/graph/scale-graph.yaml"):
            head_manifest(REPO, {"id": "000099", "base": {"manifest": rel, "version": "0.1.0"}})


def test_the_candidate_mirrors_repository_paths(tmp_path):
    repo, cs = _mini_repo(tmp_path)
    man = load_yaml(build(cs, repo))
    assert man["kernel"] == "../../core/graph/kernel.yaml" and man["domains"] == ["catalysis.yaml"]   # from domain/graph/
    assert (cs / "candidate/core/graph/kernel.yaml").is_file() and not (cs / "candidate/scale-graph.yaml").exists()
    p = load_yaml(cs / "proposal.yaml")
    p["operations"][0]["file"] = "no/such/file.yaml"
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    with pytest.raises(ScaleError, match="is not part of the base schema"):
        build(cs, repo)


def test_apply_finds_the_decision_through_the_log(tmp_path):
    repo, cs = _mini_repo(tmp_path)
    check(cs, repo, now=NOW)
    _approve(cs)
    decide(cs, repo, now=NOW)
    log = load_doc(repo / "docs/decisions/log.json")
    assert log["decisions"][0]["proposal_dir"] == CS_REL
    other = repo / "core/proposals/009001"                 # the same number, decided for the domain's directory
    shutil.copytree(cs, other)
    with pytest.raises(ScaleError, match="decision for 009001 was made on domain/proposals/009001, not core/"):
        apply(other, repo)


def test_the_decision_log_names_the_proposal_by_its_id(tmp_path):
    """apply finds the decision through the log entry whose ``proposal`` is the proposal's six-digit id; an entry
    for another id is not this proposal's decision."""
    repo, cs = _mini_repo(tmp_path)
    check(cs, repo, now=NOW)
    _approve(cs)
    decide(cs, repo, now=NOW)
    log = load_doc(repo / "docs/decisions/log.json")
    assert log["decisions"][0]["proposal"] == "009001"
    assert apply(cs, repo)["decision_record"] == "docs/decisions/0001-009001.md"
    log["decisions"][0]["proposal"] = "009042"
    write_canonical(repo / "docs/decisions/log.json", log)
    with pytest.raises(ScaleError, match="no decision record for 009001"):
        apply(cs, repo)


def test_proposals_are_numbered_and_resolve_by_id_or_path(tmp_path):
    from scale import layout
    repo, cs = _mini_repo(tmp_path)
    for name in ("009001", str(cs), cs):
        assert layout.resolve_proposal(repo, name) == cs
    assert layout.proposal_dir(repo, "009001") == cs and layout.proposal_dir(repo, "007777") is None
    with pytest.raises(ScaleError, match="no proposal pressure-gauge: give its directory or its six-digit id"):
        layout.resolve_proposal(repo, "pressure-gauge")
    # only the exact six-digit id: a shorter or longer number is refused (it could be a typo)
    for ambiguous in ("9001", "09001", "0009001", 9001):
        with pytest.raises(ScaleError, match="is (ambiguous|a number)"):
            layout.resolve_proposal(repo, ambiguous)
    with pytest.raises(ScaleError, match=r"did you mean 009001\?"):
        layout.resolve_proposal(repo, "9001")
    # a well-formed six-digit id that no proposal has is simply unknown, not ambiguous
    with pytest.raises(ScaleError, match=r"no proposal 009099 \(the next number is 009002\)"):
        layout.resolve_proposal(repo, "009099")
    # numbers are global: the next is the highest of any owner plus one, whoever opens it
    assert layout.next_proposal_id(repo) == "009002"
    with pytest.raises(ScaleError, match="unknown proposal owner 'batteries'"):
        layout.proposal_root(repo, "batteries")


def test_proposal_numbers_are_global_and_folders_are_six_digits(tmp_path):
    from scale import layout
    from scale.pgraph_proposal import load_proposal
    repo, cs = _mini_repo(tmp_path)
    shutil.copytree(cs, repo / "core/proposals/009001")          # the same number under another owner
    with pytest.raises(ScaleError, match="proposal 009001 exists twice"):
        layout.proposal_dir(repo, "009001")
    shutil.rmtree(repo / "core/proposals/009001")
    for bad in ("core/proposals/kernel-units", "domain/proposals/P-0002",
                "domain/proposals/gauges-0003", "domain/proposals/00003",
                "domain/proposals/0000003", "domain/proposals/000004-with-title"):
        (repo / bad).mkdir(parents=True)
        with pytest.raises(ScaleError, match="a proposal directory is named by its six-digit number"):
            layout.proposal_dirs(repo)
        (repo / bad).rmdir()
    # the id in proposal.yaml is its folder's number, as a string: unquoted, YAML reads 000007 as the octal number 7
    y = cs / "proposal.yaml"
    text = y.read_text()
    for wrong, msg in (("id: '009002'", "id '009002' is not its directory's number '009001'"),
                       ("id: 000007", "id 7 is not its directory's number '009001'; write it quoted, id: '009001'"),
                       # PyYAML keeps 009001 a string (no octal digit 9), but a YAML 1.2 reader takes it for 9001
                       ("id: 009001", "id 009001 is unquoted; write it quoted, id: '009001'"),
                       ("id: 009001  # the number", "id 009001 is unquoted; write it quoted, id: '009001'")):
        y.write_text(text.replace("id: '009001'", wrong))
        with pytest.raises(ScaleError, match=re.escape(msg)):
            layout.proposal_dirs(repo)
    y.write_text(text.replace("id: '009001'", "id: 009001"))
    with pytest.raises(ScaleError, match=re.escape("id 009001 is unquoted; quote it (id: '009001')")):
        load_proposal(cs)
    y.write_text(text)


def test_proposal_new_allocates_the_next_id_and_scaffolds_a_checkable_proposal(tmp_path):
    from scale import layout
    from scale.pgraph_proposal import load_proposal, new_proposal
    repo, cs = _mini_repo(tmp_path)
    d = new_proposal(repo, "catalysis", "Flow gauges", now=NOW)
    assert d == repo / "domain/proposals/009002"
    assert "id: '009002'" in (d / "proposal.yaml").read_text()   # quoted: YAML must never read it as a number
    p = load_proposal(d)
    assert (p["id"], p["title"], p["status"], p["target_version"]) == ("009002", "Flow gauges", "draft", "0.2.0")
    assert p["base"] == {"manifest": "domain/graph/scale-graph.yaml", "version": "0.1.0"}
    assert build(d, repo).is_file()                              # it builds; check says what is missing
    k = new_proposal(repo, "core", "Units in the kernel", now=NOW)   # the next number, whichever owner opens it
    assert k == repo / "core/proposals/009003" and load_proposal(k)["title"] == "Units in the kernel"
    assert layout.proposal_dirs(repo).keys() == {"009001", "009002", "009003"}
    with pytest.raises(ScaleError, match="unknown proposal owner 'batteries'"):
        new_proposal(repo, "batteries")


def test_check_warns_while_the_proposals_migration_step_is_missing(tmp_path, monkeypatch):
    """Without its step in pgraph_migrate.STEPS (base -> target, this proposal's id), `scale graph migrate` could not
    move documents pinning the base once the proposal is applied: the check says so (a warning, in its result, the
    critic report and the pull-request comment), and the scaffold `scale proposal new` writes names the line."""
    from scale import pgraph_migrate
    from scale.ci import proposal_comment
    from scale.pgraph_proposal import new_proposal
    repo, cs = _mini_repo(tmp_path)
    monkeypatch.setattr(pgraph_migrate, "STEPS", {})
    res = check(cs, repo, now=NOW)
    want = f"no migration step {BASE} -> 0.2.0 for 009001 in tools/scale/pgraph_migrate.py STEPS"
    assert res["ok"] and len(res["warnings"]) == 1 and res["warnings"][0].startswith(want), res
    assert f'"{BASE}": ("0.2.0", "009001")' in res["warnings"][0]
    assert any(o["severity"] == "advisory" and o["message"].startswith(want)
               for o in load_doc(cs / "critic_report.json")["objections"])
    row = {"proposal": "009001", "path": CS_REL, "status": "proposed", "result": "ok", "check": res}
    assert f"- warning: {want}" in proposal_comment({"repo": str(repo), "proposals": [row], "ok": True})
    monkeypatch.setattr(pgraph_migrate, "STEPS", {BASE: ("0.2.0", "009042")})     # another proposal's step
    assert "(it registers " + BASE + " -> 0.2.0 for 009042)" in check(cs, repo, now=NOW)["warnings"][0]
    monkeypatch.setattr(pgraph_migrate, "STEPS", {BASE: ("0.2.0", "009001")})     # registered: no warning
    res = check(cs, repo, now=NOW)
    assert res["ok"] and res["warnings"] == []
    assert not any("migration step" in o["message"] for o in load_doc(cs / "critic_report.json")["objections"])
    d = new_proposal(repo, "catalysis", "Flow gauges", now=NOW)
    assert f'(STEPS: "{BASE}": ("0.2.0", "009002"))' in (d / "proposal.yaml").read_text()


def test_the_proposal_commands_refuse_the_data_bundled_in_an_installed_package(tmp_path):
    """Outside a checkout the tools find the data bundled in the installed package (scale/_data); new, build, decide
    and apply would write into it, so they refuse it and say to run in a checkout (or pass --repo)."""
    from scale.pgraph_proposal import new_proposal
    repo, cs = _mini_repo(tmp_path)
    pkg = tmp_path / "site-packages/scale"
    pkg.mkdir(parents=True)
    for f in ("__init__.py", "layout.py"):
        (pkg / f).write_text("")
    bundled = pkg / "_data"
    shutil.copytree(repo, bundled)
    assert layout.is_bundled(bundled) and not layout.is_bundled(repo)
    assert layout.is_bundled(Path(layout.__file__).resolve().parent / "_data")
    bcs = bundled / CS_REL
    for what, call in (("new", lambda: new_proposal(bundled, "catalysis", "x", now=NOW)),
                       ("build", lambda: build(bcs, bundled)), ("decide", lambda: decide(bcs, bundled)),
                       ("apply", lambda: apply(bcs, bundled, confirm=True))):
        with pytest.raises(ScaleError, match=rf"scale proposal {what} writes into a repository checkout; .* is the data "
                                             r"bundled in the installed package\. Run it inside a checkout of "
                                             r"https://github\.com/hlxin/scale, or pass --repo"):
            call()
    assert sorted(p.name for p in (bundled / "domain/proposals").iterdir()) == ["009001"]     # nothing written
    assert not (bcs / "candidate").exists()


def test_proposal_ids_stay_strings_in_every_yaml_written_or_read():
    """Unquoted, YAML 1.1 reads 000007 as the octal number 7 (and YAML 1.2 reads 000008 as 8): the writer quotes
    every string of digits, and a reader that meets a number where a proposal id belongs refuses it."""
    from scale import layout
    text = dump_yaml({"id": "000008", "proposals": ["000004", "000007", "000005"], "count": 7})
    assert "id: '000008'" in text and "- '000007'" in text and "- '000004'" in text and "count: 7" in text
    assert yaml.safe_load(text) == {"id": "000008", "proposals": ["000004", "000007", "000005"], "count": 7}
    assert layout.manifest_proposals(yaml.safe_load(text)) == ["000004", "000007", "000005"]
    assert layout.manifest_proposals({"proposals": [], "proposal": "000009"}, own=True) == ["000009"]
    with pytest.raises(ScaleError, match=r"proposals entries \[4, 7\] are not strings; quote proposal ids"):
        layout.manifest_proposals(yaml.safe_load("proposals:\n- 000004\n- 000007\n- '000005'\n"), "m.yaml")
    assert layout.is_proposal_id("000008") and not layout.is_proposal_id(8) and not layout.is_proposal_id("00008")


def test_proposal_ids_are_unique_in_the_repository():
    """Whatever proposals the repository holds (none before the first, 000001): each folder of core/proposals/ and
    domain/proposals/ is a six-digit number used once across both, named again by its proposal.yaml; the migration
    steps and the head manifest cite only proposals that exist; the next number is the highest plus one."""
    from scale import layout
    from scale.pgraph_migrate import STEPS
    found = layout.proposal_dirs(REPO)                           # raises on a duplicate or a misnamed folder
    for root in (REPO / "core/proposals", REPO / "domain/proposals"):
        assert (root / "README.md").is_file(), root
        assert {p.name for p in root.iterdir()} - {"README.md"} == {pid for pid, d in found.items() if d.parent == root}
    for pid, d in found.items():                                 # one name each: the number, in the folder and the file
        p = load_yaml(d / "proposal.yaml")
        assert p["id"] == pid and d.name == pid and "aliases" not in p
    assert {pid for _, pid in STEPS.values()} <= set(found)      # the migration steps cite proposals by their ids
    assert set(layout.manifest_proposals(load_yaml(GRAPH_MANIFEST))) <= set(found)
    assert layout.next_proposal_id(REPO) == f"{max((int(x) for x in found), default=0) + 1:06d}"


def test_every_applied_proposal_has_its_migration_step():
    """Each step is its proposal's own (base -> target), registered when the proposal is prepared (so that `scale
    proposal check` assesses it, and applying the merged proposal, which adds no code, leaves no document
    stranded at an older version); every proposal applied to the catalysis head has its step. At 0.1.0 there are none."""
    from scale import layout
    from scale.pgraph_migrate import STEPS, route
    for base, (target, pid) in STEPS.items():
        p = load_yaml(layout.proposal_dir(REPO, pid) / "proposal.yaml")
        assert (p["base"]["version"], p["target_version"]) == (base, target) and p["status"] in ("proposed", "applied"), pid
    head = load_yaml(REPO / "domain/graph/scale-graph.yaml")
    applied = layout.manifest_proposals(head)
    assert set(applied) <= {pid for _, pid in STEPS.values()}
    first = min([b for b in STEPS] + [head["version"]], key=lambda v: tuple(map(int, v.split("."))))
    assert [cs for _, _, cs in route(first, head["version"])] == applied     # every frozen version reaches the head


def test_a_missing_gap_source_is_an_error_not_an_empty_list(tmp_path):
    repo, cs = _mini_repo(tmp_path)
    p = load_yaml(cs / "proposal.yaml")
    p["gap_sources"] = ["domain/examples/no-such-example/curation/fragments"]   # in neither tree
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    with pytest.raises(ScaleError, match="gap_sources: .* does not exist"):
        check(cs, repo, now=NOW)


def test_a_proposal_reads_restricted_inputs_through_the_resolver(tmp_path, monkeypatch):
    """A document or gap source that may not be committed is read from the optional restricted copy
    ($SCALE_RESTRICTED_DATA, same repository-relative path); without it the check fails and says what it needs, it
    does not assess less."""
    repo, cs = _mini_repo(tmp_path)
    rel = "domain/examples/scale-graph/example.json"
    restricted = tmp_path / "restricted"
    (restricted / rel).parent.mkdir(parents=True)
    (repo / rel).rename(restricted / rel)                                     # the assessed document is restricted
    monkeypatch.setenv("SCALE_RESTRICTED_DATA", str(tmp_path / "absent"))
    with pytest.raises(ScaleError, match=r"assess_documents: .*example.json does not exist: not in the repository; SCALE_RESTRICTED_DATA=.* does not exist"):
        check(cs, repo, now=NOW)
    monkeypatch.setenv("SCALE_RESTRICTED_DATA", str(restricted))
    assert check(cs, repo, now=NOW)["ok"]
    assert [d["document"] for d in load_doc(cs / "migration_assessment.json")["documents"]] == [rel]   # named by its path


def test_what_a_proposal_derives_from_restricted_inputs_is_written_to_the_restricted_copy(tmp_path, monkeypatch):
    """A proposal that reads restricted inputs (a gap source, an assessed document) writes its full reports to
    the restricted copy at its repository-relative path, and public summaries into its folder: no gap statement,
    no record of a restricted document, a PR body that says the details are restricted. The original proposal kept
    in the restricted copy gives the full PR body its motivation."""
    repo, cs = _mini_repo(tmp_path)
    restricted = tmp_path / "restricted"
    rel = "domain/examples/scale-graph/example.json"
    (restricted / rel).parent.mkdir(parents=True)
    (repo / rel).rename(restricted / rel)                                    # the assessed document is restricted
    gaps = "domain/examples/secret/curation/fragments"
    write_canonical(restricted / gaps / "src1.json", {"gaps": [{"kind": "missing_concept", "text": "SECRET gap statement",
                                                                 "about": "ex:secret/record/1", "locator": "p. 3"}]})
    p = load_yaml(cs / "proposal.yaml")
    p.update(gap_sources=[gaps], gap_themes=[{"id": "TH-01", "title": "A deferred theme", "resolution": "deferred",
                                              "reason": "later", "instances": ["src1#gap/0"]}])
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    rcs = restricted / CS_REL
    rcs.mkdir(parents=True)
    (rcs / "proposal.yaml").write_text(dump_yaml({**p, "motivation": "SECRET motivation quoting a source"}))
    monkeypatch.setenv("SCALE_RESTRICTED_DATA", str(restricted))
    res = check(cs, repo, now=NOW)
    assert res["ok"], res
    full = load_doc(rcs / "evidence_pack.json")["themes"][0]["instances"][0]
    assert full["text"] == "SECRET gap statement" and full["about"] == "ex:secret/record/1"
    assert "SECRET motivation" in (rcs / "PR_BODY.md").read_text() and "### Restricted data" not in (rcs / "PR_BODY.md").read_text()
    for name in ("evidence_pack.json", "migration_assessment.json", "validation_report.json", "critic_report.json",
                 "review_checklist.md", "PR_BODY.md"):
        assert (rcs / name).is_file() and (cs / name).is_file(), name
        assert "SECRET" not in (cs / name).read_text() and "ex:secret" not in (cs / name).read_text(), name
    pub = load_doc(cs / "evidence_pack.json")
    assert pub["themes"][0]["instances"] == [{"id": "src1#gap/0", "source": "src1", "status": "open", "resolved_by": None,
                                              "restricted": True}]
    assert sorted(pub["restricted"]["inputs"]) == sorted([gaps, rel])
    doc = load_doc(cs / "migration_assessment.json")["documents"][0]
    assert doc["document"] == rel and doc["restricted"] and "first_errors_after" not in doc and doc["errors_after"] == 0
    assert load_doc(cs / "validation_report.json")["tier"] == load_doc(rcs / "validation_report.json")["tier"]
    body = (cs / "PR_BODY.md").read_text()
    assert "### Restricted data" in body and f"`{gaps}`" in body
    assert (cs / "patch.diff").is_file() and not (rcs / "patch.diff").exists()   # the schema change is public


# ------------------------------------------------------------------------------------------ restructuring
def test_files_added_and_removed_change_the_manifest_lists_too(tmp_path):
    """remove_files drops the file and its entry in the candidate manifest; add_files brings a file the operations
    list; apply freezes the removed file with the base and deletes it from the head."""
    repo, cs = _mini_repo(tmp_path, extra=True)
    extra, man_rel = f"{G}/extra.yaml", (Path(G) / "scale-graph.yaml").as_posix()
    (cs / "files").mkdir()
    (cs / "files/barocatalysis.yaml").write_text(dump_yaml({
        "domain": "barocatalysis", "driving_forces": ["other"], "imports": [],
        "checklist": {"labels": {"CatalyticTest": {"must": ["pressure"]}}}}))
    p = load_yaml(cs / "proposal.yaml")
    p["remove_files"] = [extra]
    p["add_files"] = [{"path": "barocatalysis.yaml", "from": "files/barocatalysis.yaml"}]
    p["operations"].append({"op": "extend", "file": man_rel, "path": "domains", "values": ["barocatalysis.yaml"]})
    p["decision_record"] = "docs/decisions/0000-draft.md"          # removing a label is tier 3
    p["migration_spec"] = {"rule": "none needed: no document uses Kiln"}
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    man = load_yaml(build(cs, repo))
    assert "extra.yaml" not in man["domains"] and man["domains"][-1] == "barocatalysis.yaml"
    assert not (cs / "candidate" / extra).exists() and (cs / "candidate" / G / "barocatalysis.yaml").is_file()
    spec = pgraph.load_spec(cs / "candidate" / G / "scale-graph.yaml")
    assert "barocatalysis" in spec["profiles"] and "Kiln" not in spec["nodes"]
    res = check(cs, repo, now=NOW)
    assert res["tier"] == 3 and "nodes.Kiln" in load_doc(cs / "validation_report.json")["diff"]["removed"]
    assert "+++ /dev/null" in (cs / "patch.diff").read_text() and "b/domain/graph/barocatalysis.yaml" in \
        (cs / "patch.diff").read_text()
    (repo / "docs/decisions/0000-draft.md").write_text("# draft\n")
    _approve(cs)
    decide(cs, repo, now=NOW)
    plan = apply(cs, repo, confirm=True)
    assert plan["remove"] == [extra] and not (repo / extra).exists()
    assert (repo / G / f"frozen/v{BASE}/extra.yaml").is_file()
    assert (repo / G / "barocatalysis.yaml").is_file() and verify_frozen(repo)["ok"]
    head = load_yaml(repo / G / "scale-graph.yaml")
    assert "extra.yaml" not in head["domains"] and head["version"] == "0.2.0"
    for bad in ([man_rel], ["core/graph/kernel.yaml"], [f"{G}/no-such.yaml"]):
        p["remove_files"] = bad
        (cs / "proposal.yaml").write_text(dump_yaml(p))
        with pytest.raises(ScaleError, match="not a removable file of the base schema"):
            build(cs, repo)


def test_moved_concepts_keep_their_definition_and_are_not_new(tmp_path):
    """An add with moved_from takes the value verbatim from the base file and stamps nothing on it."""
    repo, cs = _mini_repo(tmp_path, extra=True)
    p = load_yaml(cs / "proposal.yaml")
    src = f"{G}/extra.yaml"
    p["operations"] = [{"op": "add", "file": f"{G}/catalysis.yaml", "path": "nodes", "key": "Kiln", "moved_from": src},
                       {"op": "remove", "file": src, "path": "nodes.Kiln", "reason": "moved"}]
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    build(cs, repo)
    moved = load_yaml(cs / "candidate" / G / "catalysis.yaml")["nodes"]["Kiln"]
    assert moved == load_yaml(repo / src)["nodes"]["Kiln"] and "added_in" not in moved and "proposal" not in moved
    res = check(cs, repo, now=NOW)
    assert not any("Kiln" in m for m in res["problems"])
    assert not any("Kiln is close" in o["message"] for o in load_doc(cs / "critic_report.json")["objections"])
    p["operations"][0]["value"] = {"is_a": "Instrument"}
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    with pytest.raises(ScaleError, match="moved_from goes with op add and no value"):
        build(cs, repo)
    del p["operations"][0]["value"]
    p["operations"][0]["key"] = "Oven"
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    with pytest.raises(ScaleError, match="has no nodes.Oven"):
        build(cs, repo)


def test_rename_renames_a_key_in_place(tmp_path):
    """`rename` renames a key where it stands and keeps its value: here a domain file becomes a vocabulary-only
    module (``domain:`` -> ``module:``, moved from the manifest's domains to its modules)."""
    from scale.pgraph_proposal import apply_op
    repo, cs = _mini_repo(tmp_path, extra=True)
    man_rel, ex = (Path(G) / "scale-graph.yaml").as_posix(), f"{G}/extra.yaml"
    p = load_yaml(cs / "proposal.yaml")
    p["operations"] = [{"op": "rename", "file": ex, "path": "domain", "to": "module", "reason": "vocabulary only"},
                       {"op": "set", "file": man_rel, "path": "domains", "value": ["catalysis.yaml"], "reason": "a module"},
                       {"op": "add", "file": man_rel, "path": "", "key": "modules", "value": ["extra.yaml"]}]
    (cs / "proposal.yaml").write_text(dump_yaml(p))
    man = load_yaml(build(cs, repo))
    assert man["domains"] == ["catalysis.yaml"] and man["modules"] == ["extra.yaml"]
    before, after = load_yaml(repo / ex), load_yaml(cs / "candidate" / ex)
    assert list(after)[0] == "module" and after["module"] == before["domain"] == "extra" and "domain" not in after
    assert list(after)[1:] == list(before)[1:]                                     # every other key stays where it was
    spec = pgraph.load_spec(cs / "candidate" / G / "scale-graph.yaml")
    assert spec["modules"]["extra"]["kind"] == "module" and "extra" not in spec["profiles"] and "Kiln" in spec["nodes"]
    doc = {"a": {"x": 1, "y": 2, "z": 3}}
    assert list(apply_op(doc, {"op": "rename", "path": "a.y", "to": "w"}, "000001", "0.2.0")["a"].items()) == \
        [("x", 1), ("w", 2), ("z", 3)]
    for op, msg in (({"path": "a.q", "to": "r"}, "does not exist"), ({"path": "a.x", "to": "z"}, "already exists"),
                    ({"path": "a.x", "to": "b.c"}, "one name, no dots"), ({"path": "a.x"}, "one name, no dots")):
        with pytest.raises(ScaleError, match=msg):
            apply_op(doc, {"op": "rename", **op}, "000001", "0.2.0")


def test_check_chains_the_steps_up_to_its_own(tmp_path, monkeypatch):
    """A document pinned before the base is moved along every registered step, the proposal's own rule included;
    when the steps do not end in this proposal's own, a document pinned before the base still moves along the
    applied steps up to the base (their rules included) and then only has its version raised."""
    from scale import pgraph_migrate
    repo, cs = _mini_repo(tmp_path)
    man = load_yaml(repo / G / "scale-graph.yaml")      # the head records the proposal of the 0.0.9 -> 0.1.0 step
    man["proposals"] = ["000000"]                       # (a step leads only to a schema built from its proposal)
    (repo / G / "scale-graph.yaml").write_text(dump_yaml(man))
    old = load_doc(repo / "domain/examples/scale-graph/example.json")
    old["graph"]["schema_version"] = "0.0.9"
    write_canonical(repo / "domain/examples/scale-graph/old.json", old)
    p = load_yaml(cs / "proposal.yaml")
    p["assess_documents"].append({"path": "domain/examples/scale-graph/old.json"})
    (cs / "proposal.yaml").write_text(dump_yaml(p))

    def mark(doc, spec):
        doc["graph"]["title"] += " (marked)"
        return [{"record": "<graph>", "change": "title marked"}]
    monkeypatch.setattr(pgraph_migrate, "STEPS", {"0.0.9": ("0.1.0", "000000"), "0.1.0": ("0.2.0", "009001")})
    monkeypatch.setattr(pgraph_migrate, "STEP_RULES", {"0.1.0": ("titles marked", mark)})
    assert check(cs, repo, now=NOW)["ok"]
    docs = {d["document"].rsplit("/", 1)[-1]: d for d in load_doc(cs / "migration_assessment.json")["documents"]}
    assert docs["example.json"]["rule"] == "titles marked" and docs["example.json"]["changes"] == [{"record": "<graph>", "change": "title marked"}]
    assert docs["old.json"]["rule"].startswith("0.0.9 → 0.1.0 (000000)") and docs["old.json"]["changes"][0]["change"] == "title marked"
    for d in docs.values():                             # "before" is the document at the base, comparable with "after"
        assert d["errors_before"] == d["errors_after"] == 0, d
        assert d["conformance_before"] and set(d["conformance_before"]) == set(d["conformance_after"]), d
    monkeypatch.setattr(pgraph_migrate, "STEPS", {"0.0.9": ("0.1.0", "000000"), "0.1.0": ("0.2.0", "000042")})
    assert check(cs, repo, now=NOW)["ok"]
    docs = {d["document"].rsplit("/", 1)[-1]: d for d in load_doc(cs / "migration_assessment.json")["documents"]}
    assert docs["example.json"]["rule"] == "schema_version raised; no record changes" and "changes" not in docs["example.json"]
    assert docs["old.json"]["rule"] == ("0.0.9 → 0.1.0 (000000): schema_version raised; meaning_preserving; "
                                        "0.1.0 → 0.2.0 (009001): schema_version raised; no record changes")
    assert docs["old.json"]["changes"] == [] and docs["old.json"]["meaning"] == "meaning_preserving"
    assert docs["old.json"]["errors_before"] == docs["old.json"]["errors_after"] == 0
    assert docs["old.json"]["conformance_before"] == docs["old.json"]["conformance_after"] != {}

    def stop(doc, spec):
        raise ScaleError("cannot map this")
    monkeypatch.setattr(pgraph_migrate, "STEPS", {"0.1.0": ("0.2.0", "009001")})
    monkeypatch.setattr(pgraph_migrate, "STEP_RULES", {"0.1.0": ("stops", stop)})
    res = check(cs, repo, now=NOW)
    assert not res["ok"] and any("the migration rule stops: cannot map this" in m for m in res["problems"])


def test_the_steps_refuse_another_proposals_candidate(tmp_path, monkeypatch, capsys):
    """A step leads only to a schema built from its own proposal: a target of the same number built from another
    proposal (another pull request's candidate) is refused, by raise_version and by `scale graph migrate --spec`,
    and nothing is written; the step's own target is reached. Synthetic steps and ids (009xxx)."""
    from scale import pgraph_migrate
    from scale.cli import main
    from scale.pgraph_migrate import raise_version
    to = load_yaml(GRAPH_MANIFEST)["version"]
    monkeypatch.setattr(pgraph_migrate, "STEPS", {"0.0.9": (to, "009001")})
    monkeypatch.setattr(pgraph_migrate, "STEP_RULES", {})
    doc = load_doc(EXAMPLES / "scale-graph/example.json")
    doc["graph"]["schema_version"] = "0.0.9"
    for other in ({"version": to, "proposals": ["009002"]}, {"version": to, "proposals": [], "proposal": "009003"}):
        with pytest.raises(ScaleError, match=rf"the step scale-graph 0\.0\.9 -> {re.escape(to)} belongs to 009001; the "
                                             rf"target {re.escape(to)} was built from 00900[23]"):
            raise_version(doc, to, other)
    for own in ({"version": to, "proposals": ["009001"]}, {"version": to, "proposal": "009001"}):
        new, rep = raise_version(doc, to, own)
        assert new["graph"]["schema_version"] == to and [s["proposal"] for s in rep["steps"]] == ["009001"]
    # the CLI, with a copy of the head schema that names another proposal as the one it was built from
    tree = tmp_path / "tree"
    shutil.copytree(REPO / "core/graph", tree / "core/graph", ignore=shutil.ignore_patterns("frozen"))
    shutil.copytree(REPO / G, tree / G, ignore=shutil.ignore_patterns("frozen"))
    shutil.copytree(REPO / "governance/registry", tree / "governance/registry")
    man = load_yaml(tree / G / "scale-graph.yaml")
    man["proposals"] = ["009002"]
    (tree / G / "scale-graph.yaml").write_text(dump_yaml(man))
    src, out = tmp_path / "old.json", tmp_path / "out.json"
    write_canonical(src, doc)
    assert main(["--repo", str(REPO), "graph", "migrate", str(src), str(out), "--spec", str(tree / G / "scale-graph.yaml"),
                 "--format", "json"]) != 0
    assert "belongs to 009001" in capsys.readouterr().err and not out.exists()


def test_the_cli_takes_a_proposal_by_id_or_directory(tmp_path, capsys):
    """`scale proposal …` and `--proposal` take the six-digit id or the directory; any other name is refused."""
    from scale.cli import main
    repo, cs = _mini_repo(tmp_path)
    assert main(["--repo", str(repo), "proposal", "check", "009001", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert main(["--repo", str(repo), "proposal", "new", "catalysis", "--title", "Flow gauges", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["proposal"].endswith("domain/proposals/009002")
    for name in ("009001", str(cs)):
        main(["--repo", str(repo), "review", "status", "--proposal", name, "--format", "json"])
        assert json.loads(capsys.readouterr().out)["tier"] == 2
    assert main(["--repo", str(repo), "proposal", "build", "pressure-gauge"]) == 2
    assert "no proposal pressure-gauge" in capsys.readouterr().err


def test_proposal_pr_prints_the_body_the_check_wrote(tmp_path, capsys):
    """`scale proposal pr` prints the PR_BODY.md the proposal's check wrote (and asks for the check first); --branch
    is a dry run."""
    from scale.cli import main
    repo, cs = _mini_repo(tmp_path)
    (cs / "PR_BODY.md").unlink(missing_ok=True)
    assert main(["--repo", str(repo), "proposal", "pr", "009001"]) == 2
    assert "run `scale proposal check 009001` first" in capsys.readouterr().err
    assert check(cs, repo, now=NOW)["ok"]
    assert main(["--repo", str(repo), "proposal", "pr", str(cs)]) in (0, None)
    assert capsys.readouterr().out == (cs / "PR_BODY.md").read_text().rstrip("\n") + "\n"
    assert main(["--repo", str(repo), "proposal", "pr", "009001", "--branch", "b", "--format", "json"]) in (0, None)
    dry = json.loads(capsys.readouterr().out)
    assert dry["dry_run"] is True
    title = load_yaml(cs / "proposal.yaml")["title"]
    assert dry["command"] == ["gh", "pr", "create", "--base", "main", "--head", "b", "--title", title, "--body", "<PR_BODY.md>"]


def test_the_gap_register_keys_themes_by_the_proposal_id(tmp_path):
    """docs/gaps/register.json keys a theme by ``<proposal id>/<theme id>``; a later decide or refresh of the
    proposal updates that entry instead of adding a second one."""
    from scale.pgraph_proposal import register
    repo, _ = _mini_repo(tmp_path)
    write_canonical(repo / "docs/gaps/register.json", {"description": "d", "themes": [
        {"id": "009001/TH-01", "title": "gauges", "proposal": "009001", "resolution": "deferred", "status": "open"}]})
    p = {"id": "009001", "target_version": "0.2.0"}
    themes = [{"id": "TH-01", "title": "gauges", "resolution": "deferred", "reason": "later", "instances": []},
              {"id": "TH-02", "title": "flows", "resolution": "rejected", "reason": "no", "instances": []}]
    register(repo, p, themes, "decided", NOW)
    got = {t["id"]: t for t in load_doc(repo / "docs/gaps/register.json")["themes"]}
    assert set(got) == {"009001/TH-01", "009001/TH-02"}
    assert got["009001/TH-01"]["reason"] == "later" and got["009001/TH-02"]["proposal"] == "009001"
