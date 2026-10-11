"""domain/DOMAIN.yaml: the catalysis domain, the first, stable and `founding: true`. Its own graph schema
manifest (graph/scale-catal.yaml) assembles the science kernel with its one file (graph/catalysis.yaml,
`domain: catalysis`, which carries the one catalysis checklist), its competency questions answer as
expected on public examples, and it passes `scale domains check` (unmet stewardship targets are warnings
for it)."""

import pytest

from conftest import CATALYSIS, HEAD_VERSION, REPO
from scale import layout
from scale.domains import DOMAIN_KEYS, check, graph_files, stewards
from scale.util import load_yaml


@pytest.fixture(scope="module")
def decl():
    return load_yaml(CATALYSIS / layout.DOMAIN_MANIFEST)


def test_catalysis_is_the_founding_stable_domain(decl):
    # DOMAIN.yaml states the schema's one version (the manifest's); no separate kernel compatibility range
    assert (decl["domain"], decl["status"], decl["founding"], decl["version"]) == ("catalysis", "stable", True, HEAD_VERSION)
    assert "compatible_core" not in decl and set(decl) <= set(DOMAIN_KEYS)
    assert decl["review_areas"] == ["catalysis", "thermo", "electrothermo", "electro", "photo", "plasma"]
    assert decl["maintainers"]["team"] == "@hlxin"                                # the owner, for now
    assert [p["github"] for p in stewards(decl)] == ["hlxin"]
    assert decl["decision_record"] == "docs/decisions/0001-scale-0.1.0.md" and (REPO / decl["decision_record"]).is_file()
    assert decl["examples"] == ["examples/scale-catal"]                         # public synthetic examples only


def test_catalysis_graph_files_are_the_parts_of_its_own_manifest(decl):
    assert decl["graph"] == {"manifest": layout.DOMAIN_GRAPH_MANIFEST}      # the manifest lists the files
    man_path = CATALYSIS / decl["graph"]["manifest"]
    assert layout.graph_manifests(REPO) == {"catalysis": man_path}           # the one released domain schema
    man = load_yaml(man_path)
    assert man["domains"] == ["catalysis.yaml"] and "modules" not in man     # one domain file, no modules
    assert graph_files(REPO, "catalysis", decl) == ["graph/catalysis.yaml"]
    own = load_yaml(man_path.parent / man["domains"][0])
    assert own["domain"] == "catalysis" and "checklist" in own              # named after the domain, with the checklist
    assert layout.manifest_kernel(man_path).resolve() == (REPO / layout.KERNEL).resolve()
    assert man["kernel"] == "../../core/graph/kernel.yaml"
    assert "graph" not in load_yaml(REPO / layout.RELEASE_MANIFEST)          # no repository-wide composition
    rel = load_yaml(REPO / layout.RELEASE_MANIFEST)
    assert rel["domain_profiles"] == ["domain/DOMAIN.yaml"]
    assert rel["schema_version"] == man["version"] == HEAD_VERSION


def test_catalysis_has_at_least_three_competency_questions_that_answer_as_expected():
    from scale.competency import run
    res = run(REPO, ["catalysis"])
    assert res["ok"] and res["stubs"] == 0 and res["answered_as_expected"] >= 3
    for q in res["questions"]:                                               # run on public synthetic examples
        assert all(d.startswith("examples/scale-catal/") for d in load_yaml(REPO / q["file"])["documents"])


def test_the_repository_passes_the_domain_check():
    res = check(REPO)
    assert res["ok"], res["errors"]
    # the catalysis domain's and the core's warnings
    mine = {f"{layout.DOMAIN}/{layout.DOMAIN_MANIFEST}", layout.CORE_MANIFEST}
    warnings = [w["message"] for w in res["warnings"] if w["where"] in mine]
    assert any("at least 2 maintainers with role steward (has 1)" in w for w in warnings)   # founding: a warning
    assert not any("listed by nobody" in w for w in warnings)              # every catalysis and kernel area has a reviewer
