"""`scale ci spec-changes --base <ref>`: releases and frozen versions are immutable, a specification change carries
what `scale schema check` asks (tested in test_schema_change; stubbed here), and the summary says whose review a pull
request needs. Each test commits a change to a small git repository and compares it with the tagged base."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scale.ci import spec_changes, spec_changes_text
from scale.cli import main

FIXTURE_CODEOWNERS = Path(__file__).parent / "fixtures/codeowners/CODEOWNERS"
CAT = "@example-org/catalysis-maintainers"           # a synthetic team named by a DOMAIN.yaml
REVIEWERS = "@hlxin"                                # the repository's CODEOWNERS: the owner
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.org", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

BASE = {
    "scale-release.yaml": "release: v0.1.0\n",
    "core/graph/kernel.yaml": "kernel: scale-kernel\n",
    "core/graph/frozen/kernel-0.1.0.yaml": "kernel: scale-kernel\n",
    "core/graph/frozen/SHA256SUMS": "kkk  kernel-0.1.0.yaml\n",
    "releases/README.md": "releases\n",
    "releases/v0.1.0/RELEASE.yaml": "release: v0.1.0\n",
    "releases/v0.1.0/domain/graph/catalysis.yaml": "domain: catalysis\n",
    "releases/v0.1.0/skills/x/SKILL.md": "x\n",
    "domain/DOMAIN.yaml": "domain: catalysis\nstatus: stable\nmaintainers:\n  team: '@example-org/catalysis-maintainers'\n",
    "domain/graph/scale-catal.yaml": "version: 0.2.0\n",
    "domain/graph/catalysis.yaml": "domain: catalysis\n",
    "domain/graph/frozen/scale-catal-0.1.0.yaml": "version: 0.1.0\n",
    "domain/graph/frozen/v0.1.0/catalysis.yaml": "domain: catalysis\n",
    "domain/graph/frozen/SHA256SUMS": "aaa  scale-catal-0.1.0.yaml\n",
    "domain/examples/x.json": "{}\n",
    "docs/decisions/log.json": "[]\n",
    "tools/cli.py": "# cli\n",
}


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, env=ENV, check=True, capture_output=True, text=True).stdout


def _init(r: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(text)
    (r / ".github").mkdir()
    shutil.copy2(FIXTURE_CODEOWNERS, r / ".github/CODEOWNERS")
    git(r, "init", "-q")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "base")
    git(r, "tag", "base")
    return r


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """The repository; the schema check is stubbed: it fails while the manifest is unchanged (version 0.2.0)."""
    def stub(r, base):
        v = (Path(r) / "domain/graph/scale-catal.yaml").read_text().strip().split()[-1]
        probs = [] if v != "0.2.0" else ["a change raises 0.2.0 to 0.2.1; the schema is at 0.2.0 (run `scale schema bump`)"]
        return {"kind": "additive", "base_version": "0.2.0", "head_version": v, "needs_version": "0.2.1",
                "problems": probs, "ok": not probs}
    monkeypatch.setattr("scale.ci.schema_check", stub)
    return _init(tmp_path / "repo", BASE)


def change(repo, write=None, delete=(), append=None):
    for rel, text in (write or {}).items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    for rel, text in (append or {}).items():
        with open(repo / rel, "a") as f:
            f.write(text)
    for rel in delete:
        (repo / rel).unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")
    return spec_changes(repo, "base")


def test_tooling_changes_pass(repo):
    res = change(repo, {"tools/cli.py": "# better cli\n", "releases/v0.2.0/RELEASE.yaml": "release: v0.2.0\n",
                        "releases/README.md": "more\n", "releases/CHANGELOG.md": "notes\n"})
    assert res["ok"], res["violations"]                       # a new release and the notes may change


@pytest.mark.parametrize("edit,expected", [
    ({"write": {"releases/v0.1.0/domain/graph/catalysis.yaml": "domain: other\n"}}, "modifies a file of the release releases/v0.1.0"),
    ({"delete": ["releases/v0.1.0/skills/x/SKILL.md"]}, "deletes a file of the release releases/v0.1.0"),
    ({"write": {"releases/v0.1.0/extra.txt": "x\n"}}, "adds a file to the release releases/v0.1.0"),
    ({"write": {"domain/graph/frozen/scale-catal-0.1.0.yaml": "version: 0.1.1\n"}}, "modifies a frozen schema file"),
    ({"delete": ["domain/graph/frozen/v0.1.0/catalysis.yaml"]}, "deletes a frozen schema file"),
    ({"write": {"domain/graph/frozen/SHA256SUMS": "bbb  scale-catal-0.1.0.yaml\n"}}, "SHA256SUMS may only gain lines"),
    ({"write": {"core/graph/frozen/kernel-0.1.0.yaml": "kernel: edited\n"}}, "modifies a frozen schema file"),
    ({"delete": ["core/graph/frozen/SHA256SUMS"]}, "deletes a frozen schema file"),
    ({"write": {"releases/notes.txt": "x\n"}, "then": {"releases/notes.txt": "y\n"}}, "modifies a file under releases/"),
])
def test_releases_and_frozen_versions_are_immutable(repo, edit, expected):
    if "then" in edit:                                         # an existing file directly under releases/
        change(repo, edit["write"])
        git(repo, "tag", "-f", "base")
        edit = {"write": edit["then"]}
    res = change(repo, **edit)
    assert not res["ok"] and any(expected in v for v in res["violations"]), res["violations"]


def test_frozen_versions_may_be_added_and_sums_appended(repo):
    res = change(repo, {"domain/graph/frozen/scale-catal-0.2.0.yaml": "version: 0.2.0\n",
                        "domain/graph/frozen/v0.2.0/catalysis.yaml": "domain: catalysis\n",
                        "core/graph/frozen/kernel-0.2.0.yaml": "kernel: scale-kernel\n",
                        "core/graph/kernel.yaml": "kernel: scale-kernel\nnodes: {}\n",
                        "domain/graph/scale-catal.yaml": "version: 0.3.0\n"},
                 append={"domain/graph/frozen/SHA256SUMS": "ccc  scale-catal-0.2.0.yaml\n",
                         "core/graph/frozen/SHA256SUMS": "ddd  kernel-0.2.0.yaml\n"})
    assert res["ok"], res["violations"]


@pytest.mark.parametrize("path", ["core/graph/kernel.yaml", "domain/graph/catalysis.yaml"])
def test_a_specification_change_needs_the_schema_check(repo, path):
    res = change(repo, {path: "changed: true\n"})
    assert not res["ok"] and "scale schema bump" in res["violations"][-1] and res["specification_files"] == [path]
    assert res["violations"][-1].startswith("schema change: ")
    git(repo, "reset", "-q", "--hard", "base")
    assert change(repo, {path: "changed: true\n", "domain/graph/scale-catal.yaml": "version: 0.2.1\n"})["ok"]


def test_path_rules_are_anchored(repo):
    res = change(repo, {"domain/examples/x.json": "{\"y\": 1}\n",
                        "tools/core/graph/notes.md": "not the core\n",
                        "tools/domain/graph/notes.md": "not the domain\n",
                        "docs/scale-catal.yaml.md": "not the manifest\n",
                        "scale-catal.yaml": "no repository-wide composition\n"})
    assert res["ok"] and not res["specification_files"], res


EXPERIMENTAL = "domain: catalysis\nstatus: experimental\nmaintainers:\n  team: '@example-org/catalysis-maintainers'\n"
STABLE = EXPERIMENTAL.replace("experimental", "stable")


def test_an_experimental_domain_is_free(repo):
    change(repo, {"domain/DOMAIN.yaml": EXPERIMENTAL})
    git(repo, "tag", "-f", "base")
    res = change(repo, {"domain/graph/catalysis.yaml": "domain: catalysis\nversion: 0.2.0\n"})
    assert res["ok"] and not res["specification_files"], res


def test_demoting_a_domain_does_not_exempt_its_graph_changes(repo):
    """CODE-5: a domain stable at the base and experimental at head counts as stable in that pull request."""
    res = change(repo, {"domain/DOMAIN.yaml": "domain: catalysis\nstatus: experimental\nmaintainers:\n"
                                                         "  team: '@example-org/catalysis-maintainers'\n",
                        "domain/graph/catalysis.yaml": "domain: catalysis\nversion: 0.1.1\n"})
    assert not res["ok"] and res["specification_files"] == ["domain/graph/catalysis.yaml"], res
    assert "scale schema bump" in res["violations"][-1]


def test_promoting_a_domain_counts_its_graph_changes(repo):
    change(repo, {"domain/DOMAIN.yaml": EXPERIMENTAL})
    git(repo, "tag", "-f", "base")
    res = change(repo, {"domain/DOMAIN.yaml": STABLE, "domain/graph/catalysis.yaml": "domain: catalysis\nversion: 0.2.0\n"})
    assert not res["ok"] and res["specification_files"] == ["domain/graph/catalysis.yaml"], res


def test_the_summary_names_the_reviewers(repo, capsys):
    res = change(repo, {"domain/graph/catalysis.yaml": "domain: catalysis\nversion: 0.1.1\n",
                        "domain/graph/scale-catal.yaml": "version: 0.3.0\n",
                        "domain/graph/frozen/scale-catal-0.2.0.yaml": "version: 0.2.0\n"},
                 append={"domain/graph/frozen/SHA256SUMS": "ccc  scale-catal-0.2.0.yaml\n"})
    assert res["ok"] and res["owners"]["minimal_reviewers"] == [REVIEWERS] and res["core_consultation"] is None
    assert f"fewest reviewers who own every changed path: {REVIEWERS}" in spec_changes_text(res)
    res = change(repo, {"core/graph/kernel.yaml": "kernel: scale-kernel\nnodes: {}\n"})
    assert res["core_consultation"]["domain_teams"] == [CAT]
    assert main(["--repo", str(repo), "ci", "spec-changes", "--base", "base"]) == 0
    out = capsys.readouterr().out
    assert "how the catalysis domain is affected" in out and "one approving review by a person" in out
    change(repo, {"releases/v0.1.0/RELEASE.yaml": "release: v0.1.1\n"})
    assert main(["--repo", str(repo), "ci", "spec-changes", "--base", "base", "--json"]) == 1
