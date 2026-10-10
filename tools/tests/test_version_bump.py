"""A schema change on a copy of the repository, end to end, the way an agent makes one: the next release built
first (v0.1.0 while none is), then a change to the kernel and the catalysis file on a branch, `scale schema check`
failing until `scale schema bump` raises the version, freezes the base and registers the migration step, a test and
a CHANGELOG line are added, and then the whole suite on the bumped copy. A change that breaks the tests on the
repository's migration steps, frozen versions or releases, or validates a document against the head instead of the
version it pins, fails here, in the pull request that introduces it, and not on main after the first real change."""

import os
import subprocess
import sys

import pytest

from conftest import HEAD_VERSION, REPO
from scale.releases import build_release, list_releases, verify_release
from scale.schema_change import bump, check, next_version
from scale.util import dump_yaml, load_doc, load_yaml, write_canonical
from scale.versions import normalize_release_id, parse_version, release_key
from test_domains import _copy_repository

GUARD = "SCALE_VERSION_BUMP_COPY"                  # set in the copy's test runs, so that this test does not recurse
FIXTURE = "tools/tests/fixtures/schema-bump/pass-probe.json"


def _git(repo, *args) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env).stdout


def _change(repo) -> None:
    """An additive change: a kernel property and a catalysis instrument, and a document that uses both."""
    kernel = repo / "core/graph/kernel.yaml"
    k = load_yaml(kernel)
    k["nodes"]["Source"]["properties"]["bump_note"] = {"type": "text", "description": "A synthetic note (test fixture)."}
    kernel.write_text(dump_yaml(k))
    cat = repo / "domain/graph/catalysis.yaml"
    c = load_yaml(cat)
    c["nodes"]["BumpProbe"] = {"is_a": "Instrument", "fixed": {"instrument_kind": "probe"}, "maturity": "provisional",
                               "description": "A synthetic instrument (test fixture).",
                               "properties": {"probe_kind": {"type": "enum", "values": ["dial", "digital", "not_reported"]}}}
    cat.write_text(dump_yaml(c))


def _fixture(repo, version: str) -> None:
    ex = load_doc(REPO / "domain/examples/scale-graph/example.json")
    src, test = "ex:exmpl/thermo/source/invented-paper", "ex:exmpl/thermo/test/zno-run-1"
    ev = [{"kind": "text", "locator": "Experimental section", "source": src}]
    ex["graph"]["schema_version"] = version
    del ex["graph"]["follows_domains"]             # no checklist: the fixture is about the vocabulary
    next(n for n in ex["nodes"] if n["id"] == src)["props"]["bump_note"] = "a synthetic note"
    ex["nodes"].append({"id": "ex:exmpl/thermo/instrument/probe", "label": "BumpProbe",
                        "props": {"name": "probe", "probe_kind": "dial", "origin": "synthetic", "evidence": ev}})
    ex["links"].append({"id": "ex:exmpl/thermo/link/probe", "type": "USES_INSTRUMENT", "source": test,
                        "target": "ex:exmpl/thermo/instrument/probe", "props": {"origin": "synthetic", "evidence": ev}})
    (repo / FIXTURE).parent.mkdir(parents=True, exist_ok=True)
    write_canonical(repo / FIXTURE, ex)


def _pytest(repo, *args) -> subprocess.CompletedProcess:
    env = {**os.environ, GUARD: "1"}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=repo,
                          capture_output=True, text=True, env=env)


def _build_next_release(repo) -> str:
    """Build the release that comes next: the one the head describes when it is not built yet (v0.1.0 before the
    first), else the next patch release."""
    built = list_releases(repo)
    manifest = repo / "scale-release.yaml"
    rid = normalize_release_id(load_yaml(manifest)["release"])
    if built and release_key(rid) <= release_key(built[-1]):
        major, minor, patch = parse_version(built[-1])
        rid = f"v{major}.{minor}.{patch + 1}"
        manifest.write_text(manifest.read_text().replace(f"release: {load_yaml(manifest)['release']}\n", f"release: {rid}\n", 1))
    dest = build_release(repo, rid, date="2026-10-08")
    assert verify_release(dest, rid)["ok"] and list_releases(repo) == built + [rid]
    return rid


def test_next_version_follows_the_rule():
    assert next_version("0.1.0", 3) == "0.2.0"          # breaking: the second number
    assert next_version("0.1.4", 2) == "0.1.5"          # additive: the third
    assert next_version("0.1.0", 0) == "0.1.1"


@pytest.mark.skipif(os.environ.get(GUARD) == "1", reason="inside the copy (this test does not run itself)")
def test_a_version_bump_keeps_the_tests_green(tmp_path):
    repo = tmp_path / "copy"
    _copy_repository(repo)
    rid = _build_next_release(repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "change")
    _change(repo)
    to = next_version(HEAD_VERSION, 2)
    res = check(repo, "main")
    assert res["kind"] == "additive" and res["needs_version"] == to and not res["ok"]
    assert any("scale schema bump" in p for p in res["problems"])
    out = bump(repo, "main")
    assert out["version"] == to and out["step"] == f"{HEAD_VERSION} -> {to}"
    res = check(repo, "main")
    assert {p.split(" is added")[0] for p in res["problems"] if "is added" in p} == {"node BumpProbe"}
    assert any("CHANGELOG" in p for p in res["problems"])
    _fixture(repo, to)
    changelog = repo / "CHANGELOG.md"
    changelog.write_text(changelog.read_text().replace("## Unreleased\n", "## Unreleased\n\n- Synthetic probe (test).\n", 1))
    res = check(repo, "main")
    assert res["ok"], res["problems"]
    assert load_yaml(repo / "domain/graph/scale-graph.yaml")["version"] == to
    assert "version" not in load_yaml(repo / "core/graph/kernel.yaml")              # the kernel carries none
    assert load_yaml(repo / "core/CORE.yaml")["version"] == load_yaml(repo / "domain/DOMAIN.yaml")["version"] == to
    assert load_yaml(repo / "scale-release.yaml")["schema_version"] == to
    assert load_yaml(repo / "core/examples/science-kernel-only.yaml")["version"] == to
    assert (repo / f"domain/graph/frozen/scale-graph-{HEAD_VERSION}.yaml").is_file()
    assert (repo / f"core/graph/frozen/kernel-{HEAD_VERSION}.yaml").is_file()         # the kernel of the base version
    assert list_releases(repo)[-1] == rid                                             # released before the bump
    # the whole suite on the copy: a release built, the schema changed, the version raised
    proc = _pytest(repo)
    assert proc.returncode == 0, "after the bump:\n" + proc.stdout[-6000:] + proc.stderr[-2000:]
