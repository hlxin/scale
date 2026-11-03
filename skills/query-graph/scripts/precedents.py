"""The precedents of a question with several requirements, from one query plan: every row the plan returns is tested
against each requirement, the rows are grouped by a key (a preparation), and the groups are ranked by the
requirements they meet, the first listed weighing most. For each requirement the closest groups that meet it are
listed too: the records to take that aspect from.

  python3 -I precedents.py --requirements req.json --graph <document> [--plan plan.json] [--server URL]
                           [--key prep.id] [--top 8] [--consensus 50] [--out precedents.json]

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

With --consensus N the N best-ranked preparations (with --within NAME, only those that meet that requirement) are read whole (scale_recipe) and what they do is counted: their
routes, their inputs by function (one count per recipe, a hydrate's water left out of the name), the temperature and
the precursors of each metal (the metal read from the
name: its symbol or its element's name) with the routes each is used in, the time of each action (by unit, never converted: median and range), and their commonest sequences of actions. Each
count names up to three records to cite. An intermediate a recipe lists as an input (a solution, a mixture, a
suspension) is not counted as a chemical.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import statistics
import re
import sys
import urllib.request
from pathlib import Path

PLAN = Path(__file__).resolve().parent.parent / "references" / "precedents-plan.json"
# The metals a precursor's name holds: the symbol as a formula writes it, or the element's name.
METALS = {"Li": "lithium", "Na": "sodium", "K": "potassium", "Mg": "magnesium", "Ca": "calcium", "Sr": "strontium",
          "Ba": "barium", "Al": "alumin", "Ga": "gallium", "In": "indium", "Sn": "(?:(?<![a-z])tin(?![a-z])|stann)", "Pb": "(?:(?<![a-z])lead(?![a-z])|plumb)", "Bi": "bismuth",
          "Sb": "antimon", "Ti": "titan", "V": "vanad", "Cr": "chrom", "Mn": "mangan", "Fe": "(?:(?<![a-z])iron|ferr)",
          "Co": "cobalt", "Ni": "nickel", "Cu": "(?:copper|cupr)", "Zn": "zinc", "Y": "yttrium", "Zr": "zircon",
          "Nb": "niob", "Mo": "molybd", "Ru": "ruthen", "Rh": "rhod", "Pd": "pallad", "Ag": "(?:silver|argent)",
          "Cd": "cadmium", "Hf": "hafnium", "Ta": "tantal", "W": "tungst", "Re": "rhenium", "Os": "osmium",
          "Ir": "iridium", "Pt": "platin", "Au": "(?:gold|(?:(?<![a-z])|(?<=chloro)|(?<=bromo))aur)", "La": "lanthan", "Ce": "cer(?:ium|ous|ic)",
          "Pr": "praseodym", "Nd": "neodym", "Sm": "samar", "Eu": "europ", "Gd": "gadolin", "Tb": "terbium",
          "Dy": "dysprosium", "Er": "erbium", "Yb": "ytterb", "Ge": "german", "Se": "selen", "Te": "tellur"}
METAL_RE = {m: re.compile(rf"(?<![A-Za-z]){m}(?![a-z])|{m}(?![a-z])(?=[A-Z0-9(\[·.]|$)|{w}")
            for m, w in METALS.items()}


def metals_in(name: str) -> set[str]:
    """The metals a precursor's name holds (K and Na only when no other metal is named: a salt's counter-ion)."""
    low = name.lower()
    found = {m for m, rx in METAL_RE.items() if rx.search(name) or re.search(METALS[m], low)}
    return found - {"K", "Na", "Li"} if found - {"K", "Na", "Li"} else found


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


INTERMEDIATE = re.compile(r"solution|mixture|suspension|dispersion|slurry|colloid|precipitate|product|filtrate|"
                          r"supernatant|powder obtained|as-prepared|obtained", re.I)
HYDRATE = re.compile(r"\s*[·•*.]\s*(?:\d+(?:\.\d+)?|x|n)?\s*H2O\s*$|\s+(?:mono|di|tri|tetra|penta|hexa|hepta|octa|nona|deca)?hydrate\b",
                     re.I)


def consensus(call, graph: str, keys: list[str]) -> dict:
    """What the given preparations do, counted (module docstring)."""
    routes, inputs, conds, seqs, by_metal = {}, {}, {}, {}, {}
    used_in = {}                                   # (metal, precursor) -> the routes of the records that use it
    spell = {}

    def add(table: dict, item: str, pid: str) -> None:
        c = table.setdefault(item, {"n": 0, "records": []})
        c["n"] += 1
        if len(c["records"]) < 3:
            c["records"].append(pid)
    read = 0
    for pid in keys:
        rec = (call("recipe", {"path": graph, "preparation": pid}).get("recipes") or [None])[0]
        if not rec:
            continue
        read += 1
        methods = rec.get("preparation_methods") or ([rec["method"]] if rec.get("method") else [])
        for m in methods:
            add(routes, m, pid)
        seq, counted = [], set()
        for st in rec.get("steps") or []:
            act = st.get("action") or "other"
            if not seq or seq[-1] != act:
                seq.append(act)
            for field in ("temperature", "duration"):
                v = st.get(field)
                if isinstance(v, dict) and isinstance(v.get("value"), (int, float)) and not isinstance(v["value"], bool):
                    conds.setdefault((act, field, v.get("unit") or ""), []).append((v["value"], pid))
            for i in st.get("inputs") or []:
                name = (i.get("name") or "").strip()
                fns = i.get("synthesis_function")
                fns = fns if isinstance(fns, list) else [fns]
                if not name or INTERMEDIATE.search(name):
                    continue
                norm = HYDRATE.sub("", name).strip().lower()
                for fn in fns:
                    if fn and (fn, norm) not in counted:
                        counted.add((fn, norm))
                        spell.setdefault((fn, norm), name)
                        add(inputs.setdefault(fn, {}), norm, pid)
                        if fn == "metal_precursor":
                            for m in metals_in(name):
                                add(by_metal.setdefault(m, {}), norm, pid)
                                used_in.setdefault((m, norm), collections.Counter()).update(methods or ["not stated"])
        add(seqs, " > ".join(seq), pid)

    def top(table: dict, n: int) -> list:
        return [{"item": k, **v} for k, v in sorted(table.items(), key=lambda x: (-x[1]["n"], x[0]))[:n]]
    out_inputs = {}
    for fn, table in sorted(inputs.items(), key=lambda x: -sum(v["n"] for v in x[1].values())):
        out_inputs[fn] = [{**r, "item": spell.get((fn, r["item"]), r["item"])} for r in top(table, 8)]
    out_conds = []
    for (act, field, unit), vals in sorted(conds.items(), key=lambda x: -len(x[1])):
        nums = [v for v, _ in vals]
        out_conds.append({"action": act, "field": field, "unit": unit, "n": len(nums),
                          "median": statistics.median(nums), "min": min(nums), "max": max(nums),
                          "records": list(dict.fromkeys(p for _, p in vals))[:3]})
    per_metal = {m: [{**r, "item": spell.get(("metal_precursor", r["item"]), r["item"]),
                      "routes": dict(used_in[(m, r["item"])].most_common(3))} for r in top(t, 5)]
                 for m, t in sorted(by_metal.items(), key=lambda x: -sum(v["n"] for v in x[1].values()))
                 if sum(v["n"] for v in t.values()) >= 2}
    return {"records_read": read, "routes": top(routes, 6), "precursors_by_metal": per_metal, "inputs": out_inputs,
            "conditions": out_conds[:20], "sequences": top(seqs, 3)}


def markdown_consensus(c: dict) -> str:
    lines = ["", f"What the {c['records_read']} closest records do (counts; each with records to cite):", "",
             "Routes: " + "; ".join(f"{r['item']} {r['n']}" for r in c["routes"]), "",
             "Metal precursors by metal (records using each [the routes they are used in]):"]
    for m, rows in (c.get("precursors_by_metal") or {}).items():
        lines.append(f"- {m}: " + "; ".join(
            f"{r['item']} {r['n']} [" + ", ".join(f"{k} {v}" for k, v in r["routes"].items()) + f"] (`{r['records'][0]}`)"
            for r in rows))
    lines += ["", "Inputs by function:"]
    for fn, rows in c["inputs"].items():
        lines.append(f"- {fn}: " + "; ".join(f"{r['item']} {r['n']} (`{r['records'][0]}`)" for r in rows))
    lines += ["", "| action | field | unit | n | median | range | e.g. |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {x['action']} | {x['field']} | {x['unit']} | {x['n']} | {x['median']:g} | {x['min']:g}-{x['max']:g} | "
              f"`{x['records'][0]}` |" for x in c["conditions"]]
    lines += ["", "Commonest sequences of actions:"]
    lines += [f"- {s['n']}×: {s['item']} (`{s['records'][0]}`)" for s in c["sequences"]]
    return "\n".join(lines)


def cached_query(call, plan_text: str, graph: str) -> dict:
    """The plan's answer, kept in a cache keyed by the plan and the graph's path, size and modification time
    ($SCALE_PRECEDENTS_CACHE, default ~/.cache/scale/precedents): the same plan over an unchanged graph is asked once.
    A graph that only the server's machine holds is keyed by its path alone."""
    if os.path.exists(graph):
        st = os.stat(graph)
        key = hashlib.sha256(f"{plan_text}|{os.path.abspath(graph)}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()
    else:
        key = hashlib.sha256(f"{plan_text}|remote:{graph}".encode()).hexdigest()
    folder = Path(os.environ.get("SCALE_PRECEDENTS_CACHE", "~/.cache/scale/precedents")).expanduser()
    f = folder / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text())
    res = call("query", {"plan": json.loads(plan_text), "path": graph})
    if not res.get("error"):
        folder.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(res))
        tmp.replace(f)
    return res


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
    ap.add_argument("--consensus", type=int, default=0, help="read this many best-ranked preparations whole and count")
    ap.add_argument("--within", action="append", default=[], help="count only preparations meeting this requirement")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    reqs = json.loads(Path(a.requirements).read_text())
    res = cached_query(tool_caller(a.server), Path(a.plan).read_text(), a.graph)
    if res.get("error"):
        print(f"the plan failed: {res['error']}", file=sys.stderr)
        return 1
    out = rank(res.get("rows") or [], reqs, a.key, 10 ** 9 if a.within else max(a.top, a.consensus))
    keys = [c["key"] for c in out["candidates"] if all(w in c["meets"] for w in a.within)][:a.consensus]
    out["candidates"] = out["candidates"][:a.top]
    out.update(status=res.get("status"), access=res.get("access"))
    if a.consensus:
        out["consensus"] = consensus(tool_caller(a.server), a.graph, keys)
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(markdown(out) + (markdown_consensus(out["consensus"]) if a.consensus else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
