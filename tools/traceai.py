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
document's schema cannot express what a need asks (an older version: its plans report a schema gap). A gap is listed
as a gap, never as satisfied or not applicable. The report says what the curated records show: a need not found may be
missing from the source (a value ``not_reported`` as ``not_stated_in_source``) or only from the curation.

The report also says how the records were curated: the autonomy level of their curation (stewardship), who curated
them and the checks people made of them (``graph.checks``), with the extraction's precision and recall where the checks
count fields (:func:`recordchecks.quality`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from . import layout
from .util import ScaleError, load_yaml

STATUSES = ("supported", "partial", "gap", "not_applicable", "by_hand", "not_assessed")
ITEM_IDS = ("A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3", "B4", "B5", "C1", "C2", "C3", "C4", "C5", "D1", "D2", "D3")
ITEM_KEYS = ("id", "section", "title", "applies", "mode", "needs", "flags", "context", "by_hand")
NEED_KEYS = ("name", "description", "plans", "check", "message")


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


def restrict(doc: dict, source: str) -> dict:
    """The records of one source: the source, the nodes REPORTED_IN it, the nodes REPORTED_IN no source (curator records,
    shared people and organisations; other sources are left out), and the links between them whose evidence cites the
    source or that carry none."""
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
    links = [e for e in doc.get("links") or [] if e.get("source") in keep and e.get("target") in keep and own(e)]
    return {**doc, "nodes": [n for i, n in nodes.items() if i in keep], "links": links}


# ---------------------------------------------------------------- named checks

def _value_at(rec: dict, path: str) -> Any:
    """The value a record_ref path names (``/result_values/<id>``, ``/results/<key>``, ``/<property>``)."""
    parts = [p for p in path.split("/") if p]
    v: Any = rec.get("props") or {}
    for p in parts:
        if isinstance(v, list):
            v = next((x for x in v if isinstance(x, dict) and x.get("id") == p), None)
        elif isinstance(v, dict):
            v = v.get(p)
        else:
            return None
    return v


def _metrics(doc: dict) -> list[dict]:
    """Each metric a validation or benchmark of a model states: the values its EVALUATES names (result_refs), else
    the evaluating experiment's results (result_values and the results map)."""
    recs = {r.get("id"): r for r in [*(doc.get("nodes") or []), *(doc.get("links") or [])] if isinstance(r, dict)}
    out = []
    for e in doc.get("links") or []:
        p = e.get("props") or {}
        if e.get("type") != "EVALUATES" or p.get("evaluation_kind") not in ("validation", "benchmark"):
            continue
        if (recs.get(e.get("target")) or {}).get("label") != "Model":
            continue
        refs = [r for r in p.get("result_refs") or [] if isinstance(r, dict)]
        if refs:
            vals = [(r.get("record"), r.get("path", ""), _value_at(recs.get(r.get("record")) or {}, r.get("path", "")))
                    for r in refs]
        else:
            run = recs.get(e.get("source")) or {}
            rp = run.get("props") or {}
            vals = [(run.get("id"), f"/result_values/{v.get('id')}", v) for v in rp.get("result_values") or []
                    if isinstance(v, dict)]
            vals += [(run.get("id"), f"/results/{k}", v) for k, v in (rp.get("results") or {}).items()]
        for rid, path, v in vals:
            if isinstance(v, dict) and v.get("status") == "present":
                out.append({"record": rid, "path": path, "evaluates": e.get("id"), "model": e.get("target"),
                            "with_uncertainty": any(k in v for k in ("uncertainty", "interval_lower"))})
    return out


def _check_metric_uncertainty(doc: dict) -> dict:
    """B3: found when every metric of a model's validations and benchmarks states its uncertainty or interval; the
    metrics stated without one are flagged (a single number is what best-only reporting looks like)."""
    ms = _metrics(doc)
    bare = [m for m in ms if not m["with_uncertainty"]]
    return {"found": bool(ms) and not bare, "partial": bool(ms) and bool(bare) and len(bare) < len(ms),
            "records": sorted({m["record"] for m in ms if m["with_uncertainty"]}),
            "flag": ({"name": "metric_without_uncertainty",
                      "message": "a metric stated as a single number, without its uncertainty or interval",
                      "records": [f"{m['record']}{m['path']}" for m in bare]} if bare else None),
            "note": None if ms else "no metric of a validation or benchmark of the model is recorded"}


CHECKS: dict[str, Callable[[dict], dict]] = {"metric_uncertainty": _check_metric_uncertainty}


# ---------------------------------------------------------------- the report

class _Runner:
    """Runs plans on one document and schema, once each, keeping what every item needs from a result."""

    def __init__(self, doc: dict, spec: dict):
        from . import pgraph_query
        self.q = pgraph_query
        self.doc, self.spec = doc, spec
        self.g = pgraph_query.Graph(doc, spec)
        self.cache: dict[str, dict] = {}

    def plan(self, plan: dict) -> dict:
        import json
        key = json.dumps(plan, sort_keys=True)
        if key not in self.cache:
            res = self.q.run(self.doc, self.spec, {**plan, "evidence": True}, None, self.g)
            rows = res.get("rows") or []
            self.cache[key] = {
                "status": res.get("status"),
                "schema_gaps": res.get("schema_gaps") or [],
                "records": sorted({x for r in rows for x in (r.get("bound") or {}).values() if isinstance(x, str)}),
                "links": sorted({x for r in rows for x in r.get("links") or [] if isinstance(x, str)}),
                "rows": [r.get("values") or {} for r in rows],
                "evidence": sorted({(ev.get("source"), ev.get("locator")) for r in rows for ev in r.get("evidence") or []
                                    if isinstance(ev, dict) and ev.get("source")}, key=str)}
        return self.cache[key]

    def plans(self, plans: list[dict]) -> dict:
        """Several plans, any of which finds the need: found, the records and rows of those that found, and whether
        every plan hit a schema gap (the document's schema cannot express the need)."""
        res = [self.plan(p) for p in plans]
        hit = [r for r in res if r["records"] or r["rows"]]
        return {"found": bool(hit), "records": sorted({x for r in hit for x in r["records"]}),
                "links": sorted({x for r in hit for x in r["links"]}),
                "rows": [row for r in hit for row in r["rows"]][:20],
                "evidence": [{"source": s, "locator": loc} for s, loc in sorted({e for r in hit for e in r["evidence"]},
                                                                                 key=str)][:20],
                "schema_gap": bool(res) and all(r["status"] == "schema_gap" for r in res),
                "schema_gaps": sorted({str(g) for r in res for g in r["schema_gaps"]})}


def _condition(run: _Runner, conds: dict, name: str | None, seen: tuple = ()) -> dict:
    if not name:
        return {"applies": True}
    c = conds[name]
    if c.get("any_of"):
        subs = [_condition(run, conds, x, seen + (name,)) for x in c["any_of"] if x not in seen]
        return {"applies": any(s["applies"] for s in subs), "description": c["description"],
                "records": sorted({x for s in subs for x in s.get("records", [])})}
    r = run.plans(c["plans"])
    return {"applies": r["found"], "description": c["description"], "records": r["records"],
            "schema_gap": r["schema_gap"]}


def _need(run: _Runner, n: dict) -> dict:
    out = {"name": n["name"], "description": n.get("description")}
    if n.get("check"):
        r = CHECKS[n["check"]](run.doc)
        out.update(found=r["found"], partial=r.get("partial", False), records=r["records"])
        if r.get("flag"):
            out["flag"] = r["flag"]
        if r.get("note"):
            out["note"] = r["note"]
        return out
    r = run.plans(n["plans"])
    out.update(found=r["found"], records=r["records"], links=r["links"], rows=r["rows"], evidence=r["evidence"])
    if r["schema_gap"]:
        out["schema_gap"] = r["schema_gaps"]
    return out


def assess(doc: dict, spec: dict, cw: dict, source: str | None = None) -> dict:
    """The TRACE-AI report of a document (or of one of its sources' records)."""
    from .recordchecks import checks_of, quality
    bad = problems(cw)
    if bad:
        raise ScaleError("the TRACE-AI crosswalk is malformed:\n  " + "\n  ".join(bad))
    view = restrict(doc, source) if source else doc
    run = _Runner(view, spec)
    conds = cw.get("conditions") or {}
    items = []
    for it in cw["items"]:
        row: dict = {"id": it["id"], "section": it["section"], "title": it["title"]}
        cond = _condition(run, conds, it.get("applies"))
        if it.get("applies"):
            row["applies_to"] = cond["description"]
        if not cond["applies"]:
            row["status"] = "not_assessed" if cond.get("schema_gap") else "not_applicable"
            row["reason"] = (f"the document's schema cannot express the condition, {cond['description']}"
                             if cond.get("schema_gap") else f"no record of {cond['description']}")
            items.append(row)
            continue
        needs = [_need(run, n) for n in it.get("needs") or []]
        flags = []
        for f in it.get("flags") or []:
            r = run.plans(f["plans"])
            if r["found"]:
                flags.append({"name": f["name"], "message": " ".join(str(f["message"]).split()), "records": r["records"]})
        flags += [n.pop("flag") for n in needs if n.get("flag")]
        context = [{"name": c["name"], "description": c.get("description"), **{k: v for k, v in run.plans(c["plans"]).items()
                                                                          if k in ("records", "rows")}}
                   for c in it.get("context") or []]
        if needs:
            found = [n for n in needs if n["found"]]
            if all(n.get("schema_gap") for n in needs):
                status = "not_assessed"
            elif (it.get("mode") == "any" and found) or len(found) == len(needs):
                status = "supported"
            elif found or any(n.get("partial") for n in needs):
                status = "partial"
            else:
                status = "gap"
        else:
            status = "by_hand"
        row.update(status=status, needs=needs)
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
    covered = {r for c in checks for r in c.get("records") or []}
    curation = {"autonomy_level": st.get("autonomy_level"), "curated_by": st.get("curated_by") or [],
                "checks": [{"checked_by": c.get("checked_by"), "checked_on": c.get("checked_on"),
                            "records": len(c.get("records") or []), "selection": c.get("selection"),
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
            lines.append(f"- {n['name']}: {got}{recs}" + (f" — {n['note']}" if n.get("note") else ""))
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
