"""Release ids, version constraints and the release directory: every release built verifies against its digests,
and the releases chain oldest first (none built is in order: the first will be v0.1.0). Nothing here assumes how many
releases the repository holds."""

import json
import re

import pytest

from conftest import REPO
from scale.cli import main
from scale.releases import list_releases, main_releases, release_root
from scale.util import ScaleError, load_yaml
from scale.versions import normalize_release_id, release_id, release_key, satisfies

RELEASES = list_releases(REPO)                     # the releases built so far, oldest first (none before the first)


def test_every_built_release_verifies_and_the_releases_chain(capsys):
    assert RELEASES == main_releases(REPO) == sorted(RELEASES, key=release_key)
    assert (REPO / "releases/README.md").is_file()               # the folder exists (it marks the repository root)
    assert main(["release", "list"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["release"] for r in rows] == RELEASES
    for i, r in enumerate(rows):                                  # each names the one before it; the first none
        assert r["previous"] == (RELEASES[i - 1] if i else None), r
    assert main(["release", "verify"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert [x["release"] for x in res] == RELEASES and all(x["ok"] for x in res), res


def test_release_ids_normalize_and_order():
    assert normalize_release_id("0.1.0") == normalize_release_id("v0.1.0") == normalize_release_id("/v0.1.0/") == "v0.1.0"
    for bad in ("legacy/v0.1.0", "other/v0.1.0", "v0.1"):
        with pytest.raises(ScaleError):
            normalize_release_id(bad)
    assert sorted(["v0.2.0", "v0.10.0", "v0.1.0"], key=release_key) == ["v0.1.0", "v0.2.0", "v0.10.0"]


def test_identity_comes_from_the_manifest():
    assert release_id({"release": "v0.2.0", "distribution": "scale-schema"}) == "v0.2.0"
    assert release_id({"release": "0.1.0", "distribution": "scale-schema"}) == "v0.1.0"
    assert release_id({"release": "v0.1.0", "distribution": "scale-other"}) is None      # not this distribution's
    assert release_id({"release": "v0.1.0"}) is None and release_id({}) is None
    with pytest.raises(ScaleError, match=r"Release v999.0.0 not found .*Available: "
                                         + re.escape(", ".join(RELEASES) or "none")):
        release_root(REPO, "v999.0.0")


def test_version_constraints():
    assert satisfies("0.2.0", ">=0.1.0,<1.0.0")
    assert not satisfies("1.0.0", ">=0.1.0,<1.0.0")
    assert satisfies("v0.1.0", "==0.1.0")
    with pytest.raises(ScaleError):
        satisfies("0.1.0", "~0.1")


def test_skills_install_from_the_latest_release_or_the_head(tmp_path, capsys):
    """The skills of the latest release; while none is built, the head's."""
    assert main(["skills", "install", str(tmp_path / "skills")]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["release"] == (RELEASES[-1] if RELEASES else "head (no release built yet)")
    assert (tmp_path / "skills/scale-curate-source/SKILL.md").is_file()
    assert (tmp_path / "skills/scale-curate-source/references/recipes.md").is_file()


def test_the_head_manifest_is_graph_only_and_states_the_one_version():
    head = load_yaml(REPO / "scale-release.yaml")
    assert set(head) == {"distribution", "framework", "release", "schema_version", "status", "core", "domain_profiles",
                         "skills"}
    assert head["framework"] == "SCALE — Shared Concepts, Attributes, and Links with Evidence"
    # the release the head describes: the latest built, or the next one being prepared (v0.1.0 before the first)
    assert head["distribution"] == "scale-schema" and release_id(head) == normalize_release_id(head["release"])
    if RELEASES:
        assert release_key(release_id(head)) >= release_key(RELEASES[-1])
    else:
        assert release_id(head) == "v0.1.0"
    assert head["schema_version"] == load_yaml(REPO / "domain/graph/scale-graph.yaml")["version"]
    assert all(s.startswith("tools/skills/") for s in head["skills"])
    assert not (REPO / "domains").exists() and not (REPO / "releases/legacy").exists()
