"""The repository layout: one module of anchors, what the wheel bundles, what pytest collects, what lint
and fmt never touch, the frozen scale-graph copies, and links in the documentation."""

import re
import shutil
from pathlib import Path

import pytest

from conftest import GRAPH_FROZEN, GRAPH_MANIFEST, HEAD_VERSION, REPO
from scale import layout
from scale.cli import main
from scale.util import ScaleError, load_yaml


# anchors that exist once a proposal has been applied: the kernels of frozen versions (none at 0.1.0)
OPTIONAL_ANCHORS = (layout.KERNEL_FROZEN,)
APPLIED = bool(load_yaml(GRAPH_MANIFEST).get("proposals"))      # a proposal has moved the schema on (none at 0.1.0)
_MAJOR, _MINOR, _ = (int(x) for x in HEAD_VERSION.split("."))
NEXT = f"{_MAJOR}.{_MINOR + 1}.0"


def test_every_anchor_exists():
    for a in layout.RUNTIME_ANCHORS + (layout.DECISIONS, layout.DECISION_LOG, layout.GAP_REGISTER):
        assert (REPO / a).exists() or a in OPTIONAL_ANCHORS, a
    assert (REPO / layout.KERNEL_FROZEN).exists() == GRAPH_FROZEN.exists() == APPLIED     # 0.1.0: nothing frozen yet


def test_two_layers_and_no_repository_wide_composition():
    """The science kernel (core/) and the domains, each self-contained: no root scale-graph.yaml and no
    scale-graph directory under releases/; each domain's frozen versions sit beside its manifest."""
    assert not (REPO / "scale-graph.yaml").exists() and not (REPO / layout.RELEASES / "scale-graph").exists()
    mans = layout.graph_manifests(REPO, experimental=True)
    assert mans == {"catalysis": REPO / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST}       # one domain, in domain/
    assert not (REPO / "domains").exists()
    assert bool(layout.frozen_graph_dirs(REPO)) == APPLIED                                   # 0.1.0: none yet


def test_every_runtime_anchor_is_bundled_and_every_bundle_root_is_grafted():
    roots = layout.BUNDLE
    for a in layout.RUNTIME_ANCHORS:
        assert any(a == r or a.startswith(r + "/") for r in roots), f"{a} is read at runtime but not bundled"
    for r in roots:
        assert (REPO / r).exists(), f"bundled item {r} does not exist"
    manifest = (REPO / "MANIFEST.in").read_text()
    grafted = set(re.findall(r"^graft (\S+)", manifest, re.M)) | {x for line in re.findall(r"^include (.+)", manifest, re.M)
                                                                   for x in line.split()}
    assert set(roots) <= grafted, set(roots) - grafted
    assert "layout.BUNDLE" in (REPO / "setup.py").read_text()            # setup.py bundles what layout declares


def test_the_bundle_drops_working_files_only_inside_proposals(tmp_path):
    src = tmp_path / "repo"
    for rel in ("domain/proposals/000001/proposal.yaml", "domain/proposals/000001/PR_BODY.md",
                "domain/proposals/000001/candidate/scale-graph.yaml", "domain/examples/pkg/README.md",
                "domain/examples/e/work/text.txt", "domain/examples/e/curation/ocr/p1.txt",
                "domain/examples/e/curation/fragments/a.json", "domain/tests/test_x.py"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text("x")
    shutil.copytree(src / "domain", tmp_path / "out", ignore=layout.bundle_ignore(src))
    got = sorted(p.relative_to(tmp_path / "out").as_posix() for p in (tmp_path / "out").rglob("*") if p.is_file())
    assert got == ["examples/e/curation/fragments/a.json", "examples/pkg/README.md", "proposals/000001/proposal.yaml"]


def test_the_wheel_bundles_only_public_documents(tmp_path):
    """What setup.py copies into scale/_data (every BUNDLE item, through bundle_ignore) holds only public synthetic
    documents: no project data, no source texts."""
    from scale import rights
    out = tmp_path / "_data"
    for item in layout.BUNDLE:
        src = REPO / item
        if src.is_dir():
            shutil.copytree(src, out / item, ignore=layout.bundle_ignore(REPO))
        else:
            (out / item).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out / item)
    files = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert len(files) > 50 and "domain/examples/scale-graph/example.json" in files
    assert sorted({f.split("/")[2] for f in files if f.startswith("domain/examples/") and f.count("/") > 2}) == ["scale-graph"]
    docs = rights.committed_documents(out)
    assert len(docs) > 20 and rights.access_problems(out, docs) == []


def test_pytest_collects_the_layout_test_dirs():
    text = (REPO / "pyproject.toml").read_text()
    paths = re.search(r"^testpaths\s*=\s*\[(.*)\]\s*$", text, re.M).group(1)
    assert tuple(re.findall(r'"([^"]+)"', paths)) == layout.TEST_DIRS
    assert "norecursedirs" not in text                     # it would replace pytest's defaults and not stop the glob anyway
    for d in layout.TEST_DIRS:
        assert sorted(REPO.glob(f"{d}/test_*.py")), d
    assert layout.TEST_DIRS[-1] == "domain/tests"                    # the one domain's tests
    def in_environment(rel: Path) -> bool:                  # any virtual environment inside the checkout (e.g. .v/, venv/)
        return any((REPO.joinpath(*rel.parts[:i]) / "pyvenv.cfg").exists() for i in range(1, len(rel.parts)))
    assert sorted(p.relative_to(REPO).as_posix() for p in REPO.rglob("conftest.py")
                  if not layout.is_excluded(p.relative_to(REPO)) and ".venv" not in p.parts
                  and not in_environment(p.relative_to(REPO))) == ["conftest.py"]
    names = [p.name for d in layout.TEST_DIRS for p in REPO.glob(f"{d}/test_*.py")]
    assert len(names) == len(set(names)), "test module basenames must be unique (pytest's prepend import mode)"


@pytest.mark.parametrize("rel, excluded", [
    ("releases/v0.1.0/RELEASE.yaml", True),
    ("core/graph/frozen/kernel-0.1.0.yaml", True), ("domain/graph/frozen/v0.1.0/catalysis.yaml", True),
    ("domain/graph/scale-graph.yaml", False),
    ("domain/proposals/000002/use_case.json", True), ("core/proposals/000006/proposal.yaml", True),
    ("domain/examples/my-corpus/work/texts/a.json", True),
    ("domain/examples/my-corpus/curation/ocr/a.json", True),
    ("domain/tests/fixtures/invalid/dangling-link.json", False), ("core/graph/kernel.yaml", False),
    ("tools/tests/fixtures/proposals/009001/proposal.yaml", False),       # a synthetic fixture, not a record
    ("tools/tests/fixtures/proposals/009001/fixtures/pass-pressure-gauge.json", False),
    ("domain/competency/cq-01-faradaic-efficiency.yaml", False),
    ("build/lib/scale/_data/README.md", True), ("dist/x.json", True)])               # build output
def test_lint_and_fmt_exclusions(rel, excluded):
    assert layout.is_excluded(rel) == excluded


def test_lint_and_fmt_fail_on_a_missing_target(tmp_path):
    from scale.cli import FMT_TARGETS, _json_docs
    from scale.style import yaml_files
    with pytest.raises(ScaleError, match="lint target nowhere does not exist"):
        yaml_files(REPO, ["nowhere"])
    with pytest.raises(ScaleError, match="fmt target nowhere does not exist"):
        _json_docs(REPO, ["nowhere"])
    linted = [p.relative_to(REPO) for p in yaml_files(REPO) + _json_docs(REPO, FMT_TARGETS)]
    assert not [p for p in linted if layout.is_proposal_record(p.parts) or p.parts[0] == "releases"]
    # the synthetic proposal kept as a test fixture is not a record: its JSON stays canonical
    assert Path("tools/tests/fixtures/proposals/009001/fixtures/pass-pressure-gauge.json") in linted


def test_fmt_exclusions_hold_from_any_working_directory(monkeypatch, capsys):
    """Exclusions are tested relative to the repository holding each file, not to the cwd: run from a
    subdirectory, `scale fmt` must still leave releases and proposal records alone."""
    from scale.cli import _json_docs
    for cwd, targets in [("domain", ["proposals"]), ("releases", ["."]),
                         ("docs", ["../releases", "../domain/proposals", "../core/proposals"])]:
        monkeypatch.chdir(REPO / cwd)
        assert _json_docs(Path.cwd(), targets) == [], cwd
        assert main(["fmt", "--check", *targets]) == 0
        assert capsys.readouterr().out.strip() == "all JSON documents canonical"
    monkeypatch.chdir(REPO / "domain")          # a live directory below a subdirectory is still formatted
    assert _json_docs(Path.cwd(), ["examples/scale-graph"])


def test_check_fails_when_the_invalid_fixtures_it_needs_are_missing_or_unexplained(tmp_path):
    from scale.devcheck import INVALID_FIXTURES, check_steps
    d = tmp_path / INVALID_FIXTURES
    d.mkdir(parents=True)
    (d / "a.json").write_text("{}\n")
    (d / "expect.yaml").write_text("fixtures:\n  - file: a.json\n    error: x\n    reason: why\n")
    step = next(s for s in check_steps(tmp_path, fast=True) if "invalid" in s["name"])   # the positive control
    assert step["expect_errors"] == ["x"] and step["cmds"][0][-1] == str(d / "a.json")
    (d / "b.json").write_text("{}\n")                     # a fixture nobody explains
    with pytest.raises(ScaleError, match=r"leaves out \['b.json'\]"):
        check_steps(tmp_path, fast=True)
    (d / "b.json").unlink()
    (d / "expect.yaml").write_text("fixtures:\n  - file: a.json\n    error: x\n")
    with pytest.raises(ScaleError, match="a.json needs an error and a reason"):
        check_steps(tmp_path, fast=True)
    (d / "expect.yaml").unlink()
    with pytest.raises(ScaleError, match="expect.yaml does not exist"):
        check_steps(tmp_path, fast=True)


def test_the_review_policy_is_required(tmp_path):
    from scale.policy import load_policy
    assert load_policy(REPO)["policy_version"] >= 1
    with pytest.raises(ScaleError, match="no review policy"):
        load_policy(tmp_path)


def test_frozen_scale_graph_copies_load_and_verify(tmp_path, capsys):
    """0.1.0 has no frozen version; once a proposal is applied, the base version is frozen (its manifest, its parts and
    the kernel of that version, all under the one version) with digests in SHA256SUMS, and `scale graph verify` checks
    them. The frozen copy here is made by hand the way `scale proposal apply` makes it."""
    import json
    import os
    from scale import pgraph
    from scale.pgraph_proposal import append_frozen_sums, verify_frozen
    assert main(["--repo", str(REPO), "graph", "verify", "--format", "json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [(h["domain"], h["version"]) for h in out["heads"] if h["domain"] == "catalysis"] == [("catalysis", HEAD_VERSION)]
    assert out["sums"]["ok"] and bool(out["frozen"]) == APPLIED
    if not APPLIED:
        assert out["frozen"] == [] and out["sums"] == {"ok": True, "files": 0, "dirs": [], "mismatched": []}
    repo = tmp_path / "repo"                           # the head alone, nothing frozen
    shutil.copytree(REPO / "core", repo / "core", ignore=shutil.ignore_patterns("frozen"))
    shutil.copytree(REPO / "domain/graph", repo / "domain/graph", ignore=shutil.ignore_patterns("frozen"))
    shutil.copy2(REPO / "domain/DOMAIN.yaml", repo / "domain/DOMAIN.yaml")
    shutil.copytree(REPO / "governance/registry", repo / "governance/registry")
    from scale.util import dump_yaml
    m = load_yaml(repo / "domain/graph/scale-graph.yaml")
    m.pop("proposals", None)                           # the proposals that froze earlier versions are not copied
    (repo / "domain/graph/scale-graph.yaml").write_text(dump_yaml(m))
    assert verify_frozen(repo)["ok"]
    as_head = pgraph.spec_sha256(pgraph.load_spec(repo / "domain/graph/scale-graph.yaml"))
    # freeze the head as `scale proposal apply` would, then move the head on
    v = HEAD_VERSION
    kfz, fz = repo / layout.KERNEL_FROZEN, repo / "domain/graph/frozen"
    (fz / f"v{v}").mkdir(parents=True)
    kfz.mkdir(parents=True)
    shutil.copy2(repo / layout.KERNEL, kfz / f"kernel-{v}.yaml")
    shutil.copy2(repo / "domain/graph/catalysis.yaml", fz / f"v{v}/catalysis.yaml")
    m = load_yaml(repo / "domain/graph/scale-graph.yaml")
    m.update(status="frozen", kernel=os.path.relpath(kfz / f"kernel-{v}.yaml", fz), domains=[f"v{v}/catalysis.yaml"])
    from scale.util import dump_yaml
    (fz / f"scale-graph-{v}.yaml").write_text(dump_yaml(m))
    append_frozen_sums(kfz, [kfz / f"kernel-{v}.yaml"])
    append_frozen_sums(fz, [fz / f"scale-graph-{v}.yaml", fz / f"v{v}/catalysis.yaml"])
    head = load_yaml(repo / "domain/graph/scale-graph.yaml")
    head["version"] = NEXT
    (repo / "domain/graph/scale-graph.yaml").write_text(dump_yaml(head))
    res = verify_frozen(repo)
    assert res["ok"] and {d["dir"]: d["files"] for d in res["dirs"]} == {"core/graph/frozen": 1, "domain/graph/frozen": 2}
    # the frozen version assembles to the same spec digest it had as the head
    frozen = pgraph.load_spec(fz / f"scale-graph-{v}.yaml")
    assert frozen["version"] == v and pgraph.spec_sha256(frozen) == as_head
    assert layout.manifest_kernel(fz / f"scale-graph-{v}.yaml").resolve() == (kfz / f"kernel-{v}.yaml").resolve()
    p = kfz / f"kernel-{v}.yaml"                      # a frozen file edited: its digest no longer matches
    p.write_text(p.read_text() + "\n")
    assert verify_frozen(repo)["mismatched"] == [f"core/graph/frozen/kernel-{v}.yaml"]
    (fz / "SHA256SUMS").unlink()
    with pytest.raises(ScaleError, match="domain/graph/frozen/SHA256SUMS is missing"):
        verify_frozen(repo)


def test_an_applied_proposal_leaves_its_base_version_frozen(tmp_path):
    """Every version an applied proposal moved away from is frozen, with the kernel of that version: documents may pin
    it."""
    from scale.pgraph_proposal import verify_frozen
    from scale.util import dump_yaml, write_yaml
    pid = "009001"                                    # synthetic (009xxx); the repository's own proposals are left out
    repo = tmp_path / "repo"
    shutil.copytree(REPO / "core", repo / "core", ignore=shutil.ignore_patterns("frozen", "proposals"))
    shutil.copytree(REPO / "domain/graph", repo / "domain/graph", ignore=shutil.ignore_patterns("frozen"))
    shutil.copy2(REPO / "domain/DOMAIN.yaml", repo / "domain/DOMAIN.yaml")
    m = load_yaml(repo / "domain/graph/scale-graph.yaml")
    m.update(version=NEXT, proposals=[pid])
    (repo / "domain/graph/scale-graph.yaml").write_text(dump_yaml(m))
    write_yaml(repo / f"domain/proposals/{pid}/proposal.yaml", {"id": pid, "base": {"version": HEAD_VERSION}})
    assert verify_frozen(repo)["mismatched"] == [
        f"domain/graph/frozen/scale-graph-{HEAD_VERSION}.yaml is missing ({pid} moved catalysis from {HEAD_VERSION})",
        f"core/graph/frozen/kernel-{HEAD_VERSION}.yaml is missing ({pid} moved catalysis from {HEAD_VERSION})"]


def test_documentation_links_resolve(tmp_path):
    from scale.style import broken_links, markdown_files
    files = [p.relative_to(REPO).as_posix() for p in markdown_files(REPO)]
    assert "README.md" in files and "core/graph/README.md" in files
    assert not [f for f in files if f.startswith("releases/v") or layout.is_proposal_record(Path(f).parts)]
    assert broken_links(REPO) == []
    (tmp_path / "a.md").write_text("[ok](a.md) [bad](missing.md#x) `[code](nowhere.md)` [web](https://x.org/y.md)\n"
                                   "```\n[fenced](nowhere.md)\n```\n[ref]: gone.md\n")
    assert broken_links(tmp_path) == ["a.md:1: missing.md#x does not exist", "a.md:5: gone.md does not exist"]


def test_no_domains_folder_and_no_live_reference_to_it():
    """One domain folder, domain/: no domains/ folder, and no live file names one."""
    folder = re.compile(r"(?:(?<![\w./-])|(?<=\.\./))domains/")
    assert not (REPO / "domains").exists()
    hits = []
    for p in sorted(REPO.rglob("*")):
        rel = p.relative_to(REPO)
        r = rel.as_posix()
        if (not p.is_file() or (p.suffix not in (".py", ".md", ".yaml", ".yml", ".toml", ".in", ".cfg", ".cff", ".json", ".txt")
                                and p.name not in ("CODEOWNERS", ".gitignore"))
                or any(x.startswith(".") and x not in (".github", ".gitignore") for x in rel.parts)
                or any(x.endswith(".egg-info") for x in rel.parts) or rel.parts[0] in layout.BUILD_DIRS
                or layout.is_excluded(rel) or r in ("tools/tests/test_layout.py", "tools/tests/test_codeowners.py")):
            continue
        hits += [f"{r}:{i}: {line.strip()[:120]}" for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1)
                 if folder.search(line)]
    assert hits == []


def test_the_optional_restricted_copy_is_named_only_by_the_environment(tmp_path, monkeypatch):
    """An optional restricted copy (inputs that may not be committed) is where $SCALE_RESTRICTED_DATA points, and nowhere
    else: no default location, no specific repository. Paths mirror repository-relative paths; the repository is read
    first."""
    repo, data = tmp_path / "scale", tmp_path / "anywhere"
    (repo / "d").mkdir(parents=True)
    (repo / "d/public.json").write_text("{}")
    (data / "d").mkdir(parents=True)
    (data / "d/data.json").write_text("{}")
    monkeypatch.delenv(layout.RESTRICTED_ENV, raising=False)
    assert layout.restricted_root(repo) is None and layout.locate(repo, "d/data.json") is None
    assert layout.missing_hint(repo, "d/data.json") == "not in the repository"
    with pytest.raises(ScaleError, match="no restricted copy"):
        layout.restricted_path(repo, "d/data.json")
    monkeypatch.setenv(layout.RESTRICTED_ENV, str(data))
    assert layout.restricted_root(repo) == data.resolve()
    assert layout.locate(repo, "d/data.json") == data.resolve() / "d/data.json"
    assert layout.locate(repo, "d/public.json") == repo / "d/public.json"
    assert layout.restricted_path(repo, "domain/proposals/000001") == data.resolve() / "domain/proposals/000001"
    monkeypatch.setenv(layout.RESTRICTED_ENV, str(tmp_path / "absent"))                # set, but not there: none
    assert layout.restricted_root(repo) is None and "does not exist" in layout.missing_hint(repo, "d/data.json")


def test_kernel_paths():
    g = Path("/r/domain/graph")
    assert layout.kernel_path(g, "../../core/graph/kernel.yaml") == Path("/r/core/graph/kernel.yaml")
    assert layout.kernel_path(g / "frozen", "../../../core/graph/frozen/kernel-0.1.0.yaml") == \
        Path("/r/core/graph/frozen/kernel-0.1.0.yaml")
    rel = Path("/r/releases/v0.1.0/domain/graph")                            # a release keeps its own kernel copy
    assert layout.kernel_path(rel, "../../core/graph/kernel.yaml") == Path("/r/releases/v0.1.0/core/graph/kernel.yaml")
    cand = Path("/r/domain/proposals/000010/candidate/domain/graph")          # a candidate mirrors the repository
    assert layout.kernel_path(cand, "../../core/graph/kernel.yaml") == Path("/r/domain/proposals/000010/candidate/core/graph/kernel.yaml")
    assert layout.manifest_kernel(GRAPH_MANIFEST).resolve() == (REPO / layout.KERNEL).resolve()
    assert load_yaml(GRAPH_MANIFEST)["kernel"] == "../../core/graph/kernel.yaml"


def test_a_manifest_named_from_inside_the_domain_finds_its_kernel(monkeypatch, tmp_path):
    """A relative manifest path given from inside domain/ (``--spec scale-graph.yaml`` in domain/graph/, ``graph/...``
    in domain/) or through a linked folder reads the kernel the manifest names: the same spec digest as from the
    repository root."""
    from scale import pgraph
    head = pgraph.spec_sha256(pgraph.load_spec(GRAPH_MANIFEST))
    for where, rel, want in ((GRAPH_MANIFEST.parent, "scale-graph.yaml", head),
                             (GRAPH_MANIFEST.parent.parent, "graph/scale-graph.yaml", head)):
        monkeypatch.chdir(where)
        assert pgraph.spec_sha256(pgraph.load_spec(Path(rel))) == want, (where, rel)
    try:
        (tmp_path / "dlink").symlink_to(REPO / layout.DOMAIN, target_is_directory=True)
    except OSError:                                        # no symbolic links here
        return
    monkeypatch.chdir(tmp_path)
    assert pgraph.spec_sha256(pgraph.load_spec(Path("dlink/graph/scale-graph.yaml"))) == head
    assert layout.manifest_kernel(Path("dlink/graph/scale-graph.yaml")).resolve() == (REPO / layout.KERNEL).resolve()


def test_a_manifest_is_named_by_the_domain_that_holds_it(tmp_path):
    """``scale graph spec --spec`` names a manifest that is not the head by its domain: a frozen version or a release's
    copy in domain/ by its DOMAIN.yaml, a candidate's copy in domain/ (no DOMAIN.yaml) by the domain around its
    proposal, and any other file by its stem."""
    r = tmp_path / "r"
    (r / "domain").mkdir(parents=True)
    (r / "domain/DOMAIN.yaml").write_text("domain: catalysis\n")
    for rel in ("domain/graph/frozen/scale-graph-0.1.0.yaml", "domain/proposals/000010/candidate/domain/graph/scale-graph.yaml",
                "releases/v0.2.0/domain/graph/scale-graph.yaml", "elsewhere/my-spec.yaml", "loose/domain/graph/x.yaml"):
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text("schema: scale-graph\n")
    (r / "releases/v0.2.0/domain/DOMAIN.yaml").write_text("domain: catalysis\n")
    for rel in ("domain/graph/frozen/scale-graph-0.1.0.yaml", "domain/proposals/000010/candidate/domain/graph/scale-graph.yaml",
                "releases/v0.2.0/domain/graph/scale-graph.yaml"):
        assert layout.manifest_layer(r / rel) == "catalysis", rel
    assert layout.manifest_layer(r / "elsewhere/my-spec.yaml") == "my-spec"
    assert layout.manifest_layer(r / "loose/domain/graph/x.yaml") == "x"          # a domain/ folder that declares no domain
    assert layout.manifest_layer(GRAPH_MANIFEST) == "catalysis"
