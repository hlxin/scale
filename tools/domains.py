"""The catalysis domain and the science kernel as declared, checked units (``scale domains list | check``).

The catalysis domain is the folder ``domain/`` with a ``DOMAIN.yaml`` that says what it is (its name,
``domain: catalysis``, its status, the schema version, its maintainers) and where its parts are; the science
kernel declares itself in ``core/CORE.yaml``. There is one domain beside the core for now (a second domain would
revisit the layout); the tests scaffold a synthetic domain in temporary repositories (:func:`new_domain`) to
exercise the rules on another one.

The specification has two layers: the science kernel (``core/graph/kernel.yaml``) and the domain. The domain is
self-contained: its graph schema manifest (DOMAIN.yaml ``graph.manifest``, ``graph/scale-catal.yaml``) assembles
the kernel with the domain's own files, listed under its ``domains:`` key; the file named after the domain
(``domain: <name>``, for catalysis ``graph/catalysis.yaml`` with one vocabulary and one checklist) is required,
and documents follow its checklist by the domain's name (``follows_domains``, ``--domain``). Frozen versions
sit in ``graph/frozen/`` beside the manifest once a schema change has been merged; there is no repository-wide
composition.

The schema has **one version**, the manifest's ``version``, for the kernel and the domain together. The kernel
and the domain files carry none; ``CORE.yaml`` and ``DOMAIN.yaml`` (``version``), ``scale-release.yaml``
(``schema_version``) and the kernel-only example manifest state it, and ``check`` requires them to agree with the
manifest (``scale schema bump`` raises them all together).

``check`` makes these declarations trustworthy: every declared path exists, the versions agree, the domain's
manifest uses the core's kernel and lists only files inside ``domain/``, among them the one named after the
domain, and loads, the domain redeclares no name the core already declares, holds no copy of a core file, is the
``domain_profiles`` of ``scale-release.yaml`` unless experimental, CODEOWNERS routes ``/domain/`` to its
maintainers, and the example documents validate against the schema they pin. :func:`new_domain` (used by the
tests) scaffolds an experimental domain in a repository that has none, from the test fixture
``tools/tests/fixtures/domain-template/``, that passes ``check``.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
from pathlib import Path

from . import codeowners, layout
from .versions import parse_version
from .util import ScaleError, load_doc, load_yaml, sha256_file

NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
GITHUB = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
# the code owner of a declaration, as CODEOWNERS names it: a GitHub team (@org/team) or, in a personal repository, a
# user (@hlxin)
TEAM = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9_.-]*(/[A-Za-z0-9][A-Za-z0-9_.-]*)?$")
ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = ("experimental", "stable", "deprecated")
MAINTAINER_ROLES = ("steward", "maintainer")
PROMOTION = {"stewards": 2, "questions": 3}      # stewardship targets of a stable domain (warnings for the founding one)

# key -> (required, types). "stable": required once the domain is stable.
_STR, _LIST, _DICT = (str,), (list,), (dict,)
DOMAIN_KEYS: dict[str, tuple[bool | str, tuple]] = {
    "domain": (True, _STR), "title": (True, _STR), "status": (True, _STR), "founding": (False, (bool,)),
    "version": (True, _STR), "depends_on": (False, _LIST),
    "alternative_to": (False, (str, type(None))), "summary": (True, _STR), "scope": (True, _STR),
    "maintainers": (True, _DICT), "review_areas": (True, _LIST), "graph": (False, _DICT),
    "examples": (True, _LIST), "example_documents": (True, _DICT), "competency": (True, _STR), "tests": (True, _STR),
    "docs": (False, _STR), "roadmap": (True, _STR),
    "decision_record": ("stable", _STR), "deprecation": (False, _STR), "contributors": (True, _LIST),
    "mappings": (False, _STR),
}
CORE_KEYS: dict[str, tuple[bool | str, tuple]] = {
    "core": (True, _STR), "title": (True, _STR), "summary": (False, _STR), "version": (True, _STR),
    "kernel": (True, _STR), "scope": (True, _STR),
    "compatibility": (True, _STR), "maintainers": (True, _DICT), "review_areas": (True, _LIST), "examples": (True, _LIST),
    "example_documents": (False, _DICT), "tests": (True, _STR), "docs": (False, _STR),
    "contributors": (True, _LIST), "mappings": (False, _STR),
}
# directories the tools read by convention (layout): a DOMAIN.yaml naming another place would be ignored
CONVENTIONS = {"competency": layout.DOMAIN_COMPETENCY, "tests": "tests",
               "mappings": layout.DOMAIN_MAPPINGS.split("/", 1)[1]}
CORE_MAPPINGS = layout.KERNEL_MAPPINGS.split("/", 1)[1]       # CORE.yaml mappings, relative to core/


class Problems:
    def __init__(self):
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append({"where": where, "message": message})

    def warn(self, where: str, message: str) -> None:
        self.warnings.append({"where": where, "message": message})


# ---------------------------------------------------------------- reading

def is_checkout(repo: Path) -> bool:
    """A repository checkout root, not the data bundled in an installed package (which has no .github/)."""
    return layout.is_root(Path(repo)) and (Path(repo) / ".github").is_dir()


def load_core(repo: Path) -> dict:
    p = Path(repo) / layout.CORE_MANIFEST
    if not p.is_file():
        raise ScaleError(f"no core declaration: {p} is missing")
    return load_yaml(p) or {}


def schema_version(repo: Path) -> str | None:
    """The schema's one version: the released domain's manifest ``version`` (None in a repository without a
    released domain, such as the tests' mini repositories before new_domain())."""
    mans = layout.graph_manifests(Path(repo), experimental=True)
    versions = sorted({str((load_yaml(m) or {}).get("version")) for m in mans.values() if m.is_file()})
    return versions[0] if len(versions) == 1 else None


def core_version(repo: Path, core: dict | None = None) -> str:
    """The version CORE.yaml states (the schema's one version, which ``check`` requires it to be)."""
    core = core if core is not None else load_core(repo)
    k = Path(repo) / layout.CORE / str(core.get("kernel"))
    if not k.is_file():
        raise ScaleError(f"{layout.CORE_MANIFEST}: kernel {core.get('kernel')!r} does not exist")
    return str(core.get("version"))


def load_domains(repo: Path) -> dict[str, dict]:
    """The domain's DOMAIN.yaml by its name (``{"catalysis": {...}}``; {} for ``domain/`` without one, keyed by
    the folder's name; nothing when there is no ``domain/``)."""
    out = {}
    for name, d in layout.domain_layers(repo).items():
        m = d / layout.DOMAIN_MANIFEST
        out[name] = (load_yaml(m) or {}) if m.is_file() else {}
    return out


def manifest_path(name: str | None = None) -> str:
    """The domain's declaration, repository-relative (``domain/DOMAIN.yaml``; one domain, whatever its name)."""
    return layout.DOMAIN_DECLARATION


def graph_files(repo: Path, name: str, m: dict) -> list[str]:
    """The domain's scale-catal files, relative to the domain directory: the entries of its manifest
    (DOMAIN.yaml ``graph.manifest``) that lie inside the domain (``check`` reports the others).
    A domain's manifest lists them under ``domains``; the keys of frozen forms (``modules``, ``extensions``) and of
    retired profile files (``profiles``) are read too, so that ``check`` sees and refuses them."""
    import os
    from .schema_change import PACKAGE_KEYS
    base = Path(repo) / layout.DOMAIN
    rel = (m.get("graph") or {}).get("manifest")
    man = base / rel if isinstance(rel, str) and rel else None
    if man is None or not man.is_file():
        return []
    g = load_yaml(man) or {}
    out = []
    for key in PACKAGE_KEYS:
        for x in g.get(key) or [] if isinstance(g.get(key), list) else []:
            p = Path(os.path.normpath(man.parent / str(x)))
            try:
                out.append(p.relative_to(Path(os.path.normpath(base))).as_posix())
            except ValueError:
                continue                                   # outside the domain: a dependency's file, or reported
    return list(dict.fromkeys(out))


def stewards(m: dict) -> list[dict]:
    """The stewards who are people (a placeholder entry is not one)."""
    return [p for p in (m.get("maintainers") or {}).get("people") or []
            if "steward" in (p.get("roles") or []) and not p.get("placeholder")]


def list_domains(repo: Path) -> list[dict]:
    rel = load_yaml(Path(repo) / layout.RELEASE_MANIFEST)
    listed = set(rel.get("domain_profiles") or [])
    rows = []
    for name, m in load_domains(repo).items():
        mt = m.get("maintainers") or {}
        rows.append({"domain": name, "title": m.get("title"), "status": m.get("status"), "version": m.get("version"),
                     "founding": bool(m.get("founding")), "team": mt.get("team"),
                     "stewards": [p.get("github") or p.get("name") for p in stewards(m)],
                     "in_release_manifest": manifest_path(name) in listed, "path": layout.DOMAIN})
    return rows


# ---------------------------------------------------------------- shape

def _check_keys(m: dict, spec: dict, where: str, pb: Problems, stable: bool = False) -> None:
    for k, (req, types) in spec.items():
        if k not in m:
            if req is True or (req == "stable" and stable):
                pb.error(where, f"missing required key {k!r}")
        elif not isinstance(m[k], types) or (types is _STR and not str(m[k]).strip()):
            pb.error(where, f"{k} must be {' or '.join('null' if t is type(None) else t.__name__ for t in types)}"
                            + (" (non-empty)" if types is _STR else ""))
    for k in m:
        if k not in spec:
            pb.error(where, f"unknown key {k!r} (known: {', '.join(spec)})")


def _check_people(m: dict, where: str, pb: Problems) -> None:
    mt = m.get("maintainers")
    if isinstance(mt, dict):
        if not TEAM.match(str(mt.get("team") or "")):
            pb.error(where, f"maintainers.team must be a code owner as CODEOWNERS names it ('@org/team' or '@user'), "
                            f"got {mt.get('team')!r}")
        people = mt.get("people")
        if not isinstance(people, list) or not people:
            pb.error(where, "maintainers.people must list at least one person")
            people = []
        for i, p in enumerate(people):
            w = f"maintainers.people[{i}]"
            if not isinstance(p, dict):
                pb.error(where, f"{w} must be a mapping")
                continue
            for k in p:
                if k not in ("name", "github", "orcid", "since", "roles", "placeholder"):
                    pb.error(where, f"{w}: unknown key {k!r}")
            if p.get("placeholder") not in (None, True):
                pb.error(where, f"{w}: placeholder is true or absent")
            if not p.get("name"):
                pb.error(where, f"{w}: name is required")
            if not GITHUB.match(str(p.get("github") or "")):
                pb.error(where, f"{w}: github must be a GitHub handle, got {p.get('github')!r}")
            if p.get("orcid") and not ORCID.match(str(p["orcid"])):
                pb.error(where, f"{w}: orcid {p['orcid']!r} is not an ORCID iD (0000-0000-0000-0000)")
            if not (p.get("placeholder") and "since" not in p) and not DATE.match(str(p.get("since") or "")):
                pb.error(where, f"{w}: since must be a date 'YYYY-MM-DD'")
            roles = p.get("roles")
            if not isinstance(roles, list) or not roles or any(r not in MAINTAINER_ROLES for r in roles):
                pb.error(where, f"{w}: roles must be a non-empty list of {MAINTAINER_ROLES}")
        if people and not stewards(m):
            pb.error(where, "no maintainer has the role 'steward'")
    contributors = m.get("contributors")
    for i, c in enumerate(contributors if isinstance(contributors, list) else []):
        w = f"contributors[{i}]"
        if not isinstance(c, dict) or not c.get("name"):
            pb.error(where, f"{w} needs a name")
            continue
        for k in c:
            if k not in ("name", "github", "orcid", "roles"):
                pb.error(where, f"{w}: unknown key {k!r}")
        if c.get("github") and not GITHUB.match(str(c["github"])):
            pb.error(where, f"{w}: github {c['github']!r} is not a GitHub handle")
        if c.get("orcid") and not ORCID.match(str(c["orcid"])):
            pb.error(where, f"{w}: orcid {c['orcid']!r} is not an ORCID iD")
        if not isinstance(c.get("roles"), list) or not c["roles"] or not all(isinstance(r, str) and r for r in c["roles"]):
            pb.error(where, f"{w}: roles must be a non-empty list of words")


def _inside(base: Path, rel: str, where: str, what: str, pb: Problems, kind: str = "any") -> list[Path]:
    """Resolve a declared path (a glob is allowed) below ``base``; report what is missing or outside."""
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        pb.error(where, f"{what}: {rel!r} must be a relative path inside {base.name}/")
        return []
    hits = sorted(base.glob(rel)) if any(c in rel for c in "*?[") else [base / rel]
    hits = [h for h in hits if h.exists()]
    if not hits:
        pb.error(where, f"{what}: {rel} does not exist")
    for h in hits:
        if kind == "dir" and not h.is_dir():
            pb.error(where, f"{what}: {rel} is not a directory")
        if kind == "file" and not h.is_file():
            pb.error(where, f"{what}: {rel} is not a file")
    return hits


# ---------------------------------------------------------------- identifiers

def declarations(doc: dict) -> list[tuple[str, str]]:
    """What a scale-catal file declares: its own name, labels, edge types, and properties per label
    (on its labels, and those it adds to other labels, bridges included). Extending is not declaring:
    ``is_a``, ``extends`` and ``adds_properties`` with a new key."""
    out = []
    for key in ("domain", "module", "extension"):
        if isinstance(doc.get(key), str):
            out.append(("scale-catal file name", doc[key]))
    if isinstance(doc.get("kernel"), str):
        out.append(("scale-catal file name", "kernel"))
    for lab, nd in (doc.get("nodes") or {}).items():
        out.append(("label", lab))
        out += [("property", f"{lab}.{k}") for k in ((nd or {}).get("properties") or {})]
    blocks = [doc] + [br for br in (doc.get("bridges") or {}).values() if isinstance(br, dict)]
    for b in blocks:
        out += [("edge type", e) for e in (b.get("edges") or {})]
        for lab, props in (b.get("adds_properties") or {}).items():
            out += [("property", f"{lab}.{k}") for k in (props or {})]
    return out


def identifier_index(repo: Path, core: dict, domains: dict[str, dict]) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """One name index over the kernel and the domain's graph files: (kind, name) -> [(owner, file)]."""
    index: dict[tuple[str, str], list[tuple[str, str]]] = {}
    files = [("core", f"{layout.CORE}/{core.get('kernel')}")]
    files += [(name, f"{layout.DOMAIN}/{f}") for name, m in domains.items() for f in graph_files(repo, name, m)]
    for owner, rel in files:
        p = Path(repo) / rel
        if not p.is_file():
            continue                                       # reported as a missing path
        for decl in declarations(load_yaml(p) or {}):
            index.setdefault(decl, []).append((owner, rel))
    return index


# ---------------------------------------------------------------- check

def check(repo: Path, only: list[str] | None = None, examples: bool = True) -> dict:
    """Check core/CORE.yaml and domain/DOMAIN.yaml (``only``: names of the domain to check; the domain's checks are
    left out when its name is not among them, the core's and the release manifest's always run). Errors fail;
    warnings inform."""
    repo = Path(repo).resolve()
    if not is_checkout(repo):
        raise ScaleError(f"scale domains check runs at the root of a repository checkout (scale-release.yaml, "
                         f"releases/ and .github/); {repo} is not one")
    pb = Problems()
    core = load_core(repo)
    cw = layout.CORE_MANIFEST
    _check_keys(core, CORE_KEYS, cw, pb)
    _check_people(core, cw, pb)
    try:
        kver = core_version(repo, core)
        parse_version(kver)
    except ScaleError as exc:
        pb.error(cw, str(exc))
        kver = None
    core_dir = repo / layout.CORE
    kernel_rel = f"{layout.CORE}/{core.get('kernel')}"
    if (repo / kernel_rel).is_file() and not isinstance((load_yaml(repo / kernel_rel) or {}).get("kernel"), str):
        pb.error(cw, f"kernel: {core.get('kernel')} is not a scale-catal kernel file (no `kernel:` key)")
    for rel in core.get("examples") or []:
        _inside(core_dir, rel, cw, "examples", pb, "dir")
    _check_dir_with(core_dir, core.get("tests"), "test_*.py", cw, "tests", pb)
    if core.get("docs"):
        _inside(core_dir, core["docs"], cw, "docs", pb)

    domains = load_domains(repo)
    rel_manifest = load_yaml(repo / layout.RELEASE_MANIFEST)
    if kernel_rel != layout.KERNEL:
        pb.error(cw, f"kernel is {core.get('kernel')!r}; the tools and every domain manifest read {layout.KERNEL}")
    index = identifier_index(repo, core, domains)
    graph_names = {n for kind, n in index if kind.startswith("scale-catal")}

    # identifiers: one index over the kernel and the domain; the incumbent, the core, is named first and the
    # error goes to the later owner (sorted() is stable, so the domain's own files keep the index order)
    for (kind, ident), owners in index.items():
        files = sorted(dict.fromkeys(owners), key=lambda o: o[0] != "core")
        if len(files) > 1:
            first = files[0]
            for owner, rel in files[1:]:
                where = manifest_path(owner) if owner != "core" else cw
                pb.error(where, f"{kind} {ident} is declared by {first[0]} ({first[1]}) and again by {owner} ({rel}); "
                                "extend it (is_a, extends, adds_properties with a new key) instead of redeclaring it")

    # the kernel (head and frozen versions), the core's examples and its declaration
    core_digests = {sha256_file(p) for p in (core_dir / "graph").rglob("*") if p.is_file() and p.stat().st_size} | \
                   {sha256_file(p) for p in (core_dir / "examples").rglob("*") if p.is_file() and p.stat().st_size}
    if (repo / cw).is_file():
        core_digests.add(sha256_file(repo / cw))

    policy_areas = _policy_areas(repo, pb)
    for a in core.get("review_areas") or []:
        if policy_areas is not None and a not in policy_areas:
            pb.warn(cw, f"review area {a!r} is listed by nobody in {layout.REVIEW_POLICY}")

    rules = codeowners.load(repo)
    if rules is None:
        pb.error(layout.CODEOWNERS, f"missing: the domain needs a {codeowners.domain_line()} line naming its team")
    else:
        team = (core.get("maintainers") or {}).get("team")
        if team and team not in codeowners.owners_for(rules, layout.CORE_MANIFEST):
            pb.error(layout.CODEOWNERS, f"{layout.CORE_MANIFEST} is not owned by the core team {team}")
        _reviewers_routed(repo, rules, pb)

    # scale-release.yaml: the domain unless experimental, and the core (no repository-wide graph manifest)
    listed = rel_manifest.get("domain_profiles")
    if not isinstance(listed, list):
        pb.error(layout.RELEASE_MANIFEST, f"domain_profiles must list {layout.DOMAIN_DECLARATION} unless the domain "
                                          "is experimental")
        listed = []
    want = sorted(manifest_path(n) for n, m in domains.items() if m and m.get("status") != "experimental")
    if sorted(listed) != want or len(listed) != len(set(listed)):
        pb.error(layout.RELEASE_MANIFEST, f"domain_profiles is {listed}; the non-experimental domains are {want}")
    if rel_manifest.get("core") != layout.CORE_MANIFEST:
        pb.error(layout.RELEASE_MANIFEST, f"core must be {layout.CORE_MANIFEST}")
    if "graph" in rel_manifest:
        pb.error(layout.RELEASE_MANIFEST, "graph: there is no repository-wide scale-catal composition; each domain "
                                          "declares its schema manifest in DOMAIN.yaml graph.manifest")
    # one version: the manifest's, stated alike by CORE.yaml, DOMAIN.yaml, scale-release.yaml and the kernel-only
    # example manifest (`scale schema bump` raises them together)
    sv = schema_version(repo)
    if sv is not None:
        stated = [(cw, "version", core.get("version")), (layout.RELEASE_MANIFEST, "schema_version", rel_manifest.get("schema_version"))]
        ko = repo / layout.KERNEL_ONLY_MANIFEST
        if ko.is_file():
            stated.append((layout.KERNEL_ONLY_MANIFEST, "version", (load_yaml(ko) or {}).get("version")))
        stated += [(manifest_path(n), "version", m.get("version")) for n, m in domains.items() if m]
        for where, key, v in stated:
            if str(v) != sv:
                pb.error(where, f"{key} is {v!r}; the schema has one version, the manifest's {sv} (kernel and domain "
                                "together): state it here")
        # and one status: the kernel and the kernel-only manifest say what the head manifest says (`candidate`; a
        # release records it as it is). A domain
        # whose manifest is still experimental (one made from the template) does not speak for the kernel.
        heads = layout.graph_manifests(repo)
        hst = (load_yaml(next(iter(heads.values()))) or {}).get("status") \
            if len(heads) == 1 and next(iter(heads.values())).is_file() else None
        if hst not in (None, "experimental"):
            for rel in (layout.KERNEL, layout.KERNEL_ONLY_MANIFEST):
                if (repo / rel).is_file():
                    st = (load_yaml(repo / rel) or {}).get("status")
                    if st != hst:
                        pb.error(rel, f"status is {st!r}; the schema's status is its manifest's, {hst!r}: state it here")

    cache: dict = {}
    ex = core.get("example_documents") or {}
    for k in ex:
        if k != "graph":
            pb.error(cw, f"example_documents: unknown key {k!r} (graph)")
    for p in [p for rel in ex.get("graph") or [] for p in _inside(core_dir, rel, cw, "example_documents.graph", pb, "file")]:
        for msg in (_validate_kernel_doc(repo, p, cache) if examples else []):
            pb.error(cw, f"example {p.relative_to(core_dir).as_posix()}: {msg}")
    for name, m in domains.items():
        if only and name not in only:
            continue
        _check_domain(repo, name, m, domains, core, kver, graph_names, core_digests, policy_areas, rules,
                      examples, cache, pb)
    # the mappings of SCALE's terms to ontology terms (core/mappings/, domain/mappings/): declared where the tools
    # read them, and every mapping on a term of the head schema and of a registered ontology (docs/mappings.md)
    if core.get("mappings") is not None and core["mappings"] != CORE_MAPPINGS:
        pb.error(cw, f"mappings must be {CORE_MAPPINGS!r}: the tools read {layout.KERNEL_MAPPINGS}")
    from . import mappings
    if (mappings.declared(repo) or (repo / layout.ONTOLOGY_REGISTRY).is_file()) and layout.graph_manifests(repo):
        try:
            res = mappings.check(repo)
        except ScaleError as exc:
            res = {"errors": [{"where": layout.ONTOLOGY_REGISTRY, "message": str(exc)}], "warnings": []}
        for e in res["errors"]:
            pb.error(e["where"], e["message"])
        for w in res["warnings"]:
            pb.warn(w["where"], w["message"])
    return {"ok": not pb.errors, "core": {"name": core.get("core"), "version": kver,
                                          "team": (core.get("maintainers") or {}).get("team")},
            "domains": [{"domain": n, "status": m.get("status"), "version": m.get("version")} for n, m in domains.items()
                        if not only or n in only],
            "errors": pb.errors, "warnings": pb.warnings}


def _check_dir_with(base: Path, rel, pattern: str, where: str, what: str, pb: Problems) -> list[Path]:
    hits = _inside(base, str(rel), where, what, pb, "dir") if rel else []
    found = sorted(p for h in hits for p in h.glob(pattern))
    if hits and not found:
        pb.error(where, f"{what}: {rel}/ has no {pattern}")
    return found


def _reviewers_routed(repo: Path, rules: list, pb: Problems) -> None:
    """Every reviewer of the review policy is named on every line of CODEOWNERS, so that GitHub asks each of them to
    review every pull request (one approval is enough; the reviewers workflow withdraws the other requests)."""
    from .policy import load_policy, reviewers
    try:
        people = reviewers(load_policy(repo))
    except ScaleError:
        return                                  # reported by _policy_areas
    for m in people:
        handle = f"@{m.get('github')}".lower()
        for r in rules:
            if handle not in {o.lower() for o in r.owners}:
                pb.error(layout.CODEOWNERS, f"line {r.line} ({r.pattern}) does not name the reviewer {handle} of "
                                            f"{layout.REVIEW_POLICY}: GitHub would not ask them to review")


def _policy_areas(repo: Path, pb: Problems) -> set[str] | None:
    """The review areas people in the review policy list, or None when the policy's reviewers review every
    area (the policy has one reviewer group for the core and every domain)."""
    from .policy import load_policy, reviewers
    try:
        pol = load_policy(repo)
    except ScaleError as exc:
        pb.error(layout.REVIEW_POLICY, str(exc))
        return None
    people = reviewers(pol)
    if not any("areas" in m for m in people):
        return None
    return {a for p in people for a in p.get("areas") or []}


def _check_domain(repo, name, m, domains, core, kver, graph_names, core_digests, policy_areas, rules,
                  examples, cache, pb: Problems) -> None:
    where = manifest_path(name)
    base = repo / layout.DOMAIN
    if not m:
        pb.error(layout.DOMAIN, f"no {layout.DOMAIN_MANIFEST}: {layout.DOMAIN}/ declares the domain it holds "
                                f"({layout.DOMAIN_DECLARATION}, whose `domain:` names it)")
        return
    status = m.get("status")
    _check_keys(m, DOMAIN_KEYS, where, pb, stable=status in ("stable", "deprecated"))
    if not isinstance(m.get("domain"), str) or not NAME.match(m["domain"]):
        pb.error(where, f"domain is {m.get('domain')!r}: the domain's name is lowercase letters, digits and single "
                        "hyphens (catalysis)")
    if status not in STATUSES:
        pb.error(where, f"status must be one of {STATUSES}")
    try:
        parse_version(str(m.get("version")))
    except ScaleError:
        pb.error(where, f"version {m.get('version')!r} is not a semantic version")
    if status == "deprecated" and not m.get("deprecation"):
        pb.error(where, "a deprecated domain says why and what replaces it in `deprecation`")
    _check_people(m, where, pb)
    for k, conv in CONVENTIONS.items():
        if k in m and m[k] != conv:
            pb.error(where, f"{k} must be {conv!r}: the tools read {layout.DOMAIN}/{conv}")

    # dependencies and alternatives: there is no other domain to depend on yet; the keys stay in DOMAIN.yaml,
    # empty, and an alternative may only name a scale-catal file
    for i, dep in enumerate(m.get("depends_on") or []):
        what = dep.get("domain") if isinstance(dep, dict) else dep
        pb.error(where, f"depends_on[{i}] names {what!r}: catalysis is the only domain beside the core, so "
                        "depends_on stays empty")
    alt = m.get("alternative_to")
    if alt and alt not in graph_names:
        pb.error(where, f"alternative_to names {alt!r}, which is not the name of a scale-catal file")

    # declared paths
    gfiles = graph_files(repo, name, m)
    g = m.get("graph") or {}
    for k in g:
        if k != "manifest":
            pb.error(where, f"graph: unknown key {k!r}: graph takes only manifest (the domain's schema manifest, which "
                            "lists the domain's files)")
    for f in gfiles:
        _inside(base, f, where, "graph", pb, "file")
    manifest = None
    if "graph" in m and not g.get("manifest"):          # a domain without scale-catal files has no `graph:`
        pb.error(where, f"graph.manifest is required: the domain's schema manifest ({layout.DOMAIN_GRAPH_MANIFEST}) "
                        "assembles the science kernel with the domain's files")
    elif g:
        hits = _inside(base, str(g["manifest"]), where, "graph.manifest", pb, "file")
        manifest = hits[0] if hits and hits[0].is_file() else None
    for rel in m.get("examples") or []:
        _inside(base, rel, where, "examples", pb, "dir")
    ex = m.get("example_documents") or {}
    for k in ex:
        if k != "graph":
            pb.error(where, f"example_documents: unknown key {k!r} (graph)")
    graph_docs = [p for rel in ex.get("graph") or [] for p in _inside(base, rel, where, "example_documents.graph", pb, "file")]
    questions = _check_dir_with(base, m.get("competency"), "*.yaml", where, "competency", pb)
    _check_dir_with(base, m.get("tests"), "test_*.py", where, "tests", pb)
    if m.get("docs"):
        _inside(base, m["docs"], where, "docs", pb, "dir")
    if m.get("roadmap"):
        _inside(base, m["roadmap"], where, "roadmap", pb, "file")
    decision_ok = False
    if m.get("decision_record"):
        dr = str(m["decision_record"])           # repository-relative: decision records are global
        decision_ok = dr.startswith(f"{layout.DECISIONS}/") and dr.endswith(".md") and (repo / dr).is_file()
        if not decision_ok:
            msg = f"decision_record {dr} is not an existing {layout.DECISIONS}/NNNN-*.md (repository-relative)"
            (pb.warn if m.get("founding") else pb.error)(where, msg)
    for i, q in enumerate(questions):
        doc = load_yaml(q)
        if not isinstance(doc, dict) or not doc.get("question"):
            pb.error(where, f"competency/{q.name}: a competency question states its question (`question`)")

    # scale-catal files: what each names itself, what it imports, and the domain's own manifest
    visible = {n for f in gfiles if (base / f).is_file()
               for kind, n in declarations(load_yaml(base / f) or {}) if kind.startswith("scale-catal")} | {"kernel"}
    for f in gfiles:
        p = base / f
        if not p.is_file():
            continue
        doc = load_yaml(p) or {}
        if not isinstance(doc.get("domain"), str):
            pb.error(where, f"{f}: a domain file names itself with `domain:`")
        if "kernel" in doc:
            pb.error(where, f"{f} is a kernel file; the kernel belongs to the core")
        for imp in doc.get("imports") or []:
            target = imp.get("module") or imp.get("extension") or imp.get("domain")
            if target not in visible:
                pb.error(where, f"{f} imports {target!r}, which is neither the kernel nor one of the domain's own files")
    domain_spec = _check_manifest(repo, name, manifest, pb, where) if manifest else None

    # no copies of core files anywhere in the domain (its frozen versions included: the frozen kernels live
    # in core/graph/frozen/)
    for p in _files_below(repo, [base]):
        rel = p.relative_to(repo).as_posix()
        if p.suffix in (".yaml", ".yml") and re.search(r"^kernel:\s*['\"]?scale-kernel", p.read_text(encoding="utf-8",
                                                                                                          errors="ignore"), re.M):
            pb.error(where, f"{rel} is a copy of a scale-catal kernel; domains use the core's kernel "
                            f"({layout.KERNEL}, the kernels of frozen versions in {layout.KERNEL_FROZEN}/)")
        elif p.stat().st_size and sha256_file(p) in core_digests:
            pb.error(where, f"{rel} is byte-identical to a core file; refer to the core instead of copying it")

    # CODEOWNERS
    team = (m.get("maintainers") or {}).get("team")
    if rules is not None and team:
        line = codeowners.domain_line(name)
        if not any(team in r.owners for r in codeowners.lines_for(rules, line)):
            pb.error(layout.CODEOWNERS, f"no {line} line naming {team}")
        elif team not in codeowners.owners_for(rules, layout.DOMAIN_DECLARATION):
            pb.error(layout.CODEOWNERS, f"a later line overrides {line}: {team} does not own {layout.DOMAIN}/")

    # review areas (F2: warn when nobody in the review policy can review them)
    for a in m.get("review_areas") or []:
        if not isinstance(a, str):
            pb.error(where, "review_areas must be words")
        elif policy_areas is not None and a not in policy_areas:
            pb.warn(where, f"review area {a!r} is listed by nobody in {layout.REVIEW_POLICY}; its changes have no area reviewer")

    # example documents validate
    if examples:
        for p in graph_docs:
            for msg in _validate_graph_doc(repo, p, manifest if domain_spec is not None else None, cache):
                pb.error(where, f"example {p.relative_to(base).as_posix()}: {msg}")

    # competency questions: only those whose plan runs and meets its expectation count (a stewardship target)
    answered = 0
    if domain_spec is not None:
        from .competency import run_question
        for q in questions:
            r = run_question(repo, name, q, m, cache)
            if r["ok"]:
                answered += 1
            elif not r["stub"] or r["problems"]:
                pb.warn(where, f"competency/{q.name} does not answer as expected: {'; '.join(r['problems'])} "
                               "(scale domains cq)")

    # stewardship targets, checked for stable domains (warnings for the founding one, catalysis)
    if status == "stable":
        report = pb.warn if m.get("founding") else pb.error
        if len(stewards(m)) < PROMOTION["stewards"]:
            report(where, f"stewardship target: at least {PROMOTION['stewards']} maintainers with role steward "
                          f"(has {len(stewards(m))})")
        if answered < PROMOTION["questions"]:
            report(where, f"stewardship target: at least {PROMOTION['questions']} competency questions that "
                          f"answer as expected (has {answered}; scale domains cq)")
        if not graph_docs:
            report(where, "stewardship target: example documents that validate (none declared)")
        if not m.get("decision_record"):
            report(where, "stewardship target: a decision record (decision_record)")


def _files_below(repo: Path, roots: list[Path]) -> list[Path]:
    """Files under the given paths, minus local material and caches (G4)."""
    out = []
    for r in roots:
        for p in ([r] if r.is_file() else sorted(r.rglob("*")) if r.is_dir() else []):
            parts = p.relative_to(repo).parts
            if p.is_file() and not layout._is_local(parts) and "__pycache__" not in parts and p.name != ".DS_Store":
                out.append(p)
    return out


def _check_manifest(repo: Path, name: str, manifest: Path, pb: Problems, where: str) -> dict | None:
    """The domain's schema manifest uses the core's kernel and lists, under ``domains``, files inside ``domain/``
    (the one named after the domain required); it loads. Returns the assembled schema."""
    import os
    from . import pgraph
    from .pgraph_schema import is_manifest
    rel_of = lambda p: Path(os.path.normpath(p)).relative_to(Path(os.path.normpath(repo))).as_posix()   # noqa: E731
    man = load_yaml(manifest) or {}
    mrel = rel_of(manifest)
    if man.get("schema") != "scale-catal" or not is_manifest(man) or not isinstance(man.get("domains"), list):
        pb.error(where, f"{mrel} is not a domain's scale-catal manifest (schema: scale-catal, kernel, domains)")
        return None
    for key in ("modules", "extensions"):
        if key in man:
            pb.error(where, f"{mrel}: `{key}:` is a form of frozen versions; a domain's manifest lists its files under "
                            "`domains:`")
    if "profiles" in man:
        pb.error(where, f"{mrel}: `profiles:` lists profile files, which are retired by design; the domain file carries "
                        "its checklist")
    try:
        kernel = rel_of(layout.manifest_kernel(manifest, str(man["kernel"])))
        listed = {rel_of(manifest.parent / str(x)) for key in ("modules", "extensions", "profiles", "domains")
                  for x in man.get(key) or []}
    except ValueError:
        pb.error(where, f"{mrel} names a file outside the repository")
        return None
    if kernel != layout.KERNEL:
        pb.error(where, f"{mrel}: kernel resolves to {kernel}; a domain uses the core's kernel {layout.KERNEL}")
    own = sorted(x for x in listed if x.startswith(f"{layout.DOMAIN}/"))
    stray = sorted(listed - set(own))
    if stray:
        pb.error(where, f"{mrel} lists {stray}, which lie outside {layout.DOMAIN}/")
    if not any((load_yaml(repo / x) or {}).get("domain") == name for x in own if (repo / x).is_file()):
        pb.error(where, f"{mrel} lists no file named after the domain (`domain: {name}`, e.g. graph/{name}.yaml): "
                        "the domain's own file is required")
    try:
        return pgraph.load_spec(manifest)
    except (ScaleError, OSError) as exc:
        pb.error(where, f"{mrel} does not load: {exc}")
        return None


def _validate_kernel_doc(repo: Path, p: Path, cache: dict) -> list[str]:
    """Validate one of the core's example documents against the kernel alone, at the version it pins
    (:func:`pgraph.kernel_only_spec`: the kernel-only example manifest at the head, a frozen kernel before)."""
    from . import pgraph
    try:
        doc = load_doc(p)
        version = (doc.get("graph") or {}).get("schema_version")
        key = ("kernel-only", str(version))
        if key not in cache:
            cache[key] = pgraph.kernel_only_spec(repo, version)
        rep = pgraph.validate(doc, cache[key])
    except (ScaleError, OSError, ValueError, KeyError) as exc:
        return [f"cannot be validated: {exc}"]
    return [f"{e['record']}: {e['message']}" for e in rep.errors[:3]] + \
           ([f"… {len(rep.errors) - 3} more errors"] if len(rep.errors) > 3 else [])


def _validate_graph_doc(repo: Path, p: Path, manifest: Path | None, cache: dict) -> list[str]:
    """Validate a graph document against the version it pins of ``manifest`` (a domain's own schema, or
    the kernel-only manifest for the core's examples); without one, against the released domain's."""
    from . import pgraph
    try:
        doc = load_doc(p)
        version = (doc.get("graph") or {}).get("schema_version")
        spec_path = pgraph.pinned(manifest, version, doc) if manifest is not None else pgraph.spec_for(repo, version, doc=doc)
        key = ("graph", str(spec_path))
        if key not in cache:
            cache[key] = pgraph.load_spec(spec_path)
        rep = pgraph.validate(doc, cache[key])
    except (ScaleError, OSError, ValueError, KeyError) as exc:
        return [f"cannot be validated: {exc}"]
    return [f"{e['record']}: {e['message']}" for e in rep.errors[:3]] + \
           ([f"… {len(rep.errors) - 3} more errors"] if len(rep.errors) > 3 else [])


# ---------------------------------------------------------------- new

def new_domain(repo: Path, name: str, title: str, steward_name: str, steward_github: str, team: str | None = None,
               since: str | None = None) -> dict:
    """Scaffold the domain folder ``domain/`` of a repository that has none (the tests' mini repositories) as the
    experimental domain ``name`` (at the schema's one version, CORE.yaml's), from the test fixture template
    (``layout.DOMAIN_TEMPLATE``), and
    append the ``/domain/`` line to CODEOWNERS, naming its team (by default the reviewers team of the review
    policy) and the reviewers team. A repository holds one domain beside the core for now."""
    repo = Path(repo).resolve()
    if not is_checkout(repo):
        raise ScaleError(f"new_domain writes into a repository checkout; {repo} is not one")
    if not NAME.match(name or ""):
        raise ScaleError(f"{name!r}: a domain name is lowercase letters, digits and single hyphens (e.g. optics)")
    dest = repo / layout.DOMAIN
    if dest.exists():
        raise ScaleError(f"{dest} exists: the repository has its one domain beside the core")
    if not GITHUB.match(steward_github or ""):
        raise ScaleError(f"{steward_github!r} is not a GitHub handle")
    if not (title or "").strip() or not (steward_name or "").strip():
        raise ScaleError("give the domain a --title and the steward a --steward-name")
    from .policy import load_policy
    reviewers_team = (load_policy(repo).get("reviewers") or {}).get("team")
    team = team or reviewers_team or f"@{steward_github}"
    if not TEAM.match(team):
        raise ScaleError(f"{team!r} is not a code owner as CODEOWNERS names it ('@org/team' or '@user')")
    since = since or _dt.date.today().isoformat()
    if not DATE.match(since):
        raise ScaleError(f"--since {since!r} is not a date YYYY-MM-DD")
    taken = {n for kind, n in identifier_index(repo, load_core(repo), load_domains(repo))
             if kind.startswith("scale-catal")}
    if name in taken:
        raise ScaleError(f"{name!r} already names a scale-catal file (the kernel's); choose another domain name")
    template = repo / layout.DOMAIN_TEMPLATE
    if not (template / layout.DOMAIN_MANIFEST).is_file():
        raise ScaleError(f"no domain template: {template / layout.DOMAIN_MANIFEST} is missing")
    values = {"__DOMAIN__": name, "__SNAKE__": name.replace("-", "_"), "__TITLE__": title.strip(),
              "__STEWARD_NAME__": steward_name.strip(), "__STEWARD_GITHUB__": steward_github, "__TEAM__": team,
              "__SINCE__": since, "__VERSION__": core_version(repo)}
    written = []
    try:
        for src in sorted(template.rglob("*")):
            rel = src.relative_to(template)
            if {"__pycache__"} & set(rel.parts) or src.suffix == ".pyc":
                continue
            out = dest / _fill(rel.as_posix(), values, "path")
            if src.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_fill(src.read_text(encoding="utf-8"), values, src.suffix), encoding="utf-8")
            written.append(out.relative_to(repo).as_posix())
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    co = repo / layout.CODEOWNERS
    line = codeowners.domain_line(name)
    if co.is_file():
        text = co.read_text(encoding="utf-8")
        rules = [r for r in codeowners.parse(text) if r.pattern == line]
        if rules and team in rules[-1].owners:
            codeowners_note = f"{layout.CODEOWNERS} already has a {line} line naming {team}; left unchanged"
        elif rules:                     # the one domain's line: name the team on it, before the owners it has
            owners = " ".join(dict.fromkeys((team, *rules[-1].owners)))
            lines = text.splitlines(keepends=True)
            lines[rules[-1].line - 1] = f"{line:<36}{owners}\n"
            co.write_text("".join(lines), encoding="utf-8")
            codeowners_note = f"named {team} on the {line} line of {layout.CODEOWNERS}: `{line} {owners}`"
        else:
            owners = " ".join(dict.fromkeys(x for x in (team, reviewers_team) if x))
            co.write_text(text.rstrip("\n") + f"\n\n# The domain {name} (experimental), added by new_domain(): its team and the "
                          "reviewers;\n# any one of them may give the code-owner review.\n" + f"{line:<36}{owners}\n", encoding="utf-8")
            codeowners_note = f"appended `{line} {owners}` to {layout.CODEOWNERS}"
    else:
        codeowners_note = (f"{layout.CODEOWNERS} does not exist: nothing was written there; add `{line} {team}` "
                           "when the file is in place (scale domains check requires it)")
    return {"domain": name, "path": layout.DOMAIN, "status": "experimental", "team": team,
            "files": written, "codeowners": codeowners_note,
            "next_steps": [f"human action: give {team} Write access to the repository (a team is created in the organization first)",
                           f"fill in {layout.DOMAIN_DECLARATION} (summary, scope), the competency questions and the example",
                           f"if the domain brings new reviewers, add them to {layout.REVIEW_POLICY} (a governance change, "
                           "reviewed like every pull request)",
                           "scale domains check", "uv run --extra dev scale check",
                           "open a pull request"]}


def _fill(text: str, values: dict[str, str], kind: str) -> str:
    """Replace the template's placeholders. YAML templates hold them inside single quotes, JSON inside
    strings, so values are escaped for that context; paths take only the name placeholders."""
    for k, v in values.items():
        if kind in (".yaml", ".yml"):
            v = v.replace("'", "''")
        elif kind == ".json":
            v = json.dumps(v, ensure_ascii=False)[1:-1]
        elif kind == "path" and k not in ("__DOMAIN__", "__SNAKE__"):
            continue
        text = text.replace(k, v)
    return text
