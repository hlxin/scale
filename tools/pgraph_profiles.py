"""scale-graph conformance contracts: the domain files' checklists over the vocabulary.

A domain file's checklist (``must``, ``should``) is turned into a contract (named after the domain; the conformance
report lists contracts under ``profiles``, its historical key). There are no profile files: they are retired by
design. A contract never adds labels, edge types or properties, and never loosens the vocabulary. It can:
- make a property required or recommended on a label (an abstract label applies to every label
  that is_a it);
- narrow the units a value may carry and the values an enum may take;
- require or recommend outgoing edges of a type, and properties on those edges;
- exempt some records from a label's constraints: ``unless: {test_kind: [equilibrium_estimate]}``
  (a computed equilibrium needs no catalyst or feed). Merged checklists keep an
  exemption only when every one of them grants it, so a merge is never looser than either side;
- apply some items only to the records they describe: ``when`` lists cases, each a condition on a
  list (or enum) property of the record and the items that hold when it is met, e.g.
  ``when: [{driving_forces: {any_of: [electro]}, must: [control_mode]}]``. ``any_of`` matches a record
  that lists one of the values, ``all_of`` one that lists every value. A case of an edge type's
  block is evaluated on the edge's source record. Items of a case that does not match are not
  checked and do not count towards completeness; a label's ``unless`` exempts its cases too. The
  catalysis domain's one checklist keys its cases on a test's ``driving_forces``.
A checklist may include the checklists of other domain files (``includes``, kept as ``profile_of``); their
constraints apply as well.

A document declares the domains it follows in ``graph.follows_domains`` (a node may override that
with its own ``follows_domains``), as ``name`` or ``name@version``. Validity (the kernel and the domain's vocabulary) and conformance
(checklists) are reported separately: a valid document can fail a checklist, and that is itself an
answer about what its sources report.
"""

from __future__ import annotations

import copy

from .versions import satisfies
from .util import ScaleError, load_yaml

PROFILE_KEYS = {"profile", "version", "title", "description", "maturity", "profile_of", "basis", "guidance",
                "constraints", "edge_constraints", "driving_force", "driving_forces"}
LABEL_KEYS = {"required", "recommended", "units", "values", "edges", "unless", "when"}
CASE_KEYS = {"if", "required", "recommended", "units", "values", "edges"}   # a case of ``when``: a condition and items
MATCH = ("any_of", "all_of")
SATISFIED = {"present", "below_detection_limit", "below_quantification_limit", "not_applicable"}


DOMAIN_CHECKLIST_KEYS = {"description", "basis", "guidance", "includes", "labels", "edges"}
LEVELS = {"must": "required", "should": "recommended"}


def domain_contract(dom: dict, rel: str) -> dict:
    """A domain's checklist as a conformance contract: ``must`` is required (a failure is a
    conformance violation), ``should`` is recommended (it counts towards completeness only). The
    contract is named after the file's ``domain:`` (catalysis); a checklist may ``include`` the checklists of
    other domain files of the schema, which then apply as well. Its version is the schema's one version."""
    ck = dom.get("checklist") or {}
    extra = set(ck) - DOMAIN_CHECKLIST_KEYS
    if extra:
        raise ScaleError(f"{rel}: unknown checklist keys {sorted(extra)}")

    def levels(c: dict, where: str, case: bool = False) -> dict:
        out = {}
        for k, v in c.items():
            if k in LEVELS:
                out[LEVELS[k]] = v
            elif k == "edges":
                out["edges"] = {LEVELS[lvl]: es for lvl, es in (v or {}).items() if lvl in LEVELS}
                if set(v or {}) - set(LEVELS):
                    raise ScaleError(f"{rel}: {where}.edges takes must and should only")
            elif k in ("units", "values") or (k == "unless" and not case):
                out[k] = v
            elif k == "when" and not case:
                if not isinstance(v, list):
                    raise ScaleError(f"{rel}: {where}.when is a list of cases")
                out["when"] = [when_case(x, f"{where}.when[{i}]") for i, x in enumerate(v)]
            elif case:
                raise ScaleError(f"{rel}: {where} has {k!r}, which is not a condition {{any_of | all_of: [...]}} "
                                 "(a case takes its condition and must, should, edges, units, values)")
            else:
                raise ScaleError(f"{rel}: {where} has unknown key {k!r} (must, should, edges, units, values, unless, when)")
        return out

    def when_case(x, where: str) -> dict:
        """A case: its condition (property: {any_of | all_of: [values]}, every one met) and its items."""
        if not isinstance(x, dict):
            raise ScaleError(f"{rel}: {where} is a mapping (a condition and its items)")
        cond = {k: v for k, v in x.items() if k not in LEVELS and k not in ("edges", "units", "values")}
        if not cond:
            raise ScaleError(f"{rel}: {where} names no condition, e.g. driving_forces: {{any_of: [electro]}}")
        bad = [k for k, v in cond.items() if not (isinstance(v, dict) and len(v) == 1 and set(v) <= set(MATCH)
                                                  and isinstance(next(iter(v.values())), list) and next(iter(v.values())))]
        if bad:
            raise ScaleError(f"{rel}: {where} has {bad[0]!r}, which is not a condition {{any_of | all_of: [...]}} "
                             "(a case takes its condition and must, should, edges, units, values)")
        return {"if": cond, **levels({k: v for k, v in x.items() if k not in cond}, where, case=True)}

    name = dom["domain"]
    return {"profile": name, "version": dom["version"], "title": dom.get("title"), "maturity": dom.get("maturity"),
            "description": ck.get("description"), "basis": ck.get("basis") or [], "guidance": ck.get("guidance"),
            "driving_forces": dom.get("driving_forces") or [],
            "profile_of": [{"module": name}] + [{"profile": i["domain"], **({"version": i["version"]} if i.get("version") else {})}
                                                for i in ck.get("includes") or []],
            "constraints": {lab: levels(c, lab) for lab, c in (ck.get("labels") or {}).items()},
            "edge_constraints": {e: levels(c, e) for e, c in (ck.get("edges") or {}).items()},
            "_path": rel, "_domain": True}


def load_profiles(contracts: list, spec: dict) -> dict:
    """The domain files' checklists (``domain_contract``), resolved with the checklists they include. (There are no
    profile files: they are retired by design.)"""
    raw = {}
    for p in contracts:
        pr = dict(p)
        extra = set(pr) - PROFILE_KEYS - {"_path", "_domain"}
        if extra:
            raise ScaleError(f"{pr.get('_path') or p.name}: unknown profile keys {sorted(extra)}")
        if pr["profile"] in raw:
            raise ScaleError(f"profile {pr['profile']} is listed twice")
        pr.setdefault("_path", pr.get("_path"))
        raw[pr["profile"]] = pr
    out = {}
    for name in raw:
        out[name] = _resolve(name, raw, spec, [])
    return out


def _resolve(name: str, raw: dict, spec: dict, stack: list) -> dict:
    if name in stack:
        raise ScaleError(f"profile_of cycle: {' -> '.join(stack + [name])}")
    pr = raw[name]
    eff: dict = {"constraints": {}, "edge_constraints": {}}
    parents = []
    for base in pr.get("profile_of") or []:
        if "extension" in base and "module" not in base:
            base = {**base, "module": base["extension"]}
        if "module" in base:
            mod = spec["modules"].get(base["module"])
            if mod is None:
                raise ScaleError(f"profile {name} is a profile of {base['module']!r}, which is not loaded")
            if base.get("version") and not satisfies(mod["version"], base["version"]):
                raise ScaleError(f"profile {name} needs {base['module']} {base['version']}; loaded {mod['version']}")
        else:
            if base["profile"] not in raw:
                raise ScaleError(f"profile {name} is a profile of {base['profile']!r}, which is not loaded")
            par = _resolve(base["profile"], raw, spec, stack + [name])
            if base.get("version") and not satisfies(par["version"], base["version"]):
                raise ScaleError(f"profile {name} needs profile {base['profile']} {base['version']}; loaded {par['version']}")
            parents.append(base["profile"])
            _merge(eff, par["effective"])
    own = _expand(name, pr, spec)
    _merge(eff, own)
    forces = sorted(raw_forces(name, raw))
    return {"version": pr["version"], "title": pr.get("title"), "maturity": pr.get("maturity"), "driving_forces": forces,
            "basis": pr.get("basis") or [], "profile_of": pr.get("profile_of") or [], "parents": parents,
            "path": pr["_path"], "effective": eff, "domain": bool(pr.get("_domain"))}


def raw_forces(name: str, raw: dict, seen: frozenset = frozenset()) -> set:
    """The driving forces a profile covers: its own and those of the profiles it is a profile of."""
    if name in seen or name not in raw:
        return set()
    pr = raw[name]
    if pr.get("driving_forces"):          # stated explicitly: exactly these (electrothermo- builds on thermo- but is its own force)
        return set(pr["driving_forces"])
    own = {pr["driving_force"]} if pr.get("driving_force") else set()
    for b in pr.get("profile_of") or []:
        if "profile" in b:
            own |= raw_forces(b["profile"], raw, seen | {name})
    return own


def _expand(name: str, pr: dict, spec: dict) -> dict:
    """Check a profile against the effective schema and expand abstract labels to concrete ones."""
    nodes, abstract, edges = spec["nodes"], spec.get("abstract") or {}, spec["edges"]
    common = spec["common"]["node"]["properties"]
    out: dict = {"constraints": {}, "edge_constraints": {}}
    for lab, c in (pr.get("constraints") or {}).items():
        extra = set(c) - LABEL_KEYS
        if extra:
            raise ScaleError(f"profile {name}: {lab} has unknown keys {sorted(extra)}")
        if lab in nodes:
            targets = [lab] + [n for n, nd in nodes.items() if lab in nd.get("ancestors", [])]
            declared = {**common, **nodes[lab]["properties"]}
        elif lab in abstract:
            targets = [n for n, nd in nodes.items() if lab in nd.get("ancestors", [])]
            declared = {**common, **abstract[lab]["properties"]}
        else:
            raise ScaleError(f"profile {name}: unknown label {lab}")
        _check_items(name, lab, c, declared, targets, edges)
        for k, vals in (c.get("unless") or {}).items():
            d = declared.get(k, {})
            if d.get("type") != "enum" or set(vals) - set(d["values"]):
                raise ScaleError(f"profile {name}: {lab} unless {k} must name values of its enum {d.get('values')}")
        _check_cases(name, lab, c, lambda k: declared.get(k), lambda x: _check_items(name, lab, x, declared, targets, edges))
        for t in targets:
            _merge(out, {"constraints": {t: copy.deepcopy(c)}, "edge_constraints": {}})
    for e, c in (pr.get("edge_constraints") or {}).items():
        if e not in edges:
            raise ScaleError(f"profile {name}: unknown edge type {e}")
        declared = {**spec["common"]["link"]["properties"], **(edges[e].get("properties") or {})}

        def props_only(x: dict, e=e, declared=declared) -> None:
            for k in (x.get("required") or []) + (x.get("recommended") or []):
                if k not in declared:
                    raise ScaleError(f"profile {name}: {e} has no property {k!r} (profiles cannot add properties)")
        props_only(c)
        sources = edges[e]["from"]                      # a case of an edge type is evaluated on the edge's source
        _check_cases(name, e, c, lambda k, sources=sources: next(
            (d for d in ({**common, **nodes[s]["properties"]}.get(k) for s in sources if s in nodes) if d), None), props_only)
        _merge(out, {"constraints": {}, "edge_constraints": {e: copy.deepcopy(c)}})
    return out


def _check_items(name: str, lab: str, c: dict, declared: dict, targets: list, edges: dict) -> None:
    """The properties, units, values and edges a label's block (or one of its cases) names exist."""
    for k in (c.get("required") or []) + (c.get("recommended") or []):
        if k not in declared:
            raise ScaleError(f"profile {name}: {lab} has no property {k!r} (profiles cannot add properties)")
    for k, units in (c.get("units") or {}).items():
        if declared.get(k, {}).get("type") != "value":
            raise ScaleError(f"profile {name}: {lab}.{k} is not a value; units apply to values only")
    for k, vals in (c.get("values") or {}).items():
        d = declared.get(k, {})
        if d.get("type") != "enum" or set(vals) - set(d["values"]):
            raise ScaleError(f"profile {name}: {lab}.{k} values must narrow its enum {d.get('values')}")
    ed = c.get("edges") or {}
    for lvl in ("required", "recommended"):
        for e in ed.get(lvl) or []:
            if e not in edges:
                raise ScaleError(f"profile {name}: unknown edge type {e}")
            if not set(targets) & set(edges[e]["from"]):
                raise ScaleError(f"profile {name}: {lab} is not a source of {e}")


def _enum_values(d: dict | None) -> list | None:
    """The values a condition can test: an enum's, or a list of enum's items'."""
    d = d or {}
    if d.get("type") == "enum":
        return d.get("values") or []
    if d.get("type") == "list" and (d.get("items") or {}).get("type") == "enum":
        return d["items"].get("values") or []
    return None


def _check_cases(name: str, where: str, c: dict, declared_of, check_items) -> None:
    """``when``: each case names conditions on enum (or list of enum) properties of the record, with
    values of their enum, and items that exist. Two blocks that may both apply to one record (the
    unconditional items and any case, or two cases) cannot narrow one property to disjoint values."""
    cases = c.get("when") or []
    if not isinstance(cases, list):
        raise ScaleError(f"profile {name}: {where} when is a list of cases")
    for i, x in enumerate(cases):
        extra = set(x) - CASE_KEYS if isinstance(x, dict) else {"(not a mapping)"}
        if extra or not x.get("if"):
            raise ScaleError(f"profile {name}: {where} when[{i}] needs a condition (if) and takes {sorted(CASE_KEYS - {'if'})}"
                             + (f"; unknown keys {sorted(extra)}" if extra else ""))
        for k, m in x["if"].items():
            allowed = _enum_values(declared_of(k))
            if allowed is None:
                raise ScaleError(f"profile {name}: {where} when[{i}] tests {k!r}, which is not an enum or a list of enum there")
            if not (isinstance(m, dict) and len(m) == 1 and set(m) <= set(MATCH) and isinstance(next(iter(m.values())), list)):
                raise ScaleError(f"profile {name}: {where} when[{i}].{k} takes one of {list(MATCH)} with a list of values")
            bad = set(next(iter(m.values()))) - set(allowed)
            if bad or not next(iter(m.values())):
                raise ScaleError(f"profile {name}: {where} when[{i}].{k} must name values of its enum {allowed}")
        check_items(x)
    blocks = [c] + cases
    for i, a in enumerate(blocks):
        for b in blocks[i + 1:]:
            for key in ("values", "units"):
                for k in set(a.get(key) or {}) & set(b.get(key) or {}):
                    if not set(a[key][k]) & set(b[key][k]):
                        raise ScaleError(f"profile {name}: {where}.{k} {key} {a[key][k]} and {b[key][k]} have nothing in "
                                         "common, and one record may meet both")


def _union(a: list, b: list) -> list:
    return a + [x for x in b if x not in a]


def _merge(into: dict, add: dict) -> None:
    """Combine constraints so the result is at least as strict as either side."""
    for lab, c in add["constraints"].items():
        fresh = lab not in into["constraints"]
        cur = into["constraints"].setdefault(lab, {})
        if fresh:
            cur["unless"] = copy.deepcopy(c.get("unless") or {})
        else:                                    # an exemption survives only if both sides grant it
            mine, theirs = cur.get("unless") or {}, c.get("unless") or {}
            cur["unless"] = {k: [v for v in mine[k] if v in theirs[k]] for k in mine if k in theirs}
            cur["unless"] = {k: v for k, v in cur["unless"].items() if v}
        _merge_block(cur, c, lab)
        if c.get("when"):                        # the cases of both sides apply, each where it matches
            cur["when"] = cur.get("when", []) + copy.deepcopy(c["when"])
    for e, c in add["edge_constraints"].items():
        cur = into["edge_constraints"].setdefault(e, {})
        cur["required"] = _union(cur.get("required", []), c.get("required") or [])
        cur["recommended"] = [x for x in _union(cur.get("recommended", []), c.get("recommended") or [])
                              if x not in cur["required"]]
        if c.get("when"):
            cur["when"] = cur.get("when", []) + copy.deepcopy(c["when"])


def _merge_block(cur: dict, c: dict, lab: str) -> None:
    """Add one block's items (a label's, or a case's) to ``cur``: a must wins over a should, narrowed
    values and units intersect."""
    cur["required"] = _union(cur.get("required", []), c.get("required") or [])
    cur["recommended"] = [x for x in _union(cur.get("recommended", []), c.get("recommended") or [])
                          if x not in cur["required"]]
    for key in ("units", "values"):
        for k, vals in (c.get(key) or {}).items():
            prev = cur.setdefault(key, {}).get(k)
            cur[key][k] = list(vals) if prev is None else [v for v in prev if v in vals]
            if not cur[key][k]:
                raise ScaleError(f"profiles conflict: {lab}.{k} {key} {prev} and {list(vals)} have nothing in common")
    ce, ae = cur.setdefault("edges", {}), c.get("edges") or {}
    ce["required"] = _union(ce.get("required", []), ae.get("required") or [])
    ce["recommended"] = [x for x in _union(ce.get("recommended", []), ae.get("recommended") or [])
                         if x not in ce["required"]]


def matches(p: dict, cond: dict) -> bool:
    """Whether a record meets a case's condition: every property it names lists one of the ``any_of``
    values, or every ``all_of`` value (an enum property counts as a list of one)."""
    for k, m in cond.items():
        v = p.get(k)
        have = {x for x in v if isinstance(x, str)} if isinstance(v, list) else ({v} if isinstance(v, str) else set())
        if "any_of" in m and not have & set(m["any_of"]):
            return False
        if "all_of" in m and not set(m["all_of"]) <= have:
            return False
    return True


def applicable(c: dict, p: dict) -> dict:
    """A block as it applies to one record: its unconditional items and those of every case it meets."""
    if not c.get("when"):
        return c
    out = copy.deepcopy({k: v for k, v in c.items() if k != "when"})
    for x in c["when"]:
        if matches(p, x["if"]):
            _merge_block(out, x, "case")
    return out


# ------------------------------------------------------------------ conformance

def parse_ref(ref: str) -> tuple[str, str | None]:
    name, _, ver = ref.partition("@")
    return name, (ver or None)


def _filled(v) -> tuple[bool, str | None]:
    """(satisfied, why not). A value object counts when its status reports or excludes a value."""
    if v is None:
        return False, "missing"
    if isinstance(v, dict) and "status" in v:
        return (True, None) if v["status"] in SATISFIED else (False, f"declared {v['status']}")
    return True, None


def declared_key(doc: dict) -> str:
    """The declaration a document follows checklists by: follows_domains (profile files and their conforms_to are
    retired by design)."""
    return "follows_domains"


def refs_of(p: dict, default: list, key: str) -> list:
    """A node's own declaration if it has one (an empty list means: none), else the graph's."""
    return p[key] if isinstance(p.get(key), list) else default


def conformance(doc: dict, spec: dict, by_record: bool = False) -> dict:
    """Check every node against the domain checklists it follows (``follows_domains``): its own declaration, else
    the graph's. ``by_record`` also reports, per
    checklist, each node's own outcome (``records``: checked, violations, should filled and expected,
    the should items it misses), its outgoing edges' included; the totals are the same either way."""
    profiles = spec.get("profiles") or {}
    key = declared_key(doc)
    what = "domain"
    default = (doc.get("graph") or {}).get(key) or []
    out: dict = {}
    problems: list[str] = []
    bad: set[str] = set()

    def entry(ref: str) -> dict | None:
        if ref in out:
            return out[ref]
        if ref in bad:
            return None
        name, ver = parse_ref(ref)
        p = profiles.get(name)
        if p is None or p.get("domain") != (key == "follows_domains"):
            problems.append(f"unknown {what} {ref!r}")
            bad.add(ref)
            return None
        if ver and ver != p["version"]:
            problems.append(f"{what} {name} {ver} is declared; this schema carries {p['version']}")
            bad.add(ref)
            return None
        out[ref] = {"profile": name, "version": p["version"], "conformant": True, "nodes_checked": 0,
                    "violations": [], "recommended": {"filled": 0, "expected": 0}, "missing_recommended": {}}
        return out[ref]

    outgoing: dict[str, dict[str, list]] = {}
    for e in doc.get("links") or []:
        outgoing.setdefault(e.get("source"), {}).setdefault(e.get("type"), []).append(e)

    for n in doc.get("nodes") or []:
        p = n.get("props") or {}
        for ref in refs_of(p, default, key):
            r = entry(ref)
            if r is None:
                continue
            eff = profiles[r["profile"]]["effective"]
            c = eff["constraints"].get(n.get("label"))
            links = outgoing.get(n.get("id"), {})
            if by_record:
                was = (r["nodes_checked"], len(r["violations"]), r["recommended"]["filled"], r["recommended"]["expected"],
                       dict(r["missing_recommended"]))
            if c is not None and not exempt(p, c):
                r["nodes_checked"] += 1
                _check_node(n, p, applicable(c, p), links, r)
            for etype, ls in links.items():
                ec = eff["edge_constraints"].get(etype)
                if ec:
                    ec = applicable(ec, p)              # a case of an edge type is evaluated on its source
                    for e in ls:
                        _check_props(e.get("id"), e.get("props") or {}, ec, r, f"{etype}.")
            if by_record:
                miss = {k: v - was[4].get(k, 0) for k, v in r["missing_recommended"].items() if v != was[4].get(k, 0)}
                r.setdefault("records", {})[n.get("id")] = {
                    "checked": r["nodes_checked"] > was[0], "violations": [v["message"] for v in r["violations"][was[1]:]],
                    "filled": r["recommended"]["filled"] - was[2], "expected": r["recommended"]["expected"] - was[3],
                    "missing": miss}
    for r in out.values():
        r["conformant"] = not r["violations"]
        ex = r["recommended"]["expected"]
        r["recommended"]["fraction"] = round(r["recommended"]["filled"] / ex, 3) if ex else None
    return {"profiles": out, "problems": problems, "declared_by": key}


def _miss(r: dict, key: str) -> None:
    r["missing_recommended"][key] = r["missing_recommended"].get(key, 0) + 1


def _check_props(rid, props: dict, c: dict, r: dict, prefix: str) -> None:
    for k in c.get("required") or []:
        ok, why = _filled(props.get(k))
        if not ok:
            r["violations"].append({"record": rid, "message": f"required {prefix}{k} is {why}"})
    for k in c.get("recommended") or []:
        r["recommended"]["expected"] += 1
        if _filled(props.get(k))[0]:
            r["recommended"]["filled"] += 1
        else:
            _miss(r, prefix + k)


def exempt(p: dict, c: dict) -> bool:
    return any(p.get(k) in vals for k, vals in (c.get("unless") or {}).items())


def _check_node(n: dict, p: dict, c: dict, links: dict, r: dict) -> None:
    rid, lab = n.get("id"), n.get("label")
    _check_props(rid, p, c, r, f"{lab}.")
    for k, units in (c.get("units") or {}).items():
        v = p.get(k)
        if isinstance(v, dict) and v.get("unit") is not None and v["unit"] not in units:
            r["violations"].append({"record": rid, "message": f"{lab}.{k} unit {v['unit']!r} is not one of {units}"})
    for k, vals in (c.get("values") or {}).items():
        if k in p and p[k] not in vals:
            r["violations"].append({"record": rid, "message": f"{lab}.{k} {p[k]!r} is not one of {vals}"})
    ed = c.get("edges") or {}
    for e in ed.get("required") or []:
        if not links.get(e):
            r["violations"].append({"record": rid, "message": f"required edge {e} is missing"})
    for e in ed.get("recommended") or []:
        r["recommended"]["expected"] += 1
        if links.get(e):
            r["recommended"]["filled"] += 1
        else:
            _miss(r, f"{lab} -{e}->")
