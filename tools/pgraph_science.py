"""Science checks of the scale-catal science kernel.

Rules about the method of science that a type check cannot express: tests that assert an outcome
cite what it rests on; predictions made after the result are flagged; a fit does not confirm its
own data; a hypothesis's status agrees with the evidence recorded for it; references and evidence
ids resolve (and so do the record_refs a value holds, its normalized_by); plans and orderings are acyclic; inputs used at an old version are flagged; records that rest on retracted sources are flagged (source lifecycle, ``lifecycle``); a model validated on the data it was fitted to is flagged, since a fit to its own data is a calibration, not independent validation (:func:`validation_checks`); a predicted value that names no producer is flagged.

The checks report; they never grade science. Severity, independence and confounding are recorded
as the source or an assessor states them and are not computed (the overlap of a validation's data with the data its
model was fitted to is read from the records, not judged).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterator

from . import results

VALUE_STATUS = {"present", "not_reported", "not_measured", "not_applicable", "below_detection_limit",
                "below_quantification_limit"}
POLAR = {"supports", "disputes", "refutes"}


def _values(obj: Any, path: str = "") -> Iterator[tuple[str, dict]]:
    """Every value object inside a props tree, with its JSON pointer."""
    if isinstance(obj, dict):
        if obj.get("status") in VALUE_STATUS and path:
            yield path, obj
        for k, v in obj.items():
            if k != "evidence":
                yield from _values(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _values(v, f"{path}/{i}")


def _pointer(props: dict, path: str) -> tuple[bool, Any]:
    """What a record_ref's path names: a key of a map, or a list item by its position or its id (results.resolve)."""
    return results.resolve(props, path)


def _when(p: dict) -> str | None:
    """A comparable ISO string for when something happened (datetime or date at any precision)."""
    for k in ("started_at", "performed_on", "finished_at"):
        if isinstance(p.get(k), str):
            return p[k]
    return None


def _before(a: str, b: str) -> bool | None:
    """a strictly before b, compared at their common precision; None when undecidable."""
    n = min(len(a), len(b), 10)
    if a[:n] == b[:n]:
        return None
    return a[:n] < b[:n]


def _cyclic(edges: list[tuple[str, str]]) -> list[str]:
    graph = defaultdict(list)
    for a, b in edges:
        graph[a].append(b)
    state: dict[str, int] = {}
    found: list[str] = []
    # depth first, iteratively (a chain of thousands of links is a valid graph, not a recursion limit): the path
    # from the start to the node being visited, and each path node's position on it
    for start in list(graph):
        if state.get(start):
            continue
        path, at, todo = [start], {start: 0}, [iter(graph[start])]
        state[start] = 1
        while todo:
            m = next(todo[-1], None)
            if m is None:                                   # every link of the deepest node followed
                n = path.pop()
                del at[n]
                state[n] = 2
                todo.pop()
            elif state.get(m) == 1:                         # back to a node on the path: a cycle
                found.append(" -> ".join(path[at[m]:] + [m]))
            elif not state.get(m):
                state[m] = 1
                at[m] = len(path)
                path.append(m)
                todo.append(iter(graph[m]))
    return found


def science_checks(doc: dict, spec: dict, rep) -> None:
    nodes = {n["id"]: n for n in doc.get("nodes") or [] if isinstance(n.get("id"), str)}
    links = [e for e in doc.get("links") or [] if isinstance(e, dict)]
    records = {**nodes, **{e["id"]: e for e in links if isinstance(e.get("id"), str)}}
    props = {rid: (r.get("props") or {}) for rid, r in records.items()}
    label = {nid: n.get("label") for nid, n in nodes.items()}
    edges_def = spec["edges"]
    out = defaultdict(list)
    inc = defaultdict(list)
    for e in links:
        out[e.get("source")].append(e)
        inc[e.get("target")].append(e)
    warn = lambda rid, msg: rep.add("warning", rid, msg)  # noqa: E731
    err = lambda rid, msg: rep.add("error", rid, msg)  # noqa: E731

    # ---- record references (paths) and evidence ids
    def refs_of(e: dict) -> Iterator[tuple[str, dict]]:
        for k, d in (edges_def.get(e.get("type"), {}).get("properties") or {}).items():
            v = (e.get("props") or {}).get(k)
            if d.get("type") == "record_ref" and isinstance(v, dict):
                yield k, v
            elif d.get("type") == "list" and d.get("items", {}).get("type") == "record_ref" and isinstance(v, list):
                for x in v:
                    if isinstance(x, dict):
                        yield k, x

    resolved_refs: dict[str, list[Any]] = defaultdict(list)
    for e in links:
        for k, r in refs_of(e):
            target = r.get("record")
            if target not in records:
                continue                      # unresolved ids are reported by the type check
            if "path" in r:
                if results.by_position(r["path"]):
                    err(e["id"], f"{k}: {target}{r['path']} names a result by its position; name it by its id "
                                 f"(/{results.RESULTS}/<id>), which no reordering or filtering changes")
                    continue
                ok, val = _pointer(props[target], r["path"])
                if not ok:
                    err(e["id"], f"{k}: {target}{r['path']} does not resolve to a property")
                    continue
                resolved_refs[e["id"]].append(val)
            want = r.get("record_version")
            have = props[target].get("record_version")
            if want is not None and have is not None and want != have:
                warn(e["id"], f"{k}: refers to {target} version {want}; the graph holds version {have}")
    # record_refs inside value objects (a value's normalized_by), at any depth, resolve as a link's do
    value_refs = [k for k, d in ((spec.get("value") or {}).get("fields") or {}).items() if d.get("type") == "record_ref"]
    for rid, p in props.items():
        for path, v in _values(p) if value_refs else ():
            for k in value_refs:
                r = v.get(k)
                if not isinstance(r, dict) or r.get("record") not in records:
                    continue                  # not a record_ref, or one that does not resolve: the type check reports it
                if isinstance(r.get("path"), str):
                    ok, _ = _pointer(props[r["record"]], r["path"])
                    if results.by_position(r["path"]):
                        err(rid, f"{path[1:]}.{k}: {r['record']}{r['path']} names a result by its position; name it by "
                                 f"its id (/{results.RESULTS}/<id>)")
                    elif not ok:
                        err(rid, f"{path[1:]}.{k}: {r['record']}{r['path']} does not resolve to a property")
                want, have = r.get("record_version"), props[r["record"]].get("record_version")
                if want is not None and have is not None and want != have:
                    warn(rid, f"{path[1:]}.{k}: refers to {r['record']} version {want}; the graph holds version {have}")
    for rid, p in props.items():
        ev_ids = [ev.get("id") for ev in p.get("evidence") or [] if isinstance(ev, dict) and ev.get("id")]
        if len(ev_ids) != len(set(ev_ids)):
            err(rid, "evidence ids repeat within the record")
        for path, v in _values(p):
            for x in v.get("evidence_ids") or []:
                if x not in ev_ids:
                    err(rid, f"{path}: evidence_ids names {x!r}, which is not an evidence item of this record")

    # ---- tests of hypotheses and predictions
    for e in links:
        if e.get("type") != "TESTS":
            continue
        p = e.get("props") or {}
        exp, tgt = props.get(e.get("source"), {}), props.get(e.get("target"), {})
        if p.get("outcome") in POLAR and not (p.get("evidence") or p.get("result_refs")):
            err(e["id"], f"a TESTS outcome '{p['outcome']}' cites evidence or result_refs")
        if label.get(e.get("target")) == "Prediction" or "Prediction" in _ancestors(spec, label.get(e.get("target"))):
            made, ran = tgt.get("proposed_at"), _when(exp)
            if isinstance(made, str) and ran and _before(ran, made):
                warn(e["id"], f"post hoc: prediction {e['target']} was proposed ({made}) after the test started ({ran})")
        if p.get("outcome") == "supports":
            fitted = [v for v in resolved_refs.get(e["id"], []) if isinstance(v, dict) and v.get("origin") == "fitted"]
            if fitted:
                warn(e["id"], "a supports outcome rests on a fitted value; a fit does not confirm its own data")

    # ---- hypothesis status agrees with the recorded evidence
    for nid, n in nodes.items():
        if n.get("label") != "Hypothesis":
            continue
        st = props[nid].get("hypothesis_status")
        ins = inc.get(nid, [])
        outcomes = {(e.get("props") or {}).get("outcome") for e in ins if e.get("type") == "TESTS"}
        types = {e.get("type") for e in ins}
        need = {"supported": ("supports" in outcomes or "SUPPORTS" in types),
                "refuted": ("refutes" in outcomes or "CONTRADICTS" in types),
                "disputed": (bool(outcomes & {"disputes", "refutes"}) or "CONTRADICTS" in types)}
        if st in need and not need[st]:
            err(nid, f"hypothesis_status {st} has no test outcome or argument link that says so")

    # ---- experiments, predictions, variables
    for nid, n in nodes.items():
        p, lab = props[nid], n.get("label")
        anc = [lab] + _ancestors(spec, lab)
        if "Experiment" in anc and p.get("approach") == "hypothesis_driven":
            if not any(e.get("type") in ("TESTS", "AIMS_TO_TEST") for e in out.get(nid, [])):
                warn(nid, "a hypothesis-driven experiment names no hypothesis or prediction it tests (TESTS or AIMS_TO_TEST)")
        if lab == "Prediction":
            if not (p.get("statement") or p.get("expected")):
                err(nid, "a prediction states its expectation (statement or expected)")
            ev = (p.get("expected") or {}).get("variable")
            if ev and p.get("variable") and ev != p["variable"]:
                err(nid, "the prediction's variable and expected.variable disagree")
        if lab == "Variable":
            if p.get("scale") == "quantitative" and not p.get("quantity_kind"):
                err(nid, "a quantitative variable names its quantity_kind")
    scale = {nid: props[nid].get("scale") for nid, n in nodes.items() if n.get("label") == "Variable"}
    cats = {nid: props[nid].get("categories") for nid in scale}
    for rid, p in props.items():
        for path, v in _values(p):
            var = v.get("variable")
            if var in scale and scale[var] in ("nominal", "ordinal") and v.get("status") == "present":
                if "text_value" not in v:
                    err(rid, f"{path}: a value of {scale[var]} variable {var} is a text_value")
                elif cats.get(var) and v["text_value"] not in cats[var]:
                    warn(rid, f"{path}: {v['text_value']!r} is not one of the categories of {var}")

    # ---- operations: static or dynamic
    for nid, n in nodes.items():
        if n.get("label") != "Operation":
            continue
        p = props[nid]
        if p.get("operation_mode") == "dynamic":
            if not p.get("varied_quantities"):
                err(nid, "a dynamic operation names its varied_quantities")
            said = any(p.get(k) for k in ("segments", "period", "frequency", "bit_duration", "pulse_width", "description"))
            if not said and not (p.get("time_pattern") == "step" and p.get("levels")):     # a step: its levels say it
                warn(nid, "a dynamic operation says how it varies (segments, period, frequency, a sequence's bit_duration, "
                          "pulse_width, a step's levels or description)")
        elif p.get("operation_mode") == "static" and p.get("time_pattern") not in (None, "constant", "not_reported"):
            err(nid, f"a static operation has time_pattern constant, not {p['time_pattern']}")

    # ---- a model validated on the data it was fitted to: not independent predictive validation
    tables = {nid for nid, lab in label.items() if lab == "Dataset" or "Dataset" in _ancestors(spec, lab)}
    validation_checks(links, label, resolved_refs, rep, tables)
    for rid, p in props.items():
        holder_is_experiment = rid in nodes and "Experiment" in [label.get(rid)] + _ancestors(spec, label.get(rid))
        for path, v in _values(p):
            if v.get("origin") == "predicted" and not v.get("produced_by") and not holder_is_experiment:
                warn(rid, f"{path[1:]}: a predicted value names the experiment that predicted it (produced_by), whose model "
                          "and the data it was fitted to say what the prediction rests on")

    # ---- controls and replication (recorded, not judged)
    for e in links:
        p = e.get("props") or {}
        if e.get("type") == "CONTROL_FOR" and not p.get("differs_in"):
            warn(e["id"], "a control names the variables in which it differs (differs_in)")
        if e.get("type") == "REPLICATES" and p.get("level") == "reproduce" and not p.get("changed"):
            warn(e["id"], "a reproduction lists what changed (data, sample, method, team, site, …)")

    # ---- a computation's level of theory is a name of the electronic-structure method it uses (advisory, for schemas
    #      that can say so)
    if "USES_METHOD" in edges_def:
        used = defaultdict(list)
        for e in links:
            if e.get("type") == "USES_METHOD" and label.get(e.get("target")) == "Method":
                used[e.get("source")].append(e["target"])
        for src, methods in used.items():
            lot = props.get(src, {}).get("level_of_theory")
            es = [m for m in methods if props.get(m, {}).get("method_kind") in ELECTRONIC_STRUCTURE]
            if not es or not (isinstance(lot, dict) and lot.get("status") == "present"
                              and isinstance(lot.get("text_value"), str)):
                continue
            names = {_name(n) for m in es for n in [props[m].get("name"), *_list(props[m].get("aliases"))]
                     if isinstance(n, str)}
            if _name(lot["text_value"]) not in names:
                warn(src, f"level_of_theory {lot['text_value']!r} is none of the names of the electronic-structure method "
                          f"it uses ({', '.join(sorted(str(props[m].get('name') or m) for m in es))}); a comparison reads "
                          "level_of_theory, so state the method's name there, or add the source's name to its aliases")

    # ---- structure: self-links, acyclic orderings, revisions
    kernel_edges = {t for t, d in edges_def.items() if d.get("module") == "kernel"}
    for e in links:
        if e.get("type") in kernel_edges and e.get("source") == e.get("target"):
            err(e["id"], f"a {e['type']} link joins a record to itself")
        if e.get("type") == "REVISES" and label.get(e.get("source")) != label.get(e.get("target")):
            err(e["id"], "REVISES joins two versions of a record of the same label")
    for t in ("PART_OF", "PRECEDES", "HAS_PART", "REVISES", "VARIANT_OF"):
        for cyc in _cyclic([(e["source"], e["target"]) for e in links if e.get("type") == t]):
            err("<graph>", f"{t} forms a cycle: {cyc}")

    # ---- product lumps (catalysis): containment is acyclic and joins two lumps, a window runs from its least to its
    # greatest carbon number, an open-ended one has no greatest
    for e in links:
        if e.get("type") == "SUBSET_OF" and e.get("source") == e.get("target"):
            err(e["id"], "a SUBSET_OF link joins a lump to itself")
    for cyc in _cyclic([(e["source"], e["target"]) for e in links
                                  if e.get("type") == "SUBSET_OF" and e.get("source") != e.get("target")]):
        err("<graph>", f"SUBSET_OF forms a cycle: {cyc}")
    for nid, n in nodes.items():
        if n.get("label") != "ProductLump":
            continue
        lo, hi, p = props[nid].get("carbon_min"), props[nid].get("carbon_max"), props[nid]
        if isinstance(lo, int) and isinstance(hi, int) and lo > hi:
            err(nid, f"a product lump runs from its least carbon number to its greatest: carbon_min {lo} is above carbon_max {hi}")
        if p.get("open_ended") is True and hi is not None:
            err(nid, "an open-ended product lump has no carbon_max (open_ended true)")

    # ---- inputs used at an older version
    for e in links:
        if e.get("type") != "HAS_INPUT":
            continue
        used = (e.get("props") or {}).get("input_version")
        now = props.get(e.get("target"), {}).get("record_version")
        if isinstance(used, int) and isinstance(now, int) and used < now \
                and props.get(e.get("source"), {}).get("freshness_status") != "inputs_revised":
            warn(e.get("source"), f"inputs revised: {e['target']} was used at version {used}; version {now} is current")

    lifecycle_checks(doc, spec, rep, nodes, links, props, inc)


ELECTRONIC_STRUCTURE = ("exchange_correlation_functional", "wavefunction_method", "semiempirical_method")


def _list(v: Any) -> list:
    """A list property's items, or none when it is not a list (the type check reports that)."""
    return v if isinstance(v, list) else []


def _name(s: str) -> str:
    """A method's name as it is matched: case, spaces, hyphens and underscores ignored (BEEF-vdW, beef vdw)."""
    return re.sub(r"[\s\-_]+", "", s.casefold())


FIT_ROLES = ("training_data", "calibration_data")          # the inputs a calibration fits a model to
SPLITS_OF_ONE_TABLE = ("random", "grouped", "time_based", "out_of_distribution", "other")   # held out within the data
CALIBRATES = ("calibration",)
VALIDATES = ("validation", "benchmark")


def validation_checks(links: list[dict], label: dict, resolved_refs: dict, rep, tables: set | None = None) -> None:
    """A validation is independent only of data its model was not fitted to. The data a model was fitted to is what an
    experiment that calibrates it (EVALUATES with evaluation_kind calibration, or HAS_OUTPUT the model) HAS_INPUT as
    training_data or calibration_data, with the records a dataset among them INCLUDES. A validation or benchmark
    (EVALUATES) of the model whose experiment HAS_INPUT any of that data, or that rests on a fitted value (result_refs),
    is reported (a warning): a fit to its own data is a calibration, never independent predictive validation. A
    validation that states it split one table (split_strategy random, grouped, time_based, out_of_distribution or
    other, 0.7.2 on: the folds of a cross-validation, a held-out part) shares that very table with the fit by design: a
    dataset (``tables``) both take directly is not reported, nor what both reach only through it. What either reaches
    some other way is (an observation both take directly, a record another dataset includes), and so is any overlap of a
    validation that claims independent data (external, prospective). Whether the split keeps the folds apart is what
    split_strategy says (a random split is flagged by `scale trace-ai`). Nothing is rewritten."""
    out = defaultdict(list)
    for e in links:
        out[e.get("source")].append(e)

    def direct(exp: str, roles: tuple | None) -> set:
        return {e.get("target") for e in out.get(exp, []) if e.get("type") == "HAS_INPUT"
                and (roles is None or (e.get("props") or {}).get("role") in roles)}

    def inputs(exp: str, roles: tuple | None) -> set:
        return _included(direct(exp, roles), out)

    tables = tables or set()
    fitted: dict[str, set] = defaultdict(set)
    fitted_direct: dict[str, set] = defaultdict(set)       # what a fit takes directly (not through INCLUDES)
    for e in links:
        p = e.get("props") or {}
        if (e.get("type") == "EVALUATES" and p.get("evaluation_kind") in CALIBRATES) or \
                (e.get("type") == "HAS_OUTPUT" and label.get(e.get("target")) is not None):
            fitted[e.get("target")] |= inputs(e.get("source"), FIT_ROLES)
            fitted_direct[e.get("target")] |= direct(e.get("source"), FIT_ROLES)
    for e in links:
        p = e.get("props") or {}
        if e.get("type") != "EVALUATES" or p.get("evaluation_kind") not in VALIDATES:
            continue
        model, exp = e.get("target"), e.get("source")
        used = inputs(exp, None) - {model}
        fit_all, fit_direct = fitted.get(model, set()), fitted_direct.get(model, set())
        shared = used & fit_all
        split = {x for x in direct(exp, None) & fit_direct if x in tables}
        if p.get("split_strategy") in SPLITS_OF_ONE_TABLE and split:
            # its folds are parts of a dataset the fit takes as well: what both reach only through it is held out by
            # the split, as stated; what either reaches another way is not
            fit_other = _included(fit_direct - split, out)
            val_other = _included(direct(exp, None) - split - {model}, out)
            shared = (used & fit_other) | (fit_all & val_other)
        overlap = sorted(str(x) for x in shared)
        if overlap:
            rep.add("warning", e.get("id"), f"a {p['evaluation_kind']} of {model} on data it was fitted to "
                                            f"({', '.join(overlap)}): a fit to its own data is a calibration, not "
                                            "independent predictive validation; it stays as recorded")
        fits = [v for v in resolved_refs.get(e.get("id"), []) if isinstance(v, dict) and v.get("origin") == "fitted"]
        if fits and p.get("outcome") in ("passes", "partial"):
            rep.add("warning", e.get("id"), f"a {p['evaluation_kind']} whose outcome rests on a fitted value: a fit does not "
                                            "validate its own data")


def _included(ids: set, out: dict) -> set:
    """Records and what the datasets among them include (INCLUDES, followed to any depth)."""
    seen, todo = set(ids), list(ids)
    while todo:
        x = todo.pop()
        for e in out.get(x, []):
            if e.get("type") == "INCLUDES" and e.get("target") not in seen:
                seen.add(e.get("target"))
                todo.append(e.get("target"))
    return seen


def lifecycle_checks(doc: dict, spec: dict, rep, nodes: dict, links: list[dict], props: dict, inc) -> None:
    """Source lifecycle: a notice is authoritative and a source's status is derived from the
    notices that reach it (``lifecycle``). What rests on retracted sources is flagged, never rewritten; the counts
    go to ``rep.lifecycle`` for the summaries. Nothing fires on a document that records no notice."""
    from .lifecycle import RETRACTED, resting, statuses, summary
    warn = lambda rid, msg: rep.add("warning", rid, msg)  # noqa: E731
    for e in links:
        if e.get("type") != "RETRACTS":
            continue
        p = e.get("props") or {}
        if not p.get("retracted_on"):
            warn(e.get("id"), "retraction_undated: a RETRACTS link states when the retraction was made (retracted_on)")
        if p.get("scope_locators") and p.get("scope") != "partial":
            rep.add("error", e.get("id"), "scope_locators go only with a partial retraction (scope partial); "
                                          "a full retraction covers the whole source")
    st = statuses(doc, spec)
    rest = resting(doc, spec, st)
    for rid in sorted(rest, key=str):
        r = rest[rid]
        if r["rests"] == "all":
            warn(rid, f"rests_on_retracted_source: all the evidence it rests on is retracted ({_retracted_support(rid, r)}); "
                      "flagged, not rewritten")
        else:
            warn(rid, f"partially_rests_on_retracted_source: some of the evidence it rests on is retracted "
                      f"({_retracted_support(rid, r)})")
    for nid, n in nodes.items():
        key = {"Claim": "claim_status", "Hypothesis": "hypothesis_status"}.get(n.get("label"))
        if not key:
            continue
        status = props[nid].get(key)
        if status == "supported" and (rest.get(nid) or {}).get("rests") == "all":
            warn(nid, f"supported_on_retracted_sources: {key} supported rests only on retracted evidence "
                      f"({_retracted_support(nid, rest[nid])})")
        if status == "retracted":
            noticed = any(e.get("type") == "RETRACTS" for e in inc.get(nid, [])) or any(
                (st.get(ev.get("source")) or {}).get("status") in RETRACTED | {"partially_retracted"}
                for ev in props[nid].get("evidence") or [] if isinstance(ev, dict))
            if not noticed:
                warn(nid, f"retracted_without_notice: {key} retracted, but no RETRACTS link reaches it and none of the "
                          "sources its evidence cites is retracted; record the notice (a Source that RETRACTS)")
    rep.lifecycle = summary(st, rest)


def _retracted_support(rid: str, r: dict) -> str:
    """What a record's retracted support is, naming only the sources that are themselves retracted (or withdrawn)
    and, apart, the retracted datasets with the sources their retraction covers: a dataset that includes the
    record itself, or one that includes an input or experiment the record uses (which is said so)."""
    parts = [f"retracted sources: {', '.join(r['sources'])}"] if r["sources"] else []
    for d in r["datasets"]:                       # each dataset with the sources whose evidence it retracts
        srcs = r["dataset_sources"].get(d) or []
        used = [x for x in r["dataset_records"].get(d) or [] if x != rid]
        if rid in (r["dataset_records"].get(d) or []):
            head = f"included in the retracted dataset {d}" + (f" (as is {', '.join(used)}, which it uses)" if used else "")
        else:
            head = f"uses {', '.join(used)}, included in the retracted dataset {d}"
        parts.append(head + (f", which retracts its evidence from {', '.join(srcs)}" if srcs else ""))
    return "; ".join(parts)


def _ancestors(spec: dict, lab: str | None) -> list[str]:
    return list((spec["nodes"].get(lab) or {}).get("ancestors") or []) if lab else []
