"""Knowledge-graph structural validator (Layer 1). Mechanical, per-file, exit-code-driven.

Validates per-paper KG *fragments* (fragments/paper_<id>.json) OR the consolidated *master*
graph (graph.json, NetworkX node-link JSON: {"directed":..., "nodes":[...], "links":[...]})
against the GIVEN schema (schema.json, written by the user — never induced). Exit code 0 if
everything passes; non-zero on any failure.

This is the ONE place the skill insists on a separate Python process: the extraction subagent
and the validator must be DIFFERENT processes, so a subagent cannot fabricate a passing
"--- summary:" line. The subagent pastes this script's literal stdout into its report.

Checks
------
  * JSON readable; fragment has paper_id; nodes/edges are lists.
  * node.label in schema.node_types or a builtin (Publication, Figure).
  * node properties: required present, type match, numeric bounds, allowed values (enum). A property is
    declared either as a hint string ("number (0-100)", "string (required)") or as an object
    {"type": "number", "required": true, "min": 0, "max": 100, "enum": [...], "unit": "%"}.
  * Figure nodes: props.path present AND the PNG exists on disk (resolved relative to the KG
    output dir = schema.json's parent). A recorded-but-missing figure is an ERROR.
  * edge.type in schema.edge_types or a builtin (REPORTED_IN, DEPICTS, MENTIONS, CITES).
  * edge endpoints resolve to real node ids (no dangling edges).
  * domain (non-builtin) edges carry provenance (_evidence/_citation/source_paper_id) -> WARN if absent.

Usage
-----
    python validate_kg.py <path>             # a fragment file, a fragments/ dir, a kg dir, or graph.json
    python validate_kg.py --strict <path>    # warnings become errors (release pass)
    python validate_kg.py --schema <schema.json> <path>
    python validate_kg.py --jobs N <dir>     # N-way parallel over fragment files (default 1)
"""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

BUILTIN_NODE_LABELS = {"Publication", "Figure"}
BUILTIN_EDGE_TYPES = {"REPORTED_IN", "DEPICTS", "MENTIONS", "CITES"}
EVIDENCE_OPTIONAL_EDGES = set(BUILTIN_EDGE_TYPES)
# Provenance/merge fields the KG format always carries on nodes — allowed without being
# declared in the schema (see references/kg_format.md). Any OTHER non-"_" extra still warns.
IMPLICIT_PROPS = {"name", "source_paper_ids", "name_variants", "evidence_count"}
SKIP_NAMES = {"schema.json", "manifest.json", "state.json", "alias_candidates.json", "alias_map.json", "hubs.json"}

_PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_UPSNAKE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


def naming_warnings(labels, etypes):
    """Warn on labels/edge-types that break the naming convention (references/kg_format.md):
    PascalCase node labels, UPPER_SNAKE_CASE edge types. Deduplicated to at most two summary
    lines, so a conforming graph stays silent and only real drift surfaces."""
    w = []
    bad_l = sorted({l for l in labels if l and l not in BUILTIN_NODE_LABELS and not _PASCAL.match(l)})
    if bad_l:
        w.append("naming: node labels not PascalCase: " + ", ".join(bad_l[:8]))
    bad_e = sorted({t for t in etypes if t and t not in BUILTIN_EDGE_TYPES and not _UPSNAKE.match(t)})
    if bad_e:
        w.append("naming: edge types not UPPER_SNAKE_CASE: " + ", ".join(bad_e[:8]))
    return w


def find_schema(start: Path):
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    for parent in [cur] + list(cur.parents):
        cand = parent / "schema.json"
        if cand.exists():
            return cand
    return None


def type_check(value, expected: str) -> bool:
    expected = expected.strip().lower()
    if expected.startswith("string"):
        return isinstance(value, str)
    if expected.startswith("integer") or expected.startswith("int"):
        return isinstance(value, int) and not isinstance(value, bool)
    if expected.startswith("number") or expected.startswith("float"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected.startswith("array") or expected.startswith("list"):
        return isinstance(value, list)
    if expected.startswith("object") or expected.startswith("dict"):
        return isinstance(value, dict)
    if expected.startswith("boolean") or expected.startswith("bool"):
        return isinstance(value, bool)
    return True


def parse_type_hint(hint: str) -> dict:
    paren = re.search(r"\(([^)]*)\)", hint)
    quals = (paren.group(1) if paren else hint).lower()
    is_optional = re.search(r"\boptional\b", quals) is not None
    is_required = re.search(r"\brequired\b", quals) is not None
    out = {"required": is_required and not is_optional}
    out["type"] = hint.split("(")[0].split(" ")[0].strip().lower()
    enum = re.search(r"one of\s*:?\s*([^)]*)", hint, re.IGNORECASE)
    if enum:
        out["enum"] = [x.strip() for x in re.split(r"[|,/]", enum.group(1)) if x.strip()]
    bound = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:to|\.\.|[-–—])\s*(-?\d+(?:\.\d+)?)", hint, re.IGNORECASE)
    if bound and not enum:
        out["min"], out["max"] = float(bound.group(1)), float(bound.group(2))
    return out


def prop_spec(hint) -> dict:
    """Hint string or property object -> {type, required, min?, max?, enum?}."""
    if isinstance(hint, dict):
        out = {"type": str(hint.get("type") or "string").lower(), "required": bool(hint.get("required"))}
        for k in ("min", "max"):
            if isinstance(hint.get(k), (int, float)):
                out[k] = float(hint[k])
        if isinstance(hint.get("enum"), list):
            out["enum"] = [str(x) for x in hint["enum"]]
        if "min" in out and "max" not in out:
            out["max"] = float("inf")
        if "max" in out and "min" not in out:
            out["min"] = float("-inf")
        return out
    if isinstance(hint, str):
        return parse_type_hint(hint)
    return {"type": "any", "required": False}


def validate_props(props, prop_schema, label, node_id, strict):
    errors, warnings = [], []
    if not isinstance(props, dict):
        errors.append(f"node {node_id} ({label}): props is not an object")
        return errors, warnings
    for fld, hint in (prop_schema or {}).items():
        info = prop_spec(hint)
        present = fld in props and props[fld] is not None
        if not present:
            if info["required"]:
                errors.append(f"node {node_id} ({label}): missing required property '{fld}'")
            continue
        val = props[fld]
        if not type_check(val, info["type"]):
            errors.append(f"node {node_id} ({label}): property '{fld}' type mismatch "
                          f"(expected {info['type']}, got {type(val).__name__})")
            continue
        if "min" in info and isinstance(val, (int, float)) and not isinstance(val, bool):
            if val < info["min"] or val > info["max"]:
                errors.append(f"node {node_id} ({label}): property '{fld}'={val} out of bounds "
                              f"[{info['min']}, {info['max']}]")
        if info.get("enum"):
            allowed = {e.lower() for e in info["enum"]}
            vals = val if isinstance(val, list) else [val]
            bad = [v for v in vals if str(v).lower() not in allowed]
            if bad:
                errors.append(f"node {node_id} ({label}): property '{fld}' value {bad[0]!r} not in the allowed values "
                              f"{info['enum'][:12]} (use null / omit it, or flag _pending_vocab_addition)")
    known = set(prop_schema or {}) | IMPLICIT_PROPS
    extra = {k for k in props if not k.startswith("_") and k not in known}
    if extra:
        warnings.append(f"node {node_id} ({label}): properties not in schema: {sorted(extra)}")
    return errors, warnings


def validate_node(node, schema, schema_dir, strict):
    errors, warnings = [], []
    nid = node.get("id")
    label = node.get("label")
    if not nid:
        errors.append("node missing 'id'")
    if not label:
        errors.append(f"node {nid}: missing 'label'")
        return errors, warnings, nid
    node_types = schema.get("node_types", {})
    if label not in node_types and label not in BUILTIN_NODE_LABELS:
        errors.append(f"node {nid}: label '{label}' not in schema node_types "
                      f"{sorted(node_types)[:6]} or builtins {sorted(BUILTIN_NODE_LABELS)}")
    props = node.get("props", {})
    if label == "Figure":
        path_str = props.get("path") if isinstance(props, dict) else None
        if not path_str:
            errors.append(f"node {nid} (Figure): missing 'path'")
        else:
            abs_path = Path(path_str) if Path(path_str).is_absolute() else (schema_dir / path_str)
            if not abs_path.exists():
                errors.append(f"node {nid} (Figure): file_missing: {path_str}")
    elif label != "Publication":
        prop_schema = node_types.get(label, {}).get("properties", {})
        e, w = validate_props(props, prop_schema, label, nid, strict)
        errors += e
        warnings += w
    return errors, warnings, nid


def validate_edge(edge, schema, node_ids, strict, labels_of=None):
    errors, warnings = [], []
    etype = edge.get("type")
    start = edge.get("start") or edge.get("source")
    end = edge.get("end") or edge.get("target")
    edge_types = schema.get("edge_types", {})
    if not etype:
        errors.append(f"edge missing 'type' ({start}->{end})")
    elif etype not in edge_types and etype not in BUILTIN_EDGE_TYPES:
        errors.append(f"edge type '{etype}' not in schema edge_types or builtins ({start}->{end})")
    if not start or not end:
        errors.append(f"edge {etype}: missing start/end")
    else:
        if start not in node_ids:
            errors.append(f"edge {etype}: dangling start '{start}' (no such node)")
        if end not in node_ids:
            errors.append(f"edge {etype}: dangling end '{end}' (no such node)")
    props = edge.get("props") or {}
    spec = edge_types.get(etype) if isinstance(edge_types.get(etype), dict) else None
    if spec and labels_of and start in labels_of and end in labels_of:
        def allowed(v):
            return set(v) if isinstance(v, list) else ({v} if v else set())
        fr, to = allowed(spec.get("from")), allowed(spec.get("to"))
        if fr and labels_of[start] not in fr | BUILTIN_NODE_LABELS:
            warnings.append(f"edge {etype}: source {start} is a {labels_of[start]}, schema expects {sorted(fr)}")
        if to and labels_of[end] not in to | BUILTIN_NODE_LABELS:
            warnings.append(f"edge {etype}: target {end} is a {labels_of[end]}, schema expects {sorted(to)}")
    if etype and etype not in EVIDENCE_OPTIONAL_EDGES:
        if not any(k in props for k in ("_evidence", "_citation", "evidence", "source_paper_id", "source_paper_ids")):
            warnings.append(f"edge {etype} ({start}->{end}): no provenance (_evidence/_citation/source_paper_id)")
    return errors, warnings


def validate_fragment(rec, schema, schema_dir, strict):
    errors, warnings = [], []
    if "paper_id" not in rec:
        errors.append("fragment missing 'paper_id'")
    nodes = rec.get("nodes", [])
    edges = rec.get("edges", [])
    if not isinstance(nodes, list):
        errors.append("'nodes' is not a list")
        nodes = []
    if not isinstance(edges, list):
        errors.append("'edges' is not a list")
        edges = []
    node_ids = set()
    labels_of = {}
    for n in nodes:
        e, w, nid = validate_node(n, schema, schema_dir, strict)
        errors += e
        warnings += w
        if nid:
            node_ids.add(nid)
            labels_of[nid] = n.get("label")
    for ed in edges:
        e, w = validate_edge(ed, schema, node_ids, strict, labels_of)
        errors += e
        warnings += w
    warnings += naming_warnings([n.get("label") for n in nodes], [ed.get("type") for ed in edges])
    paper = rec.get("paper") or {}
    if not isinstance(paper, dict) or not (paper.get("title") or paper.get("doi")):
        warnings.append("fragment has no 'paper' block with doi/title (the merge needs it to name the Publication)")
    if not nodes:
        warnings.append("fragment has 0 nodes (nothing extracted from this paper)")
    return errors, warnings


def validate_graph_json(data, schema, schema_dir, strict):
    """Validate a node-link master graph (NetworkX node_link_data shape)."""
    errors, warnings = [], []
    nodes = data.get("nodes", [])
    links = data.get("links")
    if links is None:
        links = data.get("edges", [])  # networkx>=3.4 renamed the default key
    if not isinstance(nodes, list):
        return ["graph.json 'nodes' is not a list"], []
    if not isinstance(links, list):
        return ["graph.json 'links'/'edges' is not a list"], []
    node_ids = set()
    for n in nodes:
        shim = {"id": n.get("id"), "label": n.get("label"), "props": n.get("props", {})}
        e, w, nid = validate_node(shim, schema, schema_dir, strict)
        errors += e
        warnings += w
        if nid:
            node_ids.add(nid)
    for l in links:
        shim = {"type": l.get("type"), "start": l.get("source"), "end": l.get("target"), "props": l.get("props", {})}
        e, w = validate_edge(shim, schema, node_ids, strict)
        errors += e
        warnings += w
    warnings += naming_warnings([n.get("label") for n in nodes], [l.get("type") for l in links])
    return errors, warnings


def validate_target_file(path: Path, schema: dict, schema_dir: Path, strict: bool):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        return False, [f"unreadable JSON: {e}"], []
    is_graph = isinstance(data, dict) and "paper_id" not in data and \
        ("links" in data or "directed" in data or "multigraph" in data)
    if is_graph:
        errs, warns = validate_graph_json(data, schema, schema_dir, strict)
    else:
        errs, warns = validate_fragment(data, schema, schema_dir, strict)
    if strict and warns:
        errs = errs + warns
        warns = []
    return (not errs), errs, warns


def _worker(args_tuple):
    f, schema, schema_dir, strict = args_tuple
    ok, errs, warns = validate_target_file(f, schema, schema_dir, strict)
    return (str(f), ok, errs, warns)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("target", type=Path, help="fragment file, fragments/ dir, kg dir, or graph.json")
    p.add_argument("--strict", action="store_true", help="warnings become errors (release pass)")
    p.add_argument("--schema", type=Path, default=None, help="explicit path to schema.json")
    p.add_argument("--jobs", type=int, default=1, help="parallel workers (default 1; -1 = all cores)")
    args = p.parse_args()

    schema_path = args.schema or find_schema(args.target)
    if not schema_path or not schema_path.exists():
        print(f"FAIL: could not find schema.json near {args.target} (pass --schema)", file=sys.stderr)
        return 2
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"FAIL: schema.json unreadable: {e}", file=sys.stderr)
        return 2
    schema_dir = schema_path.parent

    if args.target.is_file():
        files = [args.target]
    else:
        # Validate exactly the fragments + the master graph.json — never stray json
        # (reports, query subgraphs, manifests) that live in the same tree.
        skip_parts = {"rejected", "superseded", "errors", "reports", "views"}
        if args.target.name == "fragments":
            files = sorted(args.target.glob("*.json"))
        else:
            files = sorted((args.target / "fragments").glob("*.json"))
        gj = args.target / "graph.json"
        if gj.exists():
            files.append(gj)
        files = [
            f for f in files
            if f.name not in SKIP_NAMES
            and not f.name.endswith(".tmp")
            and not (set(f.relative_to(args.target).parts) & skip_parts)
        ]

    if not files:
        print(f"PASS: no fragments or graph.json found under {args.target}", file=sys.stderr)
        return 0

    jobs = args.jobs if args.jobs > 0 else (os.cpu_count() or 1)
    results = []
    if jobs == 1 or len(files) <= 1:
        for f in files:
            results.append((str(f), *validate_target_file(f, schema, schema_dir, args.strict)))
    else:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            tasks = [(f, schema, schema_dir, args.strict) for f in files]
            for r in ex.map(_worker, tasks):
                results.append(r)

    results.sort(key=lambda r: r[0])
    n_pass = n_fail = n_warn = 0
    for path, ok, errs, warns in results:
        name = Path(path).name
        if ok and not warns:
            print(f"PASS {name}")
            n_pass += 1
        elif ok:
            print(f"PASS {name} (warnings: {len(warns)})")
            for w in warns:
                print(f"  WARN {w}")
            n_pass += 1
            n_warn += 1
        else:
            print(f"FAIL {name}")
            for e in errs:
                print(f"  ERROR {e}")
            for w in warns:
                print(f"  WARN {w}")
            n_fail += 1
    print(f"--- summary: {n_pass} pass, {n_fail} fail, {n_warn} with warnings (jobs={jobs})")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
