"""Schema change proposals for scale-graph: from curation gaps to a reviewed, applied schema version.

A proposal is a directory named by its six-digit number: ``core/proposals/<NNNNNN>/`` (kernel changes) or
``domain/proposals/<NNNNNN>/`` (the catalysis domain's files), holding

- ``proposal.yaml`` — written by a person or an agent: the base schema, the target version (the schema's one
  version, kernel and catalysis together: a proposal raises it whichever file it changes), the
  gap themes it answers (and those it defers or rejects, with reasons), the operations on the
  schema files, fixtures that must pass and counterexamples that must fail, the documents whose
  migration is assessed, the competency questions to re-run, and the review areas;
- ``candidate/`` — the base schema with the operations applied (``scale proposal build``);
- ``evidence_pack.json``, ``patch.diff``, ``validation_report.json``, ``migration_assessment.json``,
  ``critic_report.json``, ``review_checklist.md``, ``PR_BODY.md`` — written by ``scale proposal check``.
  When a proposal reads inputs that are not committed (gap sources or assessed documents found only in the
  optional restricted copy, ``layout.restricted_root``: ``$SCALE_RESTRICTED_DATA``), the full reports go to the
  restricted copy, at the proposal's repository-relative path (``layout.restricted_path``), and the proposal
  folder gets a public summary of each: no gap statement, no record of the restricted documents (their ids,
  record-level changes or errors), and a PR body that says the details are restricted. The restricted copy may
  also hold the proposal's original ``proposal.yaml``, whose ``motivation`` the full PR body then uses;
- ``approvals/`` — one file per review of the merged pull request, written by ``scale proposal
  apply-merged`` from GitHub's reviews; only people approve, by reviewing the pull request.

``scale review status`` evaluates the approvals against ``governance/review-policy.yaml`` (one reviewer
other than the author); ``scale proposal decide`` writes the decision record; ``scale proposal apply --confirm`` freezes the base
version (the kernel into ``core/graph/frozen/kernel-<v>.yaml``, the domain's files and manifest into
``domain/graph/frozen/``, all under the base's one version ``<v>``) and installs the candidate as the new head.

The schema a proposal changes is the catalysis manifest, ``domain/graph/scale-graph.yaml``
(``base.manifest``): the science kernel plus the catalysis file. There is no repository-wide composition; a
kernel proposal is assessed through the catalysis manifest, the one manifest that uses the head kernel, and
raises the same one version as a catalysis proposal. Every part is keyed by its repository-relative
path (operations name files that way) and the candidate mirrors those paths, so the candidate manifest's
relative entries resolve inside ``candidate/`` exactly as the head's do in the repository.

A proposal's id is its directory name, a six-digit number global across the core and every domain
(``000001`` …; ``layout.proposal_dirs`` refuses a number used twice, and ``scale proposal new`` allocates
the next); the folder's location decides the owner and the title stays in ``proposal.yaml``. The id is
always a string (``id: '000001'``, quoted, so that YAML never reads it as a number), and every record
names a proposal by it (decision log, approvals, the manifests' ``proposals``, the gap register).

Operations (``proposal.operations``), each on one schema file, addressed by a dotted path::

    - {op: add, file: domain/graph/catalysis.yaml, path: nodes.CatalyticTest.properties,
       key: approach_to_equilibrium, value: {type: value, description: …}, resolves: [G-02]}
    - {op: extend, file: …, path: nodes.CatalyticTest.properties.test_kind.values, values: [equilibrium_measurement]}
    - {op: set, file: …, path: …, value: …, reason: …}          # replaces an existing value
    - {op: remove, file: …, path: …, reason: …}                # breaking
    - {op: rename, file: …, path: module, to: domain, reason: …}   # a key, renamed where it stands
    - {op: add, file: …, path: nodes, key: Heater, moved_from: domain/graph/driving-forces/thermocatalysis.yaml}

A concept an operation adds (a label, an edge type, a property) enters with ``maturity:
provisional``, ``added_in`` and ``proposal`` (the proposal's id)
unless it says otherwise; the check refuses stable entry. An ``add`` with ``moved_from`` takes its value verbatim from the same path of another file of
the base schema (a restructuring: the concept is not new and keeps what it carries). Whole files
are added (``add_files``) or removed (``remove_files``); a removed file also leaves the manifest's lists. Tiers follow the semantic diff of the assembled schemas: additions and loosenings are
tier 2 (provisional meaning), removals, narrowings, new requirements and type changes tier 3.
"""

from __future__ import annotations

import copy
import datetime as _dt
import difflib
import re
import shutil
from pathlib import Path

import yaml

from . import layout
from .util import ScaleError, dump_yaml, load_doc, load_yaml, sha256_file, write_canonical

OPS = ("add", "extend", "set", "remove", "rename")
RESOLUTIONS = ("addressed", "deferred", "rejected", "guide")      # guide: answered by curation guidance, no schema change


# ------------------------------------------------------------------------------------------ paths
def _walk(doc: dict, path: str, create: bool = False):
    cur = doc
    for part in [p for p in path.split(".") if p]:
        if not isinstance(cur, dict):
            raise ScaleError(f"path {path!r}: {part!r} is inside a non-mapping")
        if part not in cur:
            if not create:
                raise ScaleError(f"path {path!r}: {part!r} does not exist")
            cur[part] = {}
        cur = cur[part]
    return cur


def apply_op(doc: dict, op: dict, pid: str, version: str) -> dict:
    kind = op.get("op")
    if kind not in OPS:
        raise ScaleError(f"unknown operation {kind!r}; operations: {OPS}")
    if kind == "add":
        parent = _walk(doc, op["path"], create=True)
        if op["key"] in parent:
            raise ScaleError(f"add: {op['path']}.{op['key']} already exists (use set to change it)")
        val = copy.deepcopy(op["value"])
        if isinstance(val, dict) and _is_concept_path(op["path"]) and not op.get("moved_from"):
            val.setdefault("maturity", "provisional")
            val.setdefault("added_in", version)
            val.setdefault("proposal", pid)
        parent[op["key"]] = val
    elif kind == "extend":
        lst = _walk(doc, op["path"])
        if not isinstance(lst, list):
            raise ScaleError(f"extend: {op['path']} is not a list")
        for v in op["values"]:
            if v in lst:
                raise ScaleError(f"extend: {v!r} is already in {op['path']}")
            lst.append(v)
    elif kind == "set":
        head, _, last = op["path"].rpartition(".")
        parent = _walk(doc, head)
        if last not in parent:
            raise ScaleError(f"set: {op['path']} does not exist (use add)")
        parent[last] = copy.deepcopy(op["value"])
    elif kind == "rename":                              # the key keeps its place and its value (a file's kind key, …)
        head, _, last = op["path"].rpartition(".")
        parent = _walk(doc, head)
        new = op.get("to")
        if not isinstance(parent, dict) or last not in parent:
            raise ScaleError(f"rename: {op['path']} does not exist")
        if not isinstance(new, str) or not new or "." in new:
            raise ScaleError(f"rename: `to` is the new key (one name, no dots), not {new!r}")
        if new in parent:
            raise ScaleError(f"rename: {head + '.' if head else ''}{new} already exists")
        items = list(parent.items())
        parent.clear()
        parent.update((new if k == last else k, v) for k, v in items)
    else:
        head, _, last = op["path"].rpartition(".")
        parent = _walk(doc, head)
        if last not in parent:
            raise ScaleError(f"remove: {op['path']} does not exist")
        del parent[last]
    return doc


def _is_concept_path(path: str) -> bool:
    """Adding under nodes, edges or a properties map adds a concept."""
    parts = path.split(".")
    return parts[-1] in ("nodes", "edges", "properties") or (len(parts) == 1 and parts[0] in ("nodes", "edges"))


# ------------------------------------------------------------------------------------------ build
def load_proposal(cs: Path) -> dict:
    p = load_yaml(cs / "proposal.yaml")
    for k in ("id", "title", "kind", "base", "target_version", "operations"):
        if k not in p:
            raise ScaleError(f"proposal.yaml needs {k!r}")
    if p["kind"] != "scale-graph":
        raise ScaleError("this tool handles scale-graph proposals (kind: scale-graph)")
    if not isinstance(p["id"], str):                 # id: 000007 unquoted is the YAML 1.1 octal number 7
        raise ScaleError(f"{cs / 'proposal.yaml'}: id {p['id']!r} is not a string; quote it (id: '{cs.name}')")
    bare = layout.proposal_yaml_unquoted_id(cs)
    if bare is not None:                             # id: 000009 is a string to PyYAML, the integer 9 to YAML 1.2
        raise ScaleError(f"{cs / 'proposal.yaml'}: id {bare} is unquoted; quote it (id: '{bare}')")
    return p


def new_proposal(repo: Path, owner: str, title: str | None = None, manifest: str | None = None,
                 now: _dt.datetime | None = None) -> Path:
    """Allocate the next six-digit number (global: the highest of any proposal, core or domain, plus one) and
    scaffold ``<owner's proposals>/<NNNNNN>/proposal.yaml``, based on the head of the domain schema manifest it
    changes (the owner domain's; for ``core``, ``manifest`` or the only released domain's) and targeting its
    next minor version. The operations, fixtures and the rest are left for the author; ``scale proposal
    check`` says what is missing."""
    repo = Path(repo)
    layout.refuse_bundled(repo, "scale proposal new")
    root = layout.proposal_root(repo, owner)
    mans = layout.graph_manifests(repo, experimental=True)
    if manifest:
        man = repo / manifest
        if man.resolve() not in {m.resolve() for m in mans.values()}:
            raise ScaleError(f"--manifest {manifest} is not a domain's schema manifest: "
                             f"{sorted(m.relative_to(repo).as_posix() for m in mans.values())}")
    elif owner != layout.CORE:
        if owner not in mans:
            raise ScaleError(f"the domain {owner} has no schema manifest (DOMAIN.yaml graph.manifest) to change")
        man = mans[owner]
    else:
        released = layout.graph_manifests(repo)
        if len(released) != 1:
            raise ScaleError("a kernel proposal is assessed through one domain's manifest: pass --manifest "
                             f"({', '.join(sorted(m.relative_to(repo).as_posix() for m in released.values()))})")
        man = next(iter(released.values()))
    decl = repo / layout.CORE_MANIFEST if owner == layout.CORE else root.parent / layout.DOMAIN_MANIFEST
    areas = list(((load_yaml(decl) if decl.is_file() else {}) or {}).get("review_areas") or [])[:1]
    version = str(load_yaml(man).get("version"))
    major, minor, _ = (int(x) for x in version.split("."))
    pid = layout.next_proposal_id(repo)
    dest = root / pid
    if dest.exists():
        raise ScaleError(f"{dest} exists already")
    now = now or _dt.datetime.now(_dt.timezone.utc)
    doc = {"id": pid, "title": title or "(a short title of the change)", "kind": "scale-graph", "status": "draft",
           "opened_at": now.replace(microsecond=0).isoformat(), "proposer": {"name": "", "agent": False}, "areas": areas,
           "base": {"manifest": man.relative_to(repo).as_posix(), "version": version},
           "target_version": f"{major}.{minor + 1}.0",
           "motivation": "What curation could not record, with sources and locators, and why the change is the general one.\n",
           "gap_sources": [], "gap_themes": [], "operations": [], "fixtures": {"pass": [], "fail": []},
           "assess_documents": [], "expected_query_changes": [], "mappings_considered": []}
    dest.mkdir(parents=True)
    (dest / "proposal.yaml").write_text(
        f"# proposal {pid}: a schema change proposal (tools/skills/evolve-schema/SKILL.md). Fill in the gaps it answers,\n"
        f"# the operations, fixtures and counterexamples; register its migration step in tools/scale/pgraph_migrate.py\n"
        f"# (STEPS: \"{version}\": (\"{major}.{minor + 1}.0\", \"{pid}\")), then run `scale proposal check {pid}`.\n"
        + dump_yaml(doc))
    return dest


def head_manifest(repo: Path, proposal: dict) -> Path:
    """The domain schema manifest the proposal changes: ``base.manifest`` (repository-relative). A missing path is
    an error, so a misspelled manifest fails loudly."""
    repo = Path(repo)
    rel = str((proposal.get("base") or {}).get("manifest") or "")
    mans = layout.graph_manifests(repo, experimental=True)
    if rel and (repo / rel).is_file():
        if (repo / rel).resolve() not in {m.resolve() for m in mans.values()}:
            raise ScaleError(f"base.manifest {rel} is not a domain's schema manifest (DOMAIN.yaml graph.manifest): "
                             f"{sorted(m.relative_to(repo).as_posix() for m in mans.values())}")
        return repo / rel
    raise ScaleError(f"{proposal.get('id')}: base.manifest {rel or '(none)'} does not exist; "
                     f"set it to {layout.DOMAIN}/{layout.DOMAIN_GRAPH_MANIFEST}")


def base_manifest(repo: Path, proposal: dict) -> Path:
    """The base schema: the domain's head manifest while it is at the base version, afterwards (once
    the proposal is applied) its frozen copy ``frozen/scale-graph-<version>.yaml`` beside it."""
    from .pgraph import frozen_spec
    head = head_manifest(repo, proposal)
    if load_yaml(head).get("version") == proposal["base"]["version"]:
        return head
    frozen = frozen_spec(head, proposal["base"]["version"])
    if not frozen.exists():
        raise ScaleError(f"base {head} is {load_yaml(head).get('version')} and there is no frozen {frozen.name}")
    return frozen


PACKAGE_KEYS = ("modules", "extensions", "profiles", "domains")


def _strip(rel: str) -> str:
    return re.sub(r"^v\d+\.\d+\.\d+/", "", rel)


def _repo_rel(repo: Path, p: Path, what: str) -> str:
    """``p`` (lexically normalized) relative to the repository; a part outside it is refused."""
    import os
    norm = Path(os.path.normpath(p))
    try:
        return norm.relative_to(Path(os.path.normpath(Path(repo).resolve()))).as_posix()
    except ValueError:
        raise ScaleError(f"{what}: {p} lies outside the repository") from None


def _entries(repo: Path, man: Path) -> tuple[dict, list[tuple[str, int, str, Path]]]:
    """The manifest and one (manifest key, index, part key, file) per entry. A part key is the part's
    head path, repository-relative (``core/graph/kernel.yaml``, ``domain/graph/catalysis.yaml``).
    A frozen manifest's parts map back onto the head: ``frozen/v<v>/<rel>`` to ``<the domain's graph
    dir>/<rel>``, its kernel (``core/graph/frozen/kernel-<v>.yaml``) to the kernel."""
    repo = Path(repo).resolve()
    man = Path(man).resolve()
    m = load_yaml(man)
    frozen = man.parent.name == layout.GRAPH_FROZEN
    graph_dir = _repo_rel(repo, man.parent.parent if frozen else man.parent, str(man))
    out = []
    for key, i, e in [("kernel", 0, m["kernel"])] + [(k, i, x) for k in PACKAGE_KEYS for i, x in enumerate(m.get(k) or [])]:
        src = layout.kernel_path(man.parent, e) if key == "kernel" else man.parent / e
        rel = _repo_rel(repo, src, f"{man.name}: {e}")
        if key == "kernel":
            rel = layout.KERNEL if rel.startswith(f"{layout.KERNEL_FROZEN}/") else rel
        elif frozen and _strip(e) != e:
            rel = f"{graph_dir}/{_strip(e)}"
        out.append((key, i, rel, src))
    return m, out


def _base_files(repo: Path, man: Path) -> tuple[dict, dict[str, Path]]:
    """The manifest and its files by part key (see :func:`_entries`)."""
    m, entries = _entries(repo, man)
    return m, {rel: src for _, _, rel, src in entries}


def _key(f: str, keys, head_dir: str) -> str:
    """An operation's file as a part key: repository-relative, or relative to the domain's graph directory
    (``catalysis.yaml``)."""
    for alt in (f, f"{head_dir}/{f}"):
        if alt in keys:
            return alt
    return f


def _resolved(repo: Path, p: dict) -> tuple[Path, Path, dict, dict[str, Path], dict]:
    """(head manifest, base manifest, base manifest content, parts by key, the proposal with every
    file path as a part key)."""
    head = head_manifest(repo, p)
    man = base_manifest(repo, p)
    m, srcs = _base_files(repo, man)
    head_dir = Path(_repo_rel(Path(repo).resolve(), head.resolve(), str(head))).parent.as_posix()
    q = copy.deepcopy(p)
    for op in q.get("operations") or []:
        if isinstance(op, dict) and isinstance(op.get("file"), str):
            op["file"] = _key(op["file"], srcs, head_dir)
    for a in q.get("add_files") or []:                 # a new file: repository-relative, else beside the manifest
        if not str(a["path"]).startswith((f"{layout.CORE}/", f"{layout.DOMAIN}/")):
            a["path"] = f"{head_dir}/{a['path']}"
    q["remove_files"] = [_key(r, srcs, head_dir) for r in q.get("remove_files") or []]
    for op in q.get("operations") or []:
        if isinstance(op, dict) and isinstance(op.get("moved_from"), str):
            op["moved_from"] = _key(op["moved_from"], srcs, head_dir)
    return head, man, m, srcs, q


def _moved_value(op: dict, srcs: dict[str, Path], i: int):
    """The value an ``add`` with ``moved_from`` takes: the same path and key in that base file, verbatim."""
    if op.get("op") != "add" or "value" in op:
        raise ScaleError(f"operation {i}: moved_from goes with op add and no value (the value is the source's)")
    if op["moved_from"] not in srcs:
        raise ScaleError(f"operation {i}: moved_from {op['moved_from']} is not a file of the base schema")
    try:
        parent = _walk(load_yaml(srcs[op["moved_from"]]), op["path"])
    except ScaleError as e:
        raise ScaleError(f"operation {i}: moved_from {op['moved_from']}: {e}") from None
    if not isinstance(parent, dict) or op["key"] not in parent:
        raise ScaleError(f"operation {i}: moved_from {op['moved_from']} has no {op['path']}.{op['key']}")
    return copy.deepcopy(parent[op["key"]])


def _as_head(repo: Path, man: Path, head_rel: str) -> dict:
    """The base manifest with its entries pointing at the head's parts, relative to the head manifest
    (``head_rel``): a frozen copy's ``v<v>/`` parts and frozen kernel map back to the head paths."""
    import os
    head_dir = Path(head_rel).parent.as_posix()
    entry = lambda key: os.path.relpath(key, head_dir) if head_dir != "." else key   # noqa: E731
    m, entries = _entries(repo, man)
    hm = copy.deepcopy(m)
    for key, i, rel, _ in entries:
        if key == "kernel":
            hm["kernel"] = entry(rel)
        else:
            hm[key][i] = entry(rel)
    return hm


def build(cs: Path, repo: Path) -> Path:
    """candidate/ = the base schema's files with the operations applied and the version raised, at their
    repository-relative paths; the candidate manifest sits where the domain's head manifest does."""
    repo = Path(repo).resolve()
    layout.refuse_bundled(repo, "scale proposal build")
    p = load_proposal(cs)
    head, man, m, srcs, q = _resolved(repo, p)
    if m.get("version") != p["base"]["version"]:
        raise ScaleError(f"base {man} is {m.get('version')}, the proposal says {p['base']['version']}")
    dest = cs / "candidate"
    if dest.exists():
        shutil.rmtree(dest)
    try:
        return _build_into(dest, cs, repo, p, head, man, srcs, q)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)        # never a partial candidate left behind
        raise


def _build_into(dest: Path, cs: Path, repo: Path, p: dict, head: Path, man: Path, srcs: dict, q: dict) -> Path:
    head_rel = _repo_rel(repo, head.resolve(), str(head))
    files = [head_rel] + list(srcs)
    for rel, src in srcs.items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / rel)
    hm = _as_head(repo, man, head_rel)                 # entries re-pointed at the mirrored parts
    removed = set(q.get("remove_files") or [])
    drop = {(key, i) for key, i, rel, _ in _entries(repo, man)[1] if key != "kernel" and rel in removed}
    for key in PACKAGE_KEYS:                            # a removed file leaves the manifest's lists too
        if key in hm:
            hm[key] = [x for i, x in enumerate(hm[key] or []) if (key, i) not in drop]
    hm["status"] = "candidate"
    (dest / head_rel).parent.mkdir(parents=True, exist_ok=True)
    (dest / head_rel).write_text(dump_yaml(hm))
    # whole files the proposal adds (its files/ directory) or removes (a restructuring proposal)
    for add, raw in zip(q.get("add_files") or [], p.get("add_files") or []):
        src = cs / add["from"]
        if not src.exists():
            raise ScaleError(f"add_files: {add['from']} does not exist in the proposal")
        if add["path"] in files:
            raise ScaleError(f"add_files: {raw['path']} is already part of the base schema")
        (dest / add["path"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / add["path"])
        files.append(add["path"])
    for rel in q.get("remove_files") or []:
        if rel not in files or rel in (head_rel, layout.KERNEL):
            raise ScaleError(f"remove_files: {rel} is not a removable file of the base schema (a part other than "
                             "the manifest and the kernel)")
        (dest / rel).unlink()
        files.remove(rel)
        if not any((dest / rel).parent.iterdir()):
            (dest / rel).parent.rmdir()
    docs: dict[str, dict] = {}
    for i, op in enumerate(q["operations"]):
        f = op.get("file")
        if f not in files:
            raise ScaleError(f"operation {i}: file {p['operations'][i].get('file')!r} is not part of the base schema or the "
                             f"added files (repository-relative: {sorted(files)})")
        doc = docs.setdefault(f, load_yaml(dest / f))
        if op.get("moved_from") is not None:
            op = {**op, "value": _moved_value(op, srcs, i)}
        try:
            apply_op(doc, op, p["id"], p["target_version"])
        except ScaleError as e:
            raise ScaleError(f"operation {i} ({op.get('op')} {op.get('path')}): {e}") from None
    for f, doc in docs.items():
        (dest / f).write_text(dump_yaml(doc))
    cand = load_yaml(dest / head_rel)
    cand["version"], cand["status"], cand["proposal"] = p["target_version"], "candidate", p["id"]
    (dest / head_rel).write_text(dump_yaml(cand))
    return dest / head_rel


def candidate_files(cand: Path) -> dict[str, Path]:
    """A candidate's files by their repository-relative paths."""
    cand = Path(cand)
    return {p.relative_to(cand).as_posix(): p for p in sorted(cand.rglob("*")) if p.is_file()}


def candidate_differences(a: Path, b: Path) -> list[str]:
    """How two candidates differ (none: the same candidate), file by file, byte for byte."""
    fa, fb = candidate_files(a), candidate_files(b)
    out = [f"{k}: only in {'the first' if k in fa else 'the second'}" for k in sorted(set(fa) ^ set(fb))]
    out += [f"{k} differs" for k in sorted(set(fa) & set(fb)) if fa[k].read_bytes() != fb[k].read_bytes()]
    return out


# ------------------------------------------------------------------------------------------ semantic diff
def _props(d: dict) -> dict:
    return d.get("properties") or {}


def diff_specs(a: dict, b: dict) -> dict:
    """Additions, removals and changes between two assembled scale-graph schemas."""
    out = {"added": [], "removed": [], "changed": [], "narrowed": [], "loosened": []}

    def cmp_props(where: str, pa: dict, pb: dict) -> None:
        for k in sorted(set(pa) | set(pb)):
            if k not in pa:
                out["added"].append(f"{where}.{k}")
            elif k not in pb:
                out["removed"].append(f"{where}.{k}")
            else:
                da, db = pa[k], pb[k]
                if da.get("type") != db.get("type"):
                    out["changed"].append(f"{where}.{k}: type {da.get('type')} -> {db.get('type')}")
                va, vb = set(da.get("values") or []), set(db.get("values") or [])
                if vb - va:
                    out["added"] += [f"{where}.{k} = {v}" for v in sorted(vb - va)]
                if va - vb:
                    out["removed"] += [f"{where}.{k} = {v}" for v in sorted(va - vb)]

    # the kernel's shared structures: the evidence item, the value object, the record reference and
    # the properties every node and link carries
    for where, fa, fb in (("evidence", (a.get("evidence") or {}).get("fields") or {}, (b.get("evidence") or {}).get("fields") or {}),
                          ("value", (a.get("value") or {}).get("fields") or {}, (b.get("value") or {}).get("fields") or {}),
                          ("record_ref", (a.get("record_ref") or {}).get("fields") or {}, (b.get("record_ref") or {}).get("fields") or {}),
                          ("common.node", _props((a.get("common") or {}).get("node") or {}), _props((b.get("common") or {}).get("node") or {})),
                          ("common.link", _props((a.get("common") or {}).get("link") or {}), _props((b.get("common") or {}).get("link") or {}))):
        cmp_props(where, fa, fb)
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
                out["narrowed"] += [f"profiles.{pr} {lab} requires {x}" for x in sorted(sb - sa)]
                out["loosened"] += [f"profiles.{pr} {lab} no longer requires {x}" for x in sorted(sa - sb)]
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
        vals.update(x.get("values") or {})
    return out


def tier(diff: dict) -> int:
    if diff["removed"] or diff["changed"] or diff["narrowed"]:
        return 3
    if diff["added"] or diff["loosened"]:
        return 2
    return 0


# ------------------------------------------------------------------------------------------ check
def _gap_files(repo: Path, src: str) -> list[Path]:
    """The fragments of one gap source: in the repository, or in the restricted copy.
    A source that is missing or holds no fragment is an error: read as "no gaps", it would mark every theme
    resolved in the gap register."""
    where = layout.locate(repo, src)
    files = sorted(where.glob("*.json")) if where is not None else []
    if not files:
        raise ScaleError(f"gap_sources: {src} " + ("holds no *.json fragment" if where is not None and where.is_dir()
                                                    else f"does not exist: {layout.missing_hint(repo, src)}"))
    return files


def declared_inputs(p: dict) -> list[str]:
    """Every repository-relative input that ``check`` reads through the resolver (``layout.locate``): the gap
    sources, the fixtures, the assessed documents and their competency plans. Any of them may be restricted
    project data; CI (which has none) uses this list to tell an input it cannot read from a wrong path."""
    def path(x, key: str) -> str:
        v = x.get("path") if isinstance(x, dict) else x
        if not isinstance(v, str) or not v:
            raise ScaleError(f"{key}: {x!r} names no path")
        return v
    fx = p.get("fixtures") or {}
    out = [path(s, "gap_sources") for s in p.get("gap_sources") or []]
    out += [path(f, "fixtures.pass") for f in fx.get("pass") or []] + [path(f, "fixtures.fail") for f in fx.get("fail") or []]
    for d in p.get("assess_documents") or []:
        out += [path(d, "assess_documents")] + [path(q, "competency") for q in (d.get("competency") or [] if isinstance(d, dict) else [])]
    return list(dict.fromkeys(out))


def _restricted(repo: Path, where: Path) -> bool:
    """Whether a located input lies outside the repository: the restricted copy (``layout.locate``)."""
    return not Path(where).resolve().is_relative_to(Path(repo).resolve())


def _gap_instances(repo: Path, p: dict) -> dict[str, dict]:
    """Every curation gap of kind missing_concept in the named fragments, by id <slug>#gap/<i>."""
    out = {}
    for src in p.get("gap_sources") or []:
        for f in _gap_files(repo, src):
            frag = load_doc(f)
            for i, g in enumerate(frag.get("gaps") or []):
                if g.get("kind") == "missing_concept":
                    out[f"{f.stem}#gap/{i}"] = {"source": f.stem, "text": g.get("text") or g.get("description"),
                                               "about": g.get("about"), "locator": g.get("locator"),
                                               "status": g.get("status", "open"), "resolved_by": g.get("resolved_by")}
    return out


def _existing(repo: Path, rel: str, key: str) -> Path:
    """A file a proposal names: in the repository, or in the restricted copy (documents the proposal
    assesses may be project data held back from the public tree); a missing one is an error that says where."""
    where = layout.locate(repo, rel)
    if where is None or not where.is_file():
        raise ScaleError(f"{key}: {rel} does not exist: {layout.missing_hint(repo, rel)}")
    return where


def _concepts_added(cand_dir: Path, proposal: dict) -> list[tuple[str, dict, str | None]]:
    """(where, definition, file maturity) for each concept an add operation creates."""
    out = []
    for op in proposal["operations"]:
        if op["op"] == "add" and _is_concept_path(op["path"]) and not op.get("moved_from"):   # a moved concept is not new
            fm = load_yaml(cand_dir / op["file"]).get("maturity")
            out.append((f"{op['file']}:{op['path']}.{op['key']}", op["value"], fm))
    return out


def check(cs: Path, repo: Path, now: _dt.datetime | None = None) -> dict:
    """Build, diff, validate fixtures, assess migration, re-run competency questions, criticize."""
    from . import pgraph, pgraph_query
    from .passages import index_for
    from .policy import evaluate, load_policy
    now = now or _dt.datetime.now(_dt.timezone.utc)
    p = load_proposal(cs)
    repo = Path(repo).resolve()
    cand_man = build(cs, repo)
    head, man, _, srcs, q = _resolved(repo, p)       # q: the proposal with every file as a part key
    base_spec = pgraph.load_spec(man)
    try:
        cand_spec = pgraph.load_spec(cand_man)
    except ScaleError:
        shutil.rmtree(cs / "candidate", ignore_errors=True)   # a candidate that does not load is never left to apply
        raise
    diff = diff_specs(base_spec, cand_spec)
    t = tier(diff)
    problems, objections = [], []
    public_problem: dict[int, str] = {}                 # a problem about restricted data, as the public report says it
    # inputs found only in the restricted copy: their details stay out of the public reports
    restricted_inputs: list[str] = []
    rdocs: set[str] = set()

    def located(rel: str, key: str) -> Path:
        where = _existing(repo, rel, key)
        if _restricted(repo, where) and rel not in restricted_inputs:
            restricted_inputs.append(rel)
        return where

    # gap coverage
    gaps = _gap_instances(repo, p)                  # (every gap source exists from here on)
    restricted_inputs += [s for s in p.get("gap_sources") or [] if _restricted(repo, layout.locate(repo, s))]
    rsources = {f.stem for s in restricted_inputs for f in _gap_files(repo, s)}
    themes = {th["id"]: th for th in p.get("gap_themes") or []}
    assigned: dict[str, str] = {}
    for th in themes.values():
        if th.get("resolution") not in RESOLUTIONS:
            problems.append(f"gap theme {th['id']}: resolution must be one of {RESOLUTIONS}")
        if th.get("resolution") in ("deferred", "rejected", "guide") and not th.get("reason"):
            problems.append(f"gap theme {th['id']}: a {th['resolution']} theme needs a reason")
        for gid in th.get("instances") or []:
            if gid not in gaps:
                problems.append(f"gap theme {th['id']}: {gid} is not a missing_concept gap of the named sources")
            if gid in assigned:
                problems.append(f"{gid} is assigned to both {assigned[gid]} and {th['id']}")
            assigned[gid] = th["id"]
    # every open gap must be assigned; a gap an earlier proposal resolved need not be, and once a proposal
    # is applied, gaps raised later belong to a later proposal (reported, not a problem of this one)
    unassigned = sorted(g for g in set(gaps) - set(assigned) if gaps[g]["status"] != "resolved" or gaps[g]["resolved_by"] == p["id"])
    later_gaps = unassigned if p.get("status") == "applied" else []
    if unassigned and not later_gaps:
        problems.append(f"{len(unassigned)} missing_concept gaps are assigned to no theme: {unassigned[:5]}")
    resolved_by = {th: [] for th in themes}
    for i, op in enumerate(p["operations"]):
        for th in op.get("resolves") or []:
            if th not in themes:
                problems.append(f"operation {i} resolves unknown theme {th}")
            else:
                resolved_by[th].append(i)
    for th, ops in resolved_by.items():
        if themes[th].get("resolution") == "addressed" and not ops:
            problems.append(f"gap theme {th} is 'addressed' but no operation resolves it")

    # new concepts enter as provisional
    for where, d, fm in _concepts_added(cs / "candidate", q):
        mat = d.get("maturity", "provisional")
        if mat != "provisional":
            problems.append(f"{where} enters as {mat}; new concepts enter as provisional")
        if not d.get("description"):
            objections.append({"severity": "blocking", "message": f"{where} has no description"})

    # fixtures
    fixtures = []
    for f in (p.get("fixtures") or {}).get("pass") or []:
        doc = load_doc(located(f, "fixtures.pass"))
        rep = pgraph.validate(doc, cand_spec)
        conf = rep.conformance or {}
        ok = not rep.errors and all(c["conformant"] for c in (conf.get("profiles") or {}).values())
        fixtures.append({"fixture": f, "expect": "valid and conformant", "ok": ok,
                         "errors": [f"{e['record']}: {e['message']}" for e in rep.errors][:10],
                         "violations": [v["message"] for c in (conf.get("profiles") or {}).values() for v in c["violations"]][:10]})
    for f in (p.get("fixtures") or {}).get("fail") or []:
        doc = load_doc(located(f["path"], "fixtures.fail"))
        rep = pgraph.validate(doc, cand_spec)
        msgs = [e["message"] for e in rep.errors] + [v["message"] for c in ((rep.conformance or {}).get("profiles") or {}).values()
                                                     for v in c["violations"]]
        ok = any(f["expect"] in m for m in msgs)
        fixtures.append({"fixture": f["path"], "expect": f"fails: {f['expect']}", "reason": f.get("reason"), "ok": ok,
                         "observed": msgs[:10]})
    if not any(fx["expect"].startswith("fails") for fx in fixtures):
        objections.append({"severity": "blocking", "message": "no counterexample: add a fixture that must fail for a stated reason"})

    # migration assessment and competency questions
    migration, competency = [], []
    vkey = lambda v: tuple(int(x) for x in str(v).split("."))
    for d in p.get("assess_documents") or []:
        doc_path = located(d["path"], "assess_documents")
        if _restricted(repo, doc_path):
            rdocs.add(d["path"])
        doc = load_doc(doc_path)
        pinned = doc["graph"].get("schema_version")
        if vkey(pinned) > vkey(p["target_version"]):          # the document has moved past this proposal
            migration.append({"document": d["path"], "rule": f"not assessed: pins scale-graph {pinned}, later than "
                              f"{p['target_version']}", "meaning": "meaning_preserving", "errors_before": None, "errors_after": None,
                              "skipped": True})
            continue
        from .pgraph_migrate import raise_version, route
        steps = route(doc["graph"].get("schema_version"), p["target_version"])
        to_base = route(doc["graph"].get("schema_version"), p["base"]["version"])
        built = set(layout.manifest_proposals(base_spec, man))   # only steps the base was built from lead to it
        to_base = to_base if to_base and all(s[2] in built for s in to_base) else None
        # "before" is the document at the base, so that it compares with "after" (the document at the
        # target): a document pinned at the base as it stands; an older pin moved up to the base by the
        # applied steps; otherwise the document under its own pinned schema (the base when none is frozen)
        if pinned == p["base"]["version"]:
            before = pgraph.validate(doc, base_spec)
        elif to_base:
            try:
                before = pgraph.validate(raise_version(doc, p["base"]["version"], base_spec)[0], base_spec)
            except ScaleError:
                before = pgraph.validate(doc, base_spec)
        else:
            try:
                own = pgraph.load_spec(pgraph.pinned(head, pinned))
            except ScaleError:
                own = base_spec
            before = pgraph.validate(doc, own)
        changes = None
        if steps and steps[-1][2] == p["id"]:              # the steps reach this proposal's own: run every rule on the way
            try:
                moved, mrep = raise_version(doc, p["target_version"], cand_spec)
            except ScaleError as e:
                problems.append(f"{d['path']}: the migration rule stops: {e}")
                if d["path"] in rdocs:
                    public_problem[len(problems) - 1] = f"{d['path']}: the migration rule stops (details in the restricted copy)"
                continue
            rule = mrep["steps"][-1]["rule"] if len(mrep["steps"]) == 1 else "; ".join(
                f"{s['from']} → {s['to']} ({s['proposal']}): {s['rule']}" for s in mrep["steps"])
            changes = [c for s in mrep["steps"] for c in s.get("changes") or []]
        elif to_base:                                     # an older pin: the applied steps up to the base, then the raise
            try:
                moved, mrep = raise_version(doc, p["base"]["version"], base_spec)
            except ScaleError as e:
                problems.append(f"{d['path']}: the migration rule stops: {e}")
                if d["path"] in rdocs:
                    public_problem[len(problems) - 1] = f"{d['path']}: the migration rule stops (details in the restricted copy)"
                continue
            moved["graph"]["schema_version"] = p["target_version"]
            rule = "; ".join(f"{s['from']} → {s['to']} ({s['proposal']}): {s['rule']}" for s in mrep["steps"]) + \
                f"; {p['base']['version']} → {p['target_version']} ({p['id']}): schema_version raised; no record changes"
            changes = [c for s in mrep["steps"] for c in s.get("changes") or []]
        else:
            moved = copy.deepcopy(doc)
            moved["graph"]["schema_version"] = p["target_version"]
            rule = "schema_version raised; no record changes"
        after = pgraph.validate(moved, cand_spec)
        conf = lambda r: {k: {"conformant": v["conformant"], "violations": len(v["violations"]), "recommended": v["recommended"].get("fraction")}
                          for k, v in ((r.conformance or {}).get("profiles") or {}).items()}
        migration.append({"document": d["path"], "rule": rule, **({"changes": changes} if changes is not None else {}),
                          "meaning": "meaning_preserving" if not after.errors else "requires_additional_context",
                          "errors_before": len(before.errors), "errors_after": len(after.errors),
                          "first_errors_after": [f"{e['record']}: {e['message']}" for e in after.errors[:5]],
                          "conformance_before": conf(before), "conformance_after": conf(after)})
        ix_stem = doc_path                               # the evidence index lies beside the document
        ix_stem = ix_stem.with_name(ix_stem.name.removesuffix(".json").removesuffix(".graph") + ".evidence")
        ix = None
        ga, gb = pgraph_query.Graph(doc, base_spec), pgraph_query.Graph(moved, cand_spec)   # one each, for all plans
        for plan_path in d.get("competency") or []:
            plan = load_yaml(located(plan_path, "competency"))
            if isinstance(plan, dict) and "match" not in plan and isinstance(plan.get("plan"), dict):
                plan = plan["plan"]                     # a domain's competency question: its plan
            if ix is None and isinstance(plan, dict) and plan.get("text"):
                ix = index_for(ix_stem, doc)            # only this document's index, else built from it
            ra = pgraph_query.run(doc, base_spec, plan, ix, ga)
            rb = pgraph_query.run(moved, cand_spec, plan, ix, gb)
            changed = (ra["status"], ra.get("row_count")) != (rb["status"], rb.get("row_count"))
            declared = plan_path in (p.get("expected_query_changes") or [])
            competency.append({"plan": plan_path, "baseline": {"status": ra["status"], "rows": ra.get("row_count")},
                               "candidate": {"status": rb["status"], "rows": rb.get("row_count")}, "changed": changed,
                               "change_declared": declared, "ok": (not changed) or declared})
        if after.errors:
            problems.append(f"{d['path']} is not valid under the candidate: {after.errors[0]['message']}")
            if d["path"] in rdocs:
                public_problem[len(problems) - 1] = f"{d['path']} is not valid under the candidate (details in the restricted copy)"

    # critic: tier, kernel, near-duplicates, decision record
    base_names = set(base_spec["nodes"]) | set(base_spec["edges"]) | {k for n in base_spec["nodes"].values() for k in _props(n)}
    for where, d, _ in _concepts_added(cs / "candidate", q):
        name = where.rsplit(".", 1)[-1]
        close = difflib.get_close_matches(name, sorted(base_names), n=2, cutoff=0.85)
        if close:
            objections.append({"severity": "advisory", "message": f"{name} is close to existing {close}: say why it is not a duplicate"})
    if any(op["file"] == layout.KERNEL for op in q["operations"]):
        objections.append({"severity": "advisory", "message": "the change touches the science kernel, which the catalysis domain builds on: say how the catalysis domain is affected"})
    # one version for the whole schema: the target raises it, whichever file changes (minor for additions,
    # major for breaking changes); a part that names a version of its own does not load (pgraph_schema)
    from .versions import parse_version
    try:
        bv, tv = parse_version(str(p["base"]["version"])), parse_version(str(p["target_version"]))
        if tv <= bv:
            problems.append(f"target_version {p['target_version']} does not raise the base {p['base']['version']}")
        elif t == 3 and tv[0] == bv[0] and bv[0] >= 1:
            objections.append({"severity": "advisory", "message": f"a tier 3 (breaking) change raises the major version; "
                               f"{p['base']['version']} -> {p['target_version']} does not"})
    except ScaleError as e:
        problems.append(f"versions: {e}")
    step_warning = migration_step_warning(p)
    if step_warning:
        objections.append({"severity": "advisory", "message": step_warning})
    if t == 3 and not p.get("decision_record"):
        objections.append({"severity": "blocking", "message": f"a tier 3 change needs a decision record ({layout.DECISIONS}/NNNN-*.md)"})
    if not p.get("mappings_considered"):
        objections.append({"severity": "advisory", "message": "no mappings_considered: which existing concepts and vocabularies were checked?"})
    for c in competency:
        if not c["ok"]:
            objections.append({"severity": "blocking", "message": f"{c['plan']} changes ({c['baseline']} -> {c['candidate']}) without being declared"})

    ok = not problems and all(f["ok"] for f in fixtures) and not any(o["severity"] == "blocking" for o in objections)
    from .review import approvals
    status = evaluate(load_policy(repo), approvals(cs), tier=t)
    validation = {"proposal": p["id"], "ok": ok, "tier": t, "diff": diff, "problems": problems, "fixtures": fixtures,
                  **({"later_gaps": later_gaps} if later_gaps else {}),
                  "policy": {"tier": t, "required": status["required"]}, "checked_at": now.replace(microsecond=0).isoformat()}
    migration_report = {"proposal": p["id"], "documents": migration, "competency": competency,
                        "summary": "meaning_preserving" if all(m["meaning"] == "meaning_preserving" for m in migration) else "requires_additional_context"}
    critic = {"proposal": p["id"], "objections": objections}
    pack = {"proposal": p["id"], "themes": [
        {**{k: v for k, v in th.items() if k != "instances"}, "resolved_by_operations": resolved_by.get(th["id"], []),
         "instances": [{"id": g, **gaps.get(g, {})} for g in th.get("instances") or []]} for th in themes.values()]}
    head_rel = _repo_rel(repo, head.resolve(), str(head))
    # once applied, the base is the frozen copy: its manifest is compared as the head held it (parts at
    # their head paths), so the patch shows the proposal's changes, not the freeze's
    base_man = man if man.resolve() == head.resolve() else dump_yaml(_as_head(repo, man, head_rel))
    (cs / "patch.diff").write_text(patch({**srcs, head_rel: base_man}, cs / "candidate", q))
    cs_rel = _rel(cs, repo)
    if restricted_inputs:
        if Path(cs_rel).is_absolute():
            raise ScaleError(f"{cs} reads restricted inputs ({', '.join(restricted_inputs)}) but is not in the repository: "
                             "its full reports go to the restricted copy, at a path derived from the proposal's "
                             "repository-relative path (layout.restricted_path)")
        rdir = layout.restricted_path(repo, cs_rel)             # the full reports: restricted, like their inputs
        rdir.mkdir(parents=True, exist_ok=True)
        rp = rdir / "proposal.yaml"                              # the original proposal, when kept there
        full_p = {**p, "motivation": (load_yaml(rp) or {}).get("motivation") or p.get("motivation")} if rp.is_file() else p
        _write_reports(rdir, full_p, validation, migration_report, critic, pack, themes, status, cs_rel)
        validation, migration_report, pack = _public_reports(validation, migration_report, pack, problems, public_problem,
                                                             sorted(restricted_inputs), rdocs, rsources)
    _write_reports(cs, p, validation, migration_report, critic, pack, themes, status, cs_rel, restricted=sorted(restricted_inputs))
    return {"ok": ok, "tier": t, "problems": problems, "blocking": [o["message"] for o in objections if o["severity"] == "blocking"],
            "warnings": [step_warning] if step_warning else [],
            "fixtures": sum(f["ok"] for f in fixtures), "fixtures_total": len(fixtures), "diff": {k: len(v) for k, v in diff.items()},
            "policy": status}


RESTRICTED_NOTE = ("checked with restricted inputs ({inputs}); the gap statements, the records of the restricted "
                   f"documents and the full reports are in the restricted copy (${layout.RESTRICTED_ENV}) at this "
                   "proposal's repository-relative path and are left out here until the data is cleared")


def _write_reports(d: Path, p, validation, migration_report, critic, pack, themes, status, cs_rel, restricted=None) -> None:
    """The reports ``check`` writes into one folder (the proposal's, or its mirror in the restricted copy)."""
    write_canonical(d / "validation_report.json", validation)
    write_canonical(d / "migration_assessment.json", migration_report)
    write_canonical(d / "critic_report.json", critic)
    write_canonical(d / "evidence_pack.json", pack)
    objections, migration, competency = critic["objections"], migration_report["documents"], migration_report["competency"]
    (d / "review_checklist.md").write_text(checklist(p, validation, objections, migration, competency, themes, restricted))
    (d / "PR_BODY.md").write_text(pr_body(p, validation, objections, migration, competency, themes, status, cs_rel, restricted))


def _public_reports(validation, migration_report, pack, problems, public_problem, inputs, rdocs, rsources):
    """The reports with what comes from restricted inputs left out: the gap statements (text, the record
    they are about, locator), the record-level changes and errors of restricted documents, and the details of a
    problem about them. Ids of gaps and sources, verdicts and counts stay, so that reviewers and the gap register
    can use the summary."""
    note = {"inputs": inputs, "note": RESTRICTED_NOTE.format(inputs=", ".join(inputs))}
    v = {**validation, "problems": [public_problem.get(i, m) for i, m in enumerate(problems)], "restricted": note,
         "fixtures": [{k: x for k, x in f.items() if k not in ("errors", "violations", "observed")} | {"restricted": True}
                      if f["fixture"] in inputs else f for f in validation["fixtures"]]}
    m = {**migration_report, "restricted": note,
         "documents": [{k: x for k, x in d.items() if k not in ("changes", "first_errors_after")} | {"restricted": True}
                       if d["document"] in rdocs else d for d in migration_report["documents"]]}
    keep = ("id", "source", "status", "resolved_by")
    e = {**pack, "restricted": note, "themes": [
        {**th, "instances": [{k: x for k, x in i.items() if k in keep} | {"restricted": True} if i.get("source") in rsources else i
                             for i in th["instances"]]} for th in pack["themes"]]}
    return v, m, e


def patch(base_files: dict[str, Path | str], cand_dir: Path, p: dict) -> str:
    """A unified diff of every file the proposal touches (a base file given as a path, or as text)."""
    out = []
    added = {a["path"] for a in p.get("add_files") or []}
    for f in sorted({op["file"] for op in p["operations"]} | added | set(p.get("remove_files") or [])):
        base = base_files.get(f)
        a = [] if f in added else (base if isinstance(base, str) else base.read_text()).splitlines(keepends=True)
        b = (cand_dir / f).read_text().splitlines(keepends=True) if (cand_dir / f).exists() else []
        out += difflib.unified_diff(a, b, fromfile="/dev/null" if f in added else f"a/{f}",
                                    tofile=f"b/{f}" if b else "/dev/null")
    return "".join(out)


def migration_step_warning(p: dict) -> str | None:
    """None when ``pgraph_migrate.STEPS`` registers this proposal's step (base version -> target version, this
    proposal's id); otherwise what to register. Without the step, ``scale graph migrate`` (and ``call migrate``)
    cannot move a document pinning the base version once the proposal is applied. A warning, not a failure: the
    author registers the step while preparing the proposal (tools/skills/evolve-schema/SKILL.md)."""
    from .pgraph_migrate import STEPS
    base, target = str(p["base"]["version"]), str(p["target_version"])
    have = STEPS.get(base)
    if have == (target, p["id"]):
        return None
    now = f" (it registers {base} -> {have[0]} for {have[1]})" if have else ""
    return (f"no migration step {base} -> {target} for {p['id']} in tools/scale/pgraph_migrate.py STEPS{now}: add "
            f"\"{base}\": (\"{target}\", \"{p['id']}\") (and a STEP_RULES entry if records must be rewritten), or once "
            f"the proposal is applied `scale graph migrate` cannot move documents pinning {base}")


def checklist(p, validation, objections, migration, competency, themes, restricted=None) -> str:
    lines = [f"# Review checklist — proposal {p['id']}: {p['title']}", "",
             f"Tier {validation['tier']} · review areas: {', '.join(p.get('areas') or [])}", "",
             "For each item, a reviewer checks the scientific meaning, not only that the tools pass.", ""]
    for th in themes.values():
        lines.append(f"- [ ] **{th['id']} {th['title']}** — {th['resolution']}" + (f": {th.get('reason')}" if th.get("reason") else ""))
    lines += ["", "- [ ] Every new concept is where it is most generally true, and is not a near-duplicate of an existing one",
              "- [ ] Descriptions say what a record means, in terms a curator can apply",
              "- [ ] The counterexamples fail for the stated reasons",
              "- [ ] The migration keeps every existing record's meaning",
              "- [ ] The changed competency answers are the intended ones",
              "- [ ] Deferred and rejected themes: the reasons are acceptable, and the curation guide says what to do meanwhile"]
    if objections:
        lines += ["", "Critic:"] + [f"- {o['severity']}: {o['message']}" for o in objections]
    if restricted:
        lines += ["", "Restricted data: " + RESTRICTED_NOTE.format(inputs=", ".join(f"`{r}`" for r in restricted)) + "."]
    return "\n".join(lines) + "\n"


def _rel(cs: Path, repo: Path) -> str:
    """The proposal's path as a reviewer types it: repository-relative when it is inside the repository."""
    try:
        return Path(cs).resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        return str(cs)


def pr_body(p, validation, objections, migration, competency, themes, status, cs_path: str, restricted=None) -> str:
    d = validation["diff"]
    th_lines = "\n".join(f"| {th['id']} | {th['title']} | {len(th.get('instances') or [])} | {th['resolution']} |" for th in themes.values())
    fx = "\n".join(f"- [{'x' if f['ok'] else ' '}] `{f['fixture']}` — {f['expect']}" for f in validation["fixtures"])
    mg = "\n".join(f"- `{m['document']}`: {m['meaning']} (errors {m['errors_before']} → {m['errors_after']})" for m in migration)
    cq = "\n".join(f"- `{c['plan']}`: {c['baseline']['status']} {c['baseline']['rows']} → {c['candidate']['status']} {c['candidate']['rows']}"
                   f"{' (declared)' if c['change_declared'] else ''}" for c in competency)
    obj = "\n".join(f"- **{o['severity']}** — {o['message']}" for o in objections) or "- none"
    note = RESTRICTED_NOTE.format(inputs=", ".join(f"`{r}`" for r in restricted or []))
    rs = f"\n### Restricted data\n{note[0].upper()}{note[1:]}.\n" if restricted else ""
    return f"""## Proposal {p['id']}: {p['title']}

scale-graph {p['base']['version']} → **{p['target_version']}** · tier **{validation['tier']}** · areas: {', '.join(p.get('areas') or [])} · proposed by {p.get('proposer', {}).get('name', '?')}

### Motivation
{(p.get('motivation') or '').strip()}

### Gap themes
| theme | | instances | resolution |
|---|---|---:|---|
{th_lines}

### Schema changes
{len(d['added'])} added, {len(d['loosened'])} loosened, {len(d['removed'])} removed, {len(d['changed'])} changed, {len(d['narrowed'])} narrowed. New concepts enter as provisional. See `patch.diff`.

### Fixtures
{fx or '- none'}

### Migration
{mg or '- none'}

### Competency questions
{cq or '- none'}

### Critic
{obj}

### Review
Required: {status['required']} (governance/review-policy.yaml), given as reviews of this pull request.
After the merge, a person starts the apply-proposals workflow for `{cs_path}` and this pull request (it needs the
repository secret APPLY_TOKEN): it records the reviews, writes the decision record and applies the proposal
(scale-graph {p['base']['version']} → {p['target_version']}). If this is the owner's own pull request and no other reviewer has
joined, the owner applies it in a pull request under the bootstrap rule (`scale proposal decide {p['id']} --bootstrap-bypass`, then
`scale proposal apply {p['id']} --confirm`). `scale review status --proposal {p['id']}` shows what was counted.
Agent agreement is not approval.
{rs}"""


# ------------------------------------------------------------------------------------------ decide and apply
def decide(cs: Path, repo: Path, number: int | None = None, now: _dt.datetime | None = None,
           pr: int | None = None, pr_url: str | None = None, author: str | None = None,
           bootstrap_bypass: str | None = None, by: str | None = None, records: list[dict] | None = None) -> Path:
    """Write the decision record of a proposal whose approvals satisfy the policy (``NNNN-<id>.md``): the
    reviews of its merged pull request (``pr``, ``pr_url``). ``records`` are those reviews as ``scale proposal
    apply-merged`` read them from GitHub; without it the files in ``approvals/`` are read. The record lists
    under "Reviews" only the approvals the policy counted and names the others under "Reviews not counted".
    The author's own review never counts; ``author`` defaults to the pull-request author the records name.

    ``bootstrap_bypass`` (a reason) and ``by`` (the GitHub handle of the reviewer who merged under the
    ruleset's bootstrap bypass) record a decision without the required approval. It is a person's action, allowed
    only while no other filled seat can give it (no reviewer has joined besides the one who merges) and only by a
    filled reviewer; the record says so plainly (governance/GOVERNANCE.md, "Bootstrap")."""
    from .review import approvals
    from .policy import approvable, evaluate, load_policy, placeholders, reviewers
    layout.refuse_bundled(repo, "scale proposal decide")
    now = now or _dt.datetime.now(_dt.timezone.utc)
    p = load_proposal(cs)
    val = load_doc(cs / "validation_report.json")
    apr = list(records) if records is not None else approvals(cs)
    author = author or next((a["pr_author"] for a in apr if a.get("pr_author")), None)
    pol = load_policy(repo)
    st = evaluate(pol, apr, author=author, tier=val["tier"])
    if bootstrap_bypass is not None:
        if not bootstrap_bypass.strip() or not by:
            raise ScaleError("a bootstrap bypass needs a reason and the reviewer who merged (--by)")
        if not any(by.lower() == str(m.get("github", "")).lower() for m in reviewers(pol)):
            raise ScaleError(f"{by} is not a reviewer in {layout.REVIEW_POLICY}")
        if approvable(pol, by, author):
            raise ScaleError(f"no bootstrap bypass: reviewers in {layout.REVIEW_POLICY} besides {by} can approve; "
                             "get the approval on the pull request")
        st = {**st, "approved_by": [by], "missing": [],
              "notes": st["notes"] + [f"Bootstrap bypass by {by}: {bootstrap_bypass.strip()} (not approved by a reviewer other than the "
                                      f"author; {len(placeholders(pol))} reviewer seats were still placeholders)"]}
    elif not st["satisfied"]:
        raise ScaleError("not approved: " + "; ".join(st["missing"]))
    ddir = repo / layout.DECISIONS
    existing = [int(m.group(1)) for f in ddir.glob("*.md") if (m := re.match(r"(\d{4})-", f.name))]
    n = number or (max(existing, default=0) + 1)
    ev = load_doc(cs / "evidence_pack.json")
    path = ddir / f"{n:04d}-{p['id']}.md"
    where = f"pull request [#{pr}]({pr_url})" if pr and pr_url else (f"pull request #{pr}" if pr else "the recorded reviews")
    status = (f"merged under the bootstrap bypass by {by}, without an approval (governance/GOVERNANCE.md, Bootstrap)"
              if bootstrap_bypass else f"approved in {where} under governance/review-policy.yaml (policy version "
              f"{st['policy_version']})")
    lines = [f"# Decision record {n:04d} — proposal {p['id']}: {p['title']}", "",
             f"- **Status:** {status}; tier {val['tier']}",
             f"- **Date:** {now.date().isoformat()}",
             f"- **Schema:** scale-graph {p['base']['version']} → {p['target_version']}",
             f"- **Approved by:** {', '.join(st['approved_by'])}", *([f"- **Author:** {author}"] if author else []), ""]
    if st.get("notes"):
        lines += ["**Notes from the policy check**", ""] + [f"- {x}" for x in st["notes"]] + [""]
    lines += ["## Decisions per gap theme", ""]
    for th in ev["themes"]:
        k = len(th["instances"])
        lines.append(f"- **{th['id']} {th['title']}** ({k} gap{'s' if k != 1 else ''}): {th['resolution']}"
                     + (f" — {th.get('reason')}" if th.get("reason") else ""))
    lines += ["", "## Reviews", ""]
    if not st["counted"]:
        lines.append("- none counted" + (" (bootstrap bypass)" if bootstrap_bypass else ""))
    for a in st["counted"]:
        via = f" (pull request #{a['pr']}, review {a.get('review_id')})" if a.get("pr") else (f" ({a['role']})" if a.get("role") else "")
        lines.append(f"- {a.get('at')}: {a['reviewer']}{via} — {a['decision']}" + (f": {a['note']}" if a.get("note") else ""))
    if st["ignored"]:
        lines += ["", "## Reviews not counted", ""] + [f"- {x['reviewer']}: {x['why']}" for x in st["ignored"]]
    path.write_text("\n".join(lines) + "\n")
    register(repo, p, ev["themes"], "decided", now)
    log = repo / layout.DECISION_LOG
    data = load_doc(log) if log.exists() else {"decisions": []}
    data["decisions"].append({"record": path.name, "proposal": p["id"], "proposal_dir": _rel(cs, repo),
                              "decided_at": now.replace(microsecond=0).isoformat(),
                              "approved_by": st["approved_by"], "tier": val["tier"], **({"pr": pr} if pr else {}),
                              **({"bootstrap_bypass": bootstrap_bypass.strip()} if bootstrap_bypass else {})})
    write_canonical(log, data)
    return path


def decision_record(cs: Path, repo: Path, pid: str) -> Path:
    """The decision record of a proposal, found through its decision-log entry (ids are unique, but
    two directories could still claim one; the entry names the directory it decided)."""
    log = repo / layout.DECISION_LOG
    entries = [e for e in (load_doc(log) if log.exists() else {}).get("decisions") or [] if e.get("proposal") == pid]
    if not entries:
        raise ScaleError(f"no decision record for {pid}: run `scale proposal decide` once it is approved")
    if len(entries) > 1:
        raise ScaleError(f"{layout.DECISION_LOG} has {len(entries)} decisions for {pid}")
    e = entries[0]
    where = e.get("proposal_dir")
    if where and where != _rel(cs, repo):
        raise ScaleError(f"the decision for {pid} was made on {where}, not {_rel(cs, repo)}")
    rec = repo / layout.DECISIONS / e["record"]
    if not rec.exists():
        raise ScaleError(f"{layout.DECISION_LOG} names {e['record']} for {pid}, which does not exist")
    return rec


def apply(cs: Path, repo: Path, confirm: bool = False) -> dict:
    """Freeze the base version, then install the candidate as the new head.

    The schema has one version, so the base version ``<v>`` names everything frozen: the science kernel as
    ``core/graph/frozen/kernel-<v>.yaml`` (the kernel of schema version ``<v>``), the domain's parts beside its
    manifest, in ``domain/graph/frozen/v<v>/<path relative to domain/graph>``, with the frozen manifest
    ``frozen/scale-graph-<v>.yaml`` pointing at them and at the frozen kernel. New files are appended to the
    SHA256SUMS of their frozen directory. Every file that states the schema's one version follows it
    (:data:`VERSION_FILES`: CORE.yaml, DOMAIN.yaml, scale-release.yaml and the kernel-only example manifest)."""
    import os
    repo = Path(repo).resolve()
    layout.refuse_bundled(repo, "scale proposal apply")
    p = load_proposal(cs)
    man = head_manifest(repo, p)                        # the head, never the frozen copy
    head = load_yaml(man)
    if head.get("version") != p["base"]["version"]:
        raise ScaleError(f"the head schema is {head.get('version')}; {p['id']} was built on {p['base']['version']}: rebuild it")
    rec = decision_record(cs, repo, p["id"])
    _, _, _, srcs, q = _resolved(repo, p)
    ver, graph_dir = p["base"]["version"], man.parent
    head_rel = _repo_rel(repo, man.resolve(), str(man))
    verify_candidate(cs, repo, head_rel)
    fz = layout.frozen_graph_dir(man)
    frozen_dir, frozen_man = fz / f"v{ver}", fz / f"scale-graph-{ver}.yaml"
    kernel_src = repo / layout.KERNEL
    kfz = repo / layout.KERNEL_FROZEN
    frozen_kernel = kfz / f"kernel-{ver}.yaml"
    gd = _repo_rel(repo, graph_dir.resolve(), str(graph_dir))
    parts = {}                                          # part key -> path inside frozen/v<version>/
    for key in srcs:
        if key == layout.KERNEL:
            continue
        if not key.startswith(gd + "/"):
            raise ScaleError(f"{key} lies outside {gd}/: a domain's frozen version holds only its own files and the core kernel")
        parts[key] = key[len(gd) + 1:]
    stating = [(rel, key) for rel, key in VERSION_FILES if (repo / rel).is_file()]
    plan = {"freeze": frozen_dir.relative_to(repo).as_posix(), "frozen_manifest": frozen_man.relative_to(repo).as_posix(),
            "freeze_kernel": frozen_kernel.relative_to(repo).as_posix(),
            "install": sorted({op["file"] for op in q["operations"]} | {a["path"] for a in q.get("add_files") or []} | {head_rel}),
            "remove": sorted(q.get("remove_files") or []), "decision_record": rec.relative_to(repo).as_posix(),
            "raise_version": [f"{rel} {key}: {ver} -> {p['target_version']}" for rel, key in stating]}
    if not confirm:
        return {"dry_run": True, **plan}
    if frozen_dir.exists() or frozen_man.exists():
        raise ScaleError(f"{frozen_dir} exists already")
    if frozen_kernel.exists():
        raise ScaleError(f"{frozen_kernel.relative_to(repo).as_posix()} exists already: version {ver} was frozen before")
    kfz.mkdir(parents=True, exist_ok=True)
    shutil.copy2(kernel_src, frozen_kernel)
    append_frozen_sums(kfz, [frozen_kernel])
    for key, rel in parts.items():
        (frozen_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / key, frozen_dir / rel)
    fm = copy.deepcopy(head)
    fm["status"] = "frozen"
    fm["kernel"] = os.path.relpath(frozen_kernel, fz)
    for key in PACKAGE_KEYS:
        if key in head:
            fm[key] = [f"v{ver}/{x}" for x in head.get(key) or []]
    frozen_man.write_text(
        f"# Frozen copy of scale-graph {ver}. Documents that pin {ver} validate against it. Do not edit;\n"
        f"# the current version is ../{man.name} ({p['id']} moved it to {p['target_version']}).\n" + dump_yaml(fm))
    append_frozen_sums(fz, [frozen_man] + [frozen_dir / rel for rel in parts.values()])
    for rel in plan["install"]:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cs / "candidate" / rel, repo / rel)
    for rel in plan["remove"]:                          # frozen above; gone from the head
        (repo / rel).unlink()
        parent = (repo / rel).parent
        if parent != graph_dir and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    for rel, key in stating:                            # every file that states the one version follows it
        set_version(repo / rel, key, p["target_version"])
    ev = load_doc(cs / "evidence_pack.json")
    register(repo, p, ev["themes"], "applied", _dt.datetime.now(_dt.timezone.utc))
    new_head = load_yaml(man)
    new_head["status"] = "candidate"
    # the proposals the head was built from (a candidate installed as the head names its own; none before the first)
    earlier = layout.manifest_proposals(head, man) or layout.manifest_proposals(head, man, own=True)
    new_head["proposals"] = list(dict.fromkeys(earlier + [p["id"]]))
    new_head.pop("proposal", None)
    man.write_text(dump_yaml(new_head))
    set_status(cs, "applied")
    return {"dry_run": False, **plan}


def verify_candidate(cs: Path, repo: Path, head_rel: str) -> None:
    """Refuse to install a candidate/ that is not the one proposal.yaml builds on this head, or that does not load:
    the proposal is built again in a scratch copy (the committed candidate left as it is) and compared file by file,
    and the committed candidate's manifest is assembled. A candidate left behind by an earlier, failed check, or
    older than an edited proposal.yaml, is caught here, before anything is frozen or installed."""
    import tempfile
    from . import pgraph
    cand = Path(cs) / "candidate"
    pid = Path(cs).name
    if not (cand / head_rel).is_file():
        raise ScaleError(f"{pid}: candidate/{head_rel} is missing; run `scale proposal check {pid}` and commit its output")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp) / Path(cs).name
        shutil.copytree(cs, t, ignore=shutil.ignore_patterns("candidate", "approvals"))
        build(t, repo)
        diffs = candidate_differences(t / "candidate", cand)
    if diffs:
        raise ScaleError(f"{pid}: the committed candidate/ is not what proposal.yaml builds on this head ("
                         + "; ".join(diffs[:5]) + (" …" if len(diffs) > 5 else "")
                         + f"); run `scale proposal check {pid}` and commit its output")
    try:
        pgraph.load_spec(cand / head_rel)
    except ScaleError as e:
        raise ScaleError(f"{pid}: the candidate schema does not load: {e}") from None


# the files that state the schema's one version beside the manifest, and the top-level key each states it by
VERSION_FILES = ((layout.CORE_MANIFEST, "version"), (layout.DOMAIN_DECLARATION, "version"),
                 (layout.RELEASE_MANIFEST, "schema_version"), (layout.KERNEL_ONLY_MANIFEST, "version"))


def set_version(path: Path, key: str, version: str) -> None:
    """Set a top-level ``<key>: <version>`` in a YAML file in place (the rest of the file, its comments and order,
    unchanged); the key must exist."""
    f = Path(path)
    text = f.read_text()
    new, n = re.subn(rf"(?m)^{re.escape(key)}:.*$", f"{key}: {version}", text, count=1)
    if not n or str((yaml.safe_load(new) or {}).get(key)) != str(version):
        raise ScaleError(f"{f}: could not set {key}: {version}")
    f.write_text(new)


def set_status(cs: Path, status: str) -> None:
    """Set ``status:`` in proposal.yaml in place (the rest of the file, its comments and order, unchanged)."""
    f = Path(cs) / "proposal.yaml"
    text = f.read_text()
    new, n = re.subn(r"(?m)^status:.*$", f"status: {status}", text, count=1)
    if not n:
        new = re.sub(r"(?m)^(kind:.*)$", rf"\1\nstatus: {status}", text, count=1)
    if (yaml.safe_load(new) or {}).get("status") != status:
        raise ScaleError(f"{f}: could not set status: {status}")
    f.write_text(new)


def refresh_register(cs: Path, repo: Path) -> Path:
    """Recount the proposal's gap themes from the fragments (after re-curation resolves gaps)."""
    p = load_proposal(cs)
    return register(repo, p, load_doc(cs / "evidence_pack.json")["themes"], "refreshed", _dt.datetime.now(_dt.timezone.utc))


def register(repo: Path, p: dict, themes: list[dict], stage: str, now: _dt.datetime) -> Path:
    """docs/gaps/register.json: every gap theme a proposal answered, deferred or rejected.

    A deferred theme stays open for a later proposal; an addressed theme is resolved once the
    proposal is applied. A theme's id is ``<proposal id>/<theme id>`` (``000001/TH-01``); a later decide or
    refresh updates it in place."""
    path = repo / layout.GAP_REGISTER
    data = load_doc(path) if path.exists() else {
        "description": "Gap themes raised by curation and what the proposals decided (written by scale proposal decide | apply).",
        "themes": []}
    by = {t["id"]: t for t in data["themes"]}
    live = _gap_instances(repo, p)                  # the gaps as the fragments record them now
    for th in themes:
        tid = f"{p['id']}/{th['id']}"
        ids = [i["id"] for i in th["instances"]]
        still_open = [g for g in ids if g in live and live[g]["status"] != "resolved"]
        status = {"addressed": "resolved" if stage in ("applied", "refreshed") else "approved", "deferred": "open",
                  "rejected": "closed", "guide": "closed"}[th["resolution"]]
        if th["resolution"] == "addressed" and stage in ("applied", "refreshed") and still_open:
            status = "partly_resolved"
        entry = by.get(tid) or {"id": tid, "title": th["title"], "proposal": p["id"]}
        entry.update({"resolution": th["resolution"], "status": status, "gaps": len(th["instances"]),
                      "sources": sorted({i["source"] for i in th["instances"]}),
                      **({"reason": th["reason"]} if th.get("reason") else {}),
                      "open_gaps": still_open,
                      **({"resolved_in": f"scale-graph {p['target_version']}"} if status in ("resolved", "partly_resolved") else {}),
                      f"{stage}_at": now.date().isoformat()})
        by[tid] = entry
    data["themes"] = sorted(by.values(), key=lambda t: t["id"])
    write_canonical(path, data)
    return path


# ------------------------------------------------------------------------------------------ frozen copies
def _sums(fz: Path) -> dict[str, str]:
    p = Path(fz) / layout.FROZEN_SUMS
    out = {}
    for line in p.read_text().splitlines() if p.exists() else []:
        if line.strip():
            digest, rel = line.split(maxsplit=1)
            out[rel.strip()] = digest
    return out


def append_frozen_sums(fz: Path, files: list[Path]) -> None:
    """Record the sha256 of newly frozen files in ``<fz>/SHA256SUMS`` (``sha256sum`` format, paths
    relative to the frozen directory). Frozen copies are additions only: an existing entry is never
    rewritten."""
    fz = Path(fz)
    known = _sums(fz)
    lines = []
    for f in files:
        rel = Path(f).relative_to(fz).as_posix()
        if rel in known:
            raise ScaleError(f"{rel} is frozen already in {fz}")
        lines.append(f"{sha256_file(f)}  {rel}\n")
    with (fz / layout.FROZEN_SUMS).open("a") as fh:
        fh.writelines(lines)


def verify_frozen(repo: Path) -> dict:
    """The frozen scale-graph copies are unchanged: in every frozen directory (the core's kernels, each domain's
    versions) each file is listed in its SHA256SUMS with its digest, and every listed file exists; and every
    version an applied proposal moved away from is frozen. Mismatches are named repository-relative. A schema
    that no proposal has moved yet (0.1.0) has no frozen version, which is in order."""
    repo = Path(repo)
    bad, files, dirs = [], 0, []
    for fz in layout.frozen_graph_dirs(repo):
        rel_dir = fz.relative_to(repo).as_posix()
        if not (fz / layout.FROZEN_SUMS).exists():
            raise ScaleError(f"{rel_dir}/{layout.FROZEN_SUMS} is missing")
        known = _sums(fz)
        actual = {p.relative_to(fz).as_posix(): sha256_file(p) for p in sorted(fz.rglob("*"))
                  if p.is_file() and p.name != layout.FROZEN_SUMS and "__pycache__" not in p.parts and p.name != ".DS_Store"}
        bad += [f"{rel_dir}/{k}" for k in sorted(set(known) | set(actual)) if known.get(k) != actual.get(k)]
        files += len(known)
        dirs.append({"dir": rel_dir, "files": len(known)})
        if not known:
            bad.append(f"{rel_dir}/{layout.FROZEN_SUMS} (empty)")
    # every version a domain's applied proposals moved away from is frozen (documents may pin it), with its kernel
    for name, man in sorted(layout.graph_manifests(repo, experimental=True).items()):
        for pid in layout.manifest_proposals(load_yaml(man), man):
            pdir = layout.proposal_dir(repo, pid)
            if pdir is None or not (pdir / "proposal.yaml").is_file():
                bad.append(f"{man.relative_to(repo).as_posix()}: applied proposal {pid} not found")
                continue
            base = (load_yaml(pdir / "proposal.yaml").get("base") or {}).get("version")
            for frozen in (layout.frozen_graph_dir(man) / f"scale-graph-{base}.yaml",
                           repo / layout.KERNEL_FROZEN / f"kernel-{base}.yaml"):
                if not frozen.is_file():
                    bad.append(f"{frozen.relative_to(repo).as_posix()} is missing ({pid} moved {name} from {base})")
    return {"ok": not bad, "files": files, "dirs": dirs, "mismatched": bad}
