"""Check a GIVEN knowledge-graph schema (schema.json) before any extraction, and print it in readable form.

The schema always comes from the user (a file they wrote, or their document converted faithfully into this format —
never a schema the agent invented). Format: references/schema_format.md; example: examples/schema.catalysis.example.json.

  python3 -I check_schema.py <schema.json>            # errors / warnings + readable summary; exit 0 when usable
  python3 -I check_schema.py <schema.json> --json     # the same as JSON
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_kg import BUILTIN_EDGE_TYPES, BUILTIN_NODE_LABELS, prop_spec

PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
UPSNAKE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")
CHEM_TOKENS = {"pH", "pKa", "Ea", "E0", "Tg", "Tm", "BET", "TOF", "TON"}
TYPES = {"string", "number", "integer", "int", "float", "boolean", "bool", "array", "list", "object", "dict", "any"}
OPTIONAL_KEYS = {"name", "version", "topic", "description", "scope", "record_view", "never_merge", "faithfulness_rules",
                 "extraction_notes", "node_types", "edge_types"}


def check(schema):
    errs, warns = [], []
    if not isinstance(schema, dict):
        return ["schema is not a JSON object"], [], {}
    nts, ets = schema.get("node_types"), schema.get("edge_types")
    if not isinstance(nts, dict) or not nts:
        errs.append("'node_types' must be a non-empty object {Label: {description, properties}}")
        nts = {}
    if not isinstance(ets, dict):
        errs.append("'edge_types' must be an object {EDGE_TYPE: {from, to, description}} (may be empty)")
        ets = {}
    for k in schema:
        if k not in OPTIONAL_KEYS:
            warns.append(f"unknown top-level key {k!r} (ignored)")
    for label, spec in nts.items():
        if label in BUILTIN_NODE_LABELS:
            errs.append(f"node type {label!r} is a builtin (added automatically) — remove it from the schema")
        if not PASCAL.match(label):
            warns.append(f"node type {label!r} is not PascalCase (convention: Catalyst, ActiveSite)")
        if not isinstance(spec, dict):
            errs.append(f"node type {label!r} must be an object")
            continue
        props = spec.get("properties") or {}
        if not isinstance(props, dict):
            errs.append(f"{label}.properties must be an object")
            continue
        if not props:
            warns.append(f"{label} has no properties (nodes will carry only a name)")
        for pname, hint in props.items():
            if pname.startswith("_"):
                errs.append(f"{label}.{pname}: names starting with '_' are reserved for provenance")
            if re.search(r"[A-Z]", pname) and pname not in CHEM_TOKENS and \
                    not re.search(r"_(eV|pH|V|K|C|Pa|M|mM|mA|A|W|J|Hz|nm|um|mm|cm2|cm|g|mg|L|mL|h|s|min|wt|at)\b", pname):
                warns.append(f"{label}.{pname}: property names are snake_case (a unit suffix such as _eV may keep its case)")
            info = prop_spec(hint)
            if info.get("type") not in TYPES:
                errs.append(f"{label}.{pname}: unknown type {info.get('type')!r} (use string, number, integer, boolean, array, object)")
            if isinstance(hint, dict) and hint.get("enum") is not None and not isinstance(hint.get("enum"), list):
                errs.append(f"{label}.{pname}: enum must be a list")
    for et, spec in ets.items():
        if et in BUILTIN_EDGE_TYPES:
            errs.append(f"edge type {et!r} is a builtin — remove it from the schema")
        if not UPSNAKE.match(et):
            warns.append(f"edge type {et!r} is not UPPER_SNAKE_CASE (convention: HAS_METRIC, CATALYZES)")
        if not isinstance(spec, dict):
            errs.append(f"edge type {et!r} must be an object with from / to")
            continue
        for end in ("from", "to"):
            v = spec.get(end)
            labels = v if isinstance(v, list) else [v] if v else []
            if not labels:
                warns.append(f"{et}.{end} is not given (any node type will be accepted)")
            for lab in labels:
                if lab not in nts and lab not in BUILTIN_NODE_LABELS:
                    errs.append(f"{et}.{end} refers to {lab!r}, which is not a node type in the schema")
    rv = schema.get("record_view")
    if rv:
        if not isinstance(rv, dict) or rv.get("label") not in nts:
            errs.append("record_view.label must name a node type (the row of tables/records.csv)")
        for j in (rv or {}).get("join") or []:
            if j.get("edge") not in ets:
                errs.append(f"record_view.join edge {j.get('edge')!r} is not an edge type")
    for k in ("never_merge", "faithfulness_rules"):
        if schema.get(k) is not None and not isinstance(schema.get(k), list):
            errs.append(f"{k} must be a list of sentences")
    summary = {
        "name": schema.get("name"), "version": schema.get("version") or "1",
        "topic": schema.get("topic"), "scope": schema.get("scope"),
        "node_types": {l: {"properties": list((s or {}).get("properties", {}) or {}),
                           "required": [p for p, h in ((s or {}).get("properties", {}) or {}).items() if prop_spec(h).get("required")]}
                       for l, s in nts.items() if isinstance(s, dict)},
        "edge_types": {e: f"{(s or {}).get('from')} -> {(s or {}).get('to')}" for e, s in ets.items() if isinstance(s, dict)},
        "record_view": rv, "never_merge": schema.get("never_merge") or [],
        "faithfulness_rules": schema.get("faithfulness_rules") or [],
    }
    return errs, warns, summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("schema", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        schema = json.loads(a.schema.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(json.dumps({"ok": False, "errors": [f"cannot read {a.schema}: {e}"]}))
        return 1
    errs, warns, summary = check(schema)
    res = {"ok": not errs, "errors": errs, "warnings": warns, "summary": summary}
    if a.json:
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0 if not errs else 1
    print(f"Schema {summary.get('name') or a.schema.stem} v{summary.get('version')}: {len(summary['node_types'])} node types, "
          f"{len(summary['edge_types'])} edge types")
    if summary.get("topic"):
        print(f"Topic: {summary['topic']}")
    if summary.get("scope"):
        print(f"Scope: {summary['scope']}")
    for l, v in summary["node_types"].items():
        req = f" (required: {', '.join(v['required'])})" if v["required"] else ""
        print(f"  {l}: {', '.join(v['properties']) or '—'}{req}")
    for e, v in summary["edge_types"].items():
        print(f"  {e}: {v}")
    for w in warns:
        print("WARN " + w)
    for e in errs:
        print("ERROR " + e)
    print(f"--- {'OK' if not errs else 'NOT USABLE'}: {len(errs)} errors, {len(warns)} warnings")
    return 0 if not errs else 1


if __name__ == "__main__":
    raise SystemExit(main())
