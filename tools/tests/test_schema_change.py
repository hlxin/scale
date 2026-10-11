"""`scale schema diff | bump | check` on a small copy of the schema in a git repository: the version a change needs,
what `bump` writes, what `check` asks of a breaking change, and the reviewer's summary. The whole flow on a full copy,
with the test suite run after it, is test_version_bump."""

import os
import shutil
import subprocess

import pytest

from conftest import HEAD_VERSION, REPO
from scale import layout
from scale.cli import main
from scale.schema_change import bump, check, compare, next_version, repo_steps, summary
from scale.util import ScaleError, dump_yaml, load_yaml

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.org", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, env=ENV, check=True, capture_output=True, text=True).stdout


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    shutil.copytree(REPO / "core", r / "core", ignore=shutil.ignore_patterns("__pycache__", "frozen", "tests"))
    shutil.copytree(REPO / "domain/graph", r / "domain/graph", ignore=shutil.ignore_patterns("frozen"))
    for rel in ("domain/DOMAIN.yaml", "scale-release.yaml", "CHANGELOG.md", layout.PREFIX_REGISTRY,
                "tools/pgraph_migrate.py"):
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, r / rel)
    git(r, "init", "-q", "-b", "main")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "base")
    git(r, "checkout", "-q", "-b", "change")
    return r


def _edit(path, fn):
    doc = load_yaml(path)
    fn(doc)
    path.write_text(dump_yaml(doc))


def test_an_unchanged_schema_needs_nothing(repo):
    res = check(repo, "main")
    assert res["ok"] and not res["changed"] and summary(res) == "This pull request does not change the schema."
    with pytest.raises(ScaleError, match="nothing to bump"):
        bump(repo, "main")


def test_a_breaking_change_raises_the_second_number_and_needs_a_rule(repo):
    _edit(repo / "domain/graph/catalysis.yaml", lambda m: m["nodes"]["CatalyticTest"]["properties"].pop("feed_ratio"))
    c = compare(repo, "main")
    assert c["kind"] == "breaking" and c["needs_version"] == next_version(HEAD_VERSION, 3)
    assert "nodes.CatalyticTest.feed_ratio" in c["diff"]["removed"]
    to = c["needs_version"]
    out = bump(repo, "main", note="feed_ratio removed")
    assert out["version"] == to and "STEP_RULES" in out["next"]
    steps, rules = repo_steps(repo)
    assert steps[HEAD_VERSION] == (to, "feed_ratio removed") and HEAD_VERSION not in rules
    for rel, key in (("domain/graph/scale-graph.yaml", "version"), ("core/CORE.yaml", "version"),
                     ("domain/DOMAIN.yaml", "version"), ("scale-release.yaml", "schema_version"),
                     ("core/examples/science-kernel-only.yaml", "version")):
        assert str(load_yaml(repo / rel)[key]) == to, rel
    frozen = repo / f"domain/graph/frozen/scale-graph-{HEAD_VERSION}.yaml"
    assert load_yaml(frozen)["status"] == "frozen" and (repo / f"core/graph/frozen/kernel-{HEAD_VERSION}.yaml").is_file()
    with pytest.raises(ScaleError, match="bump once per change"):
        bump(repo, "main")
    res = check(repo, "main")
    assert not res["ok"] and any("STEP_RULES" in p for p in res["problems"]) and any("CHANGELOG" in p for p in res["problems"])
    assert "**Schema change: breaking**" in summary(res) and "- removed (" in summary(res)


def test_a_nested_change_that_can_invalidate_documents_is_breaking(repo):
    """A property's nested definition is compared too: identifiers' items made integer (strings fail it) is a breaking
    change; a description changed alone is no change."""
    _edit(repo / "core/graph/kernel.yaml",
          lambda k: k["common"]["node"]["properties"]["identifiers"].__setitem__("description", "Reworded only."))
    assert compare(repo, "main")["kind"] == "no change in meaning"
    _edit(repo / "core/graph/kernel.yaml",
          lambda k: k["common"]["node"]["properties"]["identifiers"]["items"].__setitem__("type", "integer"))
    c = compare(repo, "main")
    assert c["kind"] == "breaking" and c["needs_version"] == next_version(HEAD_VERSION, 3)
    assert "common.node.identifiers[items]: type string -> integer" in c["diff"]["changed"]


def test_check_finds_an_unraised_version_and_an_edited_frozen_copy(repo, capsys):
    _edit(repo / "domain/graph/catalysis.yaml",
          lambda m: m["nodes"]["CatalyticTest"]["properties"].update(test_only_note={"type": "text", "maturity": "provisional"}))
    res = check(repo, "main")
    assert res["kind"] == "additive" and res["needs_version"] == next_version(HEAD_VERSION, 2)
    assert any("run `scale schema bump`" in p for p in res["problems"])
    assert main(["--repo", str(repo), "schema", "check", "--base", "main"]) == 1
    capsys.readouterr()
    bump(repo, "main")
    changelog = repo / "CHANGELOG.md"
    changelog.write_text(changelog.read_text().replace("## Unreleased\n", "## Unreleased\n\n- A note (test).\n", 1))
    assert check(repo, "main")["ok"]
    assert main(["--repo", str(repo), "schema", "check", "--base", "main"]) == 0
    frozen = repo / f"domain/graph/frozen/v{HEAD_VERSION}/catalysis.yaml"
    _edit(frozen, lambda m: m["nodes"]["CatalyticTest"]["properties"].pop("feed_ratio"))
    assert any("frozen copy" in p for p in check(repo, "main")["problems"])


def test_new_concepts_enter_as_provisional(repo):
    """A label, edge type or property a change adds is provisional, on itself, on what it is added to or by its file."""
    _edit(repo / "domain/graph/catalysis.yaml", lambda m: m.update(maturity="stable"))
    git(repo, "commit", "-q", "-am", "the catalysis file stable (test)")
    git(repo, "branch", "-f", "main")
    _edit(repo / "domain/graph/catalysis.yaml", lambda m: m["nodes"]["CatalyticTest"]["properties"].update(
        stable_note={"type": "text"}, provisional_note={"type": "text", "maturity": "provisional"}))
    problems = check(repo, "main")["problems"]
    assert [p for p in problems if "provisional" in p] == [
        "nodes.CatalyticTest.stable_note is new but not `maturity: provisional` (new concepts enter as provisional)"]
