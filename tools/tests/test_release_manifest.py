"""Release builds: the core and the released domains, each with its scale-graph schema (its manifest, its
parts, the science kernel and any frozen versions), copied from the head and digested, with the schema's one
version, the people credited, the experimental domains left out, the source repository, the applied
proposals the release adds and a semantic comparison with the previous release."""

import json
import shutil

import pytest

from conftest import HEAD_VERSION, REPO
from scale import layout
from scale.releases import applied_since, build_release, release_root, schema_comparison, verify_release
from scale.util import ScaleError, dump_yaml, load_yaml, sha256_file, write_yaml

# the catalysis graph schema: its manifest and one catalysis file, with the kernel
GRAPH_FILES = ["core/graph/kernel.yaml", "domain/graph/scale-graph.yaml", "domain/graph/catalysis.yaml"]
STATING = [("core/CORE.yaml", "version"), ("domain/DOMAIN.yaml", "version"), ("domain/graph/scale-graph.yaml", "version"),
           ("scale-release.yaml", "schema_version"), ("core/examples/science-kernel-only.yaml", "version")]


FIRST = "v0.1.0"           # the first release of a scratch repository (whatever releases the repository has built)


def _mini(tmp_path):
    """The head in a scratch repository, without its proposals and without the releases built from it, describing
    the first release (FIRST): the tests build a first release and the ones after it, whatever the repository holds."""
    repo = tmp_path / "repo"
    for d in ("core", "governance", "tools/skills", "domain/graph"):
        shutil.copytree(REPO / d, repo / d, ignore=shutil.ignore_patterns("__pycache__", "proposals"))
    (repo / "releases").mkdir()
    shutil.copy2(REPO / "releases/README.md", repo / "releases/README.md")
    for f in ("scale-release.yaml", "domain/DOMAIN.yaml"):
        shutil.copy2(REPO / f, repo / f)
    _edit(repo / layout.RELEASE_MANIFEST, lambda m: m.update(release=FIRST))
    return repo


def _edit(path, fn):
    doc = load_yaml(path)
    fn(doc)
    path.write_text(dump_yaml(doc))


def _raise_version(repo, to):
    """What `scale proposal apply` does to the one version: every file that states it follows the manifest."""
    for rel, key in STATING:
        _edit(repo / rel, lambda m, key=key: m.update({key: to}))


PID = "009090"            # a synthetic proposal id (009xxx: test fixtures)
_MAJOR, _MINOR, _PATCH = (int(x) for x in HEAD_VERSION.split("."))
NEXT = f"{_MAJOR}.{_MINOR + 1}.0"              # what a proposal applied to the head raises the one version to
NEXT_PATCH = f"{_MAJOR}.{_MINOR}.{_PATCH + 1}"


def _apply_fake_proposal(repo, pid=PID, decided=True, to=NEXT):
    """What `scale proposal apply` leaves behind, in miniature: a new property in the catalysis file, the
    proposal's id in the manifest's proposals, the one version raised, the proposal record and (when decided)
    its decision."""
    _edit(repo / "domain/graph/catalysis.yaml",
          lambda m: m["nodes"]["CatalyticTest"]["properties"].update(test_only_note={"type": "text", "maturity": "provisional"}))
    _edit(repo / "domain/graph/scale-graph.yaml", lambda m: m.update(proposals=(m.get("proposals") or []) + [pid]))
    if to:
        _raise_version(repo, to)
    cs = repo / "domain/proposals" / pid
    write_yaml(cs / "proposal.yaml", {"id": pid, "title": "A test change", "kind": "scale-graph"})
    (cs / "validation_report.json").write_text(json.dumps({"tier": 2, "ok": True}))
    (cs / "approvals").mkdir()
    (cs / "approvals/domain-hlxin.json").write_text(json.dumps({"reviewer": "hlxin", "role": "domain", "decision": "approve"}))
    if decided:
        (repo / layout.DECISIONS).mkdir(parents=True, exist_ok=True)
        (repo / layout.DECISIONS / f"0099-{pid}.md").write_text(f"# Decision record 0099 — {pid}\n")
        (repo / layout.DECISION_LOG).write_text(json.dumps({"decisions": [
            {"record": f"0099-{pid}.md", "proposal": pid, "proposal_dir": cs.relative_to(repo).as_posix()}]}))
    _edit(repo / layout.RELEASE_MANIFEST, lambda m: m.update(release="v0.2.0"))


def test_the_build_carries_core_kernel_domain_and_skills_with_the_one_version(tmp_path):
    repo = _mini(tmp_path)
    dest = build_release(repo, "v0.1.0", date="2026-10-08")
    m = load_yaml(dest / "RELEASE.yaml")
    assert (m["distribution"], m["release"], m["status"]) == ("scale-schema", "v0.1.0", "released")
    assert m["schema_version"] == HEAD_VERSION
    assert (m["core"], m["domain_profiles"]) == ("core/CORE.yaml", ["domain/DOMAIN.yaml"]) and "graph" not in m
    for f in ["core/CORE.yaml", "domain/DOMAIN.yaml"] + GRAPH_FILES:
        assert m["digests"][f] == sha256_file(repo / f), f
    held = bool(list((REPO / "domain/graph/frozen").glob("scale-graph-*.yaml")))     # none at 0.1.0
    assert any("/frozen/" in k for k in m["digests"]) == held
    assert all(s.startswith("tools/skills/") for s in m["skills"]) and "tools/skills/query-graph/SKILL.md" in m["digests"]
    assert verify_release(dest, "v0.1.0")["ok"]
    cv = m["component_versions"]                       # one version for the kernel and the catalysis domain
    assert cv["schema"] == {"version": HEAD_VERSION}
    assert cv["core"] == {"name": "scale-core", "version": HEAD_VERSION}
    assert cv["kernel"] == {"file": layout.KERNEL, "version": HEAD_VERSION}
    assert cv["domains"] == [{"domain": "catalysis", "version": HEAD_VERSION, "status": "stable",
                              "scale_graph": {"manifest": "domain/graph/scale-graph.yaml", "version": HEAD_VERSION,
                                              "status": "candidate"}}]
    assert cv["tool"]["package"] == "scale-schema" and {s["name"] for s in cv["skills"]} == {
        "curate-source", "query-graph", "evolve-schema", "triage-feedback", "scan-conflicts", "map-coverage",
        "curate-dataset", "export-graph"}
    # a skill is its whole folder: the release carries curate-source's references with their digests
    assert m["digests"]["tools/skills/curate-source/references/recipes.md"] == sha256_file(
        repo / "tools/skills/curate-source/references/recipes.md")
    assert m["contributors"] == [{"name": "Hongliang Xin", "github": "hlxin", "roles": ["steward"], "scopes": ["core", "catalysis"]}]
    assert m["excluded_domains"] == []
    assert m["source"] == {"repository": "https://github.com/hlxin/scale", "tag": "v0.1.0"}
    # the first release: nothing to compare with
    assert m["previous"] is None and m["comparison_to_previous"] is None and "predecessor" not in m
    assert (m["proposals"], m["review"]) == ([], [])
    # the spec document of the one version, with its digest
    from scale import pgraph
    assert m["spec_documents"] == [{"domain": "catalysis", "version": v, "file": f"specs/catalysis/scale-graph-{v}.json",
                                    "sha256": pgraph.spec_sha256(pgraph.load_spec(path))}
                                   for v, path in pgraph.spec_versions(repo / "domain/graph/scale-graph.yaml")]
    assert m["spec_documents"][-1]["version"] == HEAD_VERSION
    assert list(m)[-1] == "digests"


def test_the_first_release_names_no_proposals(tmp_path):
    with pytest.raises(ScaleError, match="first release has no previous release"):
        build_release(_mini(tmp_path), "v0.1.0", proposals=["000001"])


def test_versions_typos_and_immutability(tmp_path):
    repo = _mini(tmp_path)
    with pytest.raises(ScaleError, match="the head describes release v0.1.0, not v0.2.0"):
        build_release(repo, "v0.2.0")                     # a typo must not publish the head under another number
    with pytest.raises(ScaleError, match="Not a release id"):
        build_release(repo, "legacy/v0.4.0")
    build_release(repo, "v0.1.0", date="2026-10-08")
    with pytest.raises(ScaleError, match="immutable"):
        build_release(repo, "v0.1.0")
    assert build_release(repo, "v0.1.1", override_version=True, date="2026-10-08").name == "v0.1.1"


def test_an_experimental_domain_is_never_released(tmp_path):
    repo = _mini(tmp_path)
    _edit(repo / "domain/DOMAIN.yaml", lambda m: m.update(status="experimental"))
    with pytest.raises(ScaleError, match="experimental domain catalysis is listed in domain_profiles"):
        build_release(repo, "v0.1.0", date="2026-10-08")
    assert not (repo / "releases/v0.1.0").exists()
    _edit(repo / layout.RELEASE_MANIFEST, lambda m: m.update(domain_profiles=[]))
    m = load_yaml(build_release(repo, "v0.1.0", date="2026-10-08") / "RELEASE.yaml")
    assert m["excluded_domains"] == [{"domain": "catalysis", "version": HEAD_VERSION, "status": "experimental"}]
    assert not any(k.startswith("domain/") for k in m["digests"]) and m["spec_documents"] == []


def test_a_schema_change_reaches_a_release_only_through_named_applied_proposals(tmp_path):
    repo = _mini(tmp_path)
    build_release(repo, "v0.1.0", date="2026-10-08")
    _apply_fake_proposal(repo)
    with pytest.raises(ScaleError, match=f"proposals applied since v0.1.0 are not named: {PID}"):
        build_release(repo, "v0.2.0", date="2026-10-09")
    with pytest.raises(ScaleError, match="000004 is not among the proposals applied since the previous release"):
        build_release(repo, "v0.2.0", proposals=[PID, "000004"], date="2026-10-09")
    assert not (repo / "releases/v0.2.0").exists()
    m = load_yaml(build_release(repo, "v0.2.0", proposals=[PID], date="2026-10-09") / "RELEASE.yaml")
    assert m["previous"] == "v0.1.0" and m["proposals"] == [PID] and m["schema_version"] == NEXT
    assert m["review"] == [{"id": PID, "decision_record": f"docs/decisions/0099-{PID}.md", "tier": 2,
                            "approved_by": ["hlxin"]}]
    cmp = m["comparison_to_previous"]
    assert cmp["classification"] == "additive" and cmp["kernel"]["classification"] == "identical"
    assert (cmp["kernel"]["from"], cmp["kernel"]["to"]) == (HEAD_VERSION, NEXT)        # one version: the kernel's too
    cat = cmp["domains"]["catalysis"]
    assert cat["classification"] == "additive" and cat["added"] == ["nodes.CatalyticTest.test_only_note"]
    assert (cat["from"], cat["to"]) == (HEAD_VERSION, NEXT)
    assert m["component_versions"]["schema"] == {"version": NEXT}


def test_an_applied_proposal_without_a_decision_record_is_refused(tmp_path):
    repo = _mini(tmp_path)
    build_release(repo, "v0.1.0", date="2026-10-08")
    _apply_fake_proposal(repo, decided=False)
    with pytest.raises(ScaleError, match=f"no decision record for {PID}"):
        build_release(repo, "v0.2.0", proposals=[PID], date="2026-10-09")


def test_a_schema_edit_without_a_proposal_is_refused(tmp_path):
    repo = _mini(tmp_path)
    build_release(repo, "v0.1.0", date="2026-10-08")
    _edit(repo / "domain/graph/catalysis.yaml", lambda m: m["nodes"]["CatalyticTest"]["properties"].pop("feed_ratio"))
    _raise_version(repo, "1.0.0")
    _edit(repo / layout.RELEASE_MANIFEST, lambda m: m.update(release="v0.2.0"))
    prev = release_root(repo, "v0.1.0")
    from scale.releases import head_artifacts
    art = head_artifacts(repo)
    cmp = schema_comparison(repo, prev, load_yaml(prev / "RELEASE.yaml"), art)
    assert cmp["classification"] == "breaking" and "nodes.CatalyticTest.feed_ratio" in cmp["domains"]["catalysis"]["removed"]
    assert applied_since(prev, load_yaml(prev / "RELEASE.yaml"), art) == []
    with pytest.raises(ScaleError, match=r"schemas changed since v0.1.0 \(breaking\) but no applied proposal accounts for it"):
        build_release(repo, "v0.2.0", date="2026-10-09")


@pytest.mark.parametrize("edit", ["kernel", "catalysis"])
def test_schema_content_changes_need_the_one_version_raised(tmp_path, edit):
    """The kernel and the catalysis file share one version: a release must not record one version for two contents,
    whichever of them changed."""
    repo = _mini(tmp_path)
    build_release(repo, "v0.1.0", date="2026-10-08")
    _edit(repo / layout.RELEASE_MANIFEST, lambda m: m.update(release="v0.2.0"))
    f = repo / (layout.KERNEL if edit == "kernel" else "domain/graph/catalysis.yaml")
    f.write_text(f.read_text() + "# an edited file\n")
    with pytest.raises(ScaleError, match=rf"schema content changed without a version bump: {f.relative_to(repo).as_posix()} "
                                         rf"changed since v0.1.0, but the schema is still at {HEAD_VERSION}"):
        build_release(repo, "v0.2.0", date="2026-10-09")
    assert not (repo / "releases/v0.2.0").exists()
    _raise_version(repo, NEXT_PATCH)
    m = load_yaml(build_release(repo, "v0.2.0", date="2026-10-09") / "RELEASE.yaml")
    assert m["comparison_to_previous"]["classification"] == "identical"          # a comment is not meaning
    assert f.relative_to(repo).as_posix() in m["comparison_to_previous"]["files"]["changed"]


def test_the_released_spec_digest_stays_put(tmp_path):
    """A release publishes each version's spec digest; `scale graph verify` fails when the repository's copy of that
    version drifts (the same number would then name two schemas)."""
    from scale import pgraph
    from scale.releases import spec_digest_stability
    repo = _mini(tmp_path)
    build_release(repo, "v0.1.0", date="2026-10-08")
    man = repo / "domain/graph/scale-graph.yaml"
    now = {("catalysis", v): pgraph.spec_sha256(pgraph.load_spec(path)) for v, path in pgraph.spec_versions(man)}
    assert spec_digest_stability(repo, now)["ok"]
    _edit(repo / "domain/graph/catalysis.yaml", lambda m: m["nodes"]["CatalyticTest"]["properties"].pop("feed_ratio"))
    drift = {**now, ("catalysis", HEAD_VERSION): pgraph.spec_sha256(pgraph.load_spec(man))}
    res = spec_digest_stability(repo, drift)
    assert not res["ok"] and f"catalysis scale-graph {HEAD_VERSION}: release v0.1.0 has spec digest" in res["problems"][0]
