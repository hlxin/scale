"""core/CORE.yaml declares the shared core: its kernel (which carries no version: the schema's one version is the
catalysis manifest's, which CORE.yaml states), its maintainers in the one shape for people, its review area and where
its parts are."""

from conftest import CORE, HEAD_VERSION, REPO
from scale import layout
from scale.domains import CORE_KEYS, core_version, load_core
from scale.util import load_yaml


def test_core_declaration_names_the_kernel_and_its_maintainers():
    core = load_core(REPO)
    assert core["core"] == "scale-core" and set(core) <= set(CORE_KEYS)
    assert (CORE / core["kernel"]).resolve() == (REPO / layout.KERNEL).resolve()
    for man in layout.graph_manifests(REPO, experimental=True).values():      # the catalysis domain builds on the one kernel
        assert layout.manifest_kernel(man).resolve() == (REPO / layout.KERNEL).resolve()
    # the head version is never frozen while it is the head (frozen kernels are those of earlier versions)
    assert not (REPO / layout.KERNEL_FROZEN / f"kernel-{HEAD_VERSION}.yaml").exists()
    assert "version" not in load_yaml(CORE / core["kernel"])                     # the kernel carries no version
    assert core["version"] == core_version(REPO) == HEAD_VERSION                  # CORE.yaml states the one version
    assert core["maintainers"]["team"] == "@hlxin"                               # the owner, the one reviewer group for now
    assert [(p["github"], p.get("since"), p["roles"], p.get("placeholder", False)) for p in core["maintainers"]["people"]] == [
        ("hlxin", "2026-09-26", ["steward"], False), ("mutianyou2013", "2026-10-11", ["maintainer"], False),
        ("TODO-reviewer-3", None, ["maintainer"], True)]
    assert core["review_areas"] == ["kernel"] and "proposals" not in core
    assert all((CORE / e).is_dir() for e in core["examples"]) and list((CORE / core["tests"]).glob("test_*.py"))


def test_the_core_is_reviewed_by_the_reviewers_of_the_review_policy():
    """One reviewer group reviews the core and the catalysis domain: the core's team is the policy's, and its people are
    the policy's reviewers, placeholders included."""
    pol = load_yaml(REPO / layout.REVIEW_POLICY)
    core = load_core(REPO)
    assert core["maintainers"]["team"] == pol["reviewers"]["team"]
    assert [p["github"] for p in core["maintainers"]["people"]] == [m["github"] for m in pol["reviewers"]["members"]]
