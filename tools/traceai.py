"""TRACE-AI read on scale-catal records: which items of the TRACE-AI publication checklist the records of a graph (or of
one of its sources) support, which they do not, and which a person checks in the source (``scale trace-ai``,
``scale_trace_ai``; docs/trace-ai.md).

TRACE-AI (Xin et al., Chem Catal. 2026, doi:10.1016/j.checat.2026.101755) is a reporting checklist for agentic
catalysis: data management (A1-A5), model development (B1-B5), workflow integration (C1-C5) and executable artifacts
(D1-D3). The crosswalk (``domain/reporting/trace-ai.yaml``, :data:`layout.TRACE_AI`) says, for each item, when it
applies and what it needs, as query plans over the document (:mod:`pgraph_query`, so every row comes with its records
and evidence) or a named check of this module (:data:`CHECKS`).

An item is ``supported`` when every need is found (any one, for an item of mode ``any``), ``partial`` when some are,
a ``gap`` when none is, ``not_applicable`` only when its condition finds no record (the condition is the reason),
``by_hand`` when the records cannot show it (what a person reads in the source is given), and ``not_assessed`` when the
document's schema cannot express what a need asks (an older version: its plans report a schema gap, or ask for a value
its vocabulary does not hold). A ``supplementary`` need never makes an item supported: found without the others, it
makes it partial. An item with a ``subject`` (``model``, ``design``, ``data``: a variable its condition and every plan
of its needs bind) is read record by record: it is supported only when each record its condition finds has every need
(any one, for mode ``any``), so that what one model states never stands in for what another leaves out, and the report
says how many are complete and what each other one lacks. A gap is listed as a gap, never as satisfied or not
applicable. The report says what the curated records show: a need not found may be missing from the source (a value
``not_reported`` as ``not_stated_in_source``) or only from the curation.

The report also says how the records were curated: the autonomy level of their curation (stewardship), who curated
them and the checks people made of them (``graph.checks``), with the extraction's precision and recall where the checks
count fields (:func:`recordchecks.quality`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from . import layout
from .results import VALUE_STATUS
from .util import ScaleError, load_yaml

STATUSES = ("supported", "partial", "gap", "not_applicable", "by_hand", "not_assessed")
ITEM_IDS = ("A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3", "B4", "B5", "C1", "C2", "C3", "C4", "C5", "D1", "D2", "D3")
ITEM_KEYS = ("id", "section", "title", "applies", "subject", "mode", "needs", "flags", "context", "by_hand")
NEED_KEYS = ("name", "description", "plans", "check", "message", "supplementary")


def load_crosswalk(repo: Path) -> dict:
    p = Path(repo) / layout.TRACE_AI
    if not p.is_file():
        raise ScaleError(f"no TRACE-AI crosswalk: {p} is missing")
    return load_yaml(p) or {}


def problems(cw: dict) -> list[str]:
    """What is wrong with a crosswalk's shape: every item of the checklist once and nothing else, known keys, known
    conditions and checks, a plan or a check on every need, a status that can be reached."""
    out: list[str] = []
    conds = cw.get("conditions") or {}
    for name, c in conds.items():
        if not isinstance(c, dict) or not (c.get("plans") or c.get("any_of")) or not c.get("description"):
            out.append(f"conditions.{name}: a condition has a description and plans or any_of")
        for x in (c or {}).get("any_of") or []:
            if x not in conds:
                out.append(f"conditions.{name}: any_of names an unknown condition {x!r}")
    items = cw.get("items") or []
    ids = [i.get("id") for i in items if isinstance(i, dict)]
    if sorted(ids) != sorted(ITEM_IDS):
        missing, extra = sorted(set(ITEM_IDS) - set(ids)), sorted(set(ids) - set(ITEM_IDS))
        dup = sorted({x for x in ids if ids.count(x) > 1})
        out.append(f"items: each TRACE-AI item once (missing {missing}, unknown {extra}, twice {dup})")
    for it in items:
        if not isinstance(it, dict):
            out.append("items: an item is a mapping")
            continue
        at = f"items.{it.get('id')}"
        unknown = sorted(set(it) - set(ITEM_KEYS))
        if unknown:
            out.append(f"{at}: unknown key(s) {unknown}")
        if not it.get("title") or not it.get("section"):
            out.append(f"{at}: an item has a section and a title")
        if it.get("applies") and it["applies"] not in conds:
            out.append(f"{at}: applies names an unknown condition {it['applies']!r}")
        if it.get("mode", "all") not in ("all", "any"):
            out.append(f"{at}: mode is all or any")
        if not it.get("needs") and not it.get("by_hand"):
            out.append(f"{at}: an item has needs, or says what a person checks by hand (by_hand)")
        if it.get("needs") and all(isinstance(n, dict) and n.get("supplementary") for n in it["needs"]):
            out.append(f"{at}: every need is supplementary, so the item could never be supported")
        subj = it.get("subject")
        if subj is not None:
            if not it.get("applies") or it["applies"] not in conds:
                out.append(f"{at}: an item read record by record (subject) names the condition that finds them")
            elif not _binds(conds, it["applies"], subj):
                out.append(f"{at}: every plan of condition {it['applies']!r} binds {subj!r}, the item's subject")
            for n in it.get("needs") or []:
                if isinstance(n, dict) and n.get("check"):
                    out.append(f"{at}.needs.{n.get('name')}: a check cannot be read record by record (subject)")
                elif isinstance(n, dict) and not all(subj in _bound_vars(p) for p in n.get("plans") or []):
                    out.append(f"{at}.needs.{n.get('name')}: every plan binds {subj!r}, the item's subject")
        for block in ("needs", "flags", "context"):
            for n in it.get(block) or []:
                if not isinstance(n, dict) or not n.get("name"):
                    out.append(f"{at}.{block}: each entry has a name")
                    continue
                if sorted(set(n) - set(NEED_KEYS)):
                    out.append(f"{at}.{block}.{n['name']}: unknown key(s) {sorted(set(n) - set(NEED_KEYS))}")
                if block == "needs" and bool(n.get("plans")) == bool(n.get("check")):
                    out.append(f"{at}.needs.{n['name']}: give plans or a check, one of the two")
                if block != "needs" and (not n.get("plans") or n.get("check")):
                    out.append(f"{at}.{block}.{n['name']}: a {block[:-1]} gives plans (a check flags through its need)")
                if n.get("check") and n["check"] not in CHECKS:
                    out.append(f"{at}.{block}.{n['name']}: unknown check {n['check']!r} (known: {sorted(CHECKS)})")
                if block == "flags" and not n.get("message"):
                    out.append(f"{at}.flags.{n['name']}: a flag says what to look at (message)")
    return out


def _bound_vars(plan: Any) -> set:
    """The variables a plan binds (its match and its steps)."""
    if not isinstance(plan, dict):
        return set()
    m = plan.get("match") or {}
    return {m.get("as", "self")} | {st.get("as") for st in plan.get("steps") or [] if isinstance(st, dict)}


def _binds(conds: dict, name: str, var: str, seen: tuple = ()) -> bool:
    c = conds.get(name) or {}
    if c.get("any_of"):
        return all(_binds(conds, x, var, seen + (name,)) for x in c["any_of"] if x not in seen)
    return bool(c.get("plans")) and all(var in _bound_vars(p) for p in c["plans"])


def _of_source(rec: dict, source: str) -> dict:
    """A record as one source states it: only the evidence of that source, and none of the values whose evidence_ids
    all name evidence of other sources (a value that names none, or names evidence of this source, stays); a map or a
    list left empty by that goes too, so that a property only other sources state is absent, not an empty one."""
    props = rec.get("props")
    ev = props.get("evidence") if isinstance(props, dict) else None
    if not isinstance(ev, list):
        return rec

    def other(x: Any) -> bool:
        return isinstance(x, dict) and x.get("source") not in (None, source)
    if not any(other(x) for x in ev):
        return rec
    others = {x.get("id") for x in ev if other(x) and isinstance(x.get("id"), str)}
    drop = object()

    def walk(x: Any) -> Any:
        if isinstance(x, dict):
            if x.get("status") in VALUE_STATUS:            # a value object
                ids = [i for i in x.get("evidence_ids") or [] if isinstance(i, str)]
                return drop if ids and all(i in others for i in ids) else x
            kept = {k: walk(v) for k, v in x.items()}
            kept = {k: v for k, v in kept.items() if v is not drop}
            return drop if x and not kept else kept
        if isinstance(x, list):
            kept_items = [w for w in (walk(v) for v in x) if w is not drop]
            return drop if x and not kept_items else kept_items
        return x
    new = {k: (v if k == "stewardship" else walk(v)) for k, v in props.items() if k != "evidence"}
    new = {k: v for k, v in new.items() if v is not drop}
    mine = [x for x in ev if not other(x)]
    return {**rec, "props": {**new, "evidence": mine} if mine else new}


def restrict(doc: dict, source: str) -> dict:
    """The records of one source, as it states them: the source, the nodes REPORTED_IN it, the nodes REPORTED_IN no
    source (curator records, shared people and organisations; other sources are left out), and the links between them
    whose evidence cites the source or that carry none. Each keeps only that source's evidence, and loses the values
    only other sources state (:func:`_of_source`); the graph's checks keep only the records the view holds, and their
    counts only when they keep all of them, each whole (:func:`recordchecks.prune`)."""
    from .recordchecks import checks_of, cut_records, prune
    nodes = {n["id"]: n for n in doc.get("nodes") or [] if isinstance(n, dict)}
    if nodes.get(source, {}).get("label") != "Source":
        raise ScaleError(f"{source} is not a Source of this graph")
    cited: dict[str, set] = {}
    for e in doc.get("links") or []:
        if e.get("type") == "REPORTED_IN":
            cited.setdefault(e["source"], set()).add(e["target"])
    keep = {i for i, n in nodes.items() if n.get("label") != "Source" and (source in cited.get(i, {source}))} | {source}

    def own(e: dict) -> bool:
        ev = [x for x in (e.get("props") or {}).get("evidence") or [] if isinstance(x, dict)]
        return not ev or any(x.get("source") == source for x in ev)
    links = [_of_source(e, source) for e in doc.get("links") or []
             if e.get("source") in keep and e.get("target") in keep and own(e)]
    kept = [_of_source(n, source) for i, n in nodes.items() if i in keep]
    out = {**doc, "nodes": kept, "links": links}
    if checks_of(doc.get("graph")):
        held = {r["id"] for r in kept + links if isinstance(r.get("id"), str)}
        every = {r.get("id") for r in [*nodes.values(), *(doc.get("links") or [])] if isinstance(r, dict)}
        before = {r["id"]: r.get("props") or {} for r in [*nodes.values(), *(doc.get("links") or [])]
                  if isinstance(r, dict) and isinstance(r.get("id"), str)}
        out["graph"], _ = prune(dict(doc["graph"]), held, {x for x in every if isinstance(x, str)} - held,
                                cut_records(before, kept + links))
    return out


# ---------------------------------------------------------------- named checks

def _value_objects(v: Any, path: str) -> list[tuple[str, dict]]:
    """The value objects at a place of a record: the value itself, or those a map or a list there holds."""
    from .results import VALUE_STATUS, values_in
    if isinstance(v, dict) and v.get("status") in VALUE_STATUS:
        return [(path, v)]
    return [(path + p, x) for p, x in values_in(v)]


def _results_of(rec: dict) -> list[tuple[str, dict]]:
    """A record's results: its result_values and the entries of its results map."""
    rp = rec.get("props") or {}
    out = [(f"/result_values/{v.get('id')}", v) for v in rp.get("result_values") or [] if isinstance(v, dict)]
    res = rp.get("results")
    return out + ([(f"/results/{k}", v) for k, v in res.items() if isinstance(v, dict)] if isinstance(res, dict) else [])


def _metrics(doc: dict) -> tuple[list[dict], list[str]]:
    """Each metric a validation or benchmark of a model states, and the references that name none. The metrics are the
    values its EVALUATES names (result_refs: a value, or every result of a record named without a path), else the
    evaluating experiment's results (result_values and the results map). A reference whose record is not in the
    document, whose path does not resolve (:func:`results.resolve`) or that names no value cannot be assessed."""
    from .results import resolve
    recs = {r.get("id"): r for r in [*(doc.get("nodes") or []), *(doc.get("links") or [])] if isinstance(r, dict)}
    out, unread = [], []
    for e in doc.get("links") or []:
        p = e.get("props") or {}
        if e.get("type") != "EVALUATES" or p.get("evaluation_kind") not in ("validation", "benchmark"):
            continue
        if (recs.get(e.get("target")) or {}).get("label") != "Model":
            continue
        refs = [r for r in p.get("result_refs") or [] if isinstance(r, dict)]
        vals: list[tuple[Any, str, dict]] = []
        for r in refs:
            rid, path = r.get("record"), r.get("path")
            rec = recs.get(rid)
            if rec is None:
                unread.append(f"{rid}{path or ''}")
                continue
            if path:
                ok, v = resolve(rec.get("props") or {}, path)
                got = _value_objects(v, path) if ok else []
            else:
                got = _results_of(rec)
            if not got:
                unread.append(f"{rid}{path or ''}")
            vals += [(rid, pth, v) for pth, v in got]
        if not refs:
            run = recs.get(e.get("source")) or {}
            vals = [(run.get("id"), pth, v) for pth, v in _results_of(run)]
        for rid, path, v in vals:
            if isinstance(v, dict) and v.get("status") == "present":
                out.append({"record": rid, "path": path, "evaluates": e.get("id"), "model": e.get("target"),
                            "with_uncertainty": any(k in v for k in ("uncertainty", "interval_lower"))})
    return out, unread


def _check_metric_uncertainty(doc: dict) -> dict:
    """B3: found when every metric of a model's validations and benchmarks states its uncertainty or interval, and every
    reference to one can be read; the metrics stated without one are flagged (a single number is what best-only
    reporting looks like), and a reference that names no metric keeps the need from being found."""
    ms, unread = _metrics(doc)
    bare = [m for m in ms if not m["with_uncertainty"]]
    found = bool(ms) and not bare and not unread
    note = None
    if unread:
        note = f"a reference that names no metric: {', '.join(unread[:5])}{', …' if len(unread) > 5 else ''}"
    elif not ms:
        note = "no metric of a validation or benchmark of the model is recorded"
    return {"found": found, "partial": not found and any(m["with_uncertainty"] for m in ms),
            "records": sorted({m["record"] for m in ms if m["with_uncertainty"]}),
            "flag": ({"name": "metric_without_uncertainty",
                      "message": "a metric stated as a single number, without its uncertainty or interval",
                      "records": [f"{m['record']}{m['path']}" for m in bare]} if bare else None),
            "note": note}


CHECKS: dict[str, Callable[[dict], dict]] = {"metric_uncertainty": _check_metric_uncertainty}


# ---------------------------------------------------------------- the report

class _Runner:
    """Runs plans on one document and schema, once each, keeping what every item needs from each row."""

    def __init__(self, doc: dict, spec: dict):
        from . import pgraph_query
        self.q = pgraph_query
        self.doc, self.spec = doc, spec
        self.g = pgraph_query.Graph(doc, spec)
        self.cache: dict[str, dict] = {}

    def plan(self, plan: dict) -> dict:
        """A plan's status, schema gaps and rows. A plan that asks for a value the schema's vocabulary does not hold
        is a schema gap, as one that names a property it does not declare (the document cannot state it)."""
        import json
        key = json.dumps(plan, sort_keys=True)
        if key not in self.cache:
            gaps = self.q.schema_gaps(plan, self.spec, values=True)
            if gaps:
                self.cache[key] = {"status": "schema_gap", "schema_gaps": gaps, "rows": []}
                return self.cache[key]
            res = self.q.run(self.doc, self.spec, {**plan, "evidence": True, "limit": None}, None, self.g)   # every row
            self.cache[key] = {
                "status": res.get("status"),
                "schema_gaps": res.get("schema_gaps") or [],
                "rows": [{"bound": {k: x for k, x in (r.get("bound") or {}).items() if isinstance(x, str)},
                          "links": [x for x in r.get("links") or [] if isinstance(x, str)],
                          "values": r.get("values") or {},
                          "evidence": {(ev.get("source"), ev.get("locator")) for ev in r.get("evidence") or []
                                       if isinstance(ev, dict) and ev.get("source")}}
                         for r in res.get("rows") or []]}
        return self.cache[key]

    def plans(self, plans: list[dict], subject: str | None = None, only: set | None = None) -> dict:
        """Several plans, any of which finds the need: found, the records and rows of those that found, the records
        bound to ``subject`` (kept to ``only`` when given), and whether every plan hit a schema gap (the document's
        schema cannot express the need)."""
        res = [self.plan(p) for p in plans]
        rows = [row for r in res for row in r["rows"]
                if subject is None or (row["bound"].get(subject) is not None
                                       and (only is None or row["bound"][subject] in only))]
        return {"found": bool(rows), "records": sorted({x for row in rows for x in row["bound"].values()}),
                "links": sorted({x for row in rows for x in row["links"]}),
                "rows": [row["values"] for row in rows][:20],
                "evidence": [{"source": src, "locator": loc}
                             for src, loc in sorted({e for row in rows for e in row["evidence"]}, key=str)][:20],
                "subjects": sorted({row["bound"][subject] for row in rows}) if subject else [],
                "schema_gap": bool(res) and all(r["status"] == "schema_gap" for r in res),
                "schema_gaps": sorted({str(g) for r in res for g in r["schema_gaps"]})}


def _condition(run: _Runner, conds: dict, name: str | None, subject: str | None = None, seen: tuple = ()) -> dict:
    if not name:
        return {"applies": True}
    c = conds[name]
    if c.get("any_of"):
        subs = [_condition(run, conds, x, subject, seen + (name,)) for x in c["any_of"] if x not in seen]
        return {"applies": any(x["applies"] for x in subs), "description": c["description"],
                "records": sorted({r for x in subs for r in x.get("records", [])}),
                "subjects": sorted({r for x in subs for r in x.get("subjects", [])}),
                "schema_gap": bool(subs) and all(x.get("schema_gap") for x in subs)}
    r = run.plans(c["plans"], subject)
    return {"applies": r["found"], "description": c["description"], "records": r["records"],
            "subjects": r["subjects"], "schema_gap": r["schema_gap"]}


def _need(run: _Runner, n: dict, subject: str | None = None, only: set | None = None) -> dict:
    out = {"name": n["name"], "description": n.get("description")}
    if n.get("supplementary"):
        out["supplementary"] = True
    if n.get("check"):
        r = CHECKS[n["check"]](run.doc)
        out.update(found=r["found"], partial=r.get("partial", False), records=r["records"])
        if r.get("flag"):
            out["flag"] = r["flag"]
        if r.get("note"):
            out["note"] = r["note"]
        return out
    r = run.plans(n["plans"], subject, only)
    out.update(found=r["found"], records=r["records"], links=r["links"], rows=r["rows"], evidence=r["evidence"])
    if subject:
        out["subjects"] = r["subjects"]
    if r["schema_gap"]:
        out["schema_gap"] = r["schema_gaps"]
    return out


def _status(it: dict, needs: list[dict], subject: str | None, only: set | None) -> tuple[str, dict | None]:
    """An item's status from its needs, and, read record by record, how many of its records are complete and what
    each other one lacks."""
    required = [n for n in needs if not n.get("supplementary")]
    anyof = it.get("mode") == "any"
    if all(n.get("schema_gap") for n in required) and not any(n["found"] for n in needs):
        return "not_assessed", None
    coverage = None
    if subject:
        lacks = {x: [n["name"] for n in required if x not in n.get("subjects", [])] for x in sorted(only or ())}
        done = [x for x, miss in lacks.items() if (len(miss) < len(required) if anyof else not miss)]
        coverage = {"subject": subject, "records": len(lacks), "complete": len(done),
                    "incomplete": [{"record": x, "lacks": miss} for x, miss in lacks.items() if x not in done]}
        if lacks and len(done) == len(lacks):
            return "supported", coverage
    else:
        found = [n for n in required if n["found"]]
        if (anyof and found) or (not anyof and len(found) == len(required)):
            return "supported", None
    if any(n["found"] or n.get("partial") for n in needs):
        return "partial", coverage
    return "gap", coverage


def assess(doc: dict, spec: dict, cw: dict, source: str | None = None) -> dict:
    """The TRACE-AI report of a document (or of one of its sources' records)."""
    from .recordchecks import checks_of, quality, records_of
    bad = problems(cw)
    if bad:
        raise ScaleError("the TRACE-AI crosswalk is malformed:\n  " + "\n  ".join(bad))
    view = restrict(doc, source) if source else doc
    run = _Runner(view, spec)
    conds = cw.get("conditions") or {}
    items = []
    for it in cw["items"]:
        row: dict = {"id": it["id"], "section": it["section"], "title": it["title"]}
        subject = it.get("subject")
        cond = _condition(run, conds, it.get("applies"), subject)
        if it.get("applies"):
            row["applies_to"] = cond["description"]
        if not cond["applies"]:
            row["status"] = "not_assessed" if cond.get("schema_gap") else "not_applicable"
            row["reason"] = (f"the document's schema cannot express the condition, {cond['description']}"
                             if cond.get("schema_gap") else f"no record of {cond['description']}")
            items.append(row)
            continue
        only = set(cond.get("subjects") or []) if subject else None
        needs = [_need(run, n, subject, only) for n in it.get("needs") or []]
        flags = []
        for f in it.get("flags") or []:
            r = run.plans(f["plans"])
            if r["found"]:
                flags.append({"name": f["name"], "message": " ".join(str(f["message"]).split()), "records": r["records"]})
        flags += [n.pop("flag") for n in needs if n.get("flag")]
        context = [{"name": c["name"], "description": c.get("description"), **{k: v for k, v in run.plans(c["plans"]).items()
                                                                          if k in ("records", "rows")}}
                   for c in it.get("context") or []]
        status, coverage = _status(it, needs, subject, only) if needs else ("by_hand", None)
        row.update(status=status, needs=needs)
        if coverage:
            row["coverage"] = coverage
        if flags:
            row["flags"] = flags
        if context and any(c["records"] or c["rows"] for c in context):
            row["context"] = context
        if it.get("by_hand"):
            row["by_hand"] = " ".join(str(it["by_hand"]).split())
        items.append(row)
    g = view.get("graph") or {}
    st = g.get("stewardship") if isinstance(g.get("stewardship"), dict) else {}
    checks = checks_of(g)
    evidenced = {n["id"] for n in view.get("nodes") or [] if (n.get("props") or {}).get("evidence")}
    covered = {r for c in checks for r in records_of(c)}
    curation = {"autonomy_level": st.get("autonomy_level"), "curated_by": st.get("curated_by") or [],
                "checks": [{"checked_by": c.get("checked_by"), "checked_on": c.get("checked_on"),
                            "records": len(records_of(c)), "selection": c.get("selection"),
                            "outcome": c.get("outcome"), **quality(c)} for c in checks],
                "evidenced_records": len(evidenced), "evidenced_records_checked": len(evidenced & covered)}
    counts = {s: sum(1 for i in items if i["status"] == s) for s in STATUSES}
    return {"guideline": cw.get("guideline"), "checklist_version": cw.get("checklist_version"),
            "reference": cw.get("reference"), "url": cw.get("url"), "graph_id": (doc.get("graph") or {}).get("graph_id"),
            "schema_version": (doc.get("graph") or {}).get("schema_version"), **({"source": source} if source else {}),
            "summary": counts, "items": items, "curation": curation,
            "limitations": ["The report says what the curated records show. A need not found may be absent from the "
                            "source or only from the curation; an item checked by hand is read in the source.",
                            "It decides nothing about whether a source satisfies TRACE-AI; its authors fill the "
                            "checklist."]}


def render_markdown(rep: dict) -> str:
    """The report as a person reads it: one line per item, then what each item found, flagged or leaves to a person."""
    mark = {"supported": "supported", "partial": "partly supported", "gap": "gap", "not_applicable": "not applicable",
            "by_hand": "check by hand", "not_assessed": "not assessed"}
    out = [f"# {rep['guideline']} {rep['checklist_version']} on {rep.get('graph_id')}"
           + (f", source {rep['source']}" if rep.get("source") else ""), "",
           f"{rep['reference']}; checklist at {rep['url']}.", "",
           "| item | status | what |", "| --- | --- | --- |"]
    for i in rep["items"]:
        out.append(f"| {i['id']} | {mark[i['status']]} | {i['title']} |")
    out.append("")
    for i in rep["items"]:
        lines = []
        if i.get("reason"):
            lines.append(f"- {i['reason']}")
        for n in i.get("needs") or []:
            got = "found" if n["found"] else ("partly" if n.get("partial") else "not found")
            if not n["found"] and n.get("schema_gap"):
                got = f"not expressible in scale-catal {rep.get('schema_version')} (migrate the document)"
            recs = f" ({', '.join(n['records'][:5])}{', …' if len(n['records']) > 5 else ''})" if n.get("records") else ""
            extra = " (supplementary: alone it makes the item partial)" if n.get("supplementary") else ""
            lines.append(f"- {n['name']}{extra}: {got}{recs}" + (f" — {n['note']}" if n.get("note") else ""))
        cov = i.get("coverage")
        if cov:
            lines.append(f"- record by record ({cov['subject']}): {cov['complete']} of {cov['records']} complete")
            for x in cov["incomplete"][:5]:
                lines.append(f"  - {x['record']} lacks {', '.join(x['lacks'])}")
            if len(cov["incomplete"]) > 5:
                lines.append(f"  - … and {len(cov['incomplete']) - 5} more")
        for f in i.get("flags") or []:
            lines.append(f"- look at: {f['message']} ({', '.join(f['records'][:5])})")
        for c in i.get("context") or []:
            lines.append(f"- to read: {c['description']} ({', '.join(c['records'][:5])})")
        if i.get("by_hand"):
            lines.append(f"- by hand: {i['by_hand']}")
        if lines:
            out += [f"**{i['id']}** ({mark[i['status']]})", *lines, ""]
    cur = rep["curation"]
    out += ["## How the records were curated", "",
            f"- autonomy level of the curation: {cur['autonomy_level'] or 'not stated'}",
            f"- curated by: {', '.join(cur['curated_by']) or 'not stated'}",
            f"- evidenced records checked by a person: {cur['evidenced_records_checked']} of {cur['evidenced_records']}"]
    for c in cur["checks"]:
        q = ", ".join(f"{k} {c[k]}" for k in ("precision", "recall") if c.get(k) is not None)
        how = c.get("selection") or "selection not stated"
        out.append(f"- {c['checked_on']}, {c['checked_by']}: {c['records']} records ({how}), {c['outcome']}"
                   + (f"; {q}" if q else ""))
    out += ["", *[f"_{x}_" for x in rep["limitations"]]]
    return "\n".join(out) + "\n"


__all__ = ["STATUSES", "ITEM_IDS", "CHECKS", "load_crosswalk", "problems", "restrict", "assess", "render_markdown"]
