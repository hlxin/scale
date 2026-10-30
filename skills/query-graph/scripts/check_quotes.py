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


def value(v) -> str | None:
    if not isinstance(v, dict) or v.get("value") is None:
        return None
    s = f"{v['value']} {v.get('unit') or ''}".strip()
    extra = [v[k] for k in ("basis", "as_reported") if v.get(k)]
    return s + (f" ({'; '.join(map(str, extra))})" if extra else "")


def check(text: str, graph: str, call) -> dict:
    ids = sorted(set(FULL_ID.findall(text)))
    short = sorted({s for s in SHORT_ID.findall(text) if not FULL_ID.fullmatch(s)})
    named, missing, comps, haystack = [], [], {}, []
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
    quotes = []
    for q in dict.fromkeys(QUOTE.findall(text)):
        if q.startswith((",", ".", ")", ":", " ")) or q.endswith(" "):     # text between two quotations
            continue
        quotes.append({"quote": q, "found": any(norm(q) in h for h in haystack)})
    return {"named": named, "not_a_preparation": missing, "written_short": short, "quotes": quotes,
            "compositions": comps,
            "failures": len(missing) + sum(not q["found"] for q in quotes)}


def markdown(res: dict) -> str:
    lines = [f"# Check: {len(res['quotes'])} quotations, {len(res['named'])} preparations named", ""]
    lines += [f"- {'found' if q['found'] else 'NOT FOUND'}: \"{q['quote'][:160]}\"" for q in res["quotes"]]
    lines += [f"- NOT A PREPARATION of the document: `{p}`" for p in res["not_a_preparation"]]
    lines += [f"- written short (write the full id): `{s}`" for s in res["written_short"]]
    lines += ["", "## Compositions of the named records (read each number on its basis)", ""]
    for pid, rows in res["compositions"].items():
        lines.append(f"- `{pid}`:")
        lines += [f"  - {r['catalyst']}: {r['component']} ({r['role']})"
                  + "".join(f"; {k} {r[k]}" for k in ("share", "loading") if r[k]) for r in rows]
        if not rows:
            lines.append("  - no component recorded")
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
