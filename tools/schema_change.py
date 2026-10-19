"""A schema change in a pull request: its diff against the base, the version it needs, and its checks.

    scale schema diff [--base REF]     # what the branch changes in the schema, its tier, the version that follows
    scale schema bump [--base REF]     # freeze the base version, raise the version by the rule, register the step
    scale schema check [--base REF]    # what the pull request must carry (CI runs it; --comment for the reviewer)

A schema change is a pull request like any other: it edits the schema files (the science kernel,
``core/graph/kernel.yaml``, and the catalysis file, ``domain/graph/catalysis.yaml``) directly. What it must carry
is checked here, against the base the pull request merges into (``origin/main`` by default):

* **the version.** The schema has one version for the kernel and the catalysis domain together. A change raises it
  by the rule :func:`next_version`: a breaking change (something removed, changed or narrowed) raises the second
  number (0.1.0 -> 0.2.0), any other change the third (0.1.0 -> 0.1.1);
* **the frozen base.** The version it replaces is frozen, unchanged (``core/graph/frozen/kernel-<v>.yaml``,
  ``domain/graph/frozen/scale-catal-<v>.yaml`` and ``v<v>/``), so that documents pinning it stay valid;
* **the step.** ``pgraph_migrate.STEPS[<base>] = (<new>, <note>)`` lets ``scale kg update`` move documents; a
  breaking change also registers its rule (``STEP_RULES[<base>]``), which rewrites what it must;
* **provisional.** Every label, edge type and property the change adds is ``maturity: provisional``;
* **tests.** Every label and edge type the change adds appears in a valid fixture or example document;
* **the recorded digest.** README.md's table of spec digests marks the base version frozen and records the new
  version's digest;
* **documents written for the change pin it.** A fixture or example document the branch adds pins the new version,
  not the base;
* **a CHANGELOG line.**

``scale schema bump`` writes the frozen copy, the versions, the step, the digest row and the new documents' pins; the
rest is the change itself.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import yaml

from . import layout, pgraph, quantities
from .util import ScaleError, dump_yaml, load_yaml

DEFAULT_BASE = "origin/main"
SCHEMA_DIRS = ("core/graph", "domain/graph")            # what the base is rebuilt from (frozen copies included)
PACKAGE_KEYS = ("modules", "extensions", "profiles", "domains")
# the files that state the schema's one version beside the manifest, and the top-level key each states it by
VERSION_FILES = ((layout.CORE_MANIFEST, "version"), (layout.DOMAIN_DECLARATION, "version"),
                 (layout.RELEASE_MANIFEST, "schema_version"), (layout.KERNEL_ONLY_MANIFEST, "version"))
FIXTURE_ROOTS = ("domain/tests/fixtures", "domain/examples", "core/examples", "core/tests", "tools/tests/fixtures")


# ------------------------------------------------------------------------------------------ the diff
# the keys of a property definition that say what it means or where it comes from, not what is valid
DESCRIPTIVE_KEYS = {"description", "maturity", "added_by", "title", "examples", "note", "maps_to", "iri", "see_also"}


def _props(d: dict) -> dict:
    return d.get("properties") or {}


def diff_specs(a: dict, b: dict) -> dict:
    """Additions, removals and changes between two assembled scale-catal schemas."""
    out = {"added": [], "removed": [], "changed": [], "narrowed": [], "loosened": []}

    def cmp_def(where: str, da: dict, db: dict) -> None:
        """One property definition against another, every part that decides what is valid compared (nested
        ``items`` too); a difference outside the descriptive keys that is not read as narrowing or loosening is a
        change, so nothing that can invalidate a document passes as no change."""
        if da.get("type") != db.get("type"):
            out["changed"].append(f"{where}: type {da.get('type')} -> {db.get('type')}")
        va, vb = set(da.get("values") or []), set(db.get("values") or [])
        if vb - va:
            out["added"] += [f"{where} = {v}" for v in sorted(vb - va)]
        if va - vb:
            out["removed"] += [f"{where} = {v}" for v in sorted(va - vb)]
        ta, tb = set(da.get("targets") or []), set(db.get("targets") or [])
        out["loosened"] += [f"{where} may target {x}" for x in sorted(tb - ta)]
        out["narrowed"] += [f"{where} may no longer target {x}" for x in sorted(ta - tb)]
        ia, ib = da.get("items"), db.get("items")
        if isinstance(ia, dict) and isinstance(ib, dict):
            cmp_def(f"{where}[items]", ia, ib)
        elif ia != ib:
            out["changed"].append(f"{where}: items {ia!r} -> {ib!r}")
        for key in sorted((set(da) | set(db)) - DESCRIPTIVE_KEYS - {"type", "values", "targets", "items", "quantity", "context"}):
            if da.get(key) != db.get(key):
                out["changed"].append(f"{where}: {key} {da.get(key)!r} -> {db.get(key)!r}")
        quantities.diff_binding(where, da, db, out)       # a quantity contract bound, dropped or changed

    def cmp_props(where: str, pa: dict, pb: dict) -> None:
        for k in sorted(set(pa) | set(pb)):
            if k not in pa:
                out["added"].append(f"{where}.{k}")
            elif k not in pb:
                out["removed"].append(f"{where}.{k}")
            elif isinstance(pa[k], dict) and isinstance(pb[k], dict):
                cmp_def(f"{where}.{k}", pa[k], pb[k])
            elif pa[k] != pb[k]:
                out["changed"].append(f"{where}.{k}: {pa[k]!r} -> {pb[k]!r}")

    # the names documents pin: a renamed schema or kernel invalidates every pin of the old name (a breaking change)
    if a.get("schema") != b.get("schema"):
        out["changed"].append(f"schema name: {a.get('schema')} -> {b.get('schema')}")
    if (a.get("kernel") or {}).get("name") != (b.get("kernel") or {}).get("name"):
        out["changed"].append(f"kernel name: {(a.get('kernel') or {}).get('name')} -> {(b.get('kernel') or {}).get('name')}")
    # the kernel's shared structures: the evidence item, the value object, the record reference and
    # the properties every node and link carries
    for where, fa, fb in (("evidence", (a.get("evidence") or {}).get("fields") or {}, (b.get("evidence") or {}).get("fields") or {}),
                          ("value", (a.get("value") or {}).get("fields") or {}, (b.get("value") or {}).get("fields") or {}),
                          ("record_ref", (a.get("record_ref") or {}).get("fields") or {}, (b.get("record_ref") or {}).get("fields") or {}),
                          ("common.node", _props((a.get("common") or {}).get("node") or {}), _props((b.get("common") or {}).get("node") or {})),
                          ("common.link", _props((a.get("common") or {}).get("link") or {}), _props((b.get("common") or {}).get("link") or {}))):
        cmp_props(where, fa, fb)
    # the quantity contracts: a kind's dimensions, a context it is compared by, a unit's or a term's meaning
    quantities.diff(a.get("quantities"), b.get("quantities"), out)
    quantities.diff_context_targets(a.get("context_targets"), b.get("context_targets"), out)
    for where in ("evidence", "value", "record_ref"):
        ra, rb = set((a.get(where) or {}).get("required") or []), set((b.get(where) or {}).get("required") or [])
        out["narrowed"] += [f"{where} requires {x}" for x in sorted(rb - ra)]
        out["loosened"] += [f"{where} no longer requires {x}" for x in sorted(ra - rb)]
    for kind in ("nodes", "edges"):
        for n in sorted(set(a[kind]) | set(b[kind])):
            if n not in a[kind]:
                out["added"].append(f"{kind}.{n}")
                continue
            if n not in b[kind]:
                out["removed"].append(f"{kind}.{n}")
                continue
            da, db = a[kind][n], b[kind][n]
            cmp_props(f"{kind}.{n}", _props(da), _props(db))
            ra, rb = set(da.get("required") or []), set(db.get("required") or [])
            if rb - ra:
                out["narrowed"] += [f"{kind}.{n} requires {x}" for x in sorted(rb - ra)]
            if ra - rb:
                out["loosened"] += [f"{kind}.{n} no longer requires {x}" for x in sorted(ra - rb)]
            if kind == "edges":
                for end in ("from", "to"):
                    ea, eb = set(da.get(end) or []), set(db.get(end) or [])
                    if eb - ea:
                        out["loosened"] += [f"edges.{n}.{end} + {x}" for x in sorted(eb - ea)]
                    if ea - eb:
                        out["narrowed"] += [f"edges.{n}.{end} - {x}" for x in sorted(ea - eb)]
    for pr in sorted(set(a.get("profiles") or {}) | set(b.get("profiles") or {})):
        pa, pb = (a.get("profiles") or {}).get(pr), (b.get("profiles") or {}).get(pr)
        if pa is None or pb is None:
            (out["added"] if pa is None else out["removed"]).append(f"profiles.{pr}")
            continue
        ca, cb = pa["effective"]["constraints"], pb["effective"]["constraints"]
        for lab in sorted(set(ca) | set(cb)):
            xa, xb = ca.get(lab) or {}, cb.get(lab) or {}
            for lvl in ("required",):
                sa, sb = set(xa.get(lvl) or []), set(xb.get(lvl) or [])
                sa |= {f"-{e}->" for e in (xa.get("edges") or {}).get(lvl) or []}
                sb |= {f"-{e}->" for e in (xb.get("edges") or {}).get(lvl) or []}
                sa |= {f"evidence {p['name']}" for p in (xa.get("evidence") or {}).get(lvl) or []}
                sb |= {f"evidence {p['name']}" for p in (xb.get("evidence") or {}).get(lvl) or []}
                out["narrowed"] += [f"profiles.{pr} {lab} requires {x}" for x in sorted(sb - sa)]
                out["loosened"] += [f"profiles.{pr} {lab} no longer requires {x}" for x in sorted(sa - sb)]
            # applies_by: a record that states no value of such a property has unknown applicability, never a met case
            ba, bb = set(xa.get("applies_by") or []), set(xb.get("applies_by") or [])
            out["narrowed"] += [f"profiles.{pr} {lab} applies its cases by {x} (a record that states none is unknown)"
                                for x in sorted(bb - ba)]
            out["loosened"] += [f"profiles.{pr} {lab} no longer applies its cases by {x}" for x in sorted(ba - bb)]
            ua, ub = xa.get("unless") or {}, xb.get("unless") or {}
            for k in sorted(set(ua) | set(ub)):
                more, less = set(ub.get(k) or []) - set(ua.get(k) or []), set(ua.get(k) or []) - set(ub.get(k) or [])
                out["loosened"] += [f"profiles.{pr} {lab} exempts {k} = {v}" for v in sorted(more)]
                out["narrowed"] += [f"profiles.{pr} {lab} no longer exempts {k} = {v}" for v in sorted(less)]
            # cases (``when``): what each condition requires, compared condition by condition
            wa, wb = _cases(xa), _cases(xb)
            for cond in sorted(set(wa) | set(wb)):
                sa, sb = wa.get(cond, (set(), {}))[0], wb.get(cond, (set(), {}))[0]
                out["narrowed"] += [f"profiles.{pr} {lab} when {cond} requires {x}" for x in sorted(sb - sa)]
                out["loosened"] += [f"profiles.{pr} {lab} when {cond} no longer requires {x}" for x in sorted(sa - sb)]
                va, vb = wa.get(cond, (set(), {}))[1], wb.get(cond, (set(), {}))[1]
                for k in sorted(set(va) | set(vb)):
                    if k in va and k in vb and set(va[k]) != set(vb[k]):
                        kind = "narrowed" if set(vb[k]) < set(va[k]) else "loosened" if set(vb[k]) > set(va[k]) else "changed"
                        out[kind].append(f"profiles.{pr} {lab} when {cond} {k} values {sorted(va[k])} -> {sorted(vb[k])}")
                    elif k in vb and k not in va:
                        out["narrowed"].append(f"profiles.{pr} {lab} when {cond} narrows {k} to {sorted(vb[k])}")
                    elif k in va and k not in vb:
                        out["loosened"].append(f"profiles.{pr} {lab} when {cond} no longer narrows {k}")
    return out


def _cases(c: dict) -> dict[str, tuple[set, dict]]:
    """A checklist block's cases by their condition (as text): (what each requires, the values it narrows)."""
    out: dict[str, tuple[set, dict]] = {}
    for x in c.get("when") or []:
        cond = "; ".join(f"{k} {op} [{', '.join(vals)}]" for k, m in sorted(x["if"].items()) for op, vals in m.items())
        req, vals = out.setdefault(cond, (set(), {}))
        req |= set(x.get("required") or []) | {f"-{e}->" for e in (x.get("edges") or {}).get("required") or []}
        req |= {f"evidence {p['name']}" for p in (x.get("evidence") or {}).get("required") or []}
        vals.update(x.get("values") or {})
    return out


def tier(diff: dict) -> int:
    if diff["removed"] or diff["changed"] or diff["narrowed"]:
        return 3
    if diff["added"] or diff["loosened"]:
        return 2
    return 0



def next_version(base: str, t: int) -> str:
    """The version a change of tier ``t`` raises ``base`` to: breaking, the second number (0.1.0 -> 0.2.0); any other
    change, the third (0.1.0 -> 0.1.1)."""
    major, minor, patch = (int(x) for x in str(base).split("."))
    return f"{major}.{minor + 1}.0" if t >= 3 else f"{major}.{minor}.{patch + 1}"


# ------------------------------------------------------------------------------------------ the base
def _git(repo: Path, *args: str) -> bytes:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if r.returncode:
        raise ScaleError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def merge_base(repo: Path, base: str = DEFAULT_BASE) -> str:
    return _git(repo, "merge-base", base, "HEAD").decode().strip()


def base_tree(repo: Path, ref: str, dest: Path) -> Path:
    """The schema files of ``ref`` (the schema directories and the files stating the version) under ``dest``."""
    paths = [p for p in (*SCHEMA_DIRS, *(rel for rel, _ in VERSION_FILES), layout.PREFIX_REGISTRY)
             if _git(repo, "ls-tree", "--name-only", ref, p).strip()]
    with tarfile.open(fileobj=io.BytesIO(_git(repo, "archive", ref, *paths))) as t:
        for m in t.getmembers():                   # plain files and directories under dest only
            target = (Path(dest) / m.name).resolve()
            if not (m.isfile() or m.isdir()) or not target.is_relative_to(Path(dest).resolve()):
                continue
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(t.extractfile(m).read())
    return dest


def _manifest(root: Path) -> Path:
    """The domain's manifest under ``root``; a base tree from before the rename holds it as ``scale-graph.yaml``."""
    m = Path(root) / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST
    old = m.with_name(f"{layout.LEGACY_SCHEMA_NAME}.yaml")
    return old if not m.exists() and old.exists() else m


def compare(repo: Path, base: str = DEFAULT_BASE) -> dict:
    """The schema at the merge base of ``base`` and at the working tree: their versions and spec digests, the diff,
    its tier and the version the change needs."""
    repo = Path(repo).resolve()
    mb = merge_base(repo, base)
    with tempfile.TemporaryDirectory() as tmp:
        root = base_tree(repo, mb, Path(tmp))
        a = pgraph.load_spec(_manifest(root))
    b = pgraph.load_spec(_manifest(repo))
    sa, sb = pgraph.spec_sha256(a), pgraph.spec_sha256(b)
    d = diff_specs(a, b) if sa != sb else {"added": [], "removed": [], "changed": [], "narrowed": [], "loosened": []}
    t = tier(d) if sa != sb else None
    return {"base": base, "merge_base": mb, "base_version": a["version"], "head_version": b["version"],
            "base_sha256": sa, "head_sha256": sb, "changed": sa != sb, "diff": d, "tier": t,
            "kind": None if t is None else "breaking" if t >= 3 else "additive" if t == 2 else "no change in meaning",
            "needs_version": next_version(a["version"], t) if t is not None else a["version"]}


# ------------------------------------------------------------------------------------------ bump
def set_version(path: Path, key: str, version: str) -> None:
    """Set a top-level ``<key>: <version>`` in a YAML file in place (the rest of the file unchanged)."""
    f = Path(path)
    text = f.read_text()
    new, n = re.subn(rf"(?m)^{re.escape(key)}:.*$", f"{key}: {version}", text, count=1)
    if not n or str((yaml.safe_load(new) or {}).get(key)) != str(version):
        raise ScaleError(f"{f}: could not set {key}: {version}")
    f.write_text(new)


def _sums(fz: Path) -> dict[str, str]:
    p = Path(fz) / layout.FROZEN_SUMS
    out = {}
    for line in p.read_text().splitlines() if p.exists() else []:
        if line.strip():
            digest, rel = line.split(maxsplit=1)
            out[rel.strip()] = digest
    return out


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def append_frozen_sums(fz: Path, files: list[Path]) -> None:
    """Record the sha256 of newly frozen files in ``<fz>/SHA256SUMS`` (paths relative to ``fz``); never rewritten."""
    fz = Path(fz)
    known = _sums(fz)
    lines = []
    for f in files:
        rel = Path(f).relative_to(fz).as_posix()
        if rel in known:
            raise ScaleError(f"{rel} is frozen already in {fz}")
        lines.append(f"{_sha(f)}  {rel}\n")
    with (fz / layout.FROZEN_SUMS).open("a") as fh:
        fh.writelines(lines)


MIGRATE = "tools/pgraph_migrate.py"


def repo_steps(repo: Path) -> tuple[dict[str, tuple[str, str]], set[str]]:
    """The migration steps and the versions with a rewrite rule, read from the repository's own
    ``pgraph_migrate.py`` (not the running tools: the repository may be a branch or a copy)."""
    import ast
    tree = ast.parse((Path(repo) / MIGRATE).read_text(encoding="utf-8"))
    steps, rules = {}, set()
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and isinstance(node.value, ast.Dict):
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            if node.target.id == "STEPS":
                steps = {k: tuple(ast.literal_eval(v)) for k, v in zip(keys, node.value.values)}
            elif node.target.id == "STEP_RULES":
                rules = set(keys)
    return steps, rules


def _register_step(repo: Path, frm: str, to: str, note: str) -> None:
    """Add ``"<frm>": ("<to>", "<note>"),`` to ``pgraph_migrate.STEPS`` (in the source, in place)."""
    f = Path(repo) / MIGRATE
    text = f.read_text()
    if re.search(rf'^\s*"{re.escape(frm)}":', text, re.M):
        raise ScaleError(f"{f.name}: a step from {frm} is registered already")
    anchor = "STEPS: dict[str, tuple[str, str]] = {\n"
    i = text.index(anchor) + len(anchor)
    j = text.index("\n}", i)
    f.write_text(text[:j] + f'\n    "{frm}": ("{to}", {note!r}),' + text[j:])


DIGEST_TABLE = "README.md"


def _digest_row(version: str, digest: str) -> str:
    return f"| scale-catal {version} | `{digest}` |"


def _record_digest(repo: Path, ver: str, new: str, digest: str) -> None:
    """In README.md's table of spec digests, mark the row of ``ver`` frozen and add the row of ``new`` after it."""
    f = Path(repo) / DIGEST_TABLE
    if not f.is_file():
        return
    text = f.read_text(encoding="utf-8")
    m = re.search(rf"^\| scale-catal {re.escape(ver)} \|.*$", text, re.M)           # bump checked it is there
    row = m.group(0).replace(f"scale-catal {ver} |", f"scale-catal {ver} (frozen) |", 1)
    f.write_text(text[:m.start()] + row + "\n" + _digest_row(new, digest) + text[m.end():], encoding="utf-8")


PIN = re.compile(r'"schema_version":\s*"(?P<v>\d+\.\d+\.\d+)"')


def added_documents(repo: Path, merge_base_ref: str) -> list[str]:
    """The fixture and example documents (``FIXTURE_ROOTS``, JSON) the branch adds: committed, staged or untracked."""
    roots = [r for r in FIXTURE_ROOTS if (Path(repo) / r).is_dir()]
    if not roots:
        return []
    added = _git(repo, "diff", "--name-only", "--diff-filter=A", merge_base_ref, "--", *roots).decode().split()
    added += _git(repo, "ls-files", "--others", "--exclude-standard", "--", *roots).decode().split()
    return sorted({p for p in added if p.endswith(".json") and (Path(repo) / p).is_file()})


def _documents_pinning(repo: Path, rels: list[str], version: str) -> list[str]:
    return [rel for rel in rels
            if any(m["v"] == version for m in PIN.finditer((Path(repo) / rel).read_text(encoding="utf-8")))]


def _repin(repo: Path, rels: list[str], ver: str, new: str) -> list[str]:
    """Pin the documents the branch adds (``rels``) to ``new`` where they pin ``ver``; the paths changed."""
    out = []
    for rel in _documents_pinning(repo, rels, ver):
        f = Path(repo) / rel
        text = f.read_text(encoding="utf-8")
        f.write_text(PIN.sub(lambda m: m.group(0).replace(ver, new) if m["v"] == ver else m.group(0), text),
                     encoding="utf-8")
        out.append(rel)
    return out


def _rewrite_prose(repo: Path, new: str) -> None:
    """Set the version in the sentences that name it (devcheck.VERSION_TEXTS)."""
    import re
    from .devcheck import VERSION_TEXTS
    for rel, pattern in VERSION_TEXTS:
        f = repo / rel
        if not f.is_file():
            continue
        rx = re.compile(pattern.replace(r"\ ", " ").replace(" ", r"\s+"))
        text = f.read_text(encoding="utf-8")
        m = rx.search(text)
        if m:
            f.write_text(text[:m.start("head")] + new + text[m.end("head"):], encoding="utf-8")
    status = repo / "docs/implementation-status.yaml"           # the page generated from it follows
    if status.is_file():
        from .cli import inventory_markdown
        (repo / "docs/implementation-status.md").write_text(inventory_markdown(load_yaml(status)), encoding="utf-8")


def bump(repo: Path, base: str = DEFAULT_BASE, note: str | None = None) -> dict:
    """Freeze the base version, raise the one version to what the change needs, and register the step."""
    repo = Path(repo).resolve()
    layout.refuse_bundled(repo, "scale schema bump")
    c = compare(repo, base)
    if not c["changed"]:
        raise ScaleError("the schema is unchanged against the base: nothing to bump")
    ver, new = c["base_version"], c["needs_version"]
    if c["head_version"] != ver:
        raise ScaleError(f"the schema is at {c['head_version']} already (the base is {ver}); bump once per change")
    man = _manifest(repo)
    fz, kfz = layout.frozen_graph_dir(man), repo / layout.KERNEL_FROZEN
    frozen_dir, frozen_man, frozen_kernel = fz / f"v{ver}", fz / f"scale-catal-{ver}.yaml", kfz / f"kernel-{ver}.yaml"
    for p in (frozen_dir, frozen_man, frozen_kernel):
        if p.exists():
            raise ScaleError(f"{p.relative_to(repo)} exists already: version {ver} was frozen before")
    readme = repo / DIGEST_TABLE
    if readme.is_file() and not re.search(rf"^\| scale-catal {re.escape(ver)} \|", readme.read_text(encoding="utf-8"), re.M):
        raise ScaleError(f"{DIGEST_TABLE} has no row `| scale-catal {ver} | ... |` in its table of spec digests")
    with tempfile.TemporaryDirectory() as tmp:
        root = base_tree(repo, c["merge_base"], Path(tmp))
        bman = _manifest(root)
        head = load_yaml(bman)
        kfz.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / layout.KERNEL, frozen_kernel)
        append_frozen_sums(kfz, [frozen_kernel])
        parts = [x for key in PACKAGE_KEYS for x in head.get(key) or []]
        for rel in parts:
            (frozen_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bman.parent / rel, frozen_dir / rel)
    fm = copy.deepcopy(head)
    fm["status"] = "frozen"
    fm["kernel"] = os.path.relpath(frozen_kernel, fz)
    for key in PACKAGE_KEYS:
        if key in head:
            fm[key] = [f"v{ver}/{x}" for x in head.get(key) or []]
    frozen_man.parent.mkdir(parents=True, exist_ok=True)
    frozen_man.write_text(f"# Frozen copy of scale-catal {ver}. Documents that pin {ver} validate against it. Do not edit;\n"
                          f"# the current version is ../{man.name}.\n" + dump_yaml(fm))
    append_frozen_sums(fz, [frozen_man] + [frozen_dir / rel for rel in parts])
    set_version(man, "version", new)
    for rel, key in VERSION_FILES:
        if (repo / rel).is_file():
            set_version(repo / rel, key, new)
    _register_step(repo, ver, new, note or (f"{c['kind']} change" if c["tier"] >= 2 else c["kind"]))
    _rewrite_prose(repo, new)
    _record_digest(repo, ver, new, pgraph.spec_sha256(pgraph.load_spec(man)))
    repinned = _repin(repo, added_documents(repo, c["merge_base"]), ver, new)
    return {**{k: c[k] for k in ("base_version", "kind", "tier", "diff")}, "version": new,
            "frozen": [p.relative_to(repo).as_posix() for p in (frozen_kernel, frozen_man, frozen_dir)],
            "step": f"{ver} -> {new}", "repinned": repinned,
            "next": ("register the rewrite rule in tools/pgraph_migrate.py STEP_RULES (a breaking change), "
                     if c["tier"] == 3 else "") + "add tests for what was added, and a CHANGELOG line"}


# ------------------------------------------------------------------------------------------ check
def _added_types(d: dict) -> list[tuple[str, str]]:
    """The labels and edge types the diff adds: (kind, name)."""
    return [(x.split(".")[0], x.split(".")[1]) for x in d["added"] if re.fullmatch(r"(nodes|edges)\.[A-Za-z_]+", x)]


def _not_provisional(repo: Path, d: dict) -> list[str]:
    """The labels, edge types and properties the diff adds that do not declare ``maturity: provisional`` (in the
    schema file that declares them, or, for a property, on the label or edge type it is added to)."""
    files = [Path(repo) / layout.KERNEL, *sorted((Path(repo) / layout.DOMAIN / "graph").glob("*.yaml"))]
    docs = [load_yaml(f) or {} for f in files if f.is_file()]
    out = []
    kernel = docs[0] if docs else {}
    for path in d["added"]:
        parts = path.split(".")
        if parts[0] == "quantities" and len(parts) == 3:          # a kind, a context or a dimension of the contracts
            block = kernel.get("quantities") or {}
            entry = (block.get(parts[1]) or {}).get(parts[2])
            if "provisional" not in (block.get("maturity"), (entry or {}).get("maturity") if isinstance(entry, dict) else None):
                out.append(path)
            continue
        if parts[0] == "value" and len(parts) == 2:               # a field of the kernel's value object
            field = ((kernel.get("value") or {}).get("fields") or {}).get(parts[1]) or {}
            if "provisional" not in (field.get("maturity"), kernel.get("maturity")):
                out.append(path)
            continue
        if parts[0] not in ("nodes", "edges") or len(parts) not in (2, 3):
            continue
        for doc in docs:
            owner = (doc.get(parts[0]) or {}).get(parts[1])
            if not isinstance(owner, dict):
                continue
            target = owner if len(parts) == 2 else ((owner.get("properties") or {}).get(parts[2]))
            if not isinstance(target, dict):
                continue
            if "provisional" not in (target.get("maturity"), owner.get("maturity"), doc.get("maturity")):
                out.append(path)
            break
    return out


def _used_in_fixtures(repo: Path, kind: str, name: str) -> bool:
    key = '"label"' if kind == "nodes" else '"type"'
    pat = re.compile(rf'{key}\s*:\s*"{re.escape(name)}"')
    for root in FIXTURE_ROOTS:
        for f in (Path(repo) / root).rglob("*.json") if (Path(repo) / root).is_dir() else []:
            if "invalid" in f.parts:
                continue
            if pat.search(f.read_text(encoding="utf-8", errors="ignore")):
                return True
    return False


def check(repo: Path, base: str = DEFAULT_BASE) -> dict:
    """What a pull request that changes the schema must carry (the module docstring), against the base."""
    repo = Path(repo).resolve()
    c = compare(repo, base)
    problems: list[str] = []
    if not c["changed"]:
        if c["head_version"] != c["base_version"]:
            problems.append(f"the version is raised to {c['head_version']} but the schema is unchanged (base "
                            f"{c['base_version']})")
        return {**c, "problems": problems, "ok": not problems}
    ver, new = c["base_version"], c["needs_version"]
    if c["head_version"] != new:
        problems.append(f"a {c['kind']} change raises {ver} to {new}; the schema is at {c['head_version']} "
                        f"(run `scale schema bump`)")
    man = _manifest(repo)
    frozen_man = layout.frozen_graph_dir(man) / f"scale-catal-{ver}.yaml"
    frozen_kernel = repo / layout.KERNEL_FROZEN / f"kernel-{ver}.yaml"
    if not frozen_man.is_file() or not frozen_kernel.is_file():
        problems.append(f"the base version {ver} is not frozen (run `scale schema bump`)")
    else:
        try:
            if pgraph.spec_sha256(pgraph.load_spec(frozen_man)) != c["base_sha256"]:
                problems.append(f"the frozen copy of {ver} is not the base's schema (its spec digest differs)")
        except ScaleError as e:
            problems.append(f"the frozen copy of {ver} does not load: {e}")
    for rel, key in VERSION_FILES:
        if (repo / rel).is_file() and str(load_yaml(repo / rel).get(key)) != c["head_version"]:
            problems.append(f"{rel} states {key} {load_yaml(repo / rel).get(key)}, not {c['head_version']}")
    steps, rules = repo_steps(repo)
    if steps.get(ver, (None,))[0] != c["head_version"]:
        problems.append(f"no migration step {ver} -> {c['head_version']} in tools/pgraph_migrate.py STEPS "
                        "(run `scale schema bump`)")
    if c["tier"] == 3 and ver not in rules:
        problems.append(f"a breaking change needs its rewrite rule: STEP_RULES[{ver!r}] in tools/pgraph_migrate.py "
                        "(a function that rewrites documents, or reports that none needs it)")
    for path in _not_provisional(repo, c["diff"]):
        problems.append(f"{path} is new but not `maturity: provisional` (new concepts enter as provisional)")
    for kind, name in _added_types(c["diff"]):
        if not _used_in_fixtures(repo, kind, name):
            problems.append(f"{kind[:-1]} {name} is added but used in no valid fixture or example document (add a test)")
    readme = repo / DIGEST_TABLE
    if readme.is_file() and c["head_version"] == new:
        if _digest_row(new, c["head_sha256"]) not in readme.read_text(encoding="utf-8"):
            problems.append(f"{DIGEST_TABLE} does not record the spec digest of {new} (`{c['head_sha256']}`) in its "
                            "table (run `scale schema bump`)")
        if f"| scale-catal {ver} (frozen) |" not in readme.read_text(encoding="utf-8"):
            problems.append(f"{DIGEST_TABLE} does not mark {ver} frozen in its table of spec digests")
    for rel in _documents_pinning(repo, added_documents(repo, c["merge_base"]), ver):
        problems.append(f"{rel} is added by this change but pins {ver}; documents written for it pin "
                        f"{c['head_version']}")
    if (repo / "CHANGELOG.md").read_bytes() == _git(repo, "show", f"{c['merge_base']}:CHANGELOG.md"):
        problems.append("the schema changes but CHANGELOG.md does not (add a line under Unreleased)")
    return {**c, "problems": problems, "follow_ups": stale_bundles(repo, c["head_version"]), "ok": not problems}


BUNDLE_ROOTS = ("examples", "domain/examples", "core/examples")


def stale_bundles(repo: Path, version: str) -> list[dict]:
    """Knowledge-graph bundles (zips holding a ``bundle.json``) under the example folders whose schema version is not
    ``version``: a follow-up for a separate issue (re-export them), never a reason to hold the change back."""
    import zipfile
    out = []
    for root in BUNDLE_ROOTS:
        for z in sorted((Path(repo) / root).rglob("*.zip")) if (Path(repo) / root).is_dir() else []:
            try:
                with zipfile.ZipFile(z) as f:
                    name = next((n for n in f.namelist() if n.count("/") == 1 and n.endswith("/bundle.json")), None)
                    m = json.loads(f.read(name)) if name else None
            except (zipfile.BadZipFile, ValueError, KeyError):
                continue
            if m and str(m.get("schema_version")) != str(version):
                out.append({"bundle": z.relative_to(repo).as_posix(), "schema_version": m.get("schema_version"),
                            "version": m.get("version")})
    return out


def summary(res: dict) -> str:
    """The reviewer's summary (Markdown) of a pull request's schema change."""
    if not res["changed"]:
        return "This pull request does not change the schema."
    d = res["diff"]
    L = [f"**Schema change: {res['kind']}**, scale-catal {res['base_version']} -> {res['head_version']} "
         f"(needs {res['needs_version']}).", ""]
    for key in ("added", "loosened", "changed", "narrowed", "removed"):
        if d[key]:
            L.append(f"- {key} ({len(d[key])}): " + "; ".join(d[key][:12]) + (" …" if len(d[key]) > 12 else ""))
    L += ["", "**Checks:** " + ("all pass." if res["ok"] else "")]
    L += [f"- {p}" for p in res["problems"]]
    if res.get("follow_ups"):
        L += ["", f"**Follow-ups (a separate issue, not part of this change):** re-export these bundles at schema "
                  f"{res['head_version']}:"]
        L += [f"- `{b['bundle']}` (bundle {b['version']}, schema {b['schema_version']})" for b in res["follow_ups"]]
    return "\n".join(L)


def verify_frozen(repo: Path) -> dict:
    """The frozen scale-catal copies are unchanged: in every frozen directory each file is listed in its SHA256SUMS
    with its digest, and every listed file exists. A schema never changed yet (0.1.0) has no frozen version."""
    repo = Path(repo)
    bad, files, dirs = [], 0, []
    for fz in layout.frozen_graph_dirs(repo):
        rel_dir = fz.relative_to(repo).as_posix()
        if not (fz / layout.FROZEN_SUMS).exists():
            raise ScaleError(f"{rel_dir}/{layout.FROZEN_SUMS} is missing")
        known = _sums(fz)
        actual = {p.relative_to(fz).as_posix(): _sha(p) for p in sorted(fz.rglob("*"))
                  if p.is_file() and p.name != layout.FROZEN_SUMS and "__pycache__" not in p.parts and p.name != ".DS_Store"}
        bad += [f"{rel_dir}/{k}" for k in sorted(set(known) | set(actual)) if known.get(k) != actual.get(k)]
        files += len(known)
        dirs.append({"dir": rel_dir, "files": len(known)})
        if not known:
            bad.append(f"{rel_dir}/{layout.FROZEN_SUMS} (empty)")
    bad += missing_frozen(repo)
    return {"ok": not bad, "files": files, "dirs": dirs, "mismatched": bad}


def missing_frozen(repo: Path, steps: dict | None = None) -> list[str]:
    """Every version a registered migration step leads away from, on the way to the head, is frozen with its kernel:
    documents may pin it."""
    repo = Path(repo)
    man = _manifest(repo)
    if not man.is_file():
        return []
    head = str(load_yaml(man).get("version"))
    if steps is None:
        steps = repo_steps(repo)[0] if (repo / MIGRATE).is_file() else {}
    out = []
    for frm in steps:
        seen, v = set(), frm
        while v in steps and v not in seen and v != head:
            seen.add(v)
            v = steps[v][0]
        if v != head:
            continue
        for f in (layout.frozen_graph_dir(man) / f"scale-catal-{frm}.yaml", repo / layout.KERNEL_FROZEN / f"kernel-{frm}.yaml"):
            if not f.is_file():
                out.append(f"{f.relative_to(repo).as_posix()} is missing (a step moves documents from {frm} to the head {head})")
    return out
