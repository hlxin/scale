"""The precedents of a question with several requirements, from one query plan: every row the plan returns is tested
against each requirement, the rows are grouped by a key (a preparation), and the groups are ranked by the
requirements they meet, the first listed weighing most. For each requirement the closest groups that meet it are
listed too: the records to take that aspect from.

  python3 -I precedents.py --requirements req.json --graph <document> [--plan plan.json] [--server URL]
                           [--key prep.id] [--top 8] [--out precedents.json]

req.json lists the requirements hardest first, each a test on a field the plan returns:
  [{"name": "Cu and Au", "field": "catalyst.nominal_formula", "matches": "(?=.*Cu(?![a-z]))(?=.*Au(?![a-z]))"},
   {"name": "cube", "field": "state.particle_shape", "matches": "cube"},
   {"name": "5 nm", "field": "state.properties.particle_size", "between": [4, 6], "unit": "nm"}]
`matches` is a regular expression (case ignored) on the value, or on any item of a list; `between` reads a number or
a value object in the stated unit only (nothing is converted). A group meets a requirement when one of its rows does;
a field no row of the group holds is counted as not curated, a value in another unit as not compared: neither is a
failure. The plan defaults to ../references/precedents-plan.json (every particle state of a scale-catal document with
its catalyst, composition, class, shape, size, phases, components and preparation). The tools are called through a
server that keeps the document loaded (`scale serve`, --server) or, without one, through ScaleToolkit in this process.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

PLAN = Path(__file__).resolve().parent.parent / "references" / "precedents-plan.json"


def tool_caller(server: str | None):
    """call(name, arguments) -> result, through a server's /tools/<name> or a ScaleToolkit in this process."""
    if server:
        def call(name: str, arguments: dict) -> dict:
            req = urllib.request.Request(f"{server.rstrip('/')}/tools/{name}", data=json.dumps(arguments).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3600) as r:
                return json.loads(r.read())
        return call
    from scale.api import ScaleToolkit
    return ScaleToolkit().call


UNSTATED = {"not_reported", "not_curated", "not stated", "not_stated_in_source"}


def stated(v) -> bool:
    """False for a placeholder the document writes where a value is not known (a status, a missing value object)."""
    if isinstance(v, str):
        return v.strip().lower() not in UNSTATED
    if isinstance(v, dict) and "status" in v:
        return v.get("status") == "present" or v.get("value") is not None
    return True


def meets(req: dict, value) -> bool | str | None:
    """True or False; None when the row states no value; "other" when its values are in another unit or not numbers."""
    vals = value if isinstance(value, list) else [value]
    vals = [v for v in vals if v not in (None, "", [], {}) and stated(v)]
    if not vals:
        return None
    if "matches" in req:
        rx = re.compile(req["matches"], re.I)
        return any(rx.search(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for v in vals)
    if "between" in req:
        lo, hi = req["between"]
        compared = False
        for v in vals:
            num, unit = (v.get("value"), v.get("unit")) if isinstance(v, dict) else (v, None)
            if isinstance(num, (int, float)) and not isinstance(num, bool) and unit == req.get("unit"):
                compared = True
                if lo <= num <= hi:
                    return True
        return False if compared else "other"
    raise SystemExit(f"requirement {req.get('name')!r}: give `matches` or `between`")


def short(v) -> str:
    if isinstance(v, dict):
        return " ".join(str(v[k]) for k in ("value", "unit") if v.get(k) is not None) or json.dumps(v)[:40]
    if isinstance(v, list):
        return ", ".join(short(x) for x in v)
    return str(v)


def rank(rows: list[dict], reqs: list[dict], key: str, top: int) -> dict:
    names = [r["name"] for r in reqs]
    groups: dict[str, dict] = {}
    for row in rows:
        vals = row.get("values") or row
        k = vals.get(key)
        if k is None:
            continue
        g = groups.setdefault(k, {"key": k, "met": dict.fromkeys(names, False), "held": dict.fromkeys(names, False),
                                  "compared": dict.fromkeys(names, False), "fields": {}})
        for r in reqs:
            m = meets(r, vals.get(r["field"]))
            if m is not None:
                g["held"][r["name"]] = True
            if m in (True, False):
                g["compared"][r["name"]] = True
            if m is True:
                g["met"][r["name"]] = True
        for f, v in vals.items():
            if f != key and v not in (None, "", []):
                seen = g["fields"].setdefault(f, [])
                s = short(v)
                if s not in seen and len(seen) < 3:
                    seen.append(s)

    def order(g, skip=None):
        flags = [g["met"][n] for n in names if n != skip]
        return ([not f for f in flags], -sum(flags), str(g["key"]))

    ranked = sorted(groups.values(), key=order)
    out = {"key": key, "rows": len(rows), "groups": len(groups), "requirements": [], "candidates": [],
           "closest_by_requirement": {}}
    for r in reqs:
        n = r["name"]
        out["requirements"].append({
            "name": n, "field": r["field"],
            "met_by": sum(g["met"][n] for g in groups.values()),
            "not_curated": sum(not g["held"][n] for g in groups.values()),
            "not_compared": sum(g["held"][n] and not g["compared"][n] for g in groups.values())})
        meeting = sorted((g for g in groups.values() if g["met"][n]), key=lambda g: order(g, n))
        out["closest_by_requirement"][n] = [{"key": g["key"], "also_meets": [m for m in names if m != n and g["met"][m]]}
                                            for g in meeting[:5]]
    for g in ranked[:top]:
        out["candidates"].append({"key": g["key"], "meets": [n for n in names if g["met"][n]],
                                  "misses": [n for n in names if not g["met"][n]], "fields": g["fields"]})
    return out


def markdown(res: dict) -> str:
    lines = [f"{res['rows']} rows, {res['groups']} groups by `{res['key']}`.", "",
             "| requirement | met by | not curated | not compared |", "|---|---|---|---|"]
    lines += [f"| {r['name']} | {r['met_by']} | {r['not_curated']} | {r['not_compared']} |" for r in res["requirements"]]
    lines += ["", "Candidates, ranked by the requirements met (the first listed weighs most):", "",
              "| # | record | meets | misses |", "|---|---|---|---|"]
    lines += [f"| {i} | `{c['key']}` | {', '.join(c['meets']) or '-'} | {', '.join(c['misses']) or '-'} |"
              for i, c in enumerate(res["candidates"], 1)]
    lines += ["", "Closest records for each requirement:", ""]
    for n, gs in res["closest_by_requirement"].items():
        shown = "; ".join(f"`{g['key']}`" + (f" (also {', '.join(g['also_meets'])})" if g["also_meets"] else "")
                          for g in gs)
        lines.append(f"- {n}: {shown or 'none in this document'}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--requirements", required=True)
    ap.add_argument("--graph", required=True)
    ap.add_argument("--plan", default=str(PLAN))
    ap.add_argument("--server")
    ap.add_argument("--key", default="prep.id")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    reqs = json.loads(Path(a.requirements).read_text())
    res = tool_caller(a.server)("query", {"plan": json.loads(Path(a.plan).read_text()), "path": a.graph})
    if res.get("error"):
        print(f"the plan failed: {res['error']}", file=sys.stderr)
        return 1
    out = rank(res.get("rows") or [], reqs, a.key, a.top)
    out.update(status=res.get("status"), access=res.get("access"))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(markdown(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
