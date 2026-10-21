"""Checks people made of records against their sources (``graph.checks``, the kernel's ``record_check``).

A check says that a named person compared some records with their source, when, what against what, and what they
found: how many recorded fields they compared, how many did not match and how many the records left out (the
extraction's precision and recall, which TRACE-AI asks of data extracted by AI agents). It approves nothing; a
person's review of the pull request does that.

- :func:`check_document` holds a document's checks to the kernel's rules: they name records of the graph, counts that
  add up, a sample's fraction and seed, and acknowledgements on records the check covers; a record a newer record
  REVISES is not covered (advisory).
- :func:`acknowledge` runs last in validation: a warning an acknowledgement matches (on its record, by a text only that
  warning has) is listed apart, with who acknowledged it, when and why, and no longer counts as open; an
  acknowledgement that matches no warning is reported, so that one never outlives the warning it was written for.
- :func:`prune` keeps a check to the records a view or a subset holds (``scale graph filter``, a graph of some
  sources): no id of a record left out stays in the header (an acknowledgement or a check whose text names one goes),
  a check with no record left, or whose checker is left out, goes, and a check that loses records loses its counts,
  which were over all of them.
- :func:`quality` gives a check's precision and recall from its counts.
"""

from __future__ import annotations

from typing import Any

ACK_KEYS = ("record", "warning", "reason")
COUNTS = ("fields_checked", "fields_wrong", "fields_missed")
TEXTS = ("scope", "note", "tolerance")          # a check's free text, which may name a record


def checks_of(graph: Any) -> list[dict]:
    """The checks of a graph's header that are objects (anything else is reported by the typed validation)."""
    cs = (graph or {}).get("checks") if isinstance(graph, dict) else None
    return [c for c in cs if isinstance(c, dict)] if isinstance(cs, list) else []


def _list(v: Any) -> list:
    return v if isinstance(v, list) else []


def records_of(c: dict) -> list[str]:
    """The ids a check names (a malformed list is reported by the typed validation, and read as naming none)."""
    return [r for r in _list(c.get("records")) if isinstance(r, str)]


def acknowledgements_of(c: dict) -> list[dict]:
    return [a for a in _list(c.get("acknowledged")) if isinstance(a, dict)]


def _count(c: dict, k: str) -> int | None:
    v = c.get(k)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def quality(c: dict) -> dict:
    """Precision and recall of the extraction a check measured, each from its own counts: precision = right / checked,
    recall = right / (right + missed), where right = checked - wrong. None where the counts do not give one."""
    checked, wrong, missed = (_count(c, k) for k in COUNTS)
    out: dict = {"precision": None, "recall": None}
    if checked is None or wrong is None or not 0 <= wrong <= checked:
        return out
    right = checked - wrong
    if checked:
        out["precision"] = round(right / checked, 4)
    if missed is not None and missed >= 0 and right + missed:
        out["recall"] = round(right / (right + missed), 4)
    return out


def _revised(doc: dict) -> dict[str, list[str]]:
    """Each record that a newer record REVISES, with the records that revise it (a new version REVISES the previous)."""
    out: dict[str, list[str]] = {}
    for e in doc.get("links") or []:
        if isinstance(e, dict) and e.get("type") == "REVISES" and isinstance(e.get("target"), str):
            out.setdefault(e["target"], []).append(str(e.get("source")))
    return out


def check_document(doc: dict, spec: dict, rep) -> None:
    """The kernel's rules for a document's checks, beyond their typed fields (which the validator checks; a field of the
    wrong type is read here as absent, never iterated)."""
    if not isinstance(spec.get("record_check"), dict):
        return
    ids = {r.get("id") for r in [*(doc.get("nodes") or []), *(doc.get("links") or [])] if isinstance(r, dict)}
    revised = _revised(doc)
    for i, c in enumerate(checks_of(doc.get("graph"))):
        where = f"checks[{i}]"
        recs = records_of(c)
        if isinstance(c.get("records"), list) and not recs:
            rep.add("error", "<graph>", f"{where}: a check names the records it covered")
        for r in recs:
            if r not in ids:
                rep.add("error", "<graph>", f"{where}: record {r!r} is not a node or link of this graph")
        if len(set(recs)) != len(recs):
            rep.add("error", "<graph>", f"{where}: records names a record twice")
        counts = {k: _count(c, k) for k in COUNTS}
        for k, v in counts.items():
            if v is not None and v < 0:
                rep.add("error", "<graph>", f"{where}: {k} is a count, not negative")
        if counts["fields_wrong"] is not None and counts["fields_checked"] is None:
            rep.add("error", "<graph>", f"{where}: fields_wrong is counted among fields_checked, which the check states")
        elif None not in (counts["fields_wrong"], counts["fields_checked"]) and counts["fields_wrong"] > counts["fields_checked"]:
            rep.add("error", "<graph>", f"{where}: fields_wrong ({counts['fields_wrong']}) exceeds fields_checked "
                                        f"({counts['fields_checked']})")
        fr = c.get("fraction")
        if isinstance(fr, (int, float)) and not isinstance(fr, bool) and not 0 < fr <= 1:
            rep.add("error", "<graph>", f"{where}: fraction is the share of the records a sample drew, above 0 and at "
                                        "most 1")
        if c.get("selection") in ("sample", "sample_and_flagged") and not ("fraction" in c and "seed" in c):
            rep.add("warning", "<graph>", f"{where}: a sample states its fraction and seed, so that it can be drawn "
                                          "again (`scale review sample`)")
        if c.get("outcome") in ("corrected", "failed") and counts["fields_wrong"] == 0 and not counts["fields_missed"]:
            rep.add("warning", "<graph>", f"{where}: outcome {c['outcome']} with nothing counted wrong or missed; say "
                                          "what was found (fields_wrong, fields_missed or note)")
        for r in recs:
            if r in revised:
                rep.add("warning", "<graph>", f"{where}: {r} was checked, and {', '.join(sorted(revised[r]))} "
                                              "REVISES it: the newer record is not covered by this check")
        for j, a in enumerate(_list(c.get("acknowledged"))):
            at = f"{where}.acknowledged[{j}]"
            if not isinstance(a, dict):
                continue                                   # reported by the typed validation (a map)
            unknown, missing = sorted(set(a) - set(ACK_KEYS)), [k for k in ACK_KEYS if not a.get(k)]
            if unknown:
                rep.add("error", "<graph>", f"{at}: unknown key(s) {unknown}; an acknowledgement is {{record, warning, "
                                            "reason}}")
            if missing:
                rep.add("error", "<graph>", f"{at}: an acknowledgement names {', '.join(missing)}")
            if isinstance(a.get("record"), str) and a["record"] and a["record"] not in recs:
                rep.add("error", "<graph>", f"{at}: {a['record']} is not among the records this check covers; a person "
                                            "acknowledges a warning on a record they checked")


def acknowledge(doc: dict, rep) -> None:
    """Move each warning an acknowledgement matches to ``rep.acknowledged``, with the check that acknowledged it. Each
    acknowledgement is matched against every warning of the validation (never against what another one left), and must
    match exactly one: one that matches none, or several, is reported and acknowledges nothing. Runs after every other
    check of the validation."""
    warnings = list(rep.warnings)
    moved = []
    for i, c in enumerate(checks_of(doc.get("graph"))):
        recs = set(records_of(c))
        for j, a in enumerate(_list(c.get("acknowledged"))):
            if not isinstance(a, dict) or not all(isinstance(a.get(k), str) and a[k] for k in ACK_KEYS):
                continue                                   # malformed: reported by check_document
            if a["record"] not in recs:
                continue
            at = f"checks[{i}].acknowledged[{j}]"
            hits = [w for w in warnings if w.get("record") == a["record"] and a["warning"] in str(w.get("message"))]
            if not hits:
                rep.add("warning", "<graph>", f"{at}: no warning on {a['record']} contains {a['warning']!r} any more; "
                                              "remove the acknowledgement or update it")
            elif len(hits) > 1:
                rep.add("warning", "<graph>", f"{at}: {len(hits)} warnings on {a['record']} contain {a['warning']!r}; "
                                              "quote enough of one warning that only it has (none is acknowledged)")
            else:
                moved.append((hits[0], a, c, i))
    for w, a, c, i in moved:
        if w in rep.warnings:                           # two acknowledgements of one warning: listed once
            rep.warnings.remove(w)
            rep.acknowledged.append({**w, "reason": a["reason"], "checked_by": c.get("checked_by"),
                                     "checked_on": c.get("checked_on"), "check": i})


def prune(graph: dict, present: set[str], withheld: set[str] | None = None) -> tuple[dict, int]:
    """``graph`` with its checks kept to the records in ``present``; a check with no record left, or whose checker is not
    in ``present``, goes. Nothing of ``withheld`` (the ids of the records left out) stays: an acknowledgement whose
    record is left out or whose text names one goes, and so does a check whose own text (scope, note, tolerance) names
    one. A check that loses records loses its counts, sample fraction and seed (they were over every record it
    checked), and its note says how many it kept. Returns the graph and the number of references removed."""
    if not checks_of(graph):
        return graph, 0
    withheld = withheld or set()

    def names_withheld(text: Any) -> bool:
        return isinstance(text, str) and any(x in text for x in withheld)

    out, removed = [], 0
    for c in graph["checks"]:
        if not isinstance(c, dict):
            out.append(c)
            continue
        recs = records_of(c)
        kept_recs = [r for r in recs if r in present]
        if not kept_recs or c.get("checked_by") not in present or any(names_withheld(c.get(k)) for k in TEXTS):
            removed += max(len(recs), 1)
            continue
        kept = dict(c, records=kept_recs)
        acks = [a for a in acknowledgements_of(c)
                if a.get("record") in kept_recs and not any(names_withheld(a.get(k)) for k in ACK_KEYS)]
        removed += len(_list(c.get("acknowledged"))) - len(acks)
        if acks:
            kept["acknowledged"] = acks
        else:
            kept.pop("acknowledged", None)
        lost = len(recs) - len(kept_recs)
        if lost:
            removed += lost
            for k in (*COUNTS, "fraction", "seed", "selection"):
                kept.pop(k, None)
            said = (f"this view keeps {len(kept_recs)} of the {len(recs)} records the check covered; its counts, which "
                    "were over all of them, are left out")
            kept["note"] = f"{kept['note']} ({said})" if kept.get("note") else said
        out.append(kept)
    graph = dict(graph)
    if out:
        graph["checks"] = out
    else:
        graph.pop("checks")
    return graph, removed


__all__ = ["ACK_KEYS", "COUNTS", "checks_of", "records_of", "quality", "check_document", "acknowledge", "prune"]
