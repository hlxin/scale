"""Result entries: the values an experiment reports as its results, and what identifies each one.

An entry of ``result_values`` (kernel, Experiment; scale-catal 0.4.0 on) is a value object that names its ``variable``
(a Variable, whose ``quantity_kind`` gives its contract) and has an ``id``. What tells two results of one record apart
is their identity (:func:`signature`): the variable, the target (or an ``unresolved_target``), the producer
(``produced_by``: the assay or analysis, whose timing is the result's interval), the phase, the stream, the basis, the
definition and the normalization. Two entries that nothing tells apart are an ambiguous repetition: reported, never
averaged.

* **Pointers.** A JSON pointer into a record's props may name a list item by its id instead of its position
  (``/result_values/meoh_yield_gc``, ``/evidence/e3``): :func:`resolve` reads such a step, :func:`item` finds the
  item's position. A record_ref into ``result_values`` names its entry so, never by position (:func:`by_position`), so
  that appending to the list, reordering it, migrating it or filtering it never makes a reference name another result.
* **Entries.** :func:`entries` lists the value objects of a property (one value, the items of a list, the entries of a
  map), each with the pointer a reference names it by (:func:`pointer`).
* **Documents.** :func:`check_document` reports, for a schema that declares ``result_values``: an entry without an id
  or a variable, or that states a number or a text without the evidence_ids that state it, or of a kind counted for a
  species without a target or an unresolved_target (errors); an id that is not snake_case or repeats in its record, and
  a value with both a target and an unresolved_target (errors); and an ambiguous repetition (a warning), in
  ``result_values`` and in the per-product lists (faradaic_efficiency, ...).
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

RESULTS = "result_values"
ID = re.compile(r"^[a-z][a-z0-9_]*$")            # snake_case, so never only digits (a position)
VALUE_STATUS = ("present", "not_reported", "not_measured", "not_applicable", "below_detection_limit",
                "below_quantification_limit")
STATED = ("present", "below_detection_limit", "below_quantification_limit")      # an entry that states something
# what tells two results of one record apart (the interval is the producer's timing, else the record's own)
IDENTITY = ("variable", "target", "unresolved_target", "produced_by", "phase", "stream", "basis", "definition",
            "normalized_by", "relative_to")
# the fields of an entry that name a record, which a query's field step follows (normalized_by names one as a record_ref)
REF_FIELDS = ("target", "variable", "produced_by", "calibration", "ref_value", "normalized_by", "relative_to")


# ------------------------------------------------------------------------------------------ pointers
def steps(path: str) -> list[str]:
    """The steps of a JSON pointer, unescaped."""
    return [p.replace("~1", "/").replace("~0", "~") for p in str(path).split("/")[1:]]


def item(items: list, step: str) -> int | None:
    """The position of the list item a pointer step names: a position, or the id of exactly one item."""
    if step.isdigit():
        return int(step) if int(step) < len(items) else None
    hits = [i for i, x in enumerate(items) if isinstance(x, dict) and x.get("id") == step]
    return hits[0] if len(hits) == 1 else None


def resolve(props: Any, path: str) -> tuple[bool, Any]:
    """(whether ``path`` resolves in ``props``, what it names): a key of a map, or a list item by position or id."""
    cur = props
    for step in steps(path):
        if isinstance(cur, dict) and step in cur:
            cur = cur[step]
        elif isinstance(cur, list) and item(cur, step) is not None:
            cur = cur[item(cur, step)]
        else:
            return False, None
    return True, cur


def by_position(path: Any) -> bool:
    """Whether a pointer names an entry of result_values by its position, which a reference never does."""
    s = steps(path) if isinstance(path, str) else []
    return len(s) >= 2 and s[0] == RESULTS and s[1].isdigit()


def _esc(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def pointer(prop: str, key: Any, x: Any) -> str:
    """The pointer a reference names an entry by: ``/prop`` for a single value, ``/prop/<id>`` for a list item with an
    id, ``/prop/<position>`` for one without, ``/prop/<key>`` for a map entry."""
    if key is None:
        return f"/{_esc(prop)}"
    if isinstance(key, int) and isinstance(x, dict) and isinstance(x.get("id"), str) and ID.match(x["id"]):
        return f"/{_esc(prop)}/{x['id']}"
    return f"/{_esc(prop)}/{_esc(str(key))}"


def entries(v: Any) -> Iterator[tuple[Any, dict]]:
    """(key, value object) of a property: (None, the value) for one value, (position, item) for a list, (key, entry)
    for a map; anything that is not a value object is skipped."""
    if isinstance(v, dict) and v.get("status") in VALUE_STATUS:
        yield None, v
    elif isinstance(v, list):
        for i, x in enumerate(v):
            if isinstance(x, dict) and x.get("status") in VALUE_STATUS:
                yield i, x
    elif isinstance(v, dict):
        for k in sorted(v, key=str):
            if isinstance(v[k], dict) and v[k].get("status") in VALUE_STATUS:
                yield k, v[k]


def withheld(x: dict) -> bool:
    """A value the view does not share (``scale graph filter``): its qualifiers are gone with it."""
    return x.get("status") == "not_reported" and x.get("missing_reason") == "withheld"


def signature(x: dict) -> str:
    """What identifies a result among its record's: its identity fields as JSON (the interval is its producer's)."""
    return json.dumps({k: x.get(k) for k in IDENTITY if x.get(k) is not None}, sort_keys=True, ensure_ascii=False)


def repeated(items: list[tuple[Any, dict]]) -> list[list[Any]]:
    """The groups of entries (their keys) that nothing tells apart: one signature, more than one entry. A withheld entry
    is never counted (it keeps no qualifiers)."""
    groups: dict[str, list[Any]] = {}
    for key, x in items:
        if not withheld(x):
            groups.setdefault(signature(x), []).append(key)
    return [keys for keys in groups.values() if len(keys) > 1]


def values_in(obj: Any, path: str = "") -> Iterator[tuple[str, dict]]:
    """Every value object in a props tree, with its pointer (evidence and stewardship aside)."""
    if isinstance(obj, dict):
        if obj.get("status") in VALUE_STATUS and path:
            yield path, obj
            return
        for k, x in obj.items():
            if k not in ("evidence", "stewardship"):
                yield from values_in(x, f"{path}/{_esc(str(k))}")
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            yield from values_in(x, f"{path}/{i}")


def name(path: str, x: dict) -> str:
    """A value's place for a message: its pointer as dotted steps, a list item named by its id when it has one."""
    parts = path[1:].split("/")
    if parts and parts[-1].isdigit() and isinstance(x.get("id"), str) and x["id"]:
        parts[-1] = x["id"]
    return ".".join(parts)


# ------------------------------------------------------------------------------------------ documents
def check_document(doc: dict, spec: dict, rep) -> None:
    """The result-entry diagnostics of a document (the module docstring); nothing for a schema without result_values."""
    fields = (spec.get("value") or {}).get("fields") or {}
    if "id" not in fields:
        return
    from . import quantities
    c = quantities.contracts(spec)
    variables = quantities.variable_kinds(doc)
    narrowed = set(spec.get("context_targets") or {})
    nodes = [n for n in doc.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)]
    links = [e for e in doc.get("links") or [] if isinstance(e, dict) and isinstance(e.get("id"), str)]

    def counted_for(kind: str | None) -> bool:      # a kind compared by a context a domain narrows (a species)
        return c is not None and kind in c.kinds and any(e["context"] in narrowed for e in c.kinds[kind]["compare_by"])

    for r in nodes + links:
        props = r.get("props") if isinstance(r.get("props"), dict) else {}
        rid = r["id"]
        ids: dict[str, list[str]] = {}
        for path, v in values_in(props):
            where = name(path, v)
            if "id" in v:
                if not isinstance(v["id"], str) or not ID.match(v["id"]):
                    rep.add("error", rid, f"{where}: id {v['id']!r} is not snake_case (a letter, then letters, digits and "
                                          "underscores; never only digits, which a pointer reads as a position)")
                else:
                    ids.setdefault(v["id"], []).append(where)
            if v.get("target") is not None and v.get("unresolved_target") is not None:
                rep.add("error", rid, f"{where}: target and unresolved_target do not go together (a value refers to one "
                                      "record, or to what the source names without identifying it)")
        for x, places in sorted(ids.items()):
            if len(places) > 1:
                rep.add("error", rid, f"id {x!r} names {len(places)} values of the record ({', '.join(places)}): an id "
                                      "names one value")
        if r.get("label") is None or RESULTS not in props:
            continue
        lst = props[RESULTS]
        if not isinstance(lst, list):
            continue                                    # the type check reports it
        items = list(entries(lst))
        for i, x in items:
            where = f"{RESULTS}.{x['id']}" if isinstance(x.get("id"), str) and x["id"] else f"{RESULTS}.{i}"
            if withheld(x):
                continue
            if not x.get("id"):
                rep.add("error", rid, f"{where}: a result entry has an id (a record_ref names it /{RESULTS}/<id>)")
            if not x.get("variable"):
                rep.add("error", rid, f"{where}: a result entry names its variable (a Variable, whose quantity_kind gives "
                                      "its contract)")
            if x.get("status") in STATED and not x.get("evidence_ids"):
                rep.add("error", rid, f"{where}: a result entry that states a value names the evidence items that state "
                                      "it (evidence_ids), so that an answer cites its own evidence")
            kind = variables.get(x.get("variable")) if isinstance(x.get("variable"), str) else None
            if counted_for(kind) and x.get("target") is None and x.get("unresolved_target") is None:
                rep.add("error", rid, f"{where}: a {kind} is counted for a species: name it (target) or say the source does "
                                      "not identify it (unresolved_target)")
        for keys in repeated(items):
            names = [f"{RESULTS}.{lst[k].get('id') or k}" for k in keys]
            rep.add("warning", rid, f"{', '.join(names)}: {len(keys)} results that nothing tells apart (one variable, "
                                    "target, producer, phase, stream, basis, definition and normalization): an ambiguous "
                                    "repetition, never averaged; name the assay each came from (produced_by), or record "
                                    "one value with its replicates and uncertainty")
    if c is None:
        return
    for n in nodes:                                     # the per-product lists: a repeated product, told apart by nothing
        props = n.get("props") if isinstance(n.get("props"), dict) else {}
        for prop, v in props.items():
            if prop == RESULTS or not isinstance(v, list):
                continue
            kind = quantities.binding(spec, n, prop)[0]
            if not counted_for(kind):
                continue
            for keys in repeated(list(entries(v))):
                rep.add("warning", n["id"], f"{', '.join(f'{prop}.{k}' for k in keys)}: {len(keys)} entries for one "
                                            "product that nothing tells apart (producer, phase, stream, basis, "
                                            "normalization): an ambiguous repetition, never averaged")
