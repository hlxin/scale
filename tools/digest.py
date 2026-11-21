"""A first look at one paper's graph: what it recorded, how it answers SCALE's three use cases, and what a person
should check (``scale source digest``; the first-paper skill shows it to a new contributor).

The digest reads only documents and is deterministic. Its three answers are the use cases of examples/methanol-synthesis-public/use-cases/:

1. **conditions and outcomes**: every catalytic test with its catalyst, the conditions and the results as recorded;
2. **has this been done?**: each catalyst (by its elements, O and H left out) and reaction of the paper looked up in
   the graphs SCALE holds, with the earliest source that reports the same pair. "Not found" means not in those
   graphs, never "new to the literature";
3. **negative results**: tests that failed, outcomes reported as zero, as an upper bound or below a detection limit,
   and claims the source marks as disputed or refuted.

Then the authors' claims and any hypotheses, kept apart, and the quality summary: validation and the value check
(tools/valuecheck.py) with the flagged values a person must look at first.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .util import load_doc
from .valuecheck import check_document as check_values

ELEMENT = re.compile(r"[A-Z][a-z]?")
LIGHT = {"O", "H"}                                   # left out of a catalyst's composition family
# the properties read first as conditions; the other present values of a test are its results
CONDITIONS = ("temperature", "pressure", "space_velocity", "flow_rate", "potential", "electrode_potential",
              "current_density", "duration", "time_on_stream", "irradiance", "power", "residence_time")
NEGATIVE_STATUS = {"below_detection_limit", "below_quantification_limit", "not_detected"}


def _props(r: dict) -> dict:
    return r.get("props") or {}


def _fmt(v: Any) -> str:
    if not isinstance(v, dict):
        return str(v)
    if v.get("status") != "present":
        lim = f" {v['value']} {v.get('unit') or ''}".rstrip() if v.get("value") is not None else ""
        return f"{v.get('status')}{lim}"
    b = {"upper": "≤ ", "lower": "≥ "}.get(v.get("bound"), "")
    unit = v.get("unit") if v.get("unit") not in (None, "not stated") else ""
    return f"{b}{v.get('value')} {unit}".strip()


def _index(doc: dict) -> tuple[dict, dict, dict]:
    nodes = {n["id"]: n for n in doc.get("nodes") or []}
    out, inn = defaultdict(list), defaultdict(list)
    for e in doc.get("links") or []:
        out[e["source"]].append(e)
        inn[e["target"]].append(e)
    return nodes, out, inn


def _follow(out: dict, nodes: dict, rid: str, edge: str) -> list[dict]:
    return [nodes[e["target"]] for e in out.get(rid, []) if e.get("type") == edge and e["target"] in nodes]


def elements(nodes: dict, out: dict, catalyst_id: str) -> frozenset:
    """A catalyst's composition family: the elements of its components' formulas (or names), O and H left out."""
    els = set()
    for c in _follow(out, nodes, catalyst_id, "HAS_COMPONENT"):
        p = _props(c)
        els |= set(ELEMENT.findall(p.get("formula") or p.get("nominal_formula") or ""))
    if not els:
        els = set(ELEMENT.findall(_props(nodes[catalyst_id]).get("nominal_formula") or ""))
    return frozenset(els - LIGHT)


def reaction_key(r: dict) -> str:
    """A reaction by its species: the equation's sides with coefficients and phases left out ("CO + 2 H2 -> CH3OH")."""
    eq = _props(r).get("equation") or ""
    sides = re.split(r"\s*(?:->|→|=|⇌|<=>)\s*", eq)
    if len(sides) != 2:
        return (_props(r).get("name") or r["id"]).casefold()
    side = lambda s: " + ".join(sorted(re.sub(r"^\d+(?:\.\d+)?\s*|\((?:g|l|s|aq)\)", "", t.strip())
                                        for t in s.split("+") if t.strip()))
    return f"{side(sides[0])} -> {side(sides[1])}"


def _tests(doc: dict) -> list[dict]:
    """Every catalytic test with its catalyst (formulation), the catalyst's elements, its reactions and source year."""
    nodes, out, _ = _index(doc)
    years = {i: _props(n).get("year") for i, n in nodes.items() if n.get("label") == "Source"}
    rows = []
    for t in nodes.values():
        if t.get("label") != "CatalyticTest":
            continue
        cats = [c for s in _follow(out, nodes, t["id"], "USES_CATALYST") for c in _follow(out, nodes, s["id"], "HAS_FORMULATION")]
        srcs = [e["target"] for e in out.get(t["id"], []) if e.get("type") == "REPORTED_IN"] or \
               sorted({ev.get("source") for ev in _props(t).get("evidence") or [] if isinstance(ev, dict)} - {None})
        rows.append({"test": t, "catalysts": cats, "elements": [elements(nodes, out, c["id"]) for c in cats],
                     "reactions": [reaction_key(r) for r in _follow(out, nodes, t["id"], "OF_REACTION")],
                     "sources": srcs, "years": [y for y in (years.get(s) for s in srcs) if y]})
    return rows


def _values(props: dict) -> tuple[list[str], list[str]]:
    conds, results = [], []
    for k, v in props.items():
        if isinstance(v, dict) and "status" in v and k != "evidence":
            if v.get("status") == "not_reported":
                continue
            (conds if k in CONDITIONS else results).append(f"{k} {_fmt(v)}")
    order = {k: i for i, k in enumerate(CONDITIONS)}
    conds.sort(key=lambda s: order.get(s.split(" ")[0], 99))
    return conds, results


def _negative(t: dict) -> list[str]:
    p, why = _props(t), []
    if p.get("experiment_status") in ("failed", "aborted"):
        why.append(f"experiment {p['experiment_status']}")
    for k, v in p.items():
        if not isinstance(v, dict) or k in CONDITIONS or k == "evidence":
            continue
        if v.get("status") in NEGATIVE_STATUS:
            why.append(f"{k} {_fmt(v)}")
        elif v.get("status") == "present" and (v.get("bound") == "upper" or v.get("value") == 0):
            why.append(f"{k} {_fmt(v)}")
    return why


def _reference(paths: list[Path]) -> dict:
    """(elements, reaction) -> the tests that report it in the reference graphs, with their source years."""
    ref = defaultdict(list)
    for p in paths:
        doc = load_doc(p)
        for row in _tests(doc):
            for els in row["elements"]:
                for rk in row["reactions"]:
                    if els:
                        ref[(els, rk)].append({"graph": Path(p).name, "years": row["years"], "sources": row["sources"]})
    return ref


def default_references(repo: Path | None) -> list[Path]:
    """The graphs SCALE holds: graphs/* in a checkout, else the public example the package carries."""
    out = []
    if repo and (repo / "graphs").is_dir():
        out = [g for g in sorted((repo / "graphs").iterdir()) if (g / "parts").is_dir()]
    if not out:
        ex = Path(__file__).parent / "_data/examples/methanol-synthesis-public"
        out = [ex] if ex.is_dir() else ([repo / "examples/methanol-synthesis-public"] if repo else [])
    return [p for p in out if p.exists()]


def digest(doc: dict, references: list[Path], validation: dict | None = None) -> dict:
    nodes = doc.get("nodes") or []
    count = defaultdict(int)
    for n in nodes:
        count[n.get("label")] += 1
    tests = _tests(doc)
    own = {s for r in tests for s in r["sources"]}
    ref = _reference(references)

    q1 = []
    for r in tests:
        conds, results = _values(_props(r["test"]))
        q1.append({"test": _props(r["test"]).get("name") or r["test"]["id"],
                   "catalyst": "; ".join(_props(c).get("name") or c["id"] for c in r["catalysts"]) or "(none linked)",
                   "conditions": conds, "results": results})

    pairs = {}
    for r in tests:
        for c, els in zip(r["catalysts"], r["elements"]):
            for rk in r["reactions"]:
                if els:
                    pairs.setdefault((els, rk), _props(c).get("name") or c["id"])
    q2 = []
    for (els, rk), name in sorted(pairs.items(), key=lambda x: (sorted(x[0][0]), x[0][1])):
        hits = [h for h in ref.get((els, rk), []) if not set(h["sources"]) & own]
        years = sorted(y for h in hits for y in h["years"])
        q2.append({"catalyst": name, "elements": "–".join(sorted(els)), "reaction": rk,
                   "reported_before": len(hits), "earliest_year": years[0] if years else None,
                   "graphs": sorted({h["graph"] for h in hits})})

    q3 = [{"test": _props(r["test"]).get("name") or r["test"]["id"],
           "catalyst": "; ".join(_props(c).get("name") or c["id"] for c in r["catalysts"]), "why": w}
          for r in tests if (w := _negative(r["test"]))]
    q3_claims = [_props(n).get("statement") or _props(n).get("name") for n in nodes
                 if n.get("label") == "Claim" and _props(n).get("claim_status") in ("disputed", "refuted")]

    claims = [{"statement": _props(n).get("statement") or _props(n).get("name"), "kind": _props(n).get("claim_kind"),
               "status": _props(n).get("claim_status")} for n in nodes if n.get("label") == "Claim"]
    hyps = [_props(n).get("statement") or _props(n).get("name") for n in nodes if n.get("label") == "Hypothesis"]
    vals = check_values(doc)
    return {"title": (doc.get("graph") or {}).get("title"), "counts": dict(sorted(count.items())),
            "links": len(doc.get("links") or []), "references": [Path(p).name for p in references],
            "conditions_and_outcomes": q1, "has_this_been_done": q2, "negative_results": q3,
            "disputed_or_refuted_claims": q3_claims, "claims": claims, "hypotheses": hyps,
            "validation": validation, "values": {k: v for k, v in vals.items() if k != "rows"},
            "flagged_values": [{k: r[k] for k in ("name", "path", "value", "unit", "as_reported", "locator", "problems")}
                               for r in vals["rows"] if r["outcome"] == "flag"]}


def _cell(s: Any, n: int = 120) -> str:
    s = ("" if s is None else str(s)).replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def render(d: dict, limit: int = 40) -> str:
    c = d["counts"]
    head = ", ".join(f"{v} {k}" for k, v in c.items() if k in ("CatalyticTest", "Catalyst", "CatalystSample",
                                                                "Preparation", "Characterization", "Claim", "Hypothesis"))
    out = [f"# Your paper as a knowledge graph: {d['title'] or ''}".rstrip(), "",
           f"**{sum(c.values())} records and {d['links']} links**{': ' + head if head else ''}. Every record cites the "
           "page, table or figure it comes from.", ""]

    out += ["## 1. What was tested, under which conditions, with what result", ""]
    if d["conditions_and_outcomes"]:
        out += ["| catalyst | test | conditions | results |", "|---|---|---|---|"]
        for r in d["conditions_and_outcomes"][:limit]:
            out.append(f"| {_cell(r['catalyst'], 50)} | {_cell(r['test'], 50)} | {_cell(' · '.join(r['conditions']))} | "
                       f"{_cell(' · '.join(r['results']))} |")
        if len(d["conditions_and_outcomes"]) > limit:
            out.append(f"\n… and {len(d['conditions_and_outcomes']) - limit} more tests.")
    else:
        out.append("No catalytic tests recorded.")
    out.append("")

    out += ["## 2. Has this been done before?", "",
            f"Each catalyst (by its elements, O and H left out) and reaction of the paper, looked up in the graphs SCALE "
            f"holds ({', '.join(d['references']) or 'none available'}). *Not found* means not in these graphs, not new to "
            "the literature.", ""]
    if d["has_this_been_done"]:
        out += ["| catalyst | elements | reaction | reported before in SCALE | earliest |", "|---|---|---|---|---|"]
        for r in d["has_this_been_done"][:limit]:
            seen = f"{r['reported_before']} tests ({', '.join(r['graphs'])})" if r["reported_before"] else "not found"
            out.append(f"| {_cell(r['catalyst'], 50)} | {r['elements']} | {_cell(r['reaction'], 50)} | {seen} | "
                       f"{r['earliest_year'] or ''} |")
    else:
        out.append("No catalyst is linked to both its components and a reaction, so nothing could be looked up.")
    out.append("")

    out += ["## 3. Negative and null results", ""]
    if d["negative_results"] or d["disputed_or_refuted_claims"]:
        for r in d["negative_results"][:limit]:
            out.append(f"- **{_cell(r['catalyst'], 60)}**, {_cell(r['test'], 60)}: {'; '.join(r['why'])}")
        for s in d["disputed_or_refuted_claims"]:
            out.append(f"- claim disputed or refuted: {_cell(s, 160)}")
    else:
        out.append("None recorded. If the paper or SI reports failed or inactive runs, they belong here: ask the agent "
                   "to record them as tests with their conditions.")
    out.append("")

    out += ["## The authors' claims (kept apart from the measurements)", ""]
    out += [f"- *{c['kind'] or 'claim'}, {c['status'] or 'proposed'}*: {_cell(c['statement'], 200)}"
            for c in d["claims"][:limit]] or ["None recorded."]
    if d["hypotheses"]:
        out += ["", "**Hypotheses** (proposals, not findings):", ""] + [f"- {_cell(h, 200)}" for h in d["hypotheses"]]
    out.append("")

    v, val = d["values"], d.get("validation") or {}
    out += ["## Before you share it: what to check", ""]
    if val:
        out.append(f"- Validation: **{len(val.get('errors') or [])} errors**, {len(val.get('warnings') or [])} warnings.")
    out.append(f"- Numbers: {v['values']} recorded; **{v['counts']['flag']} flagged**, {v['counts']['unverifiable']} to "
               f"check by hand (figure readings, numbers in words), {v['counts']['ok']} backed by their quotes.")
    if d["flagged_values"]:
        out += ["", "| record | property | recorded | printed | locator | why |", "|---|---|---|---|---|---|"]
        for r in d["flagged_values"][:15]:
            out.append(f"| {_cell(r['name'], 40)} | {r['path']} | {_cell(str(r['value']) + ' ' + (r['unit'] or ''), 25)} | "
                       f"{_cell(r['as_reported'], 40)} | {_cell(r['locator'], 20)} | {_cell('; '.join(r['problems']), 70)} |")
    out += ["", "The full review sheet: `scale review values <graph> --out review-values.md`. Read every claim above too: "
            "is it what the authors say?", "",
            "## Next", "",
            "- **Look at it:** open the graph file in the [graph explorer](https://hlxin.github.io/scale/) (*open a graph file*).",
            "- **Ask it questions:** `scale graph query <graph> <plan>`; the plans in "
            "`examples/methanol-synthesis-public/use-cases/` are starting points.",
            "- **Share it:** when the review sheet is clear, the agent runs `scale source finish <folder> --public` and "
            "shows you the contribution to catal-commons; a SCALE reviewer approves the pull request, with credit to you."]
    return "\n".join(out) + "\n"


def digest_path(path: str | Path, repo: Path | None, references: list[str] | None = None) -> tuple[dict, str]:
    """A curation folder (its graph checked as `scale source check` does) or a graph file."""
    p = Path(path)
    validation = None
    if p.is_dir() and (p / "source.json").is_file():
        from . import curate
        res = curate.check(p, repo)
        validation = {"errors": res["errors"], "warnings": res["warnings"]}
        info = load_doc(p / "source.json")
        doc = load_doc(p / f"{info['slug']}.graph.json")
    else:
        doc = load_doc(p)
    refs = [Path(r) for r in references] if references else default_references(repo)
    d = digest(doc, refs, validation)
    return d, render(d)
