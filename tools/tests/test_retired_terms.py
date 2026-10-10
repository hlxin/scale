"""Names and retired wording: SCALE is "Shared Concepts, Attributes, and Links with Evidence", one shared framework
for evidence-backed scientific knowledge graphs across domains (catalysis first), developed at github.com/hlxin/scale.
Its Python distribution is scale-schema, with the commands scale and scale-schema.

Live files therefore name neither the former catalysis-only expansion nor its brands (R1), nor the first package name or
the unrelated PyPI package schema (R2), nor the organization and the data repository of the repository this one was
started from, nor the folders of the restricted examples that were not carried (R3), and the documentation does not
describe a restricted-data integration (R4: the variable that names the optional restricted copy appears only in code,
tests and workflows). The projects in the stewardship registry (governance/registry/stewardship.yaml) are registry
entries, not restricted data, and may be named. This repository keeps no archive of the earlier repository's releases
(its own history starts at 0.1.0 on 2026-10-08).

The retired names are assembled from fragments below, so that no file of this repository spells them, this one
included: a search of the tree for any of them finds nothing."""

import re
from pathlib import Path

from conftest import REPO
from scale import layout

_CAT = "Cataly" + "sis"
OLD_PACKAGE = "scale" + "-science"                     # the first distribution name
ORG = "scale" + "-consortium"                          # the organization the work was started in
DATA_REPO = "catalysis" + "-kg"                        # its private data repository
OLD_EXAMPLES = ("methanol" + "-synthesis",)  # the restricted example's former folder under domain/examples/
#                                             (the methanol example is public now, under examples/ at the root)
EARLIER_PACKAGE = "scale-" + "catalysis"               # the package of the earlier contents of github.com/hlxin/scale

R1 = re.compile(rf"Shared\s+{_CAT}\s+(?:Atlas|Attributes)|SCALE\s+Science(?!\s+kernel)|SCALE-{_CAT}", re.I)
# the one use of the earlier package's name that is not retired: the id of a kg-bundle's schema (the catalysis vocabulary
# of scale-graph, named scale-<domain>), written as an identifier (in code font) or with its version, and identified by
# the digest in extends; any other use of the name is still refused
SCHEMA_ID = re.compile(rf"`{{1,2}}{EARLIER_PACKAGE}(?: \d+\.\d+\.\d+)?`{{1,2}}|{EARLIER_PACKAGE} \d+\.\d+\.\d+")
R2 = re.compile(r"scale[-_]science|\b(?:pip3? install|uv pip install|uv tool install|uv add|uvx)(?:\s+--?[\w=.-]+)*\s+schema(?![\w-])",
                re.I)
R3 = re.compile("|".join([re.escape(ORG), re.escape(DATA_REPO), "kg" + "-tiers", "cath" + "anor",
                          r"domain/examples/(?:" + "|".join(OLD_EXAMPLES) + r")\b"]), re.I)
R4 = re.compile(r"SCALE_RESTRICTED_DATA")

TEXT = (".py", ".md", ".yaml", ".yml", ".toml", ".in", ".cfg", ".cff", ".json", ".txt", ".sh")
NAMES = ("CODEOWNERS", "NOTICE", "LICENSE", "MANIFEST.in", ".gitignore")
CODE = re.compile(r"^(tools/scale/|tools/tests/|core/tests/|domain/tests/|conftest\.py$|setup\.py$|\.github/workflows/)")
THIS = "tools/tests/test_retired_terms.py"
ALLOWED = {   # (file, text): deliberate mentions
    # agents are told never to install the unrelated package schema
    ("AGENTS.md", "Never write `pip install schema` or `uvx schema`"),
    # the earlier contents of github.com/hlxin/scale, which this repository replaced, named so that their documents
    # (another numbering) are told apart; R1 refuses the name as a brand everywhere else
    *((f, f"package {EARLIER_PACKAGE});") for f in ("README.md", "AGENTS.md", "governance/repository-settings.md")),
}


def _live_files() -> list[Path]:
    out = []
    for p in sorted(REPO.rglob("*")):
        rel = p.relative_to(REPO)
        if (not p.is_file() or (p.suffix not in TEXT and p.name not in NAMES)
                or any(x.startswith(".") and x not in (".github", ".gitignore") for x in rel.parts)
                or any(x.endswith(".egg-info") for x in rel.parts) or rel.parts[0] in layout.BUILD_DIRS
                or layout.is_local(rel)):
            continue
        out.append(p)
    return out


def _hits(rel: str, text: str) -> list[str]:
    # this file states R2's rule with examples of what it refuses; the names of R1 and R3 it never spells
    rules = ([R1, R3] if rel == THIS else [R1, R2, R3]) + ([] if CODE.match(rel) else [R4])
    return [f"{rel}:{i}: {line.strip()[:160]}" for i, line in enumerate(text.splitlines(), 1)
            if any(rx.search(SCHEMA_ID.sub(" ", line) if rx is R1 else line) for rx in rules)
            and not any(f == rel and t in line for f, t in ALLOWED)]


def test_live_files_use_no_retired_wording():
    files = _live_files()
    rels = {p.relative_to(REPO).as_posix() for p in files}
    assert {"README.md", "AGENTS.md", "CONTRIBUTING.md", "tools/scale/mcp_server.py", "governance/GOVERNANCE.md",
            ".github/CODEOWNERS", "pyproject.toml", "CHANGELOG.md", "docs/decisions/0001-scale-0.1.0.md", THIS} <= rels
    hits = [h for p in files for h in _hits(p.relative_to(REPO).as_posix(), p.read_text(errors="ignore"))]
    assert hits == [], "retired wording:\n" + "\n".join(hits)


def test_every_allowed_mention_still_exists():
    """An ALLOWED entry whose text is gone would silently allow it elsewhere in the file later: keep the list exact."""
    stale = [(f, t) for f, t in sorted(ALLOWED) if t not in (REPO / f).read_text(errors="ignore")]
    assert stale == []


def test_no_archive_of_another_repository_is_kept():
    """What the earlier repository held and this one does not carry: its record-format release archive, its
    multi-domain folder, the restricted examples and the organization's shared actions. (Frozen versions, releases,
    proposals and decision records of this repository's own history are expected once it has them.)"""
    for gone in ("releases/legacy", "domains", *(f"domain/examples/{x}" for x in OLD_EXAMPLES), ".github/actions"):
        assert not (REPO / gone).exists(), gone


def test_the_names_and_the_rules():
    from scale import layout as lay, updates, versions
    from scale.pgraph import SPEC_LINEAGE
    assert versions.DISTRIBUTION == "scale-schema" and SPEC_LINEAGE == "scale"
    assert lay.REPOSITORY_URL == "https://github.com/hlxin/scale"
    assert updates.REMOTE_URL == "https://github.com/hlxin/scale.git"
    assert "github_repo: hlxin/scale\n" in (REPO / ".github/scale-project.yml").read_text()
    text = (REPO / "pyproject.toml").read_text()
    assert 'name = "scale-schema"' in text and 'scale-schema = "scale.cli:main"' in text and f"{OLD_PACKAGE} =" not in text
    assert "Shared Concepts, Attributes, and Links with Evidence" in text
    readme = (REPO / "README.md").read_text()
    assert ("**Shared Concepts, Attributes, and Links with Evidence: one shared framework for evidence-backed scientific\n"
            "knowledge graphs across domains.**") in readme
    for f in ("NOTICE", "CITATION.cff", "scale-release.yaml", "tools/scale/__init__.py"):
        assert "Shared Concepts, Attributes, and Links with Evidence" in (REPO / f).read_text(), f
    # the rules: what they catch, and what they leave alone
    for old in (f"SCALE (Shared {_CAT} Atlas of Linked Evidence)", f"uvx {OLD_PACKAGE} call status", "pip install schema",
                f"https://github.com/{ORG}/schema", f"the private data repository {DATA_REPO}",
                f"domain/examples/{OLD_EXAMPLES[0]}/README.md", f"domain/examples/{OLD_EXAMPLES[0]}/tools/curation.py"):
        assert any(rx.search(old) for rx in (R1, R2, R3)), old
    for fine in ("Shared Concepts, Attributes, and Links with Evidence", "uvx scale-schema call status",
                 "pip install scale-schema", "the catalysis domain", "a methanol-synthesis reaction (synthetic)",
                 "access consortium", "the SCALE science kernel", "follows_domains", "--domain catalysis", "https://github.com/hlxin/scale",
                 "scale:project/methanol-synthesis-pre1966", "the consortium schema repository (up to 79b4fe4)",
                 "examples/methanol-synthesis-pre1966/README.md"):
        assert not any(rx.search(fine) for rx in (R1, R2, R3, R4)), fine
    assert R1.search(f"the {EARLIER_PACKAGE} schema") and not _hits("README.md", f"numbering 0.1.0-0.8.0, package {EARLIER_PACKAGE});")
    for schema_id in (f"`{EARLIER_PACKAGE}`", f"``{EARLIER_PACKAGE} 0.1.0``", f"schema {EARLIER_PACKAGE} 0.1.0"):
        assert not _hits("x.md", schema_id), schema_id                # the bundle schema's id, as an id or with its version
    assert _hits("x.md", f"the {EARLIER_PACKAGE} schema") and _hits("x.md", f"package {EARLIER_PACKAGE};")
    assert _hits("CHANGELOG.md", f"package {EARLIER_PACKAGE});")          # allowed only where ALLOWED says
    assert _hits("docs/commands.md", "set SCALE_RESTRICTED_DATA") and not _hits("tools/scale/layout.py", "SCALE_RESTRICTED_DATA")
    # this file spells none of the names it refuses
    own = (REPO / THIS).read_text()
    assert not R1.search(own) and not R3.search(own) and OLD_PACKAGE not in own
