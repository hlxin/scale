"""A preparation read as a recipe: its stages and steps in order, each with its conditions and its inputs, and a summary
read from the steps (the highest temperature, the time, the inputs by the function they serve, the gases, the pH),
never recorded.

The steps of a preparation are ProcedureSteps PART_OF it, in order; a stage is a Preparation PART_OF it with steps of
its own; a step's sub-steps are PART_OF the step. The summary keeps every value as reported: temperatures and times
are grouped by their unit, never converted, and a step that does not state its time is listed, so a total is never
more than the sum of what was stated. What the preparation states for the whole (its own temperature, duration,
pressure, atmosphere) is shown apart, as stated for the whole. What the checklist asks of a step and does not find
(a ramp, a time, a pH) is listed with the step.
"""

from __future__ import annotations

from typing import Any

from .pgraph_query import unit_key

STEP_CONDITIONS = ("temperature", "pressure", "duration", "ramp_rate", "atmosphere", "gas_flow_mode", "ph", "agitation",
                   "stirring_rate", "fill_fraction", "cooling_mode", "energy_input", "repetitions", "method",
                   "conditions")
WHOLE_CONDITIONS = ("temperature", "pressure", "duration", "atmosphere")
INPUT_QUANTITIES = ("role", "synthesis_function", "amount", "concentration", "stock_concentration", "fraction", "ratio",
                    "flow_rate")
FLOWING = ("flowing", "static", "vacuum", "sealed")


def _number(v: Any) -> float | None:
    """The number a value object states (the upper end of a range), or None when it states none."""
    if not isinstance(v, dict) or v.get("status") != "present":
        return None
    for k in ("value", "upper"):
        x = v.get(k)
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return float(x)
    return None


class _Graph:
    def __init__(self, doc: dict):
        self.nodes = {n["id"]: n for n in doc.get("nodes", [])}
        self.links = doc.get("links", doc.get("edges", []))
        self.into: dict[str, list[dict]] = {}
        self.out: dict[str, list[dict]] = {}
        for e in self.links:
            self.into.setdefault(e.get("target"), []).append(e)
            self.out.setdefault(e.get("source"), []).append(e)

    def label(self, nid: str) -> str | None:
        return (self.nodes.get(nid) or {}).get("label")

    def props(self, nid: str) -> dict:
        return (self.nodes.get(nid) or {}).get("props") or {}

    def parts(self, nid: str) -> list[str]:
        """What is PART_OF the record, in order (unordered parts last, by id)."""
        es = [e for e in self.into.get(nid, []) if e.get("type") == "PART_OF"
              and self.label(e["source"]) in ("Preparation", "ProcedureStep")]
        def key(e):
            o = (e.get("props") or {}).get("order")
            return (o is None, o if isinstance(o, (int, float)) else 0, e["source"])
        return [e["source"] for e in sorted(es, key=key)]

    def name(self, nid: str) -> str:
        return self.props(nid).get("name") or nid


def _missing(doc: dict, spec: dict) -> dict[str, dict]:
    """{record id: {"missing": {...}, "evidence_missing": [...]}} from the document's checklists."""
    from .pgraph_profiles import conformance
    out: dict[str, dict] = {}
    for prof in (conformance(doc, spec, by_record=True).get("profiles") or {}).values():
        for rid, r in (prof.get("records") or {}).items():
            m = out.setdefault(rid, {"missing": {}, "evidence_missing": []})
            m["missing"].update(r.get("missing") or {})
            m["evidence_missing"] += [k for k, f in (r.get("evidence") or {}).items() if not f.get("found")]
    return out


def _inputs(g: _Graph, sid: str) -> list[dict]:
    out = []
    for e in g.out.get(sid, []):
        if e.get("type") != "HAS_INPUT":
            continue
        p = e.get("props") or {}
        out.append({"id": e["target"], "name": g.name(e["target"]), "label": g.label(e["target"]),
                    **{k: p[k] for k in INPUT_QUANTITIES if k in p}})
    return out


def _step(g: _Graph, sid: str, position: str, stage: str, repeat: int, missing: dict) -> dict:
    p = g.props(sid)
    rep = p.get("repetitions") if isinstance(p.get("repetitions"), int) else 1
    st = {"id": sid, "position": position, "stage": stage, "name": p.get("name"), "action": p.get("action"),
          **{k: p[k] for k in STEP_CONDITIONS if k in p},
          "inputs": _inputs(g, sid),
          "outputs": [e["target"] for e in g.out.get(sid, []) if e.get("type") == "HAS_OUTPUT"],
          "carried_out": repeat * rep}
    m = missing.get(sid) or {}
    if m.get("missing"):
        st["checklist_missing"] = sorted(m["missing"])
    if p.get("evidence"):
        st["evidence"] = p["evidence"]
    return st


def _walk(g: _Graph, pid: str, prefix: str, missing: dict, steps: list, stages: list, repeat: int = 1,
          stage: str | None = None) -> None:
    """The steps under a preparation or a step, depth first and in order; a stage is listed and walked."""
    for i, part in enumerate(g.parts(pid), 1):
        pos = f"{prefix}{i}"
        if g.label(part) == "Preparation":
            stages.append({"id": part, "position": pos, "name": g.name(part),
                           "preparation_methods": g.props(part).get("preparation_methods") or []})
            _walk(g, part, pos + ".", missing, steps, stages, repeat, part)
        else:
            st = _step(g, part, pos, stage or pid, repeat, missing)
            steps.append(st)
            if g.parts(part):
                _walk(g, part, pos + ".", missing, steps, stages, st["carried_out"], stage or pid)


def _summary(steps: list[dict]) -> dict:
    hottest: dict[str, dict] = {}
    time: dict[str, float] = {}
    untimed = []
    functions: dict[str, list] = {}
    gases = []
    ph = []
    under = {s["id"]: [t for t in steps if t["position"].startswith(s["position"] + ".")] for s in steps}
    timed = {s["id"] for s in steps if _number(s.get("duration")) is not None}
    # a step's time counts once: a step's own when none of its sub-steps states one, else its sub-steps'
    counted = {s["id"] for s in steps if s["id"] in timed and not any(t["id"] in timed for t in under[s["id"]])
               and not any(s in under[a["id"]] and a["id"] in timed and not any(t["id"] in timed for t in under[a["id"]])
                           for a in steps)}
    covered = {t["id"] for sid in counted for t in under[sid]}
    for s in steps:
        t = s.get("temperature")
        x = _number(t)
        if x is not None:
            u = unit_key(t.get("unit") or "")
            if u not in hottest or x > hottest[u]["value"]:
                hottest[u] = {"value": x, "unit": t.get("unit"), "step": s["id"]}
        d = s.get("duration")
        if s["id"] in counted:
            u = d.get("unit") or ""
            time[u] = time.get(u, 0.0) + _number(d) * s["carried_out"]
        elif not under[s["id"]] and s["id"] not in covered and s["id"] not in timed:
            untimed.append(s["id"])
        for i in s["inputs"]:
            for f in i.get("synthesis_function") or []:
                hit = {"id": i["id"], "name": i["name"], "step": s["id"]}
                if hit not in functions.setdefault(f, []):
                    functions[f].append(hit)
        if s.get("atmosphere") or s.get("gas_flow_mode") in FLOWING:
            gases.append({"step": s["id"], "atmosphere": s.get("atmosphere"), "gas_flow_mode": s.get("gas_flow_mode"),
                          "gases": [{k: i[k] for k in ("id", "name", "fraction", "flow_rate", "synthesis_function")
                                     if k in i} for i in s["inputs"] if i.get("fraction") or i.get("flow_rate")
                                    or "protective_gas" in (i.get("synthesis_function") or [])]})
        if s.get("ph"):
            ph.append({"step": s["id"], "ph": s["ph"]})
    return {"highest_temperature": sorted(hottest.values(), key=lambda h: str(h["unit"])),
            "time_by_unit": [{"unit": u, "total": round(v, 6)} for u, v in sorted(time.items())],
            "steps_without_time": untimed, "inputs_by_function": dict(sorted(functions.items())),
            "gases": gases, "ph": ph}


def recipe_context(doc: dict, spec: dict) -> tuple:
    """What every recipe of a document reads: its records indexed, and its checklists' findings by record. Made once,
    it serves every preparation of the document (a toolkit that keeps the document loaded keeps it too)."""
    return _Graph(doc), _missing(doc, spec)


def recipe(doc: dict, spec: dict, preparation: str | None = None, context: tuple | None = None) -> dict:
    """The recipes of a document's preparations (each that is not a stage of another), or of one. ``context`` is
    :func:`recipe_context` of this document and schema, made here when not given."""
    g, missing = context or recipe_context(doc, spec)
    if preparation is not None and g.label(preparation) != "Preparation":
        return {"recipes": [], "status": "no_matching_record",
                "reason": f"{preparation} is not a Preparation of this document"}
    tops = [preparation] if preparation else sorted(
        nid for nid, n in g.nodes.items() if n.get("label") == "Preparation"
        and not any(e.get("type") == "PART_OF" and g.label(e["target"]) == "Preparation" for e in g.out.get(nid, [])))
    out = []
    for pid in tops:
        p = g.props(pid)
        steps: list = []
        stages: list = []
        _walk(g, pid, "", missing, steps, stages)
        r = {"id": pid, "name": p.get("name"), "method": p.get("method"),
             "preparation_methods": p.get("preparation_methods") or [],
             "sources": sorted({e["target"] for e in g.out.get(pid, []) if e.get("type") == "REPORTED_IN"}),
             "outputs": [e["target"] for e in g.out.get(pid, []) if e.get("type") == "HAS_OUTPUT"],
             "stated_for_the_whole": {k: p[k] for k in WHOLE_CONDITIONS if k in p},
             "stages": stages, "steps": steps, "summary": _summary(steps),
             "variant_of": [{"id": e["target"], **{k: (e.get("props") or {})[k] for k in ("varied", "changed")
                                                   if k in (e.get("props") or {})}}
                            for e in g.out.get(pid, []) if e.get("type") == "VARIANT_OF"],
             "variants": [{"id": e["source"], **{k: (e.get("props") or {})[k] for k in ("varied", "changed")
                                                 if k in (e.get("props") or {})}}
                          for e in g.into.get(pid, []) if e.get("type") == "VARIANT_OF"]}
        gaps = sorted({x for rid in [pid] + [s["id"] for s in stages] for x in (missing.get(rid) or {}).get(
            "evidence_missing", [])})
        if gaps:
            r["checklist_evidence_missing"] = gaps
        if not steps:
            r["note"] = "no steps are recorded: only what is stated for the whole is known"
        out.append(r)
    return {"recipes": out, "status": "answered" if out else "no_matching_record",
            "limitations": ["values are as reported: temperatures and times are grouped by unit, never converted",
                            "a time total sums only the steps that state one (steps_without_time lists the others), "
                            "each times the number of times it was carried out",
                            "the summary is read from the steps and is not a record; cite the steps' evidence"]}


def _v(v: Any) -> str:
    if not isinstance(v, dict):
        return "" if v is None else (", ".join(map(str, v)) if isinstance(v, list) else str(v))
    if v.get("status") != "present":
        return v.get("status", "")
    num = v.get("value", v.get("text_value"))
    if num is None and "lower" in v:
        num = f"{v['lower']}–{v.get('upper')}"
    unit = v.get("unit", "")
    return f"{num} {'' if unit == '1' else unit}".strip()


def render_markdown(res: dict) -> str:
    lines: list[str] = []
    for r in res.get("recipes", []):
        lines += [f"## {r['name'] or r['id']}", "", f"`{r['id']}` · {', '.join(r['preparation_methods']) or 'no method family'}"
                  + (f" · {r['method']}" if r.get("method") else ""), ""]
        for v in r["variant_of"]:
            lines.append(f"Variant of `{v['id']}`: {', '.join(v.get('varied') or [])}"
                         + (f" ({v['changed']})" if v.get("changed") else ""))
        if r["stated_for_the_whole"]:
            lines.append("Stated for the whole: " + "; ".join(f"{k} {_v(v)}" for k, v in r["stated_for_the_whole"].items()))
        lines += ["", "| # | step | action | T | time | ramp | gas | pH | inputs | missing |", "|---|---|---|---|---|---|---|---|---|---|"]
        for s in r["steps"]:
            ins = "; ".join(i["name"] + (f" ({', '.join(i['synthesis_function'])})" if i.get("synthesis_function") else "")
                            for i in s["inputs"])
            gas = (s.get("atmosphere") or "") + (f" ({s['gas_flow_mode']})" if s.get("gas_flow_mode") else "")
            lines.append(f"| {s['position']} | {s.get('name') or ''} | {s.get('action') or ''} | {_v(s.get('temperature'))} | "
                         f"{_v(s.get('duration'))}{' ×' + str(s['carried_out']) if s['carried_out'] > 1 else ''} | "
                         f"{_v(s.get('ramp_rate'))} | {gas} | {_v(s.get('ph'))} | {ins} | "
                         f"{', '.join(s.get('checklist_missing') or [])} |")
        sm = r["summary"]
        lines += ["", "Highest temperature: " + (", ".join(f"{h['value']:g} {h['unit']}" for h in sm["highest_temperature"])
                                               or "none stated"),
                  "Time stated: " + (", ".join(f"{t['total']:g} {t['unit']}" for t in sm["time_by_unit"]) or "none")
                  + (f" (no time: {len(sm['steps_without_time'])} steps)" if sm["steps_without_time"] else ""),
                  "By function: " + "; ".join(f"{f}: {', '.join(sorted({i['name'] for i in xs}))}"
                                               for f, xs in sm["inputs_by_function"].items()), ""]
    if not res.get("recipes"):
        lines.append(res.get("reason") or "No preparation is recorded.")
    return "\n".join(lines)
