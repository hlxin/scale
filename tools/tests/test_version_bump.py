"""The repository moves on and the tests stay green. On a copy of the repository: the next release is built (the
first, v0.1.0, while none is), then a synthetic proposal that changes the kernel and the catalysis file and raises the
schema's one version is prepared (the pull-request stage: checked, not applied) and applied the way the apply workflow
applies a merged proposal (`scale proposal apply-merged`). The tests that read the repository's proposals run on the
copy at the pull-request stage, and the whole suite after the apply. A test that spells the head version, counts the
repository's proposals or releases, or validates a document against the head instead of the version it pins, fails
here, in the pull request that introduces it, and not on main after the first real proposal or release."""

import os
import subprocess
import sys

import pytest

from conftest import HEAD_VERSION, REPO
from scale.apply_merged import apply_merged
from scale.pgraph_proposal import check
from scale.releases import applied_since, build_release, head_artifacts, list_releases, release_root, verify_release
from scale.util import dump_yaml, load_doc, load_yaml, write_canonical
from scale.versions import normalize_release_id, parse_version, release_key
from test_domains import _copy_repository
from test_proposal_graph import gh_review

PID = "009010"                                     # synthetic (009xxx: test fixtures); never a real proposal's id
CS_REL = f"core/proposals/{PID}"                   # the kernel and the catalysis domain: a core proposal
GUARD = "SCALE_VERSION_BUMP_COPY"                  # set in the copy's test runs, so that this test does not recurse

# the modules that read the repository's proposals, migration steps, frozen versions or releases: run on the copy at
# the pull-request stage, when a proposal (and its step) is committed but not applied
PR_STAGE = ("tools/tests/test_proposal_graph.py", "tools/tests/test_layout.py", "tools/tests/test_retired_terms.py",
            "tools/tests/test_cli_inventory.py", "tools/tests/test_ci_spec_changes.py", "tools/tests/test_api_mcp.py",
            "tools/tests/test_domains.py", "tools/tests/test_licences.py")


def _next_minor(version: str) -> str:
    major, minor, _ = (int(x) for x in version.split("."))
    return f"{major}.{minor + 1}.0"


def _proposal(repo, to: str) -> None:
    """A tier-2 proposal built on the head: a provisional kernel property and a provisional catalysis instrument
    (one proposal, one version raised for both), a fixture that passes and one that fails for its stated reason; its
    version step registered in pgraph_migrate, as a proposal author registers it."""
    cs = repo / CS_REL
    (cs / "fixtures").mkdir(parents=True)
    ex = load_doc(REPO / "domain/examples/scale-graph/example.json")
    src, test = "ex:exmpl/thermo/source/invented-paper", "ex:exmpl/thermo/test/zno-run-1"
    ev = [{"kind": "text", "locator": "Experimental section", "source": src}]
    ex["graph"]["schema_version"] = to
    del ex["graph"]["follows_domains"]             # no checklist: the fixtures are about the vocabulary
    next(n for n in ex["nodes"] if n["id"] == src)["props"]["bump_note"] = "a synthetic note"
    ex["nodes"].append({"id": "ex:exmpl/thermo/instrument/probe", "label": "BumpProbe",
                        "props": {"name": "probe", "probe_kind": "dial", "origin": "synthetic", "evidence": ev}})
    ex["links"] += [{"id": "ex:exmpl/thermo/link/probe", "type": "USES_INSTRUMENT", "source": test,
                     "target": "ex:exmpl/thermo/instrument/probe", "props": {"origin": "synthetic", "evidence": ev}},
                    {"id": "ex:exmpl/thermo/link/probe-reported", "type": "REPORTED_IN", "source": "ex:exmpl/thermo/instrument/probe",
                     "target": src, "props": {"origin": "synthetic"}}]
    write_canonical(cs / "fixtures/pass-probe.json", ex)
    next(n for n in ex["nodes"] if n["label"] == "BumpProbe")["props"]["probe_kind"] = "laser"
    write_canonical(cs / "fixtures/fail-probe-kind.json", ex)
    (cs / "proposal.yaml").write_text(dump_yaml({
        "id": PID, "title": "A synthetic version bump (test fixture)", "kind": "scale-graph", "status": "proposed",
        "opened_at": "2026-10-06T00:00:00+00:00", "proposer": {"name": "SCALE test suite", "agent": True},
        "areas": ["kernel", "catalysis"],
        "base": {"manifest": "domain/graph/scale-graph.yaml", "version": HEAD_VERSION}, "target_version": to,
        "motivation": "A synthetic proposal: it raises the kernel and the catalysis schema so that the tests run on a bumped copy.\n",
        "operations": [
            {"op": "add", "file": "core/graph/kernel.yaml", "path": "nodes.Source.properties", "key": "bump_note",
             "value": {"type": "text", "description": "A synthetic note (test fixture)."}},
            {"op": "add", "file": "domain/graph/catalysis.yaml", "path": "nodes", "key": "BumpProbe",
             "value": {"is_a": "Instrument", "fixed": {"instrument_kind": "probe"},
                       "description": "A synthetic instrument (test fixture).",
                       "properties": {"probe_kind": {"type": "enum", "values": ["dial", "digital", "not_reported"]}}}}],
        "fixtures": {"pass": [f"{CS_REL}/fixtures/pass-probe.json"],
                     "fail": [{"path": f"{CS_REL}/fixtures/fail-probe-kind.json", "expect": "probe_kind",
                               "reason": "A probe's kind comes from the declared list."}]},
        "assess_documents": [{"path": "domain/examples/scale-graph/example.json"}],
        "expected_query_changes": [],
        "mappings_considered": ["Instruments: a probe is an Instrument with its own kind (synthetic)."]}))
    # the step goes last in the STEPS literal, so it replaces the step of any pending proposal built on the same
    # head (that one would need rebasing, as a real pending proposal does after another is applied)
    steps = repo / "tools/scale/pgraph_migrate.py"
    text = steps.read_text()
    start = text.index("STEPS: dict[str, tuple[str, str]] = {\n")
    end = text.index("\n}\n", start)
    steps.write_text(f"{text[:end]}\n    {HEAD_VERSION!r}: ({to!r}, {PID!r}),   # synthetic (test){text[end:]}")


def _pytest(repo, *args) -> subprocess.CompletedProcess:
    env = {**os.environ, GUARD: "1"}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=repo,
                          capture_output=True, text=True, env=env)


def _build_next_release(repo) -> str:
    """Build the release that comes next, as a person does at release time: the release the head describes when it
    is not built yet (v0.1.0 before the first), else the next patch release; naming every proposal applied since the
    previous release."""
    built = list_releases(repo)
    manifest = repo / "scale-release.yaml"
    rid = normalize_release_id(load_yaml(manifest)["release"])
    if built and release_key(rid) <= release_key(built[-1]):
        major, minor, patch = parse_version(built[-1])
        rid = f"v{major}.{minor}.{patch + 1}"
        manifest.write_text(manifest.read_text().replace(f"release: {load_yaml(manifest)['release']}\n", f"release: {rid}\n", 1))
    named = []
    if built:
        prev = release_root(repo, built[-1])
        named = applied_since(prev, load_yaml(prev / "RELEASE.yaml"), head_artifacts(repo))
    dest = build_release(repo, rid, proposals=named, date="2026-10-08")
    assert verify_release(dest, rid)["ok"] and list_releases(repo) == built + [rid]
    return rid


@pytest.mark.skipif(os.environ.get(GUARD) == "1", reason="inside the copy (this test does not run itself)")
def test_a_version_bump_keeps_the_tests_green(tmp_path):
    repo = tmp_path / "copy"
    _copy_repository(repo)
    rid = _build_next_release(repo)
    to = _next_minor(HEAD_VERSION)
    _proposal(repo, to)
    cs = repo / CS_REL
    res = check(cs, repo)
    assert res["ok"], load_doc(cs / "validation_report.json")
    assert load_doc(cs / "validation_report.json")["tier"] == 2
    # the pull-request stage: the proposal and its step are committed, the head is unchanged
    proc = _pytest(repo, *PR_STAGE)
    assert proc.returncode == 0, "at the pull-request stage:\n" + proc.stdout[-6000:] + proc.stderr[-2000:]
    # applied the way the apply-proposals workflow applies a merged proposal, from two recorded GitHub reviews; the
    # review policy's seats are filled for the apply only (the tests read the committed policy, placeholders and all)
    policy = repo / "governance/review-policy.yaml"
    committed = policy.read_bytes()
    pol = load_yaml(policy)
    pol["reviewers"]["members"] = [pol["reviewers"]["members"][0], {"name": "Ada", "github": "ada", "since": "2026-10-05"},
                                   {"name": "Ben", "github": "ben", "since": "2026-10-05"}]
    policy.write_text(dump_yaml(pol))
    out = apply_merged(repo, cs, 42, [gh_review("ada", rid=1, commit="feed"), gh_review("ben", rid=2, commit="feed")],
                       author="hlxin", head_sha="feed", check=None)
    policy.write_bytes(committed)
    assert out["status"] == "applied" and out["commit_message"].endswith(f"{HEAD_VERSION} → {to} (PR #42)")
    assert load_yaml(repo / "domain/graph/scale-graph.yaml")["version"] == to
    assert "version" not in load_yaml(repo / "core/graph/kernel.yaml")              # the kernel carries none
    assert load_yaml(repo / "core/CORE.yaml")["version"] == load_yaml(repo / "domain/DOMAIN.yaml")["version"] == to
    assert load_yaml(repo / "scale-release.yaml")["schema_version"] == to
    assert load_yaml(repo / "core/examples/science-kernel-only.yaml")["version"] == to
    assert (repo / f"domain/graph/frozen/scale-graph-{HEAD_VERSION}.yaml").is_file()
    assert (repo / f"core/graph/frozen/kernel-{HEAD_VERSION}.yaml").is_file()         # the kernel of the base version
    assert list_releases(repo)[-1] == rid                                             # released before the bump
    # the whole suite on the copy: a release built, a proposal applied, the version raised
    proc = _pytest(repo)
    assert proc.returncode == 0, "after the apply:\n" + proc.stdout[-6000:] + proc.stderr[-2000:]
