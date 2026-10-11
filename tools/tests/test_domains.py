"""`scale domains list | check`: the catalysis domain and the science kernel as declared, checked units.

Two layers: the science kernel in core/ and the catalysis domain in domain/, with its own schema manifest; there is
no repository-wide composition and no other domain yet. One version for the whole schema: the manifest's, which
CORE.yaml, DOMAIN.yaml, scale-release.yaml and the kernel-only example manifest state. Most tests work on a small
repository (the core, the governance files and the domain template test fixture; no domain/ yet) in which
new_domain() scaffolds a synthetic domain as domain/, which can be changed freely; the repository's own declarations
are checked in core/tests and domain/tests."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import HEAD_VERSION, REPO
from scale import codeowners, layout
from scale.cli import main
from scale.domains import check, declarations, new_domain
from scale.util import ScaleError, dump_yaml, load_doc, load_yaml, write_canonical

FIXTURE_CODEOWNERS = Path(__file__).parent / "fixtures/codeowners/CODEOWNERS"
TEAM = "@example-org/batteries-maintainers"          # a synthetic team (a GitHub team, as an organization names it)
REVIEWERS = "@hlxin"                                 # the review policy's reviewer group: the owner, for now


def _mini(tmp_path, codeowners_file=True) -> Path:
    repo = tmp_path / "repo"
    for d in ("core", "governance", layout.DOMAIN_TEMPLATE):
        shutil.copytree(REPO / d, repo / d, ignore=shutil.ignore_patterns("__pycache__"))
    (repo / ".github").mkdir()
    if codeowners_file:
        shutil.copy2(FIXTURE_CODEOWNERS, repo / layout.CODEOWNERS)
    (repo / layout.RELEASES).mkdir()
    rel = load_yaml(REPO / layout.RELEASE_MANIFEST)
    rel.update(domain_profiles=[])
    (repo / layout.RELEASE_MANIFEST).write_text(dump_yaml(rel))
    return repo


def _new(repo, name="batteries", **kw):
    kw.setdefault("team", TEAM)
    return new_domain(repo, name, kw.pop("title", "Batteries"), "Ada Lovelace", "ada-l", since="2026-10-03", **kw)


def _edit(path: Path, fn) -> None:
    doc = load_yaml(path)
    fn(doc)
    path.write_text(dump_yaml(doc))


def _messages(res, level="errors") -> str:
    return "\n".join(f"{e['where']}: {e['message']}" for e in res[level])


# ---------------------------------------------------------------- new
def test_new_scaffolds_an_experimental_domain_that_passes_the_check(tmp_path):
    repo = _mini(tmp_path)
    before = codeowners.parse((repo / layout.CODEOWNERS).read_text())
    res = _new(repo, title="Batteries: materials & cells")
    d = repo / layout.DOMAIN
    assert layout.domain_layers(repo) == {"batteries": d}                # the domain's name comes from its DOMAIN.yaml
    m = load_yaml(d / "DOMAIN.yaml")
    # the schema's one version, as CORE.yaml states it
    assert m["status"] == "experimental" and m["version"] == HEAD_VERSION == load_yaml(repo / "core/CORE.yaml")["version"]
    assert m["title"] == "Batteries: materials & cells" and "compatible_core" not in m
    assert m["maintainers"] == {"team": TEAM, "people": [{"name": "Ada Lovelace", "github": "ada-l", "since": "2026-10-03",
                                                          "roles": ["steward"]}]}
    assert len(list((d / "competency").glob("*.yaml"))) == 3 and (d / "tests/test_batteries_domain.py").is_file()
    assert load_yaml(d / "graph/batteries.yaml")["domain"] == "batteries"   # the domain file, named after the domain
    man = load_yaml(d / "graph/scale-catal.yaml")                          # the domain's own schema manifest
    assert (m["graph"], man["version"], man["domains"]) == ({"manifest": "graph/scale-catal.yaml"}, HEAD_VERSION, ["batteries.yaml"])
    assert "version" not in load_yaml(d / "graph/batteries.yaml")          # the domain file carries none
    assert "modules" not in man and not any("module" in p.read_text() for p in d.rglob("*") if p.is_file())
    assert man["kernel"] == "../../core/graph/kernel.yaml"
    assert layout.manifest_kernel(d / "graph/scale-catal.yaml").resolve() == (repo / layout.KERNEL).resolve()
    assert load_doc(d / "examples/batteries.example.graph.json")["graph"]["schema_version"] == HEAD_VERSION
    assert load_doc(d / "examples/batteries.example.graph.json")["graph"]["graph_id"] == "ex:batteries/example"
    # the domain's line, /domain/, names its team before the reviewers; the other lines are untouched
    after = codeowners.parse((repo / layout.CODEOWNERS).read_text())
    assert [(r.pattern, r.owners) for r in after] == [(r.pattern, (TEAM, REVIEWERS) if r.pattern == "/domain/" else r.owners)
                                                      for r in before]
    assert f"named {TEAM} on the /domain/ line" in res["codeowners"] and res["status"] == "experimental"
    out = check(repo)
    assert out["ok"], _messages(out)
    assert "listed by nobody" not in _messages(out, "warnings")       # the reviewers review every area
    # the scaffolded test passes where it lands
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(d / "tests")], cwd=repo,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr


def test_new_writes_nothing_to_a_missing_codeowners(tmp_path):
    repo = _mini(tmp_path, codeowners_file=False)
    res = _new(repo)
    assert not (repo / layout.CODEOWNERS).exists() and "nothing was written" in res["codeowners"]
    assert "CODEOWNERS: missing" in _messages(check(repo))


def test_new_refuses_bad_or_taken_names_and_a_second_domain(tmp_path):
    repo = _mini(tmp_path)
    for bad in ("Batteries", "_x", "two--hyphens", "kernel"):
        with pytest.raises(ScaleError):
            _new(repo, bad)
    with pytest.raises(ScaleError, match="code owner as CODEOWNERS names it"):
        new_domain(repo, "solar", "Solar", "A B", "ab", team="not-a-team")
    assert not (repo / layout.DOMAIN).exists()
    _new(repo)
    with pytest.raises(ScaleError, match="exists: the repository has its one domain beside the core"):
        _new(repo, "solar")                                              # one domain: domain/ is taken
    with pytest.raises(ScaleError, match="checkout"):
        shutil.rmtree(repo / ".github")
        _new(repo, "solar")


# ---------------------------------------------------------------- identifiers (F4)
def test_redeclaring_a_core_or_domain_name_is_an_error_naming_both_owners(tmp_path):
    repo = _mini(tmp_path)
    _new(repo)
    mod = repo / "domain/graph/batteries.yaml"
    _edit(mod, lambda m: m.update(nodes={"Cell": {"is_a": "ObjectOfStudy", "description": "x"},
                                         "Question": {"description": "a second Question"}},
                                  adds_properties={"Experiment": {"cycle_count": {"type": "integer"}}}))
    msgs = _messages(check(repo, examples=False))
    assert "domain/DOMAIN.yaml: label Question is declared by core (core/graph/kernel.yaml) and again by batteries" in msgs
    assert "Cell" not in msgs and "cycle_count" not in msgs                 # is_a and a new key extend
    # a second file of the domain that redeclares what the first declares: the first file is named first
    (repo / "domain/graph/cells.yaml").write_text(dump_yaml({
        "domain": "battery-cells", "imports": [],
        "nodes": {"Cell": {"is_a": "ObjectOfStudy", "description": "a cell again"}},
        "adds_properties": {"Experiment": {"cycle_count": {"type": "integer"}}}}))
    _edit(repo / "domain/graph/scale-catal.yaml", lambda m: m.update(domains=["batteries.yaml", "cells.yaml"]))
    msgs = _messages(check(repo, examples=False))
    assert "label Cell is declared by batteries (domain/graph/batteries.yaml) and again by batteries (domain/graph/cells.yaml)" in msgs
    assert "property Experiment.cycle_count is declared by batteries (domain/graph/batteries.yaml)" in msgs


def test_declarations_cover_labels_edges_properties_and_bridges():
    doc = {"domain": "d", "nodes": {"A": {"properties": {"p": {}}}}, "edges": {"E": {}},
           "adds_properties": {"B": {"q": {}}}, "bridges": {"other": {"edges": {"F": {}}, "adds_properties": {"C": {"r": {}}}}}}
    assert set(declarations(doc)) == {("scale-catal file name", "d"), ("label", "A"), ("property", "A.p"),
                                      ("edge type", "E"), ("property", "B.q"), ("edge type", "F"), ("property", "C.r")}


# ---------------------------------------------------------------- status rules
def test_experimental_domains_stay_out_of_releases(tmp_path):
    repo = _mini(tmp_path)
    _new(repo)
    _edit(repo / layout.RELEASE_MANIFEST, lambda m: m.update(domain_profiles=["domain/DOMAIN.yaml"]))
    msgs = _messages(check(repo, examples=False))
    assert "domain_profiles is ['domain/DOMAIN.yaml']; the non-experimental domains are []" in msgs


def test_a_domain_line_must_name_its_team(tmp_path):
    repo = _mini(tmp_path)
    _new(repo)
    co = repo / layout.CODEOWNERS
    text = co.read_text()
    assert f"/domain/                            {TEAM} {REVIEWERS}" in text
    co.write_text(text.replace(f"{TEAM} {REVIEWERS}", REVIEWERS))
    assert f"no /domain/ line naming {TEAM}" in _messages(check(repo, examples=False))
    co.write_text(text + f"/domain/DOMAIN.yaml {REVIEWERS}\n")            # a later line takes the declaration away
    assert f"a later line overrides /domain/: {TEAM} does not own domain/" in _messages(check(repo, examples=False))


def test_placeholder_maintainers_are_seats_not_people(tmp_path):
    """A placeholder seat needs no start date and never counts as a steward (nor as a person credited)."""
    repo = _mini(tmp_path)
    _new(repo)
    _edit(repo / "domain/DOMAIN.yaml", lambda m: m["maintainers"]["people"].append(
        {"name": "TODO-reviewer-2", "github": "TODO-reviewer-2", "placeholder": True, "roles": ["steward"]}))
    res = check(repo, examples=False)
    assert res["ok"], _messages(res)
    from scale.domains import stewards
    assert [p["github"] for p in stewards(load_yaml(repo / "domain/DOMAIN.yaml"))] == ["ada-l"]
    _edit(repo / "domain/DOMAIN.yaml", lambda m: m["maintainers"]["people"][-1].update(placeholder="yes"))
    assert "placeholder is true or absent" in _messages(check(repo, examples=False))


def test_a_domain_manifest_uses_the_core_kernel_and_its_own_domain_files(tmp_path):
    repo = _mini(tmp_path)
    _new(repo)
    man = repo / "domain/graph/scale-catal.yaml"
    (repo / "elsewhere").mkdir()
    shutil.copy2(repo / "domain/graph/batteries.yaml", repo / "elsewhere/solar.yaml")
    _edit(repo / "elsewhere/solar.yaml", lambda m: m.update(domain="solar"))
    _edit(man, lambda m: m.update(domains=["batteries.yaml", "../../elsewhere/solar.yaml"]))
    msgs = _messages(check(repo, examples=False))
    assert "lists ['elsewhere/solar.yaml'], which lie outside domain/" in msgs
    # further files inside the domain are allowed; the file named after the domain is required
    (repo / "domain/graph/cells.yaml").write_text("domain: battery-cells\nimports: []\n")
    _edit(man, lambda m: m.update(domains=["batteries.yaml", "cells.yaml"]))
    assert check(repo, examples=False)["ok"], _messages(check(repo, examples=False))
    _edit(man, lambda m: m.update(domains=["cells.yaml"]))
    assert "lists no file named after the domain (`domain: batteries`" in _messages(check(repo, examples=False))
    # the module form is refused in a domain's manifest, and so is the module form of the domain file
    _edit(man, lambda m: m.update(domains=["cells.yaml"], modules=["batteries.yaml"]))
    _edit(repo / "domain/graph/batteries.yaml", lambda m: m.update(module=m.pop("domain")))
    msgs = _messages(check(repo, examples=False))
    assert "`modules:` is a form of frozen versions; a domain's manifest lists its files under `domains:`" in msgs
    assert "graph/batteries.yaml: a domain file names itself with `domain:`" in msgs
    _edit(repo / "domain/graph/batteries.yaml", lambda m: m.update(domain=m.pop("module")))
    _edit(man, lambda m: [m.pop("modules"), m.update(domains=["batteries.yaml"])] and None)
    _edit(repo / "domain/DOMAIN.yaml", lambda m: m["graph"].update(modules=["graph/batteries.yaml"]))
    assert "graph: unknown key 'modules': graph takes only manifest" in _messages(check(repo, examples=False))
    _edit(repo / "domain/DOMAIN.yaml", lambda m: m["graph"].pop("modules"))
    assert check(repo, examples=False)["ok"], _messages(check(repo, examples=False))
    shutil.copy2(repo / "core/graph/kernel.yaml", repo / "core/graph/other-kernel.yaml")
    _edit(man, lambda m: m.update(kernel="../../core/graph/other-kernel.yaml"))
    assert "kernel resolves to core/graph/other-kernel.yaml; a domain uses the core's kernel core/graph/kernel.yaml" in \
        _messages(check(repo, examples=False))
    _edit(repo / "domain/DOMAIN.yaml", lambda m: m["graph"].pop("manifest"))
    assert "graph.manifest is required" in _messages(check(repo, examples=False))


def test_the_release_manifest_has_no_repository_wide_graph(tmp_path):
    repo = _mini(tmp_path)
    _edit(repo / layout.RELEASE_MANIFEST, lambda m: m.update(graph="scale-catal.yaml"))
    assert "there is no repository-wide scale-catal composition" in _messages(check(repo, examples=False))


def test_a_promoted_domain_needs_the_promotion_criteria_unless_founding(tmp_path):
    repo = _mini(tmp_path)
    _new(repo)
    _edit(repo / "domain/DOMAIN.yaml", lambda m: m.update(status="stable"))
    msgs = _messages(check(repo, examples=False))
    assert "missing required key 'decision_record'" in msgs
    assert "domain_profiles is []" in msgs
    # promote it properly: release manifest and a decision record
    _edit(repo / layout.RELEASE_MANIFEST, lambda m: m.update(domain_profiles=["domain/DOMAIN.yaml"]))
    (repo / "docs/decisions").mkdir(parents=True)
    (repo / "docs/decisions/0042-batteries.md").write_text("# 0042\n")
    _edit(repo / "domain/DOMAIN.yaml", lambda m: m.update(decision_record="docs/decisions/0042-batteries.md"))
    res = check(repo, examples=False)
    errs = _messages(res)
    assert "at least 2 maintainers with role steward (has 1)" in errs
    assert "at least 3 competency questions that answer as expected (has 1; scale domains cq)" in errs   # cq-01 runs
    assert all("stewardship target" in e["message"] for e in res["errors"]), errs
    _edit(repo / "domain/DOMAIN.yaml", lambda m: m.update(founding=True))
    res = check(repo, examples=False)
    assert res["ok"], _messages(res)
    assert "at least 2 maintainers with role steward" in _messages(res, "warnings")


def test_one_version_dependencies_and_conventions(tmp_path):
    repo = _mini(tmp_path)
    _new(repo)
    dm = repo / "domain/DOMAIN.yaml"
    _edit(dm, lambda m: m.update(version="0.9.0", compatible_core=">=1.0.0,<2.0.0",
                                 depends_on=[{"domain": "optics", "version": ">=0.1.0"}],
                                 alternative_to="nowhere", competency="questions", colour="blue"))
    msgs = _messages(check(repo, examples=False))
    assert f"version is '0.9.0'; the schema has one version, the manifest's {HEAD_VERSION}" in msgs
    assert "unknown key 'compatible_core'" in msgs                     # no separate kernel versions to be compatible with
    assert "depends_on[0] names 'optics': catalysis is the only domain beside the core" in msgs   # one domain
    assert "alternative_to names 'nowhere', which is not the name of a scale-catal file" in msgs
    assert "competency must be 'competency': the tools read domain/competency" in msgs and "unknown key 'colour'" in msgs
    _edit(dm, lambda m: [m.pop(k) for k in ("colour", "depends_on", "alternative_to", "compatible_core")] and None)
    _edit(dm, lambda m: m.update(version=HEAD_VERSION, competency="competency", domain="Two Words"))
    (repo / "domain/tests/test_batteries_domain.py").unlink()
    _edit(repo / "domain/graph/batteries.yaml", lambda m: m.update(imports=[{"module": "catalysis"}]))
    msgs = _messages(check(repo, examples=False))
    assert "domain is 'Two Words': the domain's name is lowercase letters, digits and single hyphens" in msgs
    assert "tests: tests/ has no test_*.py" in msgs
    assert "imports 'catalysis', which is neither the kernel nor one of the domain's own files" in msgs


def test_every_file_states_the_one_version_and_parts_carry_none(tmp_path):
    """The schema has one version, the manifest's: CORE.yaml, DOMAIN.yaml, scale-release.yaml and the kernel-only
    example manifest state it, and the kernel and the domain files carry none of their own."""
    repo = _mini(tmp_path)
    _new(repo)
    assert check(repo, examples=False)["ok"]
    for rel, key in (("core/CORE.yaml", "version"), (layout.RELEASE_MANIFEST, "schema_version"),
                     ("core/examples/science-kernel-only.yaml", "version")):
        before = load_yaml(repo / rel)[key]
        _edit(repo / rel, lambda m, key=key: m.update({key: "9.9.9"}))
        assert f"{rel}: {key} is '9.9.9'; the schema has one version" in _messages(check(repo, examples=False)), rel
        _edit(repo / rel, lambda m, key=key, before=before: m.update({key: before}))
    _edit(repo / "domain/graph/batteries.yaml", lambda m: m.update(version="0.3.0"))
    assert "a domain file carries no version of its own" in _messages(check(repo, examples=False))


def test_domains_hold_no_copies_of_core_files(tmp_path):
    repo = _mini(tmp_path)
    _new(repo)
    ex = repo / "domain/examples"
    shutil.copy2(repo / "core/graph/kernel.yaml", ex / "my-kernel.yaml")
    shutil.copy2(repo / "core/examples/science-examples/a-designed-series.json", ex / "copied.json")
    frozen = repo / "domain/graph/frozen/v0.1.0"                          # frozen kernels live only in core/
    frozen.mkdir(parents=True)
    shutil.copy2(repo / "core/graph/kernel.yaml", frozen / "kernel.yaml")
    (repo / "domain/notes").mkdir()
    shutil.copy2(repo / "core/CORE.yaml", repo / "domain/notes/CORE.yaml")
    msgs = _messages(check(repo, examples=False))
    assert "examples/my-kernel.yaml is a copy of a scale-catal kernel" in msgs
    assert "examples/copied.json is byte-identical to a core file" in msgs
    assert "domain/graph/frozen/v0.1.0/kernel.yaml is a copy of a scale-catal kernel" in msgs
    assert "domain/notes/CORE.yaml is byte-identical to a core file" in msgs    # anywhere in the domain


def test_example_documents_must_validate(tmp_path):
    repo = _mini(tmp_path)
    _new(repo)
    p = repo / "domain/examples/batteries.example.graph.json"
    doc = load_doc(p)
    doc["nodes"][0]["label"] = "NoSuchLabel"
    write_canonical(p, doc)
    assert "example examples/batteries.example.graph.json:" in _messages(check(repo))
    assert check(repo, examples=False)["ok"]


def test_core_example_documents_must_validate(tmp_path):
    repo = _mini(tmp_path)
    p = repo / "core/examples/science-examples/c-inconsistent-reference.json"
    doc = load_doc(p)
    doc["links"][0]["type"] = "NO_SUCH_EDGE"
    write_canonical(p, doc)
    assert "core/CORE.yaml: example examples/science-examples/c-inconsistent-reference.json:" in _messages(check(repo))


def test_the_check_runs_only_at_a_checkout_root(tmp_path):
    repo = _mini(tmp_path)
    shutil.rmtree(repo / ".github")
    with pytest.raises(ScaleError, match="root of a repository checkout"):
        check(repo)


# ---------------------------------------------------------------- CLI
def test_cli_list_and_check(tmp_path, capsys):
    repo = _mini(tmp_path)
    assert new_domain(repo, "solar-fuels", "Solar fuels", "Ada Lovelace", "ada-l", since="2026-10-03")["path"] == "domain"
    assert (repo / "domain/tests/test_solar_fuels_domain.py").is_file()
    assert main(["--repo", str(repo), "domains", "list", "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [(r["domain"], r["status"], r["team"], r["in_release_manifest"]) for r in rows] == [
        ("solar-fuels", "experimental", REVIEWERS, False)]                   # by default the reviewers team
    assert main(["--repo", str(repo), "domains", "check", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert main(["--repo", str(repo), "domain", "check", "solar-fuels", "--json"]) == 0     # `scale domain` is the same group
    assert json.loads(capsys.readouterr().out)["domains"] == [{"domain": "solar-fuels", "status": "experimental",
                                                               "version": HEAD_VERSION}]
    _edit(repo / "domain/DOMAIN.yaml", lambda m: m.update(version="one"))
    assert main(["--repo", str(repo), "domains", "check"]) == 1
    out = capsys.readouterr().out
    assert "version 'one' is not a semantic version" in out and "version is 'one'; the schema has one version" in out


def test_template_yaml_is_valid_block_yaml_with_quoted_placeholders():
    from scale.style import lint_yaml_file
    for p in (REPO / layout.DOMAIN_TEMPLATE).rglob("*.yaml"):
        assert not lint_yaml_file(p), p
        yaml.safe_load(p.read_text())


def test_a_scaffolded_domain_has_one_running_question_and_two_stubs(tmp_path):
    from scale.competency import run
    repo = _mini(tmp_path)
    _new(repo)
    res = run(repo, ["batteries"])
    assert res["ok"] and res["answered_as_expected"] == 1 and res["stubs"] == 2
    q = next(r for r in res["questions"] if not r["stub"])
    assert q["id"] == "CQ-batteries-01" and q["answer"] == {"status": "answered", "rows": 1, "schema_gaps": []}
    # a question that does not answer as expected is reported by the domain check (and fails `scale domains cq`)
    _edit(repo / "domain/competency/cq-01-batteries.yaml", lambda m: m["expect"].update(min_rows=2))
    assert "competency/cq-01-batteries.yaml does not answer as expected: 1 rows, expected at least 2" in _messages(
        check(repo, examples=False), "warnings")
    assert not run(repo, ["batteries"])["ok"]


def test_scale_check_runs_the_domain_check():
    from scale.devcheck import check_steps
    steps = {s["name"]: s["cmds"] for s in check_steps(REPO, fast=True)}
    cmds = steps["domain and core manifests are complete, compatible and do not redefine identifiers"]
    assert [c[-2:] for c in cmds] == [["domains", "check"]] and "scale-catal schemas load (head and frozen)" in steps
    assert [c[-2:] for c in steps["competency questions answer as expected"]] == [["domains", "cq"]]


# ---------------------------------------------------------------- the whole repository
def _copy_repository(dest: Path) -> None:
    """The repository without environments and caches (test_version_bump copies it). Large files (example data no
    test writes) are hard-linked when the file system allows it."""
    import os

    def copy(src, dst):
        if os.path.getsize(src) > 1_000_000:
            try:
                return os.link(src, dst)
            except OSError:
                pass
        return shutil.copy2(src, dst)

    skip = shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "*.egg-info", "build", "dist", "demo-output")
    shutil.copytree(REPO, dest, ignore=lambda d, names: {n for n in skip(d, names)} | {n for n in names if
                    (Path(d) / n / "pyvenv.cfg").exists()}, copy_function=copy)


def test_the_kernel_and_the_kernel_only_manifest_state_the_manifests_status(tmp_path):
    """The schema has one status, its manifest's (`candidate`: no release changes it): the kernel and the kernel-only example manifest state the same, so that
    no file calls the version released while the manifest calls it a candidate."""
    head = load_yaml(REPO / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST)["status"]
    assert head == "candidate"
    for rel in (layout.KERNEL, layout.KERNEL_ONLY_MANIFEST):
        assert load_yaml(REPO / rel)["status"] == head, rel
    repo = tmp_path / "repo"
    _copy_repository(repo)
    assert check(repo, examples=False)["ok"]
    for rel in (layout.KERNEL, layout.KERNEL_ONLY_MANIFEST):
        text = (repo / rel).read_text()
        (repo / rel).write_text(text.replace("\nstatus: candidate\n", "\nstatus: released\n", 1))
        assert f"{rel}: status is 'released'; the schema's status is its manifest's, 'candidate'" in \
            _messages(check(repo, examples=False)), rel
        (repo / rel).write_text(text)


def test_the_repository_holds_one_domain_beside_the_core():
    """One domain folder, domain/, declaring the catalysis domain: the domain's name read from its DOMAIN.yaml, and
    the tools find its manifest, competency questions and examples there."""
    d = REPO / layout.DOMAIN
    assert not (REPO / "domains").exists()
    assert layout.domain_dirs(REPO) == [d] and layout.domain_layers(REPO) == {"catalysis": d}
    assert layout.graph_manifests(REPO) == {"catalysis": d / layout.DOMAIN_GRAPH_MANIFEST}
    assert layout.competency_files(REPO) and all(p.parent == d / layout.DOMAIN_COMPETENCY for p in layout.competency_files(REPO))
    assert layout.example_roots(REPO) == [REPO / "core/examples", d / layout.DOMAIN_EXAMPLES]
    res = check(REPO)
    assert [x["domain"] for x in res["domains"]] == ["catalysis"]
