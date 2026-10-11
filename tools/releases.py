"""Releases: immutable, checksummed snapshots of the specification.

A SCALE release (``releases/<version>/``, ids ``vX.Y.Z``) binds, at their repository-relative
paths: the core's declaration and the science kernel with its frozen versions, each released
domain's declaration and scale-catal schema (its manifest, the domain files it lists and the frozen
versions beside it), and the skills, with a sha256 digest of every file. The files are always taken
from the repository head, the applied state; a release is never edited afterwards. ``RELEASE.yaml``
records the schema's one version and what it binds (``component_versions``), the people credited
(``contributors``), the experimental domains it leaves out and a semantic comparison of every domain's assembled schema and of the kernel with
the previous release. It also ships the spec document of every version of every released
domain's schema (``specs/<domain>/scale-catal-<version>.json``, the assembled schema as canonical JSON,
:func:`pgraph.spec_document`), listed with its sha256 in ``spec_documents``: the published artifact a reader
binds a schema by, since a bare version number names a schema only within one numbering. ``scale graph
verify`` checks that every version keeps the digest a release published for it (:func:`spec_digest_stability`).
The first release is v0.1.0, with schema 0.1.0.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
import shutil
from pathlib import Path

from . import __version__, layout
from .util import ScaleError, digest_tree, load_yaml, write_yaml
from .versions import DISTRIBUTION, normalize_release_id, release_id, release_key

# what build_release writes into RELEASE.yaml (a head manifest never carries them)
GENERATED_KEYS = ("status", "date", "previous", "comparison_to_previous",
                  "built_with", "source", "component_versions", "contributors", "excluded_domains", "spec_documents",
                  "digests")
SPECS = "specs"            # a release's spec documents: specs/<domain>/scale-catal-<version>.json


# ---------------------------------------------------------------- discovery

def list_releases(repo: Path) -> list[str]:
    """Every release id (``releases/<v>`` holding a RELEASE.yaml), oldest first."""
    root = Path(repo) / layout.RELEASES
    rels = [p.name for p in root.iterdir() if (p / "RELEASE.yaml").exists()] if root.is_dir() else []
    return sorted(rels, key=release_key)


def main_releases(repo: Path) -> list[str]:
    """The releases, oldest first (one line: :func:`list_releases`)."""
    return list_releases(repo)


def release_root(repo: Path, version: str) -> Path:
    """``vX`` (or ``X``) -> ``releases/vX``."""
    v = normalize_release_id(version)
    p = Path(repo) / layout.RELEASES / v
    if not (p / "RELEASE.yaml").exists():
        raise ScaleError(f"Release {v} not found under {Path(repo) / layout.RELEASES}. "
                         f"Available: {', '.join(list_releases(repo)) or 'none'}")
    return p


def load_manifest(root: Path) -> dict:
    """A release's ``RELEASE.yaml``, or the head's ``scale-release.yaml``."""
    for name in ("RELEASE.yaml", layout.RELEASE_MANIFEST):
        if (Path(root) / name).exists():
            return load_yaml(Path(root) / name) or {}
    raise ScaleError(f"no release manifest (RELEASE.yaml or {layout.RELEASE_MANIFEST}) in {root}")


def skill_files(root: Path) -> list[Path]:
    """The SKILL.md files a release (or the head) ships, read from its manifest's ``skills:`` list:
    an entry is a file or a directory, and a directory holding a SKILL.md is a skill."""
    manifest = load_manifest(root)
    return [root / s / "SKILL.md" for s in manifest.get("skills") or [] if (root / s / "SKILL.md").is_file()]


def skill_folder(skill: Path) -> list[Path]:
    """Every file of a skill: its SKILL.md first, then the rest of its folder (``references/`` recipes, a schema
    the procedure names), in a stable order. A skill is its whole folder: a release copies it and ``scale skills
    install`` installs it, so the files the SKILL.md points to reach the agent with it."""
    folder = Path(skill).parent
    rest = [p for p in sorted(folder.rglob("*")) if p.is_file() and p.name not in ("SKILL.md", ".DS_Store")
            and "__pycache__" not in p.parts]
    return [folder / "SKILL.md", *rest]


# ---------------------------------------------------------------- what a release binds

def head_artifacts(repo: Path) -> dict:
    """The head's core declaration, the kernel and its frozen versions, and each released domain's
    declaration and scale-catal files (its manifest, the parts it lists, the frozen versions beside it),
    repository-relative, with the loaded declarations. Refuses a listed experimental domain."""
    from .schema_change import PACKAGE_KEYS
    repo = Path(repo)
    head = load_yaml(repo / layout.RELEASE_MANIFEST)
    core_rel, profiles = head.get("core"), head.get("domain_profiles")
    if not core_rel or not isinstance(profiles, list):
        raise ScaleError(f"{layout.RELEASE_MANIFEST} must name `core` and `domain_profiles`")
    core = load_yaml(repo / core_rel)
    files = [core_rel, layout.KERNEL] + _files_in(repo, repo / layout.KERNEL_FROZEN)
    domains, graphs = {}, {}
    for prof in profiles:
        m = load_yaml(repo / prof)
        name = m.get("domain") or Path(prof).parent.name
        if m.get("status") == "experimental":
            raise ScaleError(f"{prof}: the experimental domain {name} is listed in domain_profiles; experimental "
                             "domains are not released (promote it first, or remove it from domain_profiles)")
        domains[name] = (prof, m)
        files.append(prof)
        man_rel = ((m.get("graph") or {}).get("manifest"))
        if man_rel:
            man = Path(prof).parent / man_rel
            g = load_yaml(repo / man)
            parts = [os.path.normpath(layout.kernel_path(man.parent, g["kernel"]))] + \
                [os.path.normpath(man.parent / x) for k in PACKAGE_KEYS for x in g.get(k) or []]
            outside = [x for x in parts if x.startswith("..")]
            if outside:
                raise ScaleError(f"{man.as_posix()} names files outside the repository: {outside}")
            files += [man.as_posix()] + [Path(x).as_posix() for x in parts]
            files += _files_in(repo, layout.frozen_graph_dir(repo / man))
            graphs[name] = {"manifest": man.as_posix(), "version": g.get("version"), "status": g.get("status")}
    missing = [f for f in files if not (repo / f).is_file()]
    if missing:
        raise ScaleError(f"release files missing at the head: {missing}")
    excluded = []
    for name, d in layout.domain_layers(repo).items():
        m = load_yaml(d / layout.DOMAIN_MANIFEST) if (d / layout.DOMAIN_MANIFEST).is_file() else {}
        if m.get("status") == "experimental":
            excluded.append({"domain": name, "version": m.get("version"), "status": "experimental"})
    versions = sorted({str(g["version"]) for g in graphs.values()})
    if len(versions) > 1:
        raise ScaleError(f"the released schema manifests name several versions {versions}; the schema has one")
    return {"core_rel": core_rel, "profiles": list(profiles), "files": list(dict.fromkeys(files)), "core": core,
            "schema_version": versions[0] if versions else None, "graphs": graphs, "domains": domains,
            "excluded": excluded}


def _files_in(repo: Path, d: Path) -> list[str]:
    """Every file below a frozen directory, repository-relative (none when it does not exist)."""
    return [p.relative_to(repo).as_posix() for p in sorted(Path(d).rglob("*"))
            if p.is_file() and p.name != ".DS_Store" and "__pycache__" not in p.parts] if Path(d).is_dir() else []


def _skill_meta(root: Path, skills: list[str]) -> list[dict]:
    import yaml
    out = []
    for s in skills:
        p = root / s / "SKILL.md"
        if p.is_file():
            fm = re.match(r"^---\n(.*?)\n---\n", p.read_text(encoding="utf-8"), re.S)
            meta = (yaml.safe_load(fm.group(1)) if fm else {}) or {}
            out.append({"name": meta.get("name", Path(s).name), "version": str(meta.get("version"))})
    return out


def credited_people(art: dict) -> list[dict]:
    """Everyone the core and the released domains credit (maintainers and contributors, never a placeholder
    seat), deduplicated by GitHub handle (else ORCID, else name), with their roles and where they hold them."""
    out: dict[str, dict] = {}
    sources = [("core", art["core"])] + [(d, m) for d, (_, m) in art["domains"].items()]
    for scope, m in sources:
        people = list((m.get("maintainers") or {}).get("people") or []) + list(m.get("contributors") or [])
        for p in people:
            if p.get("placeholder"):                # a reviewer seat not filled yet: nobody to credit
                continue
            key = (p.get("github") or "").lower() or p.get("orcid") or (p.get("name") or "").strip().lower()
            e = out.setdefault(key, {"name": p.get("name"), **({"github": p["github"]} if p.get("github") else {}),
                                     **({"orcid": p["orcid"]} if p.get("orcid") else {}), "roles": [], "scopes": []})
            e["roles"] = sorted(set(e["roles"]) | set(p.get("roles") or []))
            if scope not in e["scopes"]:
                e["scopes"].append(scope)
            if p.get("orcid") and "orcid" not in e:
                e["orcid"] = p["orcid"]
    return list(out.values())


def component_versions(art: dict, manifest: dict, dest: Path) -> dict:
    """The schema's one version (its manifest's, which documents pin), the core and each released domain at that
    version with the domain's scale-catal manifest; the tool and the skills."""
    v = art["schema_version"]
    return {"schema": {"version": v},
            "core": {"name": art["core"].get("core"), "version": v},
            "kernel": {"file": layout.KERNEL, "version": v},
            "domains": [{"domain": d, "version": v, "status": m.get("status"),
                         **({"scale_graph": dict(art["graphs"][d])}
                            if d in art["graphs"] else {})}
                        for d, (_, m) in art["domains"].items()],
            "tool": {"package": DISTRIBUTION, "version": __version__},
            "skills": _skill_meta(dest, manifest.get("skills") or [])}


# ---------------------------------------------------------------- comparison with the previous release

CLASSES = ("added", "removed", "changed", "narrowed", "loosened")


def classify(diff: dict | None) -> str:
    """``breaking`` (something removed, changed or narrowed), ``additive`` (only additions and
    loosenings), ``identical``; a schema present on one side only is ``added`` or ``removed``."""
    if diff is None:
        return "identical"
    from .schema_change import tier
    return {3: "breaking", 2: "additive", 0: "identical"}[tier(diff)]


def kernel_spec(kernel: Path, version: str | None = None) -> dict:
    """The science kernel assembled on its own (no domain), at the schema ``version`` it belongs to, for comparing
    two kernels."""
    from .pgraph_schema import assemble_manifest
    k = load_yaml(kernel)
    return assemble_manifest({"schema": "scale-catal", "version": version, "status": k.get("status"),
                              "kernel": Path(kernel).name, "domains": []}, Path(kernel).parent)


def _graph_diff(a: dict | None, b: dict | None) -> dict:
    from .schema_change import diff_specs
    if a is None or b is None:
        return {"classification": "added" if a is None else "removed", "from": (a or {}).get("version"),
                "to": (b or {}).get("version")}
    d = diff_specs(a, b)
    return {"classification": classify(d), "from": a.get("version"), "to": b.get("version"),
            **{k: d[k] for k in CLASSES if d[k]}}


def schema_comparison(repo: Path, prev_root: Path, prev: dict, art: dict) -> dict:
    """The semantic difference between the previous release and the head: the kernel, and each
    domain's assembled schema (labels, edge types, properties, checklist items: added, removed, changed,
    narrowed, loosened), with a classification each and overall."""
    from . import pgraph
    pk = prev_root / layout.KERNEL
    pv = ((prev.get("component_versions") or {}).get("schema") or {}).get("version")
    out = {"kernel": _graph_diff(kernel_spec(pk, pv) if pk.is_file() else None,
                                 kernel_spec(Path(repo) / layout.KERNEL, art["schema_version"])),
           "domains": {}}
    before = {d["domain"]: (d.get("scale_graph") or {}).get("manifest")
              for d in (prev.get("component_versions") or {}).get("domains") or []}
    for name in dict.fromkeys(list(before) + list(art["graphs"])):
        a = pgraph.load_spec(prev_root / before[name]) if before.get(name) else None
        b = pgraph.load_spec(Path(repo) / art["graphs"][name]["manifest"]) if name in art["graphs"] else None
        out["domains"][name] = _graph_diff(a, b)
    ranks = ["identical", "additive", "added", "breaking", "removed"]
    every = [out["kernel"]["classification"]] + [d["classification"] for d in out["domains"].values()]
    worst = max(every, key=ranks.index)
    out["classification"] = {"added": "additive", "removed": "breaking"}.get(worst, worst)
    return out


def file_changes(prev_digests: dict, new_digests: dict) -> dict:
    """Files added, removed and changed (by digest) between two releases."""
    a, b = prev_digests, new_digests
    return {"added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b)),
            "changed": sorted(k for k in set(a) & set(b) if a[k] != b[k])}


def _unbumped(prev: dict, previous: str, prev_digests: dict, art: dict, new_digests: dict) -> list[str]:
    """The schema files (the kernel and each released domain's scale-catal files) whose bytes changed since the
    previous release while the schema's one version did not."""
    schema_files = {layout.KERNEL} | {f for g in art["graphs"].values() for f in art["files"]
                                      if f.startswith(f"{Path(g['manifest']).parent.as_posix()}/")}
    changed = sorted(k for k in schema_files if k in prev_digests and k in new_digests
                     and prev_digests[k] != new_digests[k])
    before = ((prev.get("component_versions") or {}).get("schema") or {}).get("version")
    if changed and str(before) == str(art["schema_version"]):
        return [f"{', '.join(changed[:5])}{' …' if len(changed) > 5 else ''} changed since {previous}, but the schema is "
                f"still at {before}; a schema change raises the version (`scale schema bump`)"]
    return []


# ---------------------------------------------------------------- spec documents

def write_spec_documents(dest: Path, art: dict) -> list[dict]:
    """Write the spec document of every version of every released domain's schema, as the release holds it
    (its manifest and the frozen versions beside it), into ``specs/<domain>/scale-catal-<version>.json``;
    returns ``spec_documents``: domain, version, file and sha256 of each."""
    from . import pgraph
    out = []
    for name, g in art["graphs"].items():
        for v, path in pgraph.spec_versions(Path(dest) / g["manifest"]):
            data = pgraph.spec_bytes(pgraph.load_spec(path))
            rel = f"{SPECS}/{name}/scale-catal-{v}.json"
            (Path(dest) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(dest) / rel).write_bytes(data)
            out.append({"domain": name, "version": v, "file": rel, "sha256": hashlib.sha256(data).hexdigest()})
    return out


def released_spec_digests(repo: Path, rid: str) -> list[dict]:
    """The spec digests a release published: its ``spec_documents``, or, for a release without them, the digests
    of the spec documents of the schema versions it holds (its domain manifests and the frozen versions beside
    them, assembled from the release's own copy)."""
    from . import pgraph
    root = release_root(repo, rid)
    rel = load_yaml(root / "RELEASE.yaml") or {}
    if rel.get("spec_documents") is not None:
        return [{**d, "basis": "published"} for d in rel["spec_documents"]]
    out = []
    for d in (rel.get("component_versions") or {}).get("domains") or []:
        man = (d.get("scale_graph") or {}).get("manifest")
        if man and (root / man).is_file():
            for v, path in pgraph.spec_versions(root / man):
                out.append({"domain": d["domain"], "version": v, "sha256": pgraph.spec_sha256(pgraph.load_spec(path)),
                            "basis": "assembled from the release's copy"})
    return out


def spec_digest_stability(repo: Path, digests: dict[tuple[str, str], str]) -> dict:
    """Every schema version a release holds keeps its spec digest: the repository's head or
    frozen copy of that version (``digests``: (domain, version) -> sha256 of its spec document) has the digest
    the release published (or, for an older release, the digest of the release's own copy). A version is
    identified by its digest, so a frozen version, or the tools' assembly of it, must not drift."""
    checked, problems = [], []
    for rid in main_releases(repo):
        for d in released_spec_digests(repo, rid):
            now = digests.get((d["domain"], d["version"]))
            ok = now == d["sha256"]
            checked.append({"release": rid, "domain": d["domain"], "version": d["version"], "sha256": d["sha256"],
                            "basis": d["basis"], "ok": ok})
            if not ok:
                problems.append(f"{d['domain']} scale-catal {d['version']}: release {rid} has spec digest {d['sha256']}, "
                                + (f"the repository's now {now}" if now else "and the repository no longer holds that version"))
    return {"ok": not problems, "checked": checked, "problems": problems}


# ---------------------------------------------------------------- build / verify

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def build_release(repo: Path, version: str, out_root: Path | None = None,
                  date: str | None = None, override_version: bool = False) -> Path:
    """Snapshot the repository head into an immutable release directory ``<out_root>/<version>``.

    ``version`` must be the head manifest's ``release`` (``override_version`` renumbers on purpose), so a
    typo cannot publish the head under another number. When the kernel or a domain's schema differs
    from the previous release, the schema version must differ too (each change merged with its version raised).
    The first release has no predecessor and is compared with nothing."""
    repo = Path(repo)
    out_root = out_root or repo / layout.RELEASES
    manifest = load_yaml(repo / layout.RELEASE_MANIFEST) or {}
    if manifest.get("distribution") != DISTRIBUTION:
        raise ScaleError(f"{layout.RELEASE_MANIFEST} must say `distribution: {DISTRIBUTION}`")
    source_id = release_id(manifest)
    asked = normalize_release_id(version)
    if source_id is None:
        raise ScaleError(f"{layout.RELEASE_MANIFEST} names no release")
    if asked == source_id:
        v = source_id
    elif override_version:
        v = asked
    else:
        raise ScaleError(f"the head describes release {source_id}, not {asked}. Set `release:` in "
                         f"{layout.RELEASE_MANIFEST} (or pass --override-version to renumber deliberately).")
    dest = out_root / v
    if dest.exists():
        raise ScaleError(f"{dest} exists; releases are immutable. Choose a new version.")
    art = head_artifacts(repo)
    files = list(art["files"])
    for s in manifest.get("skills") or []:
        sp = repo / s
        files += [p.relative_to(repo).as_posix() for p in sorted(sp.rglob("*")) if p.is_file()] if sp.is_dir() else [s]
    files = [f for f in dict.fromkeys(files) if "__pycache__" not in f and not f.endswith(".DS_Store")]
    earlier = [r for r in main_releases(repo) if release_key(r) < release_key(v)]
    previous = earlier[-1] if earlier else None
    prev_root = release_root(repo, previous) if previous else None
    prev = load_yaml(prev_root / "RELEASE.yaml") if prev_root else {}
    comparison = schema_comparison(repo, prev_root, prev, art) if previous else None
    dest.mkdir(parents=True)
    try:
        for f in files:
            (dest / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / f, dest / f)
        rel = {}
        for k, v_ in manifest.items():                   # the head's keys in their order, the status after the release
            if k not in GENERATED_KEYS:
                rel[k] = v if k == "release" else v_
            if k == "release":
                rel["status"] = "released"
        rel.update({"date": date or _now()[:10], "previous": previous})
        specs = write_spec_documents(dest, art)
        digests = digest_tree(dest)
        if previous:
            pd = prev.get("digests") or {}
            stale = _unbumped(prev, previous, pd, art, digests)
            if stale:
                raise ScaleError("schema content changed without a version bump: " + "; ".join(stale))
            rel["comparison_to_previous"] = {**comparison, "files": file_changes(pd, digests)}
        else:
            rel["comparison_to_previous"] = None
        rel.update(built_with={"tool": "scale", "version": __version__},
                   source={"repository": layout.REPOSITORY_URL, "tag": v},
                   component_versions=component_versions(art, manifest, dest), contributors=credited_people(art),
                   excluded_domains=art["excluded"], spec_documents=specs, digests=digests)
        write_yaml(dest / "RELEASE.yaml", rel)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def verify_release(root: Path, expected_id: str | None = None) -> dict:
    """Digests of every file, and (with ``expected_id``, the id its location implies) that the manifest
    describes that release."""
    rel = load_yaml(root / "RELEASE.yaml")
    actual = digest_tree(root, exclude=("RELEASE.yaml",))
    expected = rel.get("digests") or {}
    mism = sorted(k for k in set(actual) | set(expected) if actual.get(k) != expected.get(k))
    out = {"release": release_id(rel), "ok": not mism, "files": len(expected), "mismatched": mism}
    if expected_id and release_id(rel) != expected_id:
        out.update(ok=False, problem=f"stored as {expected_id} but its manifest describes {release_id(rel)}")
    return out
