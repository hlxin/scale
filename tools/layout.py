"""Where things are in a SCALE repository: the one source of repository-relative anchors.

The repository root holds ``scale-release.yaml`` and ``releases/``. The specification has two
layers: the science kernel in ``core/`` and the catalysis domain in ``domain/`` (its graph schema
manifest ``graph/scale-catal.yaml`` assembles the kernel with the catalysis file
``graph/catalysis.yaml``: one vocabulary and one checklist), declared by ``domain/DOMAIN.yaml``, whose
``domain:`` key names the domain (``catalysis``). The manifest's ``version`` is the one version of the whole
schema, kernel and catalysis together; the kernel and the catalysis file carry none. The tooling lives in
``tools/`` and the governance files in ``governance/``. A wheel bundles the same tree as ``scale/_data`` (see
:data:`BUNDLE`), so every join below works in a checkout and in an installed package alike. Code never spells
these paths itself: moving a directory is one edit here. Catalysis is the first domain; a second domain would
revisit the one ``domain/`` folder (docs/architecture.md).

This module imports nothing from the package, because ``setup.py`` loads it by file path to learn
what to bundle.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path, PurePath

# ---------------------------------------------------------------- anchors (repository-relative)
RELEASE_MANIFEST = "scale-release.yaml"          # head distribution manifest; with releases/, the root marker
RELEASES = "releases"
CORE = "core"
KERNEL = "core/graph/kernel.yaml"                # the science kernel (head); no version of its own: the schema's is
                                                 # the catalysis manifest's
KERNEL_FROZEN = "core/graph/frozen"              # the kernel of each earlier schema version, kernel-<v>.yaml (+ SHA256SUMS),
                                                 # written by `scale schema bump`; none before the first schema change
KERNEL_ONLY_MANIFEST = "core/examples/science-kernel-only.yaml"   # the kernel alone, for the core's example documents
CORE_MANIFEST = "core/CORE.yaml"                 # the core's declaration (scale domains check)
ONTOLOGY_REGISTRY = "core/mappings/ontologies.yaml"   # the ontologies SCALE's terms are mapped to (docs/mappings.md)
KERNEL_MAPPINGS = "core/mappings/kernel.yaml"    # the kernel's terms mapped to ontology terms (CORE.yaml mappings)
DOMAIN = "domain"                                # the catalysis domain, the one folder beside core/
DOMAIN_MANIFEST = "DOMAIN.yaml"                  # domain/DOMAIN.yaml: the domain's declaration (its `domain:` names it)
DOMAIN_DECLARATION = f"{DOMAIN}/{DOMAIN_MANIFEST}"
DOMAIN_MAPPINGS = f"{DOMAIN}/mappings/catalysis.yaml"   # the catalysis terms mapped to ontology terms, and the
                                                 # subdomains of catalysis research (DOMAIN.yaml mappings)
DOMAIN_TEMPLATE = "tools/tests/fixtures/domain-template"   # what the tests' new_domain() copies (a test fixture)
CODEOWNERS = ".github/CODEOWNERS"
REPOSITORY_URL = "https://github.com/hlxin/scale"   # recorded as `source` in release manifests
TOOLS = "tools"
SKILLS = "skills"
GOVERNANCE = "governance"
REVIEW_POLICY = "governance/review-policy.yaml"
REGISTRY = "governance/registry"
PREFIX_REGISTRY = "governance/registry/extension-prefixes.yaml"
STEWARDSHIP = "governance/registry/stewardship.yaml"
DECISIONS = "docs/decisions"
DECISION_LOG = "docs/decisions/log.json"
GAP_REGISTER = "docs/gaps/register.json"
IMPLEMENTATION_STATUS = "docs/implementation-status.yaml"

# an optional restricted copy: a folder outside the repository, mirroring repository-relative paths, for inputs that may
# not be committed (data not cleared for publication). Nothing points there unless this variable names it; tools then
# look there for a path the repository does not hold (restricted_path(), locate())
RESTRICTED_ENV = "SCALE_RESTRICTED_DATA"

# the domain's directories (relative to domain/). DOMAIN.yaml declares them and
# `scale domains check` requires these names, because the tools look nowhere else
DOMAIN_COMPETENCY = "competency"
DOMAIN_EXAMPLES = "examples"
EXAMPLES = "examples"                             # the repository's real, public examples (examples/methanol-synthesis-public)
GRAPHS = "graphs"                                 # the graphs SCALE curates and shares, and bundle definitions (not packaged)
SCHEMA_NAME = "scale-catal"                      # the name documents pin (graph.schema) from 0.2.0 on
LEGACY_SCHEMA_NAME = "scale-graph"               # the name of the same schema in 0.1.0 (frozen copies and documents keep it)
DOMAIN_GRAPH_MANIFEST = "graph/scale-catal.yaml"  # a domain's schema manifest (DOMAIN.yaml graph.manifest)
GRAPH_FROZEN = "frozen"                          # beside a domain's manifest: scale-catal-<v>.yaml and their v<v>/ parts
FROZEN_SUMS = "SHA256SUMS"                       # in every frozen directory: the digests of its files (append-only)

# pytest collects these (pyproject testpaths must say the same)
TEST_DIRS = ("tools/tests", "core/tests", "service/tests", "domain/tests")

# what runtime code reads; every anchor must lie under a BUNDLE root (tools/tests checks it)
RUNTIME_ANCHORS = (RELEASE_MANIFEST, RELEASES, CORE, CORE_MANIFEST, KERNEL, KERNEL_FROZEN, KERNEL_ONLY_MANIFEST, DOMAIN,
                   DOMAIN_DECLARATION, ONTOLOGY_REGISTRY, KERNEL_MAPPINGS, DOMAIN_MAPPINGS,
                   SKILLS, REVIEW_POLICY, PREFIX_REGISTRY, STEWARDSHIP, IMPLEMENTATION_STATUS)

# ---------------------------------------------------------------- packaging (setup.py, MANIFEST.in)
BUNDLE = [RELEASE_MANIFEST, RELEASES, CORE, DOMAIN, SKILLS, REVIEW_POLICY,
          REGISTRY, IMPLEMENTATION_STATUS, "AGENTS.md", EXAMPLES]
BUNDLE_IGNORE = ("__pycache__", "*.pyc", ".DS_Store", "test_*.py", "conftest.py")
LOCAL_DIRS = ("work", "scratchpad")              # git-ignored local material (source texts, caches); never bundled
BUILD_DIRS = ("build", "dist", ".venv", "venv", "env")   # git-ignored build output and environments at the root


def _is_local(parts: tuple[str, ...]) -> bool:
    return any(p in LOCAL_DIRS for p in parts) or any(parts[i:i + 2] == ("curation", "ocr") for i in range(len(parts)))


def is_local(rel: str | PurePath) -> bool:
    """A repository-relative path inside git-ignored local material (work/, scratchpad/, curation/ocr/)."""
    return _is_local(PurePath(rel).parts)


def is_frozen(parts: tuple[str, ...]) -> bool:
    """A path inside a frozen scale-catal directory: ``core/graph/frozen/`` or ``domain/graph/frozen/``."""
    return any(parts[i:i + 2] == ("graph", GRAPH_FROZEN) for i in range(len(parts) - 1))


def is_excluded(rel: str | PurePath) -> bool:
    """Repository-relative paths that lint and fmt never touch: archived releases and frozen schema
    versions (immutable), local working material and build output."""
    parts = PurePath(rel).parts
    return bool(parts) and (parts[0] in (RELEASES, *BUILD_DIRS) or is_frozen(parts) or _is_local(parts))


def bundle_ignore(repo: Path):
    """A ``shutil.copytree`` ignore callable for BUNDLE items: local material, caches and tests everywhere."""
    repo = Path(repo).resolve()

    def ignore(d: str, names: list[str]) -> set[str]:
        parts = Path(d).resolve().relative_to(repo).parts
        return {n for n in names if _is_local(parts + (n,)) or any(fnmatch.fnmatch(n, x) for x in BUNDLE_IGNORE)}
    return ignore


# ---------------------------------------------------------------- discovery
def is_root(p: Path) -> bool:
    return (p / RELEASE_MANIFEST).exists() and (p / RELEASES).is_dir()


def is_bundled(p: Path) -> bool:
    """The data an installed package bundles (``scale/_data``, setup.py), found when a command runs outside a
    checkout: the commands that write schema versions refuse it, since they would
    write into the installed package."""
    p = Path(p).resolve()
    return p.name == "_data" and (p.parent / "__init__.py").is_file() and (p.parent / "layout.py").is_file()


def refuse_bundled(repo: Path, command: str) -> None:
    """Stop ``command`` when ``repo`` is the data bundled in an installed package (:func:`is_bundled`)."""
    if is_bundled(repo):
        from .util import ScaleError      # lazily: setup.py loads this file alone
        raise ScaleError(f"{command} writes into a repository checkout; {Path(repo).resolve()} is the data bundled in "
                         f"the installed package. Run it inside a checkout of {REPOSITORY_URL}, or pass --repo")


def find_root(start: Path) -> Path | None:
    """The repository (or bundled data) root at or above ``start``; None outside any."""
    start = Path(start).resolve()
    return next((p for p in [start, *start.parents] if is_root(p)), None)


def domain_dir(repo: Path) -> Path | None:
    """The catalysis domain's folder (``domain/``), or None when the repository has none (a test's mini repository)."""
    d = Path(repo) / DOMAIN
    return d if d.is_dir() else None


def domain_dirs(repo: Path) -> list[Path]:
    """The domain folders beside the core: ``[domain/]``, or none. One domain, catalysis, for now; the callers
    iterate, so that a repository without it reads as having none."""
    d = domain_dir(repo)
    return [d] if d is not None else []


def domain_name(d: Path) -> str:
    """A domain's name: the ``domain:`` its DOMAIN.yaml declares (``catalysis``), which documents follow
    (``follows_domains``) and ``--domain`` selects; the folder's own name when the
    declaration is missing or names none (``scale domains check`` reports it)."""
    from .util import load_yaml           # lazily: setup.py loads this file alone
    f = Path(d) / DOMAIN_MANIFEST
    name = (load_yaml(f) or {}).get("domain") if f.is_file() else None
    return name if isinstance(name, str) and name.strip() else Path(d).name


def domain_layers(repo: Path) -> dict[str, Path]:
    """The domain folders by name: ``{"catalysis": <repo>/domain}``, or {}."""
    return {domain_name(d): d for d in domain_dirs(repo)}


def graph_manifests(repo: Path, experimental: bool = False) -> dict[str, Path]:
    """Each domain's scale-catal manifest by domain name (DOMAIN.yaml ``graph.manifest``), for the
    released (non-experimental) domains unless ``experimental``. There is no repository-wide
    composition: a domain's manifest assembles the science kernel with that domain's own files."""
    from .util import load_yaml           # lazily: setup.py loads this file alone
    out = {}
    for name, d in domain_layers(repo).items():
        m = load_yaml(d / DOMAIN_MANIFEST) if (d / DOMAIN_MANIFEST).is_file() else {}
        rel = ((m or {}).get("graph") or {}).get("manifest")
        if rel and (experimental or (m or {}).get("status") != "experimental"):
            out[name] = d / rel
    return out


def frozen_graph_dir(manifest: Path) -> Path:
    """Where the frozen versions of a domain's schema live: ``frozen/`` beside its manifest."""
    return Path(manifest).parent / GRAPH_FROZEN


def frozen_graph_dirs(repo: Path) -> list[Path]:
    """Every frozen scale-catal directory: the core's frozen kernels, then each domain's frozen versions."""
    dirs = [Path(repo) / KERNEL_FROZEN] + [frozen_graph_dir(m) for m in graph_manifests(repo, experimental=True).values()]
    return [d for d in dirs if d.is_dir()]


# ---------------------------------------------------------------- manifests
def kernel_path(base: Path, ref: str) -> Path:
    """The kernel file a scale-catal manifest in directory ``base`` names (its ``kernel:`` entry ``ref``), lexically
    normalized and built on ``base`` as given (a repository-relative base gives a repository-relative path). When the
    base passes through a symbolic link, lexical normalization no longer says where ``..`` leads; the path is then the
    file the system reaches (absolute), as when the reference is opened as written."""
    ref = str(ref)
    out = Path(os.path.normpath(Path(base) / ref))
    reached = os.path.realpath(Path(os.path.realpath(base)) / ref)   # `..` after a link leads to the link target's parent
    return out if os.path.realpath(out) == reached else Path(reached)


def manifest_kernel(manifest: Path, ref: str | None = None) -> Path:
    """The kernel file a scale-catal manifest names (:func:`kernel_path`); ``ref`` when the manifest is given
    as data, else its ``kernel:`` as the file says."""
    if ref is None:
        from .util import load_yaml       # lazily: setup.py loads this file alone
        ref = str((load_yaml(manifest) or {}).get("kernel") or "")
    return kernel_path(Path(manifest).parent, ref)


def manifest_layer(manifest: Path) -> str:
    """The name of the domain a scale-catal manifest given by its path belongs to (``catalysis``): the ``domain/``
    folder holding it whose DOMAIN.yaml declares the domain (:func:`domain_name`; the head, a frozen version, a
    release). The file's
    stem when no folder holding it is one."""
    parts = Path(os.path.realpath(manifest)).parts
    for i in range(len(parts) - 2, -1, -1):
        if parts[i] == DOMAIN and (Path(*parts[:i + 1]) / DOMAIN_MANIFEST).is_file():
            return domain_name(Path(*parts[:i + 1]))
    return Path(manifest).stem


# ---------------------------------------------------------------- the optional restricted copy
def restricted_root(repo: Path | None = None) -> Path | None:
    """The restricted copy (``$SCALE_RESTRICTED_DATA``), mirroring repository-relative paths, or None when the variable
    names none or names a folder that does not exist: what needs it is then refused with a reason, never read from
    somewhere else."""
    env = os.environ.get(RESTRICTED_ENV, "").strip()
    p = Path(env).expanduser().resolve() if env else None
    return p if p is not None and p.is_dir() else None


def restricted_path(repo: Path | None, rel: str | PurePath) -> Path:
    """Where a repository-relative path is in the restricted copy (whether or not it exists there); an error when no
    restricted copy is set."""
    root = restricted_root(repo)
    if root is None:
        from .util import ScaleError
        raise ScaleError(f"no restricted copy: set {RESTRICTED_ENV} to a folder that mirrors the repository's paths")
    return root / PurePath(rel).as_posix()


def locate(repo: Path, rel: str | PurePath) -> Path | None:
    """A repository-relative file or directory: in the repository, else in the restricted copy (when one is set);
    None when neither has it."""
    here = Path(repo) / PurePath(rel).as_posix()
    if here.exists():
        return here
    root = restricted_root(repo)
    if root is not None and (root / PurePath(rel).as_posix()).exists():
        return root / PurePath(rel).as_posix()
    return None


def missing_hint(repo: Path, rel: str | PurePath) -> str:
    """Why a repository-relative path is not found, for an error message."""
    root = restricted_root(repo)
    if root is not None:
        return f"not in the repository nor in the restricted copy at {root}"
    if os.environ.get(RESTRICTED_ENV, "").strip():
        return f"not in the repository; {RESTRICTED_ENV}={os.environ[RESTRICTED_ENV].strip()} does not exist"
    return "not in the repository"


def competency_files(repo: Path) -> list[Path]:
    """The catalysis domain's competency questions (``domain/competency/*.yaml``)."""
    return sorted(p for d in domain_dirs(repo) for p in (d / DOMAIN_COMPETENCY).glob("*.yaml"))


def example_roots(repo: Path) -> list[Path]:
    """Directories holding example documents: the core's and the catalysis domain's."""
    return [p for p in [Path(repo) / CORE / "examples"] + [d / DOMAIN_EXAMPLES for d in domain_dirs(repo)] if p.is_dir()]
