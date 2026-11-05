"""Check a proposal against the records it names: every quotation of 20 characters or more is looked up in the recipes
of the preparations it names by their full ids (read with scale_recipe), and the composition of each one's products
is listed with its unit and basis (by mass, by atoms), so that a number taken from it is read on the basis it states.

  python3 -I check_quotes.py proposal.md --graph <document> [--server URL] [--out check.json]

A quotation found in none of the named records, or an id that names no preparation of the document, is a failure
(exit 1); an id written short (without its prefix) is listed so that it is written in full. The tools are called as
precedents.py calls them (a server that keeps the document loaded, or ScaleToolkit in this process).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from precedents import tool_caller  # noqa: E402

QUOTE = re.compile(r"[“\"]([^“”\"\n]{20,600})[”\"]")
FULL_ID = re.compile(r"[A-Za-z][\w-]*:[\w.\-/]*?/prep(?:aration)?/[\w.\-]+")
SHORT_ID = re.compile(r"`([^`\s:]*?/prep(?:aration)?/[\w.\-,]+)`")


def norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("…", "...")
    return re.sub(r"\s+", " ", s).strip().lower()


def composition(call, graph: str, prep: str) -> list[dict]:
    """Each component of the catalysts a preparation gives, with its share or loading as recorded and the basis."""
    rows = []
    for label in ("ChemicalSpecies", "Material"):
        plan = {"question": f"What is {prep} made of, on which basis?",
                "match": {"label": "Preparation", "as": "prep", "where": [{"prop": "id", "op": "eq", "value": prep}]},
                "steps": [{"from": "prep", "edge": "HAS_OUTPUT", "to": "CatalystSample", "as": "sample"},
                          {"from": "sample", "edge": "HAS_FORMULATION", "to": "Catalyst", "as": "catalyst"},
                          {"from": "catalyst", "edge": "HAS_COMPONENT", "to": label, "as": "component",
                           "edge_as": "link"}],
                "return": ["catalyst.nominal_formula", "component.name", "link.role", "link.fraction",
                           "link.fraction_basis", "link.loading", "link.loading_basis"],
                "limit": 200, "evidence": False}
        res = call("query", {"plan": plan, "path": graph})
        rows += [r["values"] for r in res.get("rows") or []]
    return rows


MEASURED_KINDS = ("composition_fraction", "loading", "microscopy_particle_size", "particle_edge_length",
                  "crystallite_size")


def measured(call, graph: str, prep: str) -> list[dict]:
    """What a characterization of the preparation's samples measured (CQ-19): compositions, loadings and sizes, with the
    technique and the state. The catalyst's composition and the state's labels are not measurements; only these are."""
    rows = []
    for kind in MEASURED_KINDS:
        plan = {"question": f"What did a characterization of {prep}'s samples measure ({kind})?",
                "match": {"label": "Preparation", "as": "prep", "where": [{"prop": "id", "op": "eq", "value": prep}]},
                "steps": [{"from": "prep", "edge": "HAS_OUTPUT", "to": "CatalystSample", "as": "sample"},
                          {"from": "sample", "edge": "CHARACTERIZES", "direction": "in", "to": "Characterization",
                           "as": "measurement", "edge_as": "measured_in"},
                          {"from": "measurement", "entries": "result_values", "kind": kind, "as": "result"}],
                "return": ["result", "measurement.technique", "measured_in.state"],
                "limit": 200, "evidence": False}
        try:
            res = call("query", {"plan": plan, "path": graph})
        except Exception:                                    # a graph with no characterization at all
            continue
        rows += [dict(r["values"], kind=kind) for r in res.get("rows") or []]
    return rows


def outcomes(call, graph: str, prep: str) -> list[dict]:
    """The claims about the preparation: what its authors say it obtained or failed to obtain, in the curator's words."""
    plan = {"question": f"What do the authors claim about what {prep} obtained?",
            "match": {"label": "Preparation", "as": "prep", "where": [{"prop": "id", "op": "eq", "value": prep}]},
            "steps": [{"from": "prep", "edge": "ABOUT", "direction": "in", "to": "Claim", "as": "claim"}],
            "return": ["claim.claim_kind", "claim.statement"], "limit": 50, "evidence": False}
    try:
        res = call("query", {"plan": plan, "path": graph})
    except Exception:                                        # a graph with no claim at all
        return []
    return [{"kind": r["values"].get("claim.claim_kind"), "statement": r["values"].get("claim.statement")}
            for r in res.get("rows") or []]


def obtained(call, graph: str, prep: str) -> list[dict]:
    """What the preparation obtained, per state it reached: shape, architecture, morphology and phases, and the
    characterizations that determine the state (none: the state is the record's label)."""
    base = {"match": {"label": "Preparation", "as": "prep", "where": [{"prop": "id", "op": "eq", "value": prep}]},
            "limit": 200, "evidence": False}
    reach = {"from": "prep", "edge": "REACHED_BY", "direction": "in", "to": "CatalystState", "as": "state"}
    states = {}
    try:
        plan = dict(base, question=f"What did {prep} obtain?", steps=[
            reach, {"from": "state", "edge": "HAS_PHASE", "to": "Material", "as": "phase", "optional": True}],
            **{"return": ["state.id", "state.particle_shape", "state.architecture", "state.morphology",
                          "phase.name"]})
        res = call("query", {"plan": plan, "path": graph})
        for r in res.get("rows") or []:
            v = r["values"]
            st = states.setdefault(v.get("state.id"), {"shape": v.get("state.particle_shape"),
                                                      "architecture": v.get("state.architecture"),
                                                      "morphology": v.get("state.morphology"),
                                                      "phases": [], "shown_by": []})
            if v.get("phase.name") and v["phase.name"] not in st["phases"]:
                st["phases"].append(v["phase.name"])
        plan = dict(base, question=f"What shows the states {prep} reached?", steps=[
            reach, {"from": "state", "edge": "DETERMINED_BY", "to": "Characterization", "as": "measurement"}],
            **{"return": ["state.id", "measurement.technique"]})
        res = call("query", {"plan": plan, "path": graph})
        for r in res.get("rows") or []:
            v = r["values"]
            t = v.get("measurement.technique")
            if v.get("state.id") in states and t and t not in states[v["state.id"]]["shown_by"]:
                states[v["state.id"]]["shown_by"].append(t)
    except Exception:                                        # a graph with no state at all
        pass
    return list(states.values())


def listed(x) -> str:
    if isinstance(x, list):
        x = ", ".join(str(i) for i in x if i not in (None, "not_reported"))
    return str(x) if x not in (None, "", "None") else "not stated"


def result(r) -> str:
    """A measured entry as its target, value and unit (with its basis when stated)."""
    if not isinstance(r, dict):
        return json.dumps(r, ensure_ascii=False)
    shown = value(r) or (r.get("as_reported") and f"{r['as_reported']} (as printed)") or r.get("status") or "no value"
    return f"{r.get('target') or r.get('id')}: {shown}"


def value(v) -> str | None:
    if not isinstance(v, dict) or v.get("value") is None:
        return None
    s = f"{v['value']} {v.get('unit') or ''}".strip()
    extra = [v[k] for k in ("basis", "as_reported") if v.get(k)]
    return s + (f" ({'; '.join(map(str, extra))})" if extra else "")


def check(text: str, graph: str, call) -> dict:
    ids = sorted(set(FULL_ID.findall(text)))
    short = sorted({s for s in SHORT_ID.findall(text) if not FULL_ID.fullmatch(s)})
    named, missing, comps, meas, outs, objs, haystack = [], [], {}, {}, {}, {}, []
    for pid in ids:
        rec = call("recipe", {"path": graph, "preparation": pid})
        if not rec.get("recipes"):
            missing.append(pid)
            continue
        named.append(pid)
        haystack.append(norm(json.dumps(rec, ensure_ascii=False)))
        comps[pid] = []
        for row in composition(call, graph, pid):
            share = value(row.get("link.fraction"))
            load = value(row.get("link.loading"))
            comps[pid].append({"catalyst": row.get("catalyst.nominal_formula"), "component": row.get("component.name"),
                               "role": row.get("link.role"),
                               "share": share and f"{share}, basis {row.get('link.fraction_basis') or 'not stated'}",
                               "loading": load and f"{load}, basis {row.get('link.loading_basis') or 'not stated'}"})
        meas[pid] = [{"kind": row["kind"], "result": result(row.get("result")),
                      "technique": row.get("measurement.technique"), "state": row.get("measured_in.state")}
                     for row in measured(call, graph, pid)]
        outs[pid] = outcomes(call, graph, pid)
        objs[pid] = obtained(call, graph, pid)
    quotes = []
    for q in dict.fromkeys(QUOTE.findall(text)):
        if q.startswith((",", ".", ")", ":", " ")) or q.endswith(" "):     # text between two quotations
            continue
        quotes.append({"quote": q, "found": any(norm(q) in h for h in haystack)})
    return {"named": named, "not_a_preparation": missing, "written_short": short, "quotes": quotes,
            "compositions": comps, "measured": meas, "outcomes": outs, "obtained": objs,
            "failures": len(missing) + sum(not q["found"] for q in quotes)}


def markdown(res: dict) -> str:
    lines = [f"# Check: {len(res['quotes'])} quotations, {len(res['named'])} preparations named", ""]
    lines += [f"- {'found' if q['found'] else 'NOT FOUND'}: \"{q['quote'][:160]}\"" for q in res["quotes"]]
    lines += [f"- NOT A PREPARATION of the document: `{p}`" for p in res["not_a_preparation"]]
    lines += [f"- written short (write the full id): `{s}`" for s in res["written_short"]]
    lines += ["", "## The named records: compositions as stated (read each on its basis), what each obtained, what was "
              "measured, and the authors' outcome", ""]
    for pid, rows in res["compositions"].items():
        lines.append(f"- `{pid}`:")
        lines += [f"  - {r['catalyst']}: {r['component']} ({r['role']})"
                  + "".join(f"; {k} {r[k]}" for k in ("share", "loading") if r[k]) for r in rows]
        if not rows:
            lines.append("  - no component recorded")
        for o in res.get("obtained", {}).get(pid) or []:
            how = ("shown by " + "; ".join(o["shown_by"])) if o["shown_by"] else "a label, nothing shows it"
            lines.append(f"  - obtained ({how}): shape {listed(o['shape'])}; architecture {listed(o['architecture'])}; "
                         f"{listed(o['morphology'])}; phases {listed(o['phases'])}")
        got = res.get("measured", {}).get(pid) or []
        lines += [f"  - measured ({m['kind']}, {m['technique'] or 'technique not stated'}, "
                  f"{m['state'] or 'state not stated'}): {m['result']}" for m in got]
        if not got:
            lines.append("  - measured: nothing recorded (the composition, phase, shape and size are the record's labels)")
        lines += [f"  - authors' outcome ({o['kind'] or 'claim'}): {o['statement']}"
                  for o in res.get("outcomes", {}).get(pid) or []]
    lines += ["", f"failures: {res['failures']}"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("proposal")
    ap.add_argument("--graph", required=True)
    ap.add_argument("--server")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    res = check(Path(a.proposal).read_text(), a.graph, tool_caller(a.server))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(markdown(res))
    return 1 if res["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
