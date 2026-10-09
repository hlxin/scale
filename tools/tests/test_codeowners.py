"""The CODEOWNERS evaluator (last matching pattern wins; any owner on a line may approve) and the
routing it gives the repository today: the owner owns every path, the core and the catalysis domain."""

from pathlib import Path

import pytest

from conftest import REPO
from scale import codeowners, layout
from scale.util import load_yaml

FIXTURE = Path(__file__).parent / "fixtures/codeowners/CODEOWNERS"
REVIEWERS = "@hlxin"                     # the owner, the reviewer group of the review policy for now


@pytest.fixture(scope="module")
def rules():
    return codeowners.parse(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("pattern,path,hit", [
    ("*", "anything/at/all.txt", True),
    ("/domain/", "domain/DOMAIN.yaml", True),
    ("/domain/", "tools/domain/x", False),                       # anchored at the root
    ("/domain/", "domains/catalysis/DOMAIN.yaml", False),         # another folder is another path
    ("docs/", "tools/docs/x.md", True),                          # no inner slash: any depth
    ("/scale-release.yaml", "scale-release.yaml", True),
    ("/scale-release.yaml", "releases/v0.1.0/scale-release.yaml", False),
    ("*.md", "domain/README.md", True),
    ("/docs/*", "docs/a.md", True),
    ("/docs/*", "docs/decisions/0001.md", False),                # `*` does not cross a directory
    ("/docs/**/log.json", "docs/decisions/log.json", True),
    ("/tools/scale/ci.py", "tools/scale/ci.py", True),
    ("/tools/scale/ci.py", "tools/scale/ci.pyc", False),
])
def test_patterns_follow_github_rules(pattern, path, hit):
    assert bool(codeowners._regex(pattern).match(path)) is hit


def test_a_trailing_slash_pattern_matches_a_directory_anywhere():
    """GitHub's example: `apps/` owns any file in an apps directory anywhere; an inner slash anchors."""
    assert codeowners._regex("apps/").match("src/apps/x.js") and not codeowners._regex("apps/").match("src/apps")
    assert not codeowners._regex("docs/getting-started.md").match("x/docs/getting-started.md")


def test_the_last_matching_line_wins_and_comments_are_dropped():
    rules = codeowners.parse("# header\n*  @a\n/releases/  @b   # immutable\n/docs/  @c @d\n/empty/\n")
    assert codeowners.owners_for(rules, "releases/v0.1.0/RELEASE.yaml") == ("@b",)
    assert codeowners.owners_for(rules, "docs/README.md") == ("@c", "@d")
    assert codeowners.owners_for(rules, "README.md") == ("@a",)
    assert codeowners.owners_for(rules, "empty/x") == ()                       # a line without owners un-owns
    assert codeowners.rule_for(rules, "releases/x").line == 3


def test_minimal_reviewers_is_a_smallest_cover():
    assert codeowners.minimal_reviewers([("@a", "@b"), ("@b",), ("@b", "@c")]) == ["@b"]
    assert codeowners.minimal_reviewers([("@a",), ("@c",)]) == ["@a", "@c"]
    assert codeowners.minimal_reviewers([]) == []


def test_the_owner_owns_every_path(rules):
    own = lambda p: set(codeowners.owners_for(rules, p))
    for path in ("core/graph/kernel.yaml", "core/graph/frozen/SHA256SUMS", "tools/scale/cli.py", "tools/scale/policy.py",
                 "domain/graph/catalysis.yaml", "domain/graph/frozen/SHA256SUMS",
                 "domain/README.md", "domain/proposals/000001/proposal.yaml", "governance/review-policy.yaml",
                 ".github/workflows/apply-proposals.yml", ".github/CODEOWNERS", "scale-release.yaml",
                 "releases/v0.1.0/RELEASE.yaml", "docs/decisions/log.json", "docs/gaps/register.json", "LICENSE"):
        assert own(path) == {REVIEWERS}, path
    # the structure stays ready for catalysis maintainers: domain/ has its own line (they join it later)
    assert codeowners.domain_line("catalysis") == codeowners.domain_line() == "/domain/"
    assert codeowners.lines_for(rules, codeowners.domain_line("catalysis"))
    assert load_yaml(REPO / layout.REVIEW_POLICY)["reviewers"]["team"] == REVIEWERS


def _catalysis_proposal_changed_paths(pid: str = "000001", ver: str = "0.1.0") -> list[str]:
    """What applying a catalysis-only scale-graph proposal changes in a pull request: its record, the domain file it
    installs, the domain's schema manifest, the files that state the one version, the frozen copy of the base
    version with its kernel and their SHA256SUMS lines, the decision record with its log entry and the gap register."""
    cs = f"domain/proposals/{pid}"
    record = [f"{cs}/proposal.yaml", f"{cs}/candidate/domain/graph/catalysis.yaml", f"{cs}/validation_report.json"]
    fz = "domain/graph/frozen"
    frozen = [f"{fz}/scale-graph-{ver}.yaml", f"{fz}/{layout.FROZEN_SUMS}", f"{fz}/v{ver}/catalysis.yaml",
              f"core/graph/frozen/kernel-{ver}.yaml", f"core/graph/frozen/{layout.FROZEN_SUMS}"]
    stating = ["core/CORE.yaml", "domain/DOMAIN.yaml", "scale-release.yaml", "core/examples/science-kernel-only.yaml"]
    return record + ["domain/graph/catalysis.yaml", "domain/graph/scale-graph.yaml"] + stating + frozen + [
        f"{layout.DECISIONS}/0002-{pid}.md", layout.DECISION_LOG, layout.GAP_REGISTER]


def test_a_catalysis_proposal_and_a_core_change_go_to_the_owner(rules):
    req = codeowners.review_requirements(rules, _catalysis_proposal_changed_paths())
    assert not req["unowned"] and req["minimal_reviewers"] == [REVIEWERS]
    req = codeowners.review_requirements(rules, ["core/graph/kernel.yaml", "core/proposals/000002/proposal.yaml",
                                                 "core/graph/frozen/kernel-0.1.0.yaml", "core/graph/frozen/SHA256SUMS"])
    assert req["minimal_reviewers"] == [REVIEWERS]


def test_fixture_rules_match_the_repository_file():
    real = REPO / layout.CODEOWNERS
    if not real.exists():
        pytest.skip(".github/CODEOWNERS is not in place")
    strip = lambda rs: [(r.pattern, r.owners) for r in rs]
    got = strip(codeowners.parse(real.read_text(encoding="utf-8")))
    want = strip(codeowners.parse(FIXTURE.read_text(encoding="utf-8")))
    assert got == want                     # one domain: no line beyond the fixture's
