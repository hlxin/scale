"""scale-catal conformance contracts: the domain files' checklists over the vocabulary.

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
  catalysis domain's one checklist keys its cases on a test's ``driving_forces``. A case may carry its
  ``maturity`` and the ``basis`` its items rest on (a provisional case cites its rationale);
- say which properties a label's cases apply by (``applies_by: [driving_forces]``). A record that states no value of
  one (absent, null or an empty list) has **unknown applicability**: the cases keyed on that property, and the cases
  of its outgoing edges, are neither checked nor met, the record is counted as unknown, and the contract is not
  ``complete``. A record an ``unless`` exempts is counted as exempt; any other record's applicability is known.
  A checklist without ``applies_by`` (every frozen version before it) reads an absent property as before: no case
  matches it;
- require or recommend connected evidence (``evidence: {must | should: [pattern]}``, in a label's block or a case):
  a named pattern of at most two links from the record, incoming or outgoing, each with conditions on the link and
  on the record it reaches, e.g. ``{name: transport_assessment, path: [{edge: HAS_INPUT, direction: in, label:
  Analysis, where: {analysis_kind: {any_of: [transport_check]}}}]}``. An edge type counts its specializations and a
  label its subtypes; ``any_of`` lists alternative paths, ``min`` the records a path must reach, ``report`` a
  property of the reached records that the report shows (a transport check's ``evaluation_basis``). A missing
  ``must`` pattern is a violation; a ``should`` pattern counts towards completeness apart from the should items.
  Evidence is looked for, never inferred, and a record without it stays what it is: a gap is reported, nothing is
  removed.
A checklist may include the checklists of other domain files (``includes``, kept as ``profile_of``); their
constraints apply as well.

A document declares the domains it follows in ``graph.follows_domains`` (a node may override that
with its own ``follows_domains``), as ``name`` or ``name@version``. Validity (the kernel and the domain's vocabulary) and conformance
(checklists) are reported separately: a valid document can fail a checklist, and that is itself an
answer about what its sources report.
"""

from __future__ import annotations

import copy
import re

from .versions import satisfies
from .util import ScaleError, load_yaml

PROFILE_KEYS = {"profile", "version", "title", "description", "maturity", "profile_of", "basis", "guidance",
                "constraints", "edge_constraints", "driving_force", "driving_forces"}
LABEL_KEYS = {"required", "recommended", "units", "values", "edges", "unless", "when", "applies_by", "evidence"}
CASE_KEYS = {"if", "required", "recommended", "units", "values", "edges", "evidence", "maturity", "basis"}
CASE_ITEMS = ("edges", "units", "values", "evidence", "maturity", "basis")   # a case's keys besides must, should and its condition
MATCH = ("any_of", "all_of")
STEP_MATCH = ("any_of", "all_of", "none_of", "present")     # a pattern step's conditions on a record or a link
PATTERN_KEYS = {"name", "description", "path", "any_of", "min", "report"}
STEP_KEYS = {"edge", "direction", "label", "where", "edge_where"}
MAX_STEPS = 2                       # a pattern follows at most two links from the record: bounded, never a graph search
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
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
            elif k in ("edges", "evidence"):
                out[k] = {LEVELS[lvl]: es for lvl, es in (v or {}).items() if lvl in LEVELS}
                if not isinstance(v or {}, dict) or set(v or {}) - set(LEVELS):
                    raise ScaleError(f"{rel}: {where}.{k} takes must and should only")
            elif k in ("units", "values") or (k in ("unless", "applies_by") and not case) or (k in ("maturity", "basis") and case):
                out[k] = v
            elif k == "when" and not case:
                if not isinstance(v, list):
                    raise ScaleError(f"{rel}: {where}.when is a list of cases")
                out["when"] = [when_case(x, f"{where}.when[{i}]") for i, x in enumerate(v)]
            elif case:
                raise ScaleError(f"{rel}: {where} has {k!r}, which is not a condition {{any_of | all_of: [...]}} "
                                 "(a case takes its condition and must, should, edges, units, values, evidence, maturity, basis)")
            else:
                raise ScaleError(f"{rel}: {where} has unknown key {k!r} "
                                 "(must, should, edges, units, values, evidence, unless, applies_by, when)")
        return out

    def when_case(x, where: str) -> dict:
        """A case: its condition (property: {any_of | all_of: [values]}, every one met) and its items."""
        if not isinstance(x, dict):
            raise ScaleError(f"{rel}: {where} is a mapping (a condition and its items)")
        cond = {k: v for k, v in x.items() if k not in LEVELS and k not in CASE_ITEMS}
        if not cond:
            raise ScaleError(f"{rel}: {where} names no condition, e.g. driving_forces: {{any_of: [electro]}}")
        bad = [k for k, v in cond.items() if not (isinstance(v, dict) and len(v) == 1 and set(v) <= set(MATCH)
                                                  and isinstance(next(iter(v.values())), list) and next(iter(v.values())))]
        if bad:
            raise ScaleError(f"{rel}: {where} has {bad[0]!r}, which is not a condition {{any_of | all_of: [...]}} "
                             "(a case takes its condition and must, should, edges, units, values, evidence, maturity, basis)")
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
        named: set = set()
        _check_items(name, lab, c, declared, targets, edges)
        _check_evidence(name, lab, c, targets, spec, named)
        for k, vals in (c.get("unless") or {}).items():
            d = declared.get(k, {})
            if d.get("type") != "enum" or set(vals) - set(d["values"]):
                raise ScaleError(f"profile {name}: {lab} unless {k} must name values of its enum {d.get('values')}")
        for k in c.get("applies_by") or []:
            if _enum_values(declared.get(k)) is None:
                raise ScaleError(f"profile {name}: {lab} applies_by names {k!r}, which is not an enum or a list of enum there")
            if not any(k in (x.get("if") or {}) for x in c.get("when") or []):
                raise ScaleError(f"profile {name}: {lab} applies_by names {k!r}, which no case of {lab} is keyed on")
        _check_cases(name, lab, c, lambda k: declared.get(k),
                     lambda x: (_check_items(name, lab, x, declared, targets, edges),
                                _check_evidence(name, lab, x, targets, spec, named)))
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
            for k in ("evidence", "applies_by"):
                if x.get(k):
                    raise ScaleError(f"profile {name}: {e} has {k}, which a label's block takes (an edge type's cases "
                                     "follow its source)")
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


def _concrete(lab: str, nodes: dict) -> list:
    """A label and every concrete label that is_a it (an abstract label stands for its concrete subtypes)."""
    return ([lab] if lab in nodes else []) + [n for n, nd in nodes.items() if lab in nd.get("ancestors", [])]


def _check_evidence(name: str, lab: str, c: dict, targets: list, spec: dict, named: set) -> None:
    """A block's evidence patterns: each named once in the label's checklist, with one path or alternative paths
    (``any_of``) of at most two steps that the schema allows from the label, conditions on declared properties and
    values, a ``min`` of at least one and a ``report`` property its last records declare."""
    ev = c.get("evidence") or {}
    for lvl, pats in ev.items():
        if not isinstance(pats, list):
            raise ScaleError(f"profile {name}: {lab} evidence is a list of patterns at each level (must, should)")
        for i, pat in enumerate(pats):
            w = f"profile {name}: {lab} evidence[{i}]"
            if not isinstance(pat, dict) or set(pat) - PATTERN_KEYS:
                raise ScaleError(f"{w} is a pattern: name, description, path or any_of, min, report"
                                 + (f"; unknown keys {sorted(set(pat) - PATTERN_KEYS)}" if isinstance(pat, dict) else ""))
            nm = pat.get("name")
            if not isinstance(nm, str) or not NAME.match(nm):
                raise ScaleError(f"{w} needs a snake_case name")
            if nm in named:
                raise ScaleError(f"{w}: {nm} names two patterns of {lab}")
            named.add(nm)
            if ("path" in pat) == ("any_of" in pat):
                raise ScaleError(f"{w} ({nm}) takes a path or any_of (alternative paths), one of them")
            alts = [pat["path"]] if "path" in pat else pat["any_of"]
            if not isinstance(alts, list) or not alts:
                raise ScaleError(f"{w} ({nm}): any_of lists alternative paths, each {{path: [steps]}}")
            ends: set = set()
            for j, alt in enumerate(alts):
                path = alt if "path" in pat else (alt.get("path") if isinstance(alt, dict) and set(alt) == {"path"} else None)
                ends |= _check_path(f"{w} ({nm})" + ("" if "path" in pat else f" any_of[{j}]"), path, targets, spec)
            mn = pat.get("min", 1)
            if not isinstance(mn, int) or isinstance(mn, bool) or mn < 1:
                raise ScaleError(f"{w} ({nm}): min is a whole number of at least 1")
            rep = pat.get("report")
            if rep is not None:
                common = spec["common"]["node"]["properties"]
                if not isinstance(rep, str) or not any(rep in {**common, **spec["nodes"][x]["properties"]} for x in ends):
                    raise ScaleError(f"{w} ({nm}): report names {rep!r}, which no record the pattern reaches declares")


def _check_path(w: str, path, targets: list, spec: dict) -> set:
    """One path of a pattern: one or two steps, each an edge type the schema lets the current records take in the
    stated direction, to a label at its other end, with conditions on declared properties. Returns the concrete labels
    the path ends at."""
    if not isinstance(path, list) or not 1 <= len(path) <= MAX_STEPS:
        raise ScaleError(f"{w}: a path is a list of one or two steps (a pattern follows at most {MAX_STEPS} links)")
    nodes, edges, abstract = spec["nodes"], spec["edges"], spec.get("abstract") or {}
    cur = set(targets)
    for j, st in enumerate(path):
        ws = f"{w} step {j + 1}"
        if not isinstance(st, dict) or set(st) - STEP_KEYS or "edge" not in st:
            raise ScaleError(f"{ws} takes edge, direction, label, where, edge_where")
        e, d = st["edge"], st.get("direction", "out")
        if e not in edges:
            raise ScaleError(f"{ws}: unknown edge type {e}")
        if d not in ("in", "out"):
            raise ScaleError(f"{ws}: direction is in or out")
        near, far = (edges[e]["to"], edges[e]["from"]) if d == "in" else (edges[e]["from"], edges[e]["to"])
        if not cur & set(near):
            raise ScaleError(f"{ws}: {e} never {'ends at' if d == 'in' else 'starts from'} {sorted(cur)[0]}"
                             + (" or the other labels here" if len(cur) > 1 else ""))
        lab = st.get("label")
        if lab is not None:
            if lab not in nodes and lab not in abstract:
                raise ScaleError(f"{ws}: unknown label {lab}")
            other = set(_concrete(lab, nodes)) & set(far)
            if not other:
                raise ScaleError(f"{ws}: {lab} is never at the other end of {e}")
            declared = {**spec["common"]["node"]["properties"], **(nodes.get(lab) or abstract.get(lab) or {}).get("properties", {})}
        else:
            other, declared = set(far), None
        if st.get("where") is not None:
            if declared is None:
                raise ScaleError(f"{ws}: where tests the record the step reaches; name its label")
            _check_conditions(ws, st["where"], declared)
        if st.get("edge_where") is not None:
            _check_conditions(ws, st["edge_where"], {**spec["common"]["link"]["properties"], **(edges[e].get("properties") or {})})
        cur = other
    return cur


def _check_conditions(ws: str, conds, declared: dict) -> None:
    """A step's conditions: property: {any_of | all_of | none_of: [values of its enum]} or {present: true}."""
    if not isinstance(conds, dict) or not conds:
        raise ScaleError(f"{ws}: conditions map a property to {{any_of | all_of | none_of: [values]}} or {{present: true}}")
    for k, m in conds.items():
        if k not in declared:
            raise ScaleError(f"{ws}: no property {k!r} there")
        if not isinstance(m, dict) or len(m) != 1 or not set(m) <= set(STEP_MATCH):
            raise ScaleError(f"{ws}: {k} takes one of {list(STEP_MATCH)}")
        op, vals = next(iter(m.items()))
        if op == "present":
            if vals is not True:
                raise ScaleError(f"{ws}: {k} present takes true")
            continue
        allowed = _enum_values(declared[k])
        if allowed is None:
            raise ScaleError(f"{ws}: {k} is not an enum or a list of enum; test it with present: true")
        if not isinstance(vals, list) or not vals or set(vals) - set(allowed):
            raise ScaleError(f"{ws}: {k} {op} must name values of its enum {allowed}")


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
        if c.get("applies_by"):                  # either side's: a property either applies by stays one
            cur["applies_by"] = _union(cur.get("applies_by", []), c["applies_by"])
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
    if c.get("evidence") or cur.get("evidence"):   # patterns by name: a must wins over a should of the same name
        cv, av = cur.setdefault("evidence", {}), c.get("evidence") or {}
        cv["required"] = _union_named(cv.get("required", []), av.get("required") or [])
        must = {p["name"] for p in cv["required"]}
        cv["recommended"] = [p for p in _union_named(cv.get("recommended", []), av.get("recommended") or [])
                             if p["name"] not in must]


def _union_named(a: list, b: list) -> list:
    names = {p["name"] for p in a}
    return a + [copy.deepcopy(p) for p in b if p["name"] not in names]


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


def applicable(c: dict, p: dict, unknown=()) -> dict:
    """A block as it applies to one record: its unconditional items and those of every case it meets. A case keyed on
    a property in ``unknown`` (one the record's label applies by and the record does not state) is undetermined: it
    is neither met nor applied."""
    if not c.get("when"):
        return c
    out = copy.deepcopy({k: v for k, v in c.items() if k != "when"})
    for x in c["when"]:
        if set(x["if"]) & set(unknown):
            continue
        if matches(p, x["if"]):
            _merge_block(out, x, "case")
    return out


def _states(v) -> bool:
    """Whether a record states a value of a property: not absent, null or empty."""
    return v is not None and not (isinstance(v, (list, dict, str)) and not v)


def unknown_of(c: dict | None, p: dict) -> list:
    """The properties a label applies its cases by (``applies_by``) that the record does not state."""
    return [k for k in (c or {}).get("applies_by") or [] if not _states(p.get(k))]


class _Graph:
    """What an evidence pattern walks: the document's records and its links both ways, the edge types that specialize
    an edge type and the labels a label is."""

    def __init__(self, doc: dict, spec: dict):
        self.nodes = {n.get("id"): n for n in doc.get("nodes") or []}
        self.out: dict = {}
        self.inc: dict = {}
        for e in doc.get("links") or []:
            self.out.setdefault(e.get("source"), []).append(e)
            self.inc.setdefault(e.get("target"), []).append(e)
        self.edges = spec.get("edges") or {}
        self.labels = spec.get("nodes") or {}
        self._sub: dict = {}

    def subtypes(self, e: str) -> set:
        if e not in self._sub:
            out, grew = {e}, True
            while grew:
                grew = False
                for n, d in self.edges.items():
                    if n not in out and d.get("specializes") in out:
                        out.add(n)
                        grew = True
            self._sub[e] = out
        return self._sub[e]

    def is_a(self, label, target: str) -> bool:
        return label == target or target in ((self.labels.get(label) or {}).get("ancestors") or [])


def _meets(props: dict, conds: dict | None) -> bool:
    """A step's conditions on a record's or a link's properties: any_of, all_of, none_of (the property is stated and
    lists none of the values), present (a value object counts when its status reports or excludes a value)."""
    for k, m in (conds or {}).items():
        v = props.get(k)
        have = {x for x in v if isinstance(x, str)} if isinstance(v, list) else ({v} if isinstance(v, str) else set())
        stated = _filled(v)[0] and _states(v) and v != "not_reported"      # an enum's not_reported states nothing
        if "present" in m and stated != bool(m["present"]):
            return False
        if "any_of" in m and not have & set(m["any_of"]):
            return False
        if "all_of" in m and not set(m["all_of"]) <= have:
            return False
        if "none_of" in m and (not have or have & set(m["none_of"])):
            return False
    return True


def _reach(start: str, path: list, g: _Graph) -> set:
    """The records one path of a pattern reaches from a record, step by step."""
    cur = {start}
    for st in path:
        nxt: set = set()
        out = st.get("direction", "out") == "out"
        types = g.subtypes(st["edge"])
        for rid in cur:
            for e in (g.out if out else g.inc).get(rid, []):
                if e.get("type") not in types or not _meets(e.get("props") or {}, st.get("edge_where")):
                    continue
                other = e.get("target") if out else e.get("source")
                n = g.nodes.get(other)
                if n is None or (st.get("label") and not g.is_a(n.get("label"), st["label"])):
                    continue
                if _meets(n.get("props") or {}, st.get("where")):
                    nxt.add(other)
        cur = nxt
    return cur


def evidence_of(rid: str, pat: dict, g: _Graph) -> list:
    """The records a pattern's met paths reach from a record (empty when none is met): a path is met when it reaches
    at least ``min`` records."""
    found: set = set()
    for path in ([pat["path"]] if "path" in pat else [a["path"] for a in pat["any_of"]]):
        r = _reach(rid, path, g)
        if len(r) >= pat.get("min", 1):
            found |= r
    return sorted(found)


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
    the graph's. Per checklist: ``conformant`` (no must item, edge or evidence is missing), the should items filled
    of those expected, the evidence patterns found of those expected, ``applicability`` (records whose cases are
    known, ``unknown`` because they state no value of a property their label applies by, or ``exempt``), the
    ``unknown`` records, and ``complete``: conformant, nothing unknown, every should item and evidence pattern found.
    Validity is reported apart (``pgraph.validate``), and so is what a scientific comparison may compare
    (``pgraph_query``): a complete record is not thereby comparable, nor an incomplete one invalid.

    ``by_record`` also reports, per checklist, each node's own outcome (``records``: checked, its applicability and
    the properties it is unknown for, violations, should filled and expected, the should items it misses, and each
    evidence pattern with the records found), its outgoing edges' included; the totals are the same either way."""
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
                    "violations": [], "recommended": {"filled": 0, "expected": 0}, "missing_recommended": {},
                    "evidence": {"found": 0, "expected": 0}, "missing_evidence": {},
                    "applicability": {"known": 0, "unknown": 0, "exempt": 0}, "unknown": []}
        return out[ref]

    outgoing: dict[str, dict[str, list]] = {}
    for e in doc.get("links") or []:
        outgoing.setdefault(e.get("source"), {}).setdefault(e.get("type"), []).append(e)
    g = _Graph(doc, spec)

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
            unknown = unknown_of(c, p)
            state, found = None, {}
            if c is not None and exempt(p, c):
                state = "exempt"
            elif c is not None:
                r["nodes_checked"] += 1
                blk = applicable(c, p, unknown)
                _check_node(n, p, blk, links, r)
                found = _check_evidence_of(n, blk, r, g)
                state = "unknown" if unknown else "known"
            if state:
                r["applicability"][state] += 1
                if state == "unknown":
                    r["unknown"].append({"record": n.get("id"), "label": n.get("label"), "properties": unknown})
            for etype, ls in links.items():
                ec = eff["edge_constraints"].get(etype)
                if ec:
                    ec = applicable(ec, p, unknown)     # a case of an edge type is evaluated on its source
                    for e in ls:
                        _check_props(e.get("id"), e.get("props") or {}, ec, r, f"{etype}.")
            if by_record:
                miss = {k: v - was[4].get(k, 0) for k, v in r["missing_recommended"].items() if v != was[4].get(k, 0)}
                r.setdefault("records", {})[n.get("id")] = {
                    "checked": r["nodes_checked"] > was[0], "applicability": state,
                    **({"unknown_for": unknown} if state == "unknown" else {}),
                    "violations": [v["message"] for v in r["violations"][was[1]:]],
                    "filled": r["recommended"]["filled"] - was[2], "expected": r["recommended"]["expected"] - was[3],
                    "missing": miss, **({"evidence": found} if found else {})}
    for r in out.values():
        r["conformant"] = not r["violations"]
        ex = r["recommended"]["expected"]
        r["recommended"]["fraction"] = round(r["recommended"]["filled"] / ex, 3) if ex else None
        r["complete"] = (r["conformant"] and not r["applicability"]["unknown"] and r["recommended"]["filled"] == ex
                         and r["evidence"]["found"] == r["evidence"]["expected"])
    return {"profiles": out, "problems": problems, "declared_by": key}


def _check_evidence_of(n: dict, c: dict, r: dict, g: _Graph) -> dict:
    """The evidence patterns of a record's applicable block, looked for in the document: a missing must is a
    violation, a should counts towards completeness (``evidence``, ``missing_evidence``). Returns, per pattern, whether
    it was found, the records found and the values of its ``report`` property."""
    rid, out = n.get("id"), {}
    ev = c.get("evidence") or {}
    for lvl in ("required", "recommended"):
        for pat in ev.get(lvl) or []:
            recs = evidence_of(rid, pat, g)
            rep = pat.get("report")
            out[pat["name"]] = {"level": "must" if lvl == "required" else "should", "found": bool(recs), "records": recs,
                                **({"report": {rep: sorted({str(v) for x in recs
                                                            if (v := (g.nodes[x].get("props") or {}).get(rep)) is not None})}}
                                   if rep else {})}
            if lvl == "required":
                if not recs:
                    r["violations"].append({"record": rid, "message": f"required evidence {pat['name']} is missing"
                                            + (f": {pat['description']}" if pat.get("description") else "")})
                continue
            r["evidence"]["expected"] += 1
            if recs:
                r["evidence"]["found"] += 1
            else:
                r["missing_evidence"][pat["name"]] = r["missing_evidence"].get(pat["name"], 0) + 1
    return out


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
