"""Assemble a scale-catal schema from its parts: the science kernel + a domain's files -> one effective schema.

There are two layers. The science kernel (``core/graph/kernel.yaml``) holds the document format, the
shared structures (value object, evidence, record reference, stewardship, common properties) and the
domain-neutral labels and edges of the method of science. A domain's manifest (the catalysis domain's
``domain/graph/scale-catal.yaml``) names the kernel and the domain's own files (``domains``); a
domain file names itself with ``domain:`` and builds on the kernel, which it sees without importing
it: it declares new labels (a label that refines a kernel label says ``is_a``), new edge types (one
that narrows a kernel edge says ``specializes``), *extends* an edge type's endpoints, adds properties
to a label it can see (``adds_properties``), binds a value property to one of the kernel's quantity contracts
(``quantity:``, with ``context:`` naming the sibling property that states a context; ``quantities``) and may carry
the domain's ``checklist:`` (``must`` and
``should`` fields, ``unless`` and ``when`` cases), which becomes a conformance contract named after the
domain file (``pgraph_profiles.domain_contract``) that documents follow by that name. Checklists only
constrain (see ``pgraph_profiles``).

The schema has one version: the manifest's ``version``, for the kernel and the domain files together. The
kernel and the domain files carry no version of their own (a ``version:`` in one is an error); every part
reports the manifest's. Besides ``domains``, a manifest may list vocabulary-only files under ``modules`` (a
file keyed ``module:``, without a checklist) and extension files that only add vocabulary (``extensions``); there
are no profile files (retired by design: a domain file carries its checklist, and a manifest listing ``profiles``
is refused). A domain file may import another (``imports``), and may carry
*bridges* that apply only when another named file is loaded.

The effective schema has the same shape as a monolithic spec (``nodes``, ``edges``, ``value``, …),
so the validator reads both. In it:
- abstract labels are removed from ``nodes`` (kept under ``abstract``); a label that ``is_a``
  another inherits its properties and required list;
- endpoint lists are concrete: ``ANY`` is every concrete label, ``any_except`` every other one,
  and a label stands for itself and every label that is_a it;
- ``modules`` indexes the loaded parts (the kernel and every listed file, each with its ``kind``)
  and every label and edge type names the part that declares it (``module``): internal keys, kept
  under these names because frozen specs and their tools read them.
"""

from __future__ import annotations

import copy
from pathlib import Path

from . import layout
from .util import ScaleError, load_yaml

KERNEL_KEYS = ("format", "property_types", "value", "evidence", "record_ref", "stewardship", "status_check", "common",
               "extensions", "rules", "quantities")
PREFIX_REGISTRY = Path(layout.PREFIX_REGISTRY)


def is_manifest(spec: dict) -> bool:
    """A manifest names the kernel and its parts: a domain's files (``domains``), and possibly ``modules``."""
    return "kernel" in spec and ("domains" in spec or "modules" in spec)


def _registry(start: Path) -> dict:
    """The extension-prefix registry of the repository that holds the schema (nearest ancestor).

    Inside a repository (or the bundled data) a missing registry is an error: every extension key
    would otherwise be reported as unregistered without saying why. A schema outside any repository
    (a scratch copy) may have none."""
    start = Path(start).resolve()
    for d in [start, *start.parents]:
        p = d / PREFIX_REGISTRY
        if p.exists():
            return {x["prefix"]: x for x in load_yaml(p).get("prefixes") or []}
    root = layout.find_root(start)
    if root is not None:
        raise ScaleError(f"no extension-prefix registry: {root / PREFIX_REGISTRY} is missing")
    return {}


def assemble(path: Path) -> dict:
    return assemble_manifest(load_yaml(path), Path(path).parent)


def spec_sources(path: Path) -> list[Path]:
    """Every file a schema is read from: a schema file itself, or a manifest with the kernel, the files it lists and
    the extension-prefix registry it assembles (:func:`assemble_manifest`). A cache of the schema is good only while
    none of them changes."""
    path = Path(path)
    man = load_yaml(path)
    if not is_manifest(man):
        return [path]
    base = path.parent
    files = [path, layout.kernel_path(base, man["kernel"])]
    files += [base / rel for key in ("modules", "extensions", "domains") for rel in man.get(key) or []]
    start = base.resolve()
    files += [d / PREFIX_REGISTRY for d in [start, *start.parents] if (d / PREFIX_REGISTRY).exists()][:1]
    return files


def assemble_manifest(man: dict, base: Path) -> dict:
    """Assemble a manifest given as data, its paths relative to ``base`` (``scale domains check``
    composes an experimental domain's files with the kernel without writing a manifest)."""
    version = man.get("version")                 # the one version of the schema: every part reports it
    if man.get("profiles"):
        raise ScaleError("profile files (`profiles:`) are retired by design: a domain file carries its checklist "
                         "(`checklist:`), and documents follow it with follows_domains")
    kernel = load_yaml(layout.kernel_path(base, man["kernel"]))
    if "version" in kernel:
        raise ScaleError(f"{man['kernel']}: the kernel carries no version of its own; the schema's one version is the "
                         "manifest's (remove `version:` from the kernel)")
    spec = {k: v for k, v in man.items() if k not in ("kernel", "modules", "profiles", "domains")}
    for k in KERNEL_KEYS:
        if k in kernel:
            spec[k] = copy.deepcopy(kernel[k])
    spec["kernel"] = {"name": kernel.get("kernel"), "version": version}
    if "quantities" in spec:                     # the quantity contracts: compiled here, so a malformed one never loads
        from .quantities import check_block
        check_block(spec["quantities"])

    mods: dict[str, dict] = {}
    # the science kernel declares labels and edges; every part sees them without importing
    if kernel.get("nodes") or kernel.get("edges"):
        mods["kernel"] = {"module": "kernel", "version": version, "title": "Science kernel",
                          "maturity": kernel.get("maturity"), "nodes": kernel.get("nodes") or {},
                          "edges": kernel.get("edges") or {}, "_path": man["kernel"], "imports": []}
    # a domain's files, each with its vocabulary and (optionally) its checklist; modules (vocabulary only) and
    # extensions (optional vocabularies) compose alike
    domain_files: list[tuple[str, dict]] = []
    for kind, rels in (("module", man.get("modules") or []), ("extension", man.get("extensions") or []),
                       ("domain", man.get("domains") or [])):
        for rel in rels:
            m = load_yaml(base / rel)
            name = m.get(kind)
            if not name or any(k in m for k in ("module", "extension", "domain") if k != kind):
                raise ScaleError(f"{rel}: a {kind} file names itself with '{kind}:'")
            if "version" in m:
                raise ScaleError(f"{rel}: a {kind} file carries no version of its own; the schema's one version is the "
                                 "manifest's (remove `version:` from the file)")
            m["version"] = version
            if name in mods:
                raise ScaleError(f"{kind} {name!r} is listed twice (or collides with the kernel or another file)")
            if "quantities" in m:
                raise ScaleError(f"{rel}: a {kind} file declares no quantity contracts (quantities:); they are the "
                                 "kernel's, and a property binds one with quantity:")
            if kind != "domain" and "checklist" in m:
                raise ScaleError(f"{rel}: a {kind} file carries no checklist; a checklist belongs to a domain file "
                                 "(domain:, listed under domains)")
            if kind == "domain":
                domain_files.append((rel, copy.deepcopy(m)))
                m = {k: v for k, v in m.items() if k != "checklist"}
            m["module"], m["_kind"], m["_path"] = name, kind, rel
            for imp in m.get("imports") or []:
                imp["module"] = imp.get("module") or imp.get("extension") or imp.get("domain")
            mods[name] = m
    for name, m in mods.items():
        for imp in m.get("imports") or []:
            dep = mods.get(imp["module"])
            if dep is None:
                raise ScaleError(f"{m.get('_kind', 'file')} {name} imports {imp['module']!r}, which is not loaded")
            if imp.get("version"):
                raise ScaleError(f"{name} imports {imp['module']} at version {imp['version']}; the files of one schema share "
                                 "its one version, so an import names a file only")

    def closure(name: str, seen=None) -> set:
        seen = set() if seen is None else seen
        if name not in seen:
            seen.add(name)
            if "kernel" in mods:
                seen.add("kernel")
            for imp in mods[name].get("imports") or []:
                closure(imp["module"], seen)
        return seen

    # ---- labels
    labels: dict[str, dict] = {}
    owner: dict[str, str] = {}
    for name, m in mods.items():
        for lab, nd in (m.get("nodes") or {}).items():
            if lab in labels:
                raise ScaleError(f"node label {lab} is declared by {owner[lab]} and {name}")
            labels[lab], owner[lab] = copy.deepcopy(nd), name
    visible = {name: {lab for lab, o in owner.items() if o in closure(name)} for name in mods}

    # ---- edges: declarations, then extensions (file-level, then active bridges)
    edges: dict[str, dict] = {}
    eowner: dict[str, str] = {}
    exts: list[tuple[str, str, dict, set]] = []

    def declare(block: dict, name: str, scope: set, how: str = "") -> None:
        for e, ed in (block or {}).items():
            if e in edges:
                raise ScaleError(f"edge type {e} is declared by {eowner[e]} and {name}")
            edges[e], eowner[e] = copy.deepcopy(ed), name
            _check_refs(ed, scope, f"{name}{how}: {e}")

    for name, m in mods.items():
        declare(m.get("edges"), name, visible[name])
        if m.get("extends"):
            exts.append((name, "extends", m["extends"], visible[name]))
        for other, br in (m.get("bridges") or {}).items():
            if other not in mods:
                continue
            scope = visible[name] | visible[other]
            declare(br.get("edges"), name, scope, f" (bridge to {other})")
            if br.get("extends"):
                exts.append((name, f"bridge to {other}", br["extends"], scope))
    for name, how, block, scope in exts:
        for e, sides in block.items():
            if e not in edges:
                raise ScaleError(f"{name} ({how}) extends {e}, which no loaded file declares")
            for side in ("from", "to"):
                add = sides.get(side) or []
                if not add:
                    continue
                bad = [x for x in add if x not in scope]
                if bad:
                    raise ScaleError(f"{name} ({how}) extends {e}.{side} with {bad}, not visible to it")
                cur = edges[e][side]
                if not isinstance(cur, list):
                    raise ScaleError(f"{e}.{side} is {cur!r}; only listed endpoints can be extended")
                edges[e][side] = cur + [x for x in add if x not in cur]

    # ---- properties a file adds to a label it can see (driving-force vocabulary on CatalyticTest, …)
    adds: list[tuple[str, str, dict, set]] = []
    for name, m in mods.items():
        if m.get("adds_properties"):
            adds.append((name, "adds_properties", m["adds_properties"], visible[name]))
        for other, br in (m.get("bridges") or {}).items():
            if other in mods and br.get("adds_properties"):
                adds.append((name, f"bridge to {other}", br["adds_properties"], visible[name] | visible[other]))
    for name, how, block, scope in adds:
        for lab, props in block.items():
            if lab not in labels or lab not in scope:
                raise ScaleError(f"{name} ({how}) adds properties to {lab}, which is not visible to it")
            cur = labels[lab].setdefault("properties", {})
            for k, d in props.items():
                if k in cur:
                    raise ScaleError(f"{name} ({how}) adds {lab}.{k}, which is already declared")
                cur[k] = dict(copy.deepcopy(d), added_by=name)

    # ---- inheritance
    for lab, nd in labels.items():
        if nd.get("is_a") and nd["is_a"] not in labels:
            raise ScaleError(f"{lab} is_a {nd['is_a']}, which is not declared")

    def ancestors(lab: str) -> list[str]:
        out, cur = [], labels[lab].get("is_a")
        while cur:
            if cur in out or cur == lab:
                raise ScaleError(f"is_a cycle at {lab}")
            out.append(cur)
            cur = labels[cur].get("is_a")
        return out

    resolved = {}
    for lab, nd in labels.items():
        props, req = {}, []
        for a in reversed(ancestors(lab)):
            props.update(copy.deepcopy(labels[a].get("properties") or {}))
            req += [r for r in labels[a].get("required") or [] if r not in req]
        for k in nd.get("properties") or {}:
            if k in props:
                raise ScaleError(f"{lab} redefines inherited property {k!r}")
        props.update(copy.deepcopy(nd.get("properties") or {}))
        req += [r for r in nd.get("required") or [] if r not in req]
        fixed = {}
        for a in reversed(ancestors(lab)):
            fixed.update(labels[a].get("fixed") or {})
        for k, v in (nd.get("fixed") or {}).items():
            if k in fixed and fixed[k] != v:
                raise ScaleError(f"{lab} fixes {k}={v!r}, but an ancestor fixes it to {fixed[k]!r}")
            if k not in props:
                raise ScaleError(f"{lab} fixes {k!r}, which it does not have")
            d = props[k]
            if d.get("type") == "enum" and v not in d["values"]:
                raise ScaleError(f"{lab} fixes {k}={v!r}, not one of {d['values']}")
            fixed[k] = v
        r = {k: v for k, v in nd.items() if k not in ("properties", "required", "fixed")}
        r.update(properties=props, required=[x for x in req if x not in fixed], fixed=fixed, module=owner[lab],
                 ancestors=ancestors(lab))
        resolved[lab] = r
    concrete = [lab for lab, r in resolved.items() if not r.get("abstract")]

    def expand(v) -> list[str]:
        if v == "ANY":
            return list(concrete)
        if isinstance(v, dict):
            ex = set(v.get("any_except") or [])
            return [lab for lab in concrete if lab not in ex and not ex & set(resolved[lab]["ancestors"])]
        if "ANY" in v:
            raise ScaleError(f"ANY must stand alone, not inside a list: {v}")
        out = []
        for x in v:
            if x not in resolved:
                raise ScaleError(f"unknown label {x!r} in {v}")
            for lab in concrete:
                if (lab == x or x in resolved[lab]["ancestors"]) and lab not in out:
                    out.append(lab)
        return out

    for e, ed in edges.items():
        ed["from"], ed["to"], ed["module"] = expand(ed["from"]), expand(ed["to"]), eowner[e]
    for e, ed in edges.items():
        gen = ed.get("specializes")
        if gen:
            if gen not in edges:
                raise ScaleError(f"{e} specializes {gen}, which is not declared")
            for side in ("from", "to"):
                extra = set(ed[side]) - set(edges[gen][side])
                if extra:
                    raise ScaleError(f"{e} specializes {gen} but its {side} {sorted(extra)} is outside {gen}'s")
    def expand_defs(d) -> None:
        """Resolve ref targets (with subtypes) wherever a property definition appears, at any depth."""
        if isinstance(d, dict):
            if d.get("type") == "ref" and "targets" in d:
                d["targets"] = expand(d["targets"])
            for k, v in d.items():
                if k != "targets":
                    expand_defs(v)
        elif isinstance(d, list):
            for v in d:
                expand_defs(v)

    for r in resolved.values():
        expand_defs(r["properties"])
    for ed in edges.values():
        expand_defs(ed.get("properties") or {})
    for k in ("value", "evidence", "record_ref", "stewardship", "common", "format"):
        if k in spec:
            expand_defs(spec[k])

    # ---- the records a context read from a value's target names, as a domain narrows them (context_targets)
    narrowed: dict[str, dict] = {}
    for name, m in mods.items():
        for ctx, d in (m.get("context_targets") or {}).items():
            where = f"{m.get('_path', name)}: context_targets.{ctx}"
            if m.get("_kind") != "domain":
                raise ScaleError(f"{where}: only a domain file narrows the targets of a context")
            contexts = (spec.get("quantities") or {}).get("contexts") or {}
            if ctx not in contexts or "target" not in (contexts[ctx].get("read_from") or []):
                raise ScaleError(f"{where}: names no context of the kernel's quantity contracts read from a target")
            if ctx in narrowed:
                raise ScaleError(f"{where}: the context is narrowed by {narrowed[ctx]['module']} already")
            if not isinstance(d, dict) or set(d) - {"description", "maturity", "targets"} or not d.get("targets"):
                raise ScaleError(f"{where}: a mapping of description, maturity and targets (the labels its records have)")
            bad = [x for x in d["targets"] if x not in visible[name]]
            if bad:
                raise ScaleError(f"{where}: names {bad}, which are not declared by the file, the kernel or its imports")
            narrowed[ctx] = {"targets": expand(d["targets"]), "description": d.get("description"),
                             "maturity": d.get("maturity"), "module": name}
    if narrowed:
        spec["context_targets"] = narrowed

    spec["nodes"] = {lab: resolved[lab] for lab in concrete}
    spec["abstract"] = {lab: r for lab, r in resolved.items() if r.get("abstract")}
    spec["edges"] = edges
    spec["modules"] = {n: {"version": m["version"], "title": m.get("title"), "maturity": m.get("maturity"),
                           "kind": m.get("_kind", "kernel"), "driving_forces": m.get("driving_forces") or [],
                           "path": m["_path"], "imports": [i["module"] for i in m.get("imports") or []]}
                       for n, m in mods.items()}
    spec["extension_prefixes"] = _registry(base)
    from .quantities import check_bindings
    check_bindings(spec)                          # every quantity: and context: of a property names what exists
    from .pgraph_profiles import domain_contract, load_profiles
    spec["profiles"] = load_profiles([domain_contract(d, rel) for rel, d in domain_files], spec)   # the checklists
    spec["domains"] = {d["domain"]: {"version": d["version"], "title": d.get("title"), "driving_forces": d.get("driving_forces") or [],
                                     "replaces": d.get("replaces") or {}, "path": rel} for rel, d in domain_files}
    return spec


def _check_refs(ed: dict, scope: set, where: str) -> None:
    for side in ("from", "to"):
        v = ed.get(side)
        names = (v.get("any_except") or []) if isinstance(v, dict) else ([] if v == "ANY" else v or [])
        if "ANY" in names:
            raise ScaleError(f"{where}.{side}: ANY must stand alone, not inside a list")
        bad = [x for x in names if x not in scope]
        if bad:
            raise ScaleError(f"{where}.{side} names {bad}, which are not declared by the file, the kernel or its imports")
