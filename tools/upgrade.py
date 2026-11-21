"""Upgrade a curated graph to a newer schema version, on demand, with a report of what the upgrade means for it.

A graph pins the schema version it was curated under and stays valid under it: every earlier version is kept frozen,
so nothing forces a graph to move when the schema changes. When its maintainers decide a newer version is worth it,
``scale graph upgrade`` says, before anything is written:

* **step by step**, what each schema version between the two adds, removes or tightens (:func:`schema_change.diff_specs`)
  and which of it touches this graph: properties now available on the labels it uses, value and evidence fields, new
  checklist requirements, breaking changes, and what touches none of its records ("nothing to do");
* **the mechanical upgrade** (:func:`pgraph_migrate.raise_version`): every record id kept, a rule's rewrites listed,
  a case a rule cannot map stopping the upgrade at its step;
* **validation and the checklist** before (under the pinned version) and after (under the target): errors, and the
  must and should items the records now lack, by item, with the records and sources they concern;
* **comparability**: values whose kind a newer version compares by a context (a selectivity by what it counts and what
  it is a share of, a pressure by absolute or gauge) that the value does not state - queries then keep them apart;
* **the re-reading worklist**: the records a targeted re-reading would revisit (they lack what the newer checklist
  asks, or a context their comparisons now need; and, only when asked with ``enrich``, a new property), grouped by
  source with the locators of their evidence, so that only those passages are read again, never the whole paper.

The report is markdown (and JSON); ``--write`` writes the upgraded graph. Nothing reads a source or calls a model: the
re-reading itself is the upgrade-curation skill, run on the worklist when the maintainers want it.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import pgraph
from .pgraph_migrate import STEP_RULES, raise_version, route
from .schema_change import diff_specs
from .util import ScaleError

_NODE = re.compile(r"^nodes\.(\w+)\.(\w+)(?: = (.+))?$")
_EDGE = re.compile(r"^edges\.(\w+)\.(\w+)(?: = (.+))?$")
_PROFILE = re.compile(r"^profiles\.\w+ (\w+) (.+)$")
_LABEL_ONLY = re.compile(r"^(nodes|edges)\.(\w+)$")


def _counts(doc: dict) -> tuple[Counter, Counter, int]:
    labels = Counter(n.get("label") for n in doc.get("nodes") or [])
    edges = Counter(e.get("type") for e in doc.get("links") or [])
    values = 0

    def walk(x: Any) -> None:
        nonlocal values
        if isinstance(x, dict):
            if "status" in x and ("value" in x or x.get("status") != "present"):
                values += 1
            for k, v in x.items():
                if k != "evidence":
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for r in (doc.get("nodes") or []) + (doc.get("links") or []):
        walk(r.get("props") or {})
    return labels, edges, values


_COMPARED_BY = re.compile(r"^quantities\.kinds\.(\w+) is compared by (\w+)")
_HOLDS = re.compile(r"^(?:nodes|edges)\.\w+\.\w+ holds quantity \w+")


def step_impact(diff: dict, labels: Counter, edges: Counter, values: int, held: Counter | None = None,
                kinds: Counter | None = None) -> dict:
    """What one schema step means for a graph with these labels, edge types and value objects (``held``: how many
    records hold each Label.property; ``kinds``: how many present values of each quantity kind it has)."""
    held, kinds = held or Counter(), kinds or Counter()
    out = {"new_properties": [], "new_terms": [], "new_requirements": [], "breaking": [], "value_and_evidence": [],
           "new_comparisons": [], "unit_contracts": 0, "new_record_kinds": [], "elsewhere": 0}

    def used(kind: str, name: str) -> int:
        return (labels if kind == "nodes" else edges).get(name, 0)

    for entry in diff["added"]:
        m = _NODE.match(entry) or _EDGE.match(entry)
        kind = "nodes" if entry.startswith("nodes.") else "edges"
        if m and used(kind, m.group(1)):
            key = "new_terms" if m.group(3) else "new_properties"
            out[key].append({"on": m.group(1), "property": m.group(2), "term": m.group(3),
                             "records": used(kind, m.group(1))})
        elif _LABEL_ONLY.match(entry):
            out["new_record_kinds"].append(entry.split(".", 1)[1])
        elif entry.startswith(("value.", "evidence.", "common.")) or entry.startswith(("quantit", "context")):
            out["value_and_evidence"].append({"change": entry, "values": values})
        else:
            out["elsewhere"] += 1
    for kind in ("narrowed", "removed", "changed"):
        for entry in diff[kind]:
            cm = _COMPARED_BY.match(entry)
            if cm:
                if kinds.get(cm.group(1)):
                    out["new_comparisons"].append({"kind": cm.group(1), "context": cm.group(2),
                                                   "values": kinds[cm.group(1)]})
                else:
                    out["elsewhere"] += 1
                continue
            if _HOLDS.match(entry) or entry.startswith("quantities: units are checked"):
                out["unit_contracts"] += 1           # validation checks every unit against its kind
                continue
            pm = _PROFILE.match(entry)
            if pm:
                if labels.get(pm.group(1)) or edges.get(pm.group(1)):
                    out["new_requirements"].append({"on": pm.group(1), "requirement": pm.group(2),
                                                    "records": labels.get(pm.group(1)) or edges.get(pm.group(1))})
                else:
                    out["elsewhere"] += 1
                continue
            m = re.match(r"^(nodes|edges)\.(\w+)(?:\.(\w+))?", entry)
            if m and used(m.group(1), m.group(2)):
                n = held.get(f"{m.group(2)}.{m.group(3)}", 0) if m.group(3) else used(m.group(1), m.group(2))
                if n:
                    out["breaking"].append({"kind": kind, "change": entry, "records": n})
            elif entry.startswith(("value", "evidence", "record_ref", "common", "schema name", "kernel name")) or \
                    not m and values and re.search(r"quantit|kind|context|unit", entry):
                out["breaking"].append({"kind": kind, "change": entry, "records": None})
            else:
                out["elsewhere"] += 1
    if any(out[k] for k in ("new_requirements", "breaking", "new_comparisons")):
        out["verdict"] = "needs attention"
    elif out["new_properties"] or out["value_and_evidence"]:
        out["verdict"] = "optional"
    elif out["unit_contracts"]:
        out["verdict"] = "checked automatically"
    else:
        out["verdict"] = "nothing to do"
    return out


def comparability(doc: dict, spec: dict) -> tuple[Counter, dict[tuple[str, str, str], str]]:
    """Under ``spec``'s quantity contracts: the number of present values of each kind, and every (record, value path,
    context) a value cannot state although its kind is compared by that context (``kind``)."""
    from . import quantities as q
    c = q.contracts(spec)
    kinds, gaps = Counter(), {}
    if c is None:
        return kinds, gaps
    nodes = [n for n in doc.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)]
    links = [e for e in doc.get("links") or [] if isinstance(e, dict) and isinstance(e.get("id"), str)]
    records = {r["id"]: r for r in nodes + links}
    variables = q.variable_kinds(doc)
    for r in nodes + links:
        props = r.get("props") if isinstance(r.get("props"), dict) else {}
        for path, v in q._values_anywhere(props):
            if v.get("status") != "present":
                continue
            top = path.split("/")[1]
            bound = q.binding(spec, r, top)[0]
            prop = top if bound is not None and re.fullmatch(rf"/{re.escape(top)}(?:/\d+)?", path) else ""
            try:
                got = q.read_value(c, spec, r, prop, v, records, variables)
            except Exception:                       # a value the contracts cannot read is validation's to report
                continue
            if got is None:
                continue
            kinds[got.kind] += 1
            for name, ctx in (got.contexts or {}).items():
                if ctx.value is None or ctx.unstated:
                    gaps[(r["id"], path[1:], name)] = got.kind
    return kinds, gaps


def _checklist(report) -> dict[tuple[str, str, str], None]:
    """(level, record, message) of every checklist item a document's records lack."""
    out = {}
    for p in ((report.conformance or {}).get("profiles") or {}).values():
        for level, key in (("must", "violations"), ("should", "missing_recommended"), ("evidence", "missing_evidence"),
                           ("applicability unknown", "unknown")):
            for v in p.get(key) or []:
                if isinstance(v, dict):
                    out[(level, v.get("record") or "", v.get("message") or v.get("item") or str(v))] = None
    return out


def _item(message: str) -> str:
    """A checklist message without the record it names, to group records by what they lack."""
    return re.sub(r"\s+", " ", message).strip()


def _sources(doc: dict) -> tuple[dict[str, set], dict[str, list], dict[str, str]]:
    """Each record's cited sources, its evidence locators, and each source's short name (title, year)."""
    srcs, locs, names = {}, {}, {}
    for n in doc.get("nodes") or []:
        if n.get("label") == "Source":
            p = n.get("props") or {}
            names[n["id"]] = f"{(p.get('title') or n['id'])[:70]}{' (' + str(p['year']) + ')' if p.get('year') else ''}"
    for r in (doc.get("nodes") or []) + (doc.get("links") or []):
        ev = [e for e in (r.get("props") or {}).get("evidence") or [] if isinstance(e, dict)]
        srcs[r["id"]] = {e.get("source") for e in ev if e.get("source")}
        locs[r["id"]] = sorted({f"{e.get('locator')}" for e in ev if e.get("locator")})
    return srcs, locs, names


def plan(doc: dict, repo: Path, to: str | None = None, spec_path: str | None = None,
         enrich: list[str] | None = None) -> tuple[dict, dict | None]:
    """The upgrade report for ``doc`` to version ``to`` (default: the head), and the upgraded document (None when a
    step stops). ``enrich`` (``Label.property``) adds to the worklist the records that could record a new property."""
    manifest = pgraph.spec_path(repo, spec_path, doc)
    head = pgraph.load_spec(manifest)
    target = to or head["version"]
    have = (doc.get("graph") or {}).get("schema_version")
    if have == target:
        raise ScaleError(f"the graph is already at scale-catal {have}")
    steps = route(have, target)
    if steps is None:
        raise ScaleError(f"no upgrade path from scale-catal {have} to {target}")
    specs = {v: pgraph.load_spec(pgraph.pinned(manifest, v, doc)) for v in {have, target} | {s[1] for s in steps}}
    labels, edges, values = _counts(doc)
    held = Counter(f"{r.get('label') or r.get('type')}.{k}" for r in (doc.get("nodes") or []) + (doc.get("links") or [])
                   for k in (r.get("props") or {}))
    kinds_after, _ = comparability(doc, specs[target])

    out_steps = []
    for frm, nxt, note in steps:
        imp = step_impact(diff_specs(specs[frm], specs[nxt]), labels, edges, values, held, kinds_after)
        rule = STEP_RULES.get(frm)
        out_steps.append({"from": frm, "to": nxt, "note": note, "rule": rule[0] if rule else None, **imp})

    new, blocked = None, None
    try:
        new, mig = raise_version(doc, target, specs[target])
        for s, m in zip(out_steps, mig["steps"]):
            s["rewrites"] = m.get("changes") or []
            if s["rewrites"] and s["verdict"] != "needs attention":
                s["verdict"] = "needs attention"
    except ScaleError as e:
        blocked = str(e)

    before = pgraph.validate(doc, specs[have])
    res = {"graph": (doc.get("graph") or {}).get("title") or (doc.get("graph") or {}).get("graph_id"),
           "from": have, "to": target, "records": {"nodes": sum(labels.values()), "links": sum(edges.values()),
                                                  "values": values},
           "steps": out_steps, "blocked": blocked,
           "before": {"errors": len(before.errors), "warnings": len(before.warnings)}}
    if new is None:
        return res, None
    after = pgraph.validate(new, specs[target])
    res["after"] = {"errors": len(after.errors), "warnings": len(after.warnings), "error_examples": after.errors[:10]}

    lack_before, lack_after = _checklist(before), _checklist(after)
    added = [k for k in lack_after if k not in lack_before]
    srcs, locs, names = _sources(new)
    by_item: dict[tuple[str, str], list[str]] = defaultdict(list)
    for level, rec, msg in added:
        by_item[(level, _item(msg))].append(rec)
    res["checklist"] = {"lacking_before": len(lack_before), "lacking_after": len(lack_after), "new": len(added),
                        "new_by_item": [{"level": lv, "item": it, "records": len(set(rs)),
                                         "sources": len({s for r in rs for s in srcs.get(r, ())})}
                                        for (lv, it), rs in sorted(by_item.items(), key=lambda x: -len(x[1]))]}

    # comparisons the upgrade leaves undecidable: contexts a value cannot state under the target that it did not lack
    _, gaps_before = comparability(doc, specs[have])
    _, gaps_after = comparability(new, specs[target])
    new_gaps = {k: v for k, v in gaps_after.items() if k not in gaps_before}
    by_ctx: dict[tuple[str, str], set] = defaultdict(set)
    for (rec, path, ctx), kind in new_gaps.items():
        by_ctx[(kind, ctx)].add(rec)
    res["comparability"] = {"values_now_needing_a_context": len(new_gaps),
                            "by_context": [{"kind": k, "context": c, "values": sum(1 for x, kk in new_gaps.items()
                                                                                  if kk == k and x[2] == c),
                                            "records": len(rs), "sources": len({s for r in rs for s in srcs.get(r, ())})}
                                           for (k, c), rs in sorted(by_ctx.items(), key=lambda x: -len(x[1]))]}

    # the re-reading worklist: what the newer checklist asks, the contexts comparisons now need, and (only when asked)
    # the new properties named in ``enrich``
    work: dict[str, dict] = {}
    for level, rec, msg in added:
        work.setdefault(rec, {"record": rec, "asks": set(), "could_add": set()})["asks"].add(_item(msg))
    for (rec, path, ctx), kind in new_gaps.items():
        work.setdefault(rec, {"record": rec, "asks": set(), "could_add": set()})["asks"].add(
            f"{path}: state its {ctx} ({kind} values are compared by it)")
    available = {f"{p['on']}.{p['property']}" for s in out_steps for p in s["new_properties"]}
    unknown = [e for e in enrich or [] if e not in available]
    if unknown:
        raise ScaleError(f"--enrich names no property this upgrade adds to a label of the graph: {', '.join(unknown)} "
                         f"(available: {', '.join(sorted(available)) or 'none'})")
    for r in (new.get("nodes") or []) + (new.get("links") or []):
        lab = r.get("label") or r.get("type")
        want = {e.split(".", 1)[1] for e in enrich or [] if e.split(".", 1)[0] == lab} - set(r.get("props") or {})
        if want:
            work.setdefault(r["id"], {"record": r["id"], "asks": set(), "could_add": set()})["could_add"] |= want
    res["enrich"] = sorted(enrich or [])
    per_source: dict[str, dict] = defaultdict(lambda: {"must_or_should": 0, "could_add": 0, "locators": set()})
    items = []
    for w in work.values():
        if not (w["asks"] or w["could_add"]):
            continue
        item = {"record": w["record"], "sources": sorted(srcs.get(w["record"], ())), "locators": locs.get(w["record"], []),
                "asks": sorted(w["asks"]), "could_add": sorted(w["could_add"])}
        items.append(item)
        for s in item["sources"] or ["(no source cited)"]:
            per_source[s]["must_or_should"] += bool(item["asks"])
            per_source[s]["could_add"] += bool(item["could_add"])
            per_source[s]["locators"] |= set(item["locators"])
    res["worklist"] = {"records": len(items), "records_lacking_checklist_items": sum(bool(i["asks"]) for i in items),
                       "sources": len(per_source),
                       "by_source": [{"source": s, "name": names.get(s, s), **{k: v for k, v in d.items() if k != "locators"},
                                      "passages": len(d["locators"])}
                                     for s, d in sorted(per_source.items(), key=lambda x: -(x[1]["must_or_should"] * 1000 + x[1]["could_add"]))],
                       "items": items}
    return res, new


def write(doc: dict, path: Path) -> Path:
    """The upgraded graph written as the input was kept: a folder of parts rewritten in place, else one JSON file."""
    from .util import write_canonical
    if path.is_dir() and (path / "parts" / "header.json").is_file():
        from . import graphparts as gp
        return gp.write_parts(gp.split(doc), path)
    write_canonical(path, doc)
    return path


def _cell(x: Any, n: int = 110) -> str:
    s = ("" if x is None else str(x)).replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


VERDICT_NOTE = {
    "needs attention": "the step rewrites records, asks the checklist for more, or compares values this graph holds "
                       "by something they may not state",
    "optional": "new properties or value fields the records could record; nothing in them changes",
    "checked automatically": "unit contracts: validation after the upgrade checks every value against them",
    "nothing to do": "nothing in it concerns the labels, properties or values this graph uses",
}


def render(r: dict, limit: int = 25) -> str:
    rec = r["records"]
    count = Counter(s["verdict"] for s in r["steps"])
    o = [f"# Upgrade report: {r['graph'] or ''} — scale-catal {r['from']} → {r['to']}".rstrip(), "",
         f"{rec['nodes']} records, {rec['links']} links, {rec['values']} values; {len(r['steps'])} schema steps: "
         + ", ".join(f"**{count[v]} {v}**" for v in VERDICT_NOTE if count[v]) + ".", ""]

    o += ["## Summary", ""]
    if r["blocked"]:
        o += [f"- **The mechanical upgrade stops:** {r['blocked']}. A person decides how the records the rule cannot map "
              "are written; nothing is written until then.", ""]
    else:
        a, c, w, q = r["after"], r["checklist"], r["worklist"], r["comparability"]
        n_rw = sum(len(s.get("rewrites") or []) for s in r["steps"])
        o += [f"- **Mechanical upgrade:** {n_rw} rewrites by migration rules, every record id kept. Validation errors "
              f"{r['before']['errors']} → **{a['errors']}**, warnings {r['before']['warnings']} → {a['warnings']}.",
              f"- **Newer checklist:** {c['new']} items the records now lack ({c['lacking_before']} lacking before → "
              f"{c['lacking_after']} after). Not errors: the records stay valid and queries report what is missing.",
              f"- **Comparability:** {q['values_now_needing_a_context']} values are compared by a context they do not "
              "state; queries keep them apart from values that state it, never mix them.",
              f"- **Targeted re-reading:** {w['records']} records in {w['sources']} sources"
              + (f" (including the new properties {', '.join(r['enrich'])})" if r["enrich"] else "")
              + ". Only their cited passages would be read again.", "",
              "**Your options:**", "",
              f"1. **Stay at {r['from']}.** Nothing to do; the graph stays valid and queryable under its own version.",
              f"2. **Upgrade mechanically** (`scale graph upgrade <graph> --write`): the graph pins {r['to']}; nothing "
              "is read again, and what the newer version could record stays unrecorded.",
              "3. **Upgrade and re-read the worklist** (the upgrade-curation skill), all of it or only the sources at the "
              "top of the table below.", ""]

    o += ["## Step by step", "", "| step | what changed | for this graph |", "|---|---|---|"]
    for s in r["steps"]:
        bits = []
        if s["new_requirements"]:
            bits.append(f"{len(s['new_requirements'])} checklist changes")
        if s["new_comparisons"]:
            bits.append("compares " + ", ".join(f"{x['kind']} by {x['context']}" for x in s["new_comparisons"]))
        if s["breaking"]:
            bits.append(f"{len(s['breaking'])} changes to properties its records hold")
        if s.get("rewrites"):
            bits.append(f"{len(s['rewrites'])} rewrites")
        if s["new_properties"]:
            bits.append(f"{len(s['new_properties'])} new properties on "
                        + ", ".join(sorted({p['on'] for p in s['new_properties']})))
        if s["unit_contracts"]:
            bits.append(f"{s['unit_contracts']} unit contracts")
        o.append(f"| {s['from']} → {s['to']} | {_cell(s['note'], 130)} | **{s['verdict']}**"
                 f"{': ' + '; '.join(bits) if bits else ''} |")
    o += ["", "Verdicts: " + "; ".join(f"*{k}*: {v}" for k, v in VERDICT_NOTE.items()) + ".", ""]

    for s in [x for x in r["steps"] if x["verdict"] == "needs attention"]:
        o += [f"### {s['from']} → {s['to']}", "", _cell(s["note"], 600), ""]
        if s["rule"]:
            o += [f"*Migration rule:* {_cell(s['rule'], 400)}", ""]
        if s.get("rewrites"):
            o += [f"*Rewrites ({len(s['rewrites'])}):* " + "; ".join(_cell(x, 80) for x in s["rewrites"][:5])
                  + (" …" if len(s["rewrites"]) > 5 else ""), ""]
        for key, head in (("new_comparisons", "Comparisons that now need a context"),
                          ("new_requirements", "Checklist changes on labels this graph uses"),
                          ("breaking", "Changes to properties its records hold")):
            xs = s[key]
            if not xs:
                continue
            o.append(f"*{head}:*")
            for x in xs[:limit]:
                if key == "new_comparisons":
                    o.append(f"- {x['kind']} by `{x['context']}` ({x['values']} {x['kind']} values in this graph)")
                elif key == "new_requirements":
                    o.append(f"- {x['on']}: {_cell(x['requirement'], 160)}")
                else:
                    o.append(f"- {_cell(x['change'], 160)} ({x['records']} records hold it)")
            if len(xs) > limit:
                o.append(f"- … and {len(xs) - limit} more")
            o.append("")

    opt = [(s["to"], p) for s in r["steps"] for p in s["new_properties"]]
    if opt:
        o += ["## New properties available (optional)", "",
              "Records could hold these; none needs them. Name the ones worth re-reading for with "
              "`--enrich Label.property` and they join the worklist.", "",
              "| property | since | records of that label |", "|---|---|---|"]
        o += [f"| `{p['on']}.{p['property']}` | {v} | {p['records']} |" for v, p in opt[:limit * 2]]
        if len(opt) > limit * 2:
            o.append(f"\n… and {len(opt) - limit * 2} more (JSON report).")
        o.append("")

    if not r["blocked"]:
        c, w, q = r["checklist"], r["worklist"], r["comparability"]
        o += ["## What the newer checklist asks that the records lack", ""]
        if c["new_by_item"]:
            o += ["| level | item | records | sources |", "|---|---|---|---|"]
            o += [f"| {x['level']} | {_cell(x['item'], 120)} | {x['records']} | {x['sources']} |"
                  for x in c["new_by_item"][:limit]]
        else:
            o.append("Nothing new: the records meet the newer checklist as well as they met the old one.")
        o += ["", "## Comparisons that now need a context the values do not state", "",
              "Re-reading settles each one either way: the passage states it (gauge or absolute, which reactant a "
              "conversion counts), or it does not, and the value records that the source is silent, so that a query "
              "can say why it keeps the value apart.", ""]
        if q["by_context"]:
            o += ["| kind | context | values | records | sources |", "|---|---|---|---|---|"]
            o += [f"| {x['kind']} | `{x['context']}` | {x['values']} | {x['records']} | {x['sources']} |"
                  for x in q["by_context"][:limit]]
        else:
            o.append("None.")
        o += ["", "## Re-reading worklist, by source", "",
              "Only these sources' cited passages would be read again, the top ones first. Each record, its locators "
              "and what it lacks are in the JSON report (`--format json`).", ""]
        if w["by_source"]:
            o += ["| source | records with a gap | records for a new property | passages |", "|---|---|---|---|"]
            o += [f"| {_cell(x['name'], 80)} | {x['must_or_should']} | {x['could_add']} | {x['passages']} |"
                  for x in w["by_source"][:limit]]
            if len(w["by_source"]) > limit:
                o.append(f"\n… and {len(w['by_source']) - limit} more sources.")
        else:
            o.append("Nothing to re-read.")
        if r["after"]["errors"]:
            o += ["", "## Validation errors after the upgrade", ""] + [f"- {_cell(e, 200)}" for e in r["after"]["error_examples"]]
    o += ["", "---", "", "Generated by `scale graph upgrade`. Nothing was written unless `--write` was given; the graph "
          f"stays valid at {r['from']} either way."]
    return "\n".join(o) + "\n"
