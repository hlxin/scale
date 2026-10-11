"""Licences: code MIT, vocabulary, records and documentation CC-BY-4.0, third-party material under its owners'
terms. REUSE.toml gives every file its licence (``reuse lint``, a step of ``scale check``); the package metadata
states the expression; the wheel carries no third-party text; the licence files are the owner's to change."""

import re
import subprocess
import sys

import pytest

from conftest import REPO
from scale import codeowners, devcheck

LICENCES = ("MIT", "CC-BY-4.0")            # the project's own; anything else is third-party (NOTICE)
PUBLIC_DOMAIN = "LicenseRef-PublicDomain-US"     # copies of public-domain works (NOTICE)
PUBLIC_DOMAIN_PATHS = ("examples/methanol-synthesis-public/pdfs/", "examples/methanol-synthesis-public/texts/")


def _reuse(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "reuse", "--root", str(REPO), *args], capture_output=True, text=True)


@pytest.fixture(scope="module")
def file_licences() -> dict[str, set[str]]:
    """Each file's licence identifiers, as reuse concludes them from REUSE.toml (its SPDX document)."""
    if not (REPO / ".git").exists():
        pytest.skip("reuse reads the git checkout (what git ignores is not checked); this tree is not one")
    res = _reuse("spdx")
    assert res.returncode == 0, res.stderr
    out, name = {}, None
    for line in res.stdout.splitlines():
        if line.startswith("FileName: "):
            name = line.removeprefix("FileName: ").removeprefix("./")
            out[name] = set()
        elif line.startswith("LicenseInfoInFile: ") and name:
            out[name].add(line.removeprefix("LicenseInfoInFile: "))
    assert len(out) > 200                   # the whole tree, not a part of it
    return out


def test_reuse_lint_passes_and_scale_check_runs_it():
    if not (REPO / ".git").exists():
        pytest.skip("reuse reads the git checkout; this tree is not one")
    res = _reuse("lint")
    assert res.returncode == 0, res.stdout[-2000:]
    steps = {s["name"]: s["cmds"] for s in devcheck.check_steps(REPO, fast=True)}
    assert steps["licence annotations are complete (reuse lint)"] == [[sys.executable, "-m", "reuse", "--root", str(REPO), "lint"]]


@pytest.mark.parametrize("path,licences", [
    ("tools/cli.py", {"MIT"}), ("setup.py", {"MIT"}), ("pyproject.toml", {"MIT"}), (".github/CODEOWNERS", {"MIT"}),
    ("core/graph/kernel.yaml", {"CC-BY-4.0"}), ("domain/graph/catalysis.yaml", {"CC-BY-4.0"}),
    ("domain/examples/scale-catal/example.json", {"CC-BY-4.0"}), ("docs/architecture.md", {"CC-BY-4.0"}),
    ("governance/GOVERNANCE.md", {"CC-BY-4.0"}), ("skills/curate-source/SKILL.md", {"CC-BY-4.0"}),
    ("README.md", {"CC-BY-4.0"}), ("CITATION.cff", {"CC-BY-4.0"}), ("NOTICE", {"CC-BY-4.0"}),
    ("scale-release.yaml", {"CC-BY-4.0"}), ("releases/README.md", {"MIT"}),
    ("domain/tests/test_invalid_fixtures.py", {"MIT"}), ("domain/examples/scale-catal/driving-force-examples/build_examples.py", {"MIT"}),
    ("core/examples/science-examples/build_examples.py", {"MIT"}), ("docs/figures/science-kernel-overview.py", {"MIT"}),
    ("docs/decisions/0001-scale-0.1.0.md", {"CC-BY-4.0"}),
    # the domain template, a test fixture: its texts CC-BY-4.0, its code MIT
    ("tools/tests/fixtures/domain-template/README.md", {"CC-BY-4.0"}),
    ("tools/tests/fixtures/domain-template/graph/__DOMAIN__.yaml", {"CC-BY-4.0"}),
    ("tools/tests/fixtures/domain-template/examples/__DOMAIN__.example.graph.json", {"CC-BY-4.0"}),
    ("tools/tests/fixtures/domain-template/tests/test___SNAKE___domain.py", {"MIT"}),
    ("tools/tests/fixtures/codeowners/CODEOWNERS", {"MIT"}),
])
def test_each_path_has_the_licence_of_its_kind(file_licences, path, licences):
    assert file_licences[path] == licences


def test_no_file_is_under_a_third_party_licence(file_licences):
    """Every file is under the project's own licences, except the copies of public-domain works of the public
    methanol example, and LICENSES/ holds only those texts; the repository holds no third-party text under copyright
    (NOTICE). Material under another licence would need a REUSE.toml entry, its text in LICENSES/ and a NOTICE line
    (licensing.md)."""
    pd = {f for f, lic in file_licences.items() if lic == {PUBLIC_DOMAIN}}
    assert pd and all(f.startswith(PUBLIC_DOMAIN_PATHS) for f in pd)
    assert {f: lic for f, lic in file_licences.items() if f not in pd and lic - set(LICENCES)} == {}
    assert sorted(p.name for p in (REPO / "LICENSES").iterdir()) == sorted(
        [f"{lic}.txt" for lic in LICENCES] + [f"{PUBLIC_DOMAIN}.txt"])
    assert "Public-domain works: examples/methanol-synthesis-public/" in (REPO / "NOTICE").read_text()
    assert "NC-ND" not in (REPO / "REUSE.toml").read_text()
    assert not re.search(r"^exclude ", (REPO / "MANIFEST.in").read_text(), re.M)    # nothing left out of the sdist
    assert "The repository holds no\n  third-party text" in (REPO / "NOTICE").read_text()


def test_licence_texts_and_package_metadata():
    mit = (REPO / "LICENSES/MIT.txt").read_text()
    root = (REPO / "LICENSE").read_text()
    assert root.startswith("MIT License\n\nCopyright (c) 2026 SCALE contributors\n")   # GitHub detects it; holder unchanged
    body = lambda t: " ".join(t.split("Permission is hereby granted", 1)[1].split())
    assert body(root) == body(mit)                                         # the same licence text (wrapped differently)
    assert (REPO / "LICENSES/CC-BY-4.0.txt").read_text().startswith("Creative Commons Attribution 4.0 International")
    py = (REPO / "pyproject.toml").read_text()
    assert re.search(r'^license = "MIT AND CC-BY-4\.0"$', py, re.M)
    files = re.search(r"^license-files = \[(.*)\]$", py, re.M).group(1)
    assert [f.strip('" ') for f in files.split(",")] == ["LICENSE", "LICENSES/MIT.txt", "LICENSES/CC-BY-4.0.txt", "NOTICE"]
    assert 'requires = ["setuptools>=77"]' in py and '"reuse[charset-normalizer]>=5"' in py
    manifest = (REPO / "MANIFEST.in").read_text()
    assert re.search(r"^include .*\bNOTICE\b.*\bREUSE\.toml\b", manifest, re.M) and "include LICENSES/*.txt" in manifest
    assert re.search(r"^license: MIT$", (REPO / "CITATION.cff").read_text(), re.M)   # the software's licence


def test_the_licence_files_belong_to_the_reviewers():
    rules = codeowners.parse((REPO / ".github/CODEOWNERS").read_text(encoding="utf-8"))
    for path in ("LICENSE", "LICENSES/CC-BY-4.0.txt", "NOTICE", "REUSE.toml"):
        assert codeowners.owners_for(rules, path) == ("@hlxin", "@mutianyou2013", "@diazr04"), path
    assert (REPO / ".github/CODEOWNERS").read_text() == (REPO / "tools/tests/fixtures/codeowners/CODEOWNERS").read_text()
