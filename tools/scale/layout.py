"""Where things are in a SCALE repository: the one source of repository-relative anchors.

The repository root holds ``scale-release.yaml`` and ``releases/``. The specification has two
layers: the science kernel in ``core/`` and the catalysis domain in ``domain/`` (its graph schema
manifest ``graph/scale-graph.yaml`` assembles the kernel with the catalysis file
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
                                                 # written by `scale proposal apply`; none before the first applied proposal
KERNEL_ONLY_MANIFEST = "core/examples/science-kernel-only.yaml"   # the kernel alone, for the core's example documents
CORE_MANIFEST = "core/CORE.yaml"                 # the core's declaration (scale domains check)
CORE_PROPOSALS = "core/proposals"                # kernel schema change proposals
DOMAIN = "domain"                                # the catalysis domain, the one folder beside core/
DOMAIN_MANIFEST = "DOMAIN.yaml"                  # domain/DOMAIN.yaml: the domain's declaration (its `domain:` names it)
DOMAIN_DECLARATION = f"{DOMAIN}/{DOMAIN_MANIFEST}"
DOMAIN_TEMPLATE = "tools/tests/fixtures/domain-template"   # what the tests' new_domain() copies (a test fixture)
CODEOWNERS = ".github/CODEOWNERS"
REPOSITORY_URL = "https://github.com/hlxin/scale"   # recorded as `source` in release manifests
TOOLS = "tools"
SKILLS = "tools/skills"
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
# look there for a path the repository does not hold (restricted_path(), locate()), and `scale proposal check` writes
# the full reports of a proposal that reads such inputs there and public summaries in the repository
RESTRICTED_ENV = "SCALE_RESTRICTED_DATA"

# the domain's directories (relative to domain/). DOMAIN.yaml declares them and
# `scale domains check` requires these names, because the tools look nowhere else
DOMAIN_COMPETENCY = "competency"
DOMAIN_PROPOSALS = "proposals"                  # one domain's schema change proposals (<NNNNNN>/)
DOMAIN_EXAMPLES = "examples"
DOMAIN_GRAPH_MANIFEST = "graph/scale-graph.yaml"  # a domain's schema manifest (DOMAIN.yaml graph.manifest)
GRAPH_FROZEN = "frozen"                          # beside a domain's manifest: scale-graph-<v>.yaml and their v<v>/ parts
FROZEN_SUMS = "SHA256SUMS"                       # in every frozen directory: the digests of its files (append-only)

# pytest collects these (pyproject testpaths must say the same)
TEST_DIRS = ("tools/tests", "core/tests", "domain/tests")

# what runtime code reads; every anchor must lie under a BUNDLE root (tools/tests checks it)
RUNTIME_ANCHORS = (RELEASE_MANIFEST, RELEASES, CORE, CORE_MANIFEST, KERNEL, KERNEL_FROZEN, KERNEL_ONLY_MANIFEST, CORE_PROPOSALS, DOMAIN,
                   DOMAIN_DECLARATION,
                   SKILLS, REVIEW_POLICY, PREFIX_REGISTRY, STEWARDSHIP, IMPLEMENTATION_STATUS)

# ---------------------------------------------------------------- packaging (setup.py, MANIFEST.in)
BUNDLE = [RELEASE_MANIFEST, RELEASES, CORE, DOMAIN, SKILLS, REVIEW_POLICY,
          REGISTRY, IMPLEMENTATION_STATUS, "AGENTS.md"]
# proposal records are bundled for their use cases and proposal.yaml (which gaps a release addresses)
PROPOSAL_IGNORE = ("candidate", "patch.diff", "withdrawn-sources", "*.md", "*_report.json", "*_pack.json",
                    "migration_assessment.json", "agent_log.json", "approvals")
BUNDLE_IGNORE = ("__pycache__", "*.pyc", ".DS_Store", "test_*.py", "conftest.py")
LOCAL_DIRS = ("work", "scratchpad")              # git-ignored local material (source texts, caches); never bundled
BUILD_DIRS = ("build", "dist", ".venv", "venv", "env")   # git-ignored build output and environments at the root


def _is_local(parts: tuple[str, ...]) -> bool:
    return any(p in LOCAL_DIRS for p in parts) or any(parts[i:i + 2] == ("curation", "ocr") for i in range(len(parts)))


def is_local(rel: str | PurePath) -> bool:
    """A repository-relative path inside git-ignored local material (work/, scratchpad/, curation/ocr/)."""
    return _is_local(PurePath(rel).parts)


def is_proposal_record(parts: tuple[str, ...]) -> bool:
    """A path inside a proposal record directory: ``core/proposals/`` or ``domain/proposals/``. Synthetic
    proposals kept as test fixtures (``tools/tests/fixtures/proposals/``) are not records."""
    return parts[:2] in ((CORE, DOMAIN_PROPOSALS), (DOMAIN, DOMAIN_PROPOSALS))


def proposal_record(parts: tuple[str, ...]) -> tuple[str, ...] | None:
    """The proposal record directory (``core/proposals/<NNNNNN>`` or ``domain/proposals/<NNNNNN>``) a
    repository-relative path lies in, as parts; None outside one."""
    return parts[:3] if is_proposal_record(parts) and len(parts) > 3 else None


def is_frozen(parts: tuple[str, ...]) -> bool:
    """A path inside a frozen scale-graph directory: ``core/graph/frozen/`` or ``domain/graph/frozen/``."""
    return any(parts[i:i + 2] == ("graph", GRAPH_FROZEN) for i in range(len(parts) - 1))


def is_excluded(rel: str | PurePath) -> bool:
    """Repository-relative paths that lint and fmt never touch: archived releases and frozen schema
    versions (immutable), proposal records (history, and candidates mirroring other files), local
    working material and build output."""
    parts = PurePath(rel).parts
    return bool(parts) and (parts[0] in (RELEASES, *BUILD_DIRS) or is_proposal_record(parts) or is_frozen(parts)
                            or _is_local(parts))


def bundle_ignore(repo: Path):
    """A ``shutil.copytree`` ignore callable for BUNDLE items: local material everywhere, and the
    proposal working files only below ``*/proposals/<NNNNNN>/`` (never ``*.md`` elsewhere, e.g. in
    a ``.scale-verbatim`` package)."""
    repo = Path(repo).resolve()

    def ignore(d: str, names: list[str]) -> set[str]:
        parts = Path(d).resolve().relative_to(repo).parts
        pats = BUNDLE_IGNORE + (PROPOSAL_IGNORE if DOMAIN_PROPOSALS in parts[:-1] else ())
        return {n for n in names if _is_local(parts + (n,)) or any(fnmatch.fnmatch(n, x) for x in pats)}
    return ignore


# ---------------------------------------------------------------- discovery
def is_root(p: Path) -> bool:
    return (p / RELEASE_MANIFEST).exists() and (p / RELEASES).is_dir()


def is_bundled(p: Path) -> bool:
    """The data an installed package bundles (``scale/_data``, setup.py), found when a command runs outside a
    checkout: the commands that write proposals, decision records or schema versions refuse it, since they would
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
    (``follows_domains``), ``--domain`` selects and proposal owners name; the folder's own name when the
    declaration is missing or names none (``scale domains check`` reports it)."""
    from .util import load_yaml           # lazily: setup.py loads this file alone
    f = Path(d) / DOMAIN_MANIFEST
    name = (load_yaml(f) or {}).get("domain") if f.is_file() else None
    return name if isinstance(name, str) and name.strip() else Path(d).name


def domain_layers(repo: Path) -> dict[str, Path]:
    """The domain folders by name: ``{"catalysis": <repo>/domain}``, or {}."""
    return {domain_name(d): d for d in domain_dirs(repo)}


def graph_manifests(repo: Path, experimental: bool = False) -> dict[str, Path]:
    """Each domain's scale-graph manifest by domain name (DOMAIN.yaml ``graph.manifest``), for the
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
    """Every frozen scale-graph directory: the core's frozen kernels, then each domain's frozen versions."""
    dirs = [Path(repo) / KERNEL_FROZEN] + [frozen_graph_dir(m) for m in graph_manifests(repo, experimental=True).values()]
    return [d for d in dirs if d.is_dir()]


# a proposal is named by a six-digit number, global across the kernel and the catalysis domain (000001, 000002, ...;
# numbers never repeat anywhere): its id is its directory name and the title stays in proposal.yaml. Where the
# directory lies decides the owner (``core/proposals/``: core; ``domain/proposals/``: the domain's name, catalysis)
PROPOSAL_ID = re.compile(r"\d{6}")


def _proposal_roots(repo: Path) -> list[tuple[str, Path]]:
    return [(CORE, Path(repo) / CORE_PROPOSALS)] + [(name, d / DOMAIN_PROPOSALS) for name, d in domain_layers(repo).items()]


def is_proposal_id(name: object) -> bool:
    """A proposal id: exactly six digits, as a string (an id read as a number has lost its zeros)."""
    return isinstance(name, str) and PROPOSAL_ID.fullmatch(name) is not None


def _listed(root: Path) -> list[str]:
    return sorted(q.name for q in root.iterdir() if q.is_dir() and not q.name.startswith((".", "_"))) if root.is_dir() else []


def proposal_dirs(repo: Path) -> dict[str, Path]:
    """Every proposal by id, in ``core/proposals/`` and ``domain/proposals/``. A directory there whose name
    is not six digits is an error, and so is one number in two places (two branches, or two owners, may each
    have allocated it): numbers are global."""
    from .util import ScaleError          # lazily: setup.py loads this file alone
    out: dict[str, Path] = {}
    for _owner, root in _proposal_roots(repo):
        for name in _listed(root):
            p = root / name
            if not is_proposal_id(name):
                raise ScaleError(f"{p}: a proposal directory is named by its six-digit number (e.g. 000001; "
                                 "`scale proposal new` allocates the next one); the title stays in proposal.yaml")
            if name in out:
                raise ScaleError(f"proposal {name} exists twice: {out[name]} and {p}; numbers are global across "
                                 "core/ and domain/")
            stated = proposal_yaml_id(p)
            if stated is not None and stated != name:
                raise ScaleError(f"{p}/proposal.yaml: id {stated!r} is not its directory's number {name!r}" + (
                    f"; write it quoted, id: '{name}' (unquoted, YAML reads it as the number {stated})"
                    if isinstance(stated, int) else ""))
            bare = proposal_yaml_unquoted_id(p)
            if bare is not None:
                raise ScaleError(f"{p}/proposal.yaml: id {bare} is unquoted; write it quoted, id: '{name}' (a YAML "
                                 "reader may take unquoted digits for a number)")
            out[name] = p
    return out


_UNQUOTED_ID = re.compile(r"^id:[ \t]*([0-9]+)[ \t]*(?:#.*)?$", re.M)


def proposal_unquoted_id(text: str) -> str | None:
    """The digits of a top-level ``id:`` written unquoted in a proposal.yaml's text (None if quoted or absent).
    The id is always a quoted string: YAML 1.1 reads ``000007`` as the octal 7, and YAML 1.2 reads ``000009``
    as the integer 9, though PyYAML keeps it a string."""
    m = _UNQUOTED_ID.search(text)
    return m.group(1) if m else None


def proposal_yaml_unquoted_id(path: Path) -> str | None:
    """:func:`proposal_unquoted_id` of a proposal directory's proposal.yaml (None without the file)."""
    f = Path(path) / "proposal.yaml"
    return proposal_unquoted_id(f.read_text(encoding="utf-8")) if f.is_file() else None


def proposal_yaml_id(path: Path) -> object:
    """The ``id`` a proposal directory's proposal.yaml states, as loaded (None without the file)."""
    from .util import load_yaml           # lazily: setup.py loads this file alone
    f = Path(path) / "proposal.yaml"
    return (load_yaml(f) or {}).get("id") if f.is_file() else None


def manifest_proposals(manifest: dict | None, where: object = "a schema manifest", own: bool = False) -> list[str]:
    """The proposals a schema manifest says it was built from (``proposals``; with ``own``, a candidate's
    ``proposal`` last), as strings. An id YAML read as a number (an unquoted 000004 is the octal 4) is an
    error, never a guess at the digits it had."""
    from .util import ScaleError
    m = manifest or {}
    names = list(m.get("proposals") or []) + ([m["proposal"]] if own and m.get("proposal") else [])
    bad = [n for n in names if not isinstance(n, str)]
    if bad:
        raise ScaleError(f"{where}: proposals entries {bad} are not strings; quote proposal ids ('000001')")
    return names


def proposal_dir(repo: Path, ref: str) -> Path | None:
    """The proposal a six-digit id names; None when none does."""
    return proposal_dirs(repo).get(str(ref))


def resolve_proposal(repo: Path, ref: str | Path) -> Path:
    """A proposal directory from what a person types: a path to it or its six-digit id. Nothing else is
    guessed: a number with fewer or more digits (``8``, ``0008``) is refused with the id it may mean, because
    it could as well be a typo."""
    from .util import ScaleError
    if not isinstance(ref, Path) and isinstance(ref, int):
        raise ScaleError(f"proposal {ref!r} is a number; a proposal id is a six-digit string such as {int(ref):06d}")
    if Path(ref).is_dir():
        return Path(ref)
    p = proposal_dir(repo, str(ref))
    if p is not None:
        return p
    known = ", ".join(sorted(proposal_dirs(repo)))
    s = str(ref).strip()
    if s.isdigit() and len(s) == 6:
        raise ScaleError(f"no proposal {s} (the next number is {next_proposal_id(repo)}); known: {known}")
    if s.isdigit():
        guess = f"{int(s):06d}" if len(s) < 6 else None
        hint = f" (did you mean {guess}?)" if guess and proposal_dir(repo, guess) else ""
        raise ScaleError(f"proposal {s!r} is ambiguous: a proposal id is exactly six digits{hint}; known: {known}")
    raise ScaleError(f"no proposal {ref}: give its directory or its six-digit id (e.g. 000001); known: {known}")


def proposal_root(repo: Path, owner: str) -> Path:
    """Where an owner's proposals live: ``core/proposals``, or ``domain/proposals`` for the domain's name (catalysis)."""
    from .util import ScaleError
    roots = dict(_proposal_roots(repo))
    if owner not in roots:
        raise ScaleError(f"unknown proposal owner {owner!r}: {', '.join(roots)}")
    return roots[owner]


def next_proposal_id(repo: Path) -> str:
    """The next proposal number: the highest used by any proposal (in core/ or domain/) plus one, six digits."""
    return f"{max([0, *map(int, proposal_dirs(repo))]) + 1:06d}"


# ---------------------------------------------------------------- manifests
def kernel_path(base: Path, ref: str) -> Path:
    """The kernel file a scale-graph manifest in directory ``base`` names (its ``kernel:`` entry ``ref``), lexically
    normalized and built on ``base`` as given (a repository-relative base gives a repository-relative path). When the
    base passes through a symbolic link, lexical normalization no longer says where ``..`` leads; the path is then the
    file the system reaches (absolute), as when the reference is opened as written."""
    ref = str(ref)
    out = Path(os.path.normpath(Path(base) / ref))
    reached = os.path.realpath(Path(os.path.realpath(base)) / ref)   # `..` after a link leads to the link target's parent
    return out if os.path.realpath(out) == reached else Path(reached)


def manifest_kernel(manifest: Path, ref: str | None = None) -> Path:
    """The kernel file a scale-graph manifest names (:func:`kernel_path`); ``ref`` when the manifest is given
    as data, else its ``kernel:`` as the file says."""
    if ref is None:
        from .util import load_yaml       # lazily: setup.py loads this file alone
        ref = str((load_yaml(manifest) or {}).get("kernel") or "")
    return kernel_path(Path(manifest).parent, ref)


def manifest_layer(manifest: Path) -> str:
    """The name of the domain a scale-graph manifest given by its path belongs to (``catalysis``): the ``domain/``
    folder holding it whose DOMAIN.yaml declares the domain (:func:`domain_name`; the head, a frozen version, a
    release; a candidate's ``domain/`` holds no DOMAIN.yaml, so the domain around its proposal names it). The file's
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
