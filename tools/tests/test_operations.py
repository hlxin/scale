"""The operating model's automation, offline: the placeholder warning of `scale check`, the review policy, who may
start the agent and what the workflows may write, and the update of a data repository's documents to a schema
version a change raised (`scale kg update`)."""

import hashlib
import shutil

import pytest

from conftest import HEAD_VERSION, REPO
from scale.util import ScaleError, load_doc, load_yaml, write_canonical
from test_schema_change import git

TO = f"{HEAD_VERSION.rsplit('.', 1)[0]}.{int(HEAD_VERSION.rsplit('.', 1)[1]) + 1}"     # an additive change's version


def tree(repo):
    """Every file's digest: what 'nothing written' means."""
    return {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(repo.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def test_check_warns_about_placeholder_reviewers(tmp_path):
    import io
    import unittest.mock as mock
    from scale import devcheck
    assert devcheck.reviewer_warnings(REPO) == []                    # no placeholder listed
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance/review-policy.yaml").write_text(
        "reviewers:\n  members:\n    - name: Ada\n      github: ada\n")
    assert devcheck.reviewer_warnings(tmp_path) == []
    (tmp_path / "governance/review-policy.yaml").write_text(
        "reviewers:\n  members:\n    - name: Ada\n      github: ada\n    - name: TODO-reviewer-2\n"
        "      github: TODO-reviewer-2\n      placeholder: true\n")
    assert devcheck.reviewer_warnings(tmp_path) == ["reviewers: 1 placeholder to fill (governance/review-policy.yaml)"]
    step = devcheck.check_steps(REPO, fast=True)[0]
    assert step["cmds"] == [] and step["warning"] is devcheck.reviewer_warnings
    out = io.StringIO()
    step = {**step, "warning": lambda repo: devcheck.reviewer_warnings(tmp_path)}
    with mock.patch.object(devcheck, "check_steps", lambda *a, **k: [step]):
        assert devcheck.run_checks(REPO, fast=True, out=out)          # a warning never fails the check
    assert out.getvalue().splitlines()[0] == "warn reviewers: 1 placeholder to fill (governance/review-policy.yaml)"


def test_the_repository_policy_has_three_reviewers_and_no_placeholder():
    from scale.policy import load_policy, placeholders, reviewers
    pol = load_policy(REPO)
    assert pol["approvals"]["required"] == 1 and pol["reviewers"]["team"] == "@hlxin"
    assert [m["github"] for m in reviewers(pol)] == ["hlxin", "mutianyou2013", "diazr04"]
    assert placeholders(pol) == []


def test_every_reviewer_is_asked_and_one_approval_withdraws_the_other_requests(tmp_path):
    """CODEOWNERS names every reviewer on every line (scale domains check fails otherwise), so GitHub asks all of
    them; the reviewers workflow withdraws the open requests when one approves and asks again, after a push, those
    whose approval it dismissed or who asked for changes. It reads no text a person wrote into a shell command."""
    from scale import codeowners
    from scale.domains import Problems, _reviewers_routed
    rules = codeowners.load(REPO)
    assert all({"@hlxin", "@mutianyou2013", "@diazr04"} <= set(r.owners) for r in rules)
    pb = Problems()
    _reviewers_routed(REPO, codeowners.parse("*  @hlxin @diazr04\n/domain/  @hlxin @mutianyou2013 @diazr04\n"), pb)
    assert [e["message"] for e in pb.errors] == ["line 1 (*) does not name the reviewer @mutianyou2013 of "
                                         "governance/review-policy.yaml: GitHub would not ask them to review"]
    wf = REPO / ".github/workflows/reviewers.yml"
    doc = load_yaml(wf)
    assert doc["on"] == {"pull_request_review": {"types": ["submitted"]}, "pull_request": {"types": ["synchronize"]}}
    job = doc["jobs"]["reviewers"]
    assert job["permissions"] == {"pull-requests": "write"} and doc["permissions"] == {"contents": "read"}
    assert "github.event.pull_request.head.repo.full_name == github.repository" in job["if"]
    approve, again = job["steps"]
    assert "approved" in approve["if"] and "DELETE" in approve["run"] and "requested_reviewers" in approve["run"]
    assert "CHANGES_REQUESTED" in again["run"] and "DISMISSED" in again["run"] and "POST" in again["run"]
    assert all("${{" not in s["run"] for s in job["steps"])           # event text reaches the shell only via env
    assert "pull_request_target" not in wf.read_text() and "review.body" not in wf.read_text()


def test_who_may_start_the_agents_and_what_workflows_may_write():
    """@scale-agents start on their own on every new issue, comment and review (no label or tag), never on a bot's
    event, and by hand only from main; the job token only reads the contents (the team pushes with the Claude GitHub
    App's token); the discovery strategist's instructions and every other role are installed for the run, the evidence
    verifier unable to edit. No workflow asks for contents: write. The main ruleset needs one approval, no code
    owner, and lets nobody bypass it, the owner included."""
    import json
    rules = json.loads((REPO / "governance/github/ruleset-main.json").read_text())
    assert rules["bypass_actors"] == []
    pr = next(r for r in rules["rules"] if r["type"] == "pull_request")["parameters"]
    assert pr["required_approving_review_count"] == 1 and not pr["require_code_owner_review"]
    checks = next(r for r in rules["rules"] if r["type"] == "required_status_checks")["parameters"]
    assert [c["context"] for c in checks["required_status_checks"]] == [
        "test (3.10)", "test (3.11)", "test (3.12)", "test (3.13)", "package", "specification-changes"]
    wf = REPO / ".github/workflows/scale-agents.yml"
    agents = load_yaml(wf)
    assert agents["on"] == {"issues": {"types": ["opened", "reopened"]}, "issue_comment": {"types": ["created"]},
                            "pull_request_review": {"types": ["submitted"]},
                            "workflow_dispatch": agents["on"]["workflow_dispatch"]}
    job = agents["jobs"]["agents"]
    cond = " ".join(job["if"].split())
    assert cond == ("github.event.sender.type != 'Bot' && (github.event_name != 'workflow_dispatch' || github.ref == 'refs/heads/main') "
                    "&& !(github.event_name == 'pull_request_review' && github.event.review.state == 'approved' "
                    "&& !github.event.review.body) "            # an approval with no text starts no run
                    "&& (github.event_name == 'workflow_dispatch' || contains(fromJSON('[\"OWNER\", \"MEMBER\", \"COLLABORATOR\"]'), "
                    "github.event.comment.author_association || github.event.review.author_association "
                    "|| github.event.issue.author_association))")   # only a collaborator's event: the repository is public
    assert job["permissions"]["contents"] == "read"
    action = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("anthropics/claude-code-action"))
    assert "trigger_phrase" not in action["with"] and "label_trigger" not in action["with"]
    # the agents' commits are credited to claude[bot]; the action's default id (41898282) is github-actions[bot]'s
    assert action["with"]["bot_id"] == "209825114"
    args = action["with"]["claude_args"]
    assert "Agent," in args and ",Bash\"" in args
    for denied in ("git push origin main", "gh pr merge", "gh pr review", "gh api", "gh secret", "gh workflow", "git tag"):
        assert f"Bash({denied}:*)" in args, denied
    assert "github.event.issue.body" not in wf.read_text() and "github.event.comment.body" not in wf.read_text()
    roles = {p.stem: load_yaml_front(p) for p in sorted((REPO / ".github/scale-agents/roles").glob("*.md"))}
    assert set(roles) == {"data-scientist", "protocol-compiler", "evidence-verifier", "systems-engineer"}
    assert all(r["name"] == n for n, r in roles.items())
    assert not {"Edit", "Write"} & {t.strip() for t in roles["evidence-verifier"]["tools"].split(",")}
    text = (REPO / ".github/scale-agents/instructions.md").read_text()
    assert "discovery strategist" in text and all(part in text for part in (
        "the proposed patch", "the evidence record", "test cases with explicit expected outcomes", "the migration assessment"))
    for name in roles:
        assert f"`{name}`" in (REPO / ".github/scale-agents/instructions.md").read_text(), name
    # a manual run names its issue and waits its turn with the runs on that issue; a run that ends blocked, or without
    # saying how it ended, fails
    assert "inputs.issue" in agents["concurrency"]["group"] and "issue" in agents["on"]["workflow_dispatch"]["inputs"]
    last = job["steps"][-1]["run"]
    assert "OUTCOME: [a-z]*" in last and "exit 1" in last
    # the instructions and roles go outside the checkout, from main: on an event about a pull request the action resets
    # the checkout's .claude/ to main's, which has none; the prompt itself says how to read the event and how to end
    names = [s.get("name", s.get("uses", "")) for s in job["steps"]]
    install = next(s for s in job["steps"] if "~/.claude/CLAUDE.md" in s.get("run", ""))
    assert names.index(install["name"]) < job["steps"].index(action)
    assert "git show origin/main:.github/scale-agents/instructions.md > ~/.claude/CLAUDE.md" in install["run"]
    assert "~/.claude/agents/" in install["run"] and " .claude/" not in install["run"]
    assert "uv run scale thread" in action["with"]["prompt"] and "OUTCOME: blocked" in action["with"]["prompt"]
    assert "Follow .claude/CLAUDE.md" not in wf.read_text()
    assert "OUTCOME: blocked" in (REPO / ".github/scale-agents/instructions.md").read_text()
    assert not (REPO / ".github/workflows/scale-agent.yml").exists()
    assert not (REPO / ".github/workflows/apply-proposals.yml").exists()
    for f in sorted((REPO / ".github/workflows").glob("*.yml")):
        perms = [load_yaml(f).get("permissions") or {}] + [j.get("permissions") or {} for j in load_yaml(f)["jobs"].values()]
        assert all(p.get("contents") != "write" for p in perms), f.name


def load_yaml_front(path):
    """The YAML front matter of a role file."""
    import yaml
    return yaml.safe_load(path.read_text().split("---\n")[1])


def _two_versions(tmp_path):
    """A schema repository after an additive change (HEAD_VERSION frozen, the head at TO, the step registered), and a
    data repository with documents at HEAD_VERSION."""
    from scale.schema_change import bump
    from scale.util import dump_yaml
    repo = tmp_path / "repo"
    shutil.copytree(REPO / "core", repo / "core", ignore=shutil.ignore_patterns("__pycache__", "frozen", "tests"))
    shutil.copytree(REPO / "domain/graph", repo / "domain/graph", ignore=shutil.ignore_patterns("frozen"))
    for rel in ("domain/DOMAIN.yaml", "scale-release.yaml", "CHANGELOG.md",
                "governance/registry/extension-prefixes.yaml", "tools/pgraph_migrate.py"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, repo / rel)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    cat = load_yaml(repo / "domain/graph/catalysis.yaml")
    cat["nodes"]["CatalyticTest"]["properties"]["test_only_note"] = {"type": "text", "maturity": "provisional"}
    (repo / "domain/graph/catalysis.yaml").write_text(dump_yaml(cat))
    assert bump(repo, "main")["version"] == TO
    data = tmp_path / "kg"
    ex = data / "examples/demo"
    ex.mkdir(parents=True)
    src = REPO / "domain/examples/scale-catal/driving-force-examples"
    def at_head(name):                         # an example stays at the version it pins until migrated
        doc = load_doc(src / f"{name}.json")
        doc["graph"]["schema_version"] = HEAD_VERSION    # the examples are valid at the head (test_examples)
        return doc
    write_canonical(ex / "electro.graph.json", at_head("electro"))
    write_canonical(ex / f"electro.scale-catal-{HEAD_VERSION}.graph.json", at_head("electro"))   # a copy kept at its version
    bad = at_head("photo")
    bad["graph"]["follows_domains"] = ["no-such-checklist"]
    write_canonical(ex / "odd.graph.json", bad)
    shutil.copytree(src, data / "sealed")                                   # a sealed package is not read
    (data / "sealed/.scale-verbatim").write_text("")
    from scale.passages import Index, evidence_items
    Index.build(evidence_items(load_doc(ex / "electro.graph.json"))).save(ex / "electro.evidence")
    return repo, data, ex


@pytest.fixture()
def step(monkeypatch):
    """The step HEAD_VERSION -> TO as `scale schema bump` registers it, with a rule that stops on a document it cannot
    map (a checklist the schema does not have)."""
    from scale import pgraph_migrate

    def rule(doc, spec):
        if doc["graph"].get("follows_domains") != ["catalysis"]:
            raise ScaleError(f"follows_domains {doc['graph'].get('follows_domains')} cannot be mapped")
        return []
    monkeypatch.setitem(pgraph_migrate.STEPS, HEAD_VERSION, (TO, "additive change"))
    monkeypatch.setitem(pgraph_migrate.STEP_RULES, HEAD_VERSION, ("checklists checked", rule))


def test_kg_update_dry_run_writes_nothing(tmp_path, step):
    from scale.kg import update
    repo, data, _ = _two_versions(tmp_path)
    before = tree(data)
    res = update(repo, data, dry_run=True)
    assert tree(data) == before and not res["ok"]
    by = {r["document"].rsplit("/", 1)[-1]: r for r in res["documents"]}
    assert set(by) == {"electro.graph.json", f"electro.scale-catal-{HEAD_VERSION}.graph.json", "odd.graph.json"}
    assert by["electro.graph.json"]["status"] == "would update" and by["electro.graph.json"]["steps"] == [
        f"{HEAD_VERSION} → {TO} (additive change)"]
    assert by[f"electro.scale-catal-{HEAD_VERSION}.graph.json"]["status"] == "kept"
    assert by["odd.graph.json"]["status"] == "refused" and "a step rule cannot migrate it" in by["odd.graph.json"]["why"]


def test_kg_update_migrates_validates_and_reindexes(tmp_path, capsys, step):
    from scale.cli import main
    repo, data, ex = _two_versions(tmp_path)
    odd, kept = (ex / "odd.graph.json").read_bytes(), (ex / f"electro.scale-catal-{HEAD_VERSION}.graph.json").read_bytes()
    index = (ex / "electro.evidence.jsonl").stat().st_mtime_ns
    assert main(["--repo", str(repo), "kg", "update", "--data", str(data), "--out", str(tmp_path / "r.json")]) == 1   # one refused
    res = load_doc(tmp_path / "r.json")
    row = next(r for r in res["documents"] if r["document"].endswith("/electro.graph.json"))
    assert row["status"] == "updated" and row["after"]["errors"] == 0 and row["index"].endswith("electro.evidence.jsonl")
    doc = load_doc(ex / "electro.graph.json")
    assert doc["graph"]["schema_version"] == TO and doc["graph"]["follows_domains"] == ["catalysis"]
    assert (ex / "odd.graph.json").read_bytes() == odd and (ex / f"electro.scale-catal-{HEAD_VERSION}.graph.json").read_bytes() == kept
    assert (ex / "electro.evidence.jsonl").stat().st_mtime_ns != index
    assert "refused" in capsys.readouterr().out
    assert res["counts"] == {"kept": 1, "refused": 1, "updated": 1}
    from scale.kg import update
    again = update(repo, data)
    assert next(r for r in again["documents"] if r["document"].endswith("/electro.graph.json"))["status"] == "current"


def test_a_published_release_publishes_scale_catal_by_trusted_publishing():
    """A published GitHub release runs publish.yml in the pypi environment with an OIDC token (no stored secret); it
    checks that the tag is the package version and on main and that the release directory verifies, then uploads."""
    wf = REPO / ".github/workflows/publish.yml"
    doc, text = load_yaml(wf), wf.read_text()
    assert doc["on"] == {"release": {"types": ["published"]}}
    job = doc["jobs"]["publish"]
    assert job["environment"]["name"] == "pypi" and job["permissions"] == {"contents": "read", "id-token": "write"}
    assert "${{ secrets." not in text and 'test "${TAG}" = "v${version}"' in text and 'release verify "v${VERSION}"' in text
    assert job["steps"][-1]["uses"] == "pypa/gh-action-pypi-publish@release/v1"
    assert 'scale-catal = "scale.cli:main"' in (REPO / "pyproject.toml").read_text()
