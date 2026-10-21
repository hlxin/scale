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
  sources): no id of a record left out stays in the header, and a check with no record left, or whose checker is left
  out, goes.
- :func:`quality` gives a check's precision and recall from its counts.
"""

from __future__ import annotations

from typing import Any

ACK_KEYS = ("record", "warning", "reason")


def checks_of(graph: Any) -> list[dict]:
    """The checks of a graph's header that are objects (anything else is reported by the typed validation)."""
    cs = (graph or {}).get("checks") if isinstance(graph, dict) else None
    return [c for c in cs if isinstance(c, dict)] if isinstance(cs, list) else []


def _count(c: dict, k: str) -> int | None:
    v = c.get(k)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def quality(c: dict) -> dict:
    """Precision and recall of the extraction a check measured: precision = 1 - wrong / checked; recall = right /
    (right + missed). None where the counts do not give it."""
    checked, wrong, missed = _count(c, "fields_checked"), _count(c, "fields_wrong"), _count(c, "fields_missed")
    out: dict = {"precision": None, "recall": None}
    if checked and wrong is not None and 0 <= wrong <= checked:
        out["precision"] = round(1 - wrong / checked, 4)
        if missed is not None and missed >= 0 and (checked - wrong + missed):
            out["recall"] = round((checked - wrong) / (checked - wrong + missed), 4)
    return out


def _revised(doc: dict) -> dict[str, list[str]]:
    """Each record that a newer record REVISES, with the records that revise it (a new version REVISES the previous)."""
    out: dict[str, list[str]] = {}
    for e in doc.get("links") or []:
        if isinstance(e, dict) and e.get("type") == "REVISES" and isinstance(e.get("target"), str):
            out.setdefault(e["target"], []).append(str(e.get("source")))
    return out


def check_document(doc: dict, spec: dict, rep) -> None:
    """The kernel's rules for a document's checks, beyond their typed fields (which the validator checks)."""
    if not isinstance(spec.get("record_check"), dict):
        return
    ids = {r.get("id") for r in [*(doc.get("nodes") or []), *(doc.get("links") or [])] if isinstance(r, dict)}
    revised = _revised(doc)
    for i, c in enumerate(checks_of(doc.get("graph"))):
        where = f"checks[{i}]"
        recs = [r for r in c.get("records") or [] if isinstance(r, str)]
        if "records" in c and not recs:
            rep.add("error", "<graph>", f"{where}: a check names the records it covered")
        for r in recs:
            if r not in ids:
                rep.add("error", "<graph>", f"{where}: record {r!r} is not a node or link of this graph")
        if len(set(recs)) != len(recs):
            rep.add("error", "<graph>", f"{where}: records names a record twice")
        counts = {k: _count(c, k) for k in ("fields_checked", "fields_wrong", "fields_missed")}
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
        acks = c.get("acknowledged")
        for j, a in enumerate(acks if isinstance(acks, list) else []):
            at = f"{where}.acknowledged[{j}]"
            if not isinstance(a, dict):
                continue
            unknown, missing = sorted(set(a) - set(ACK_KEYS)), [k for k in ACK_KEYS if not a.get(k)]
            if unknown:
                rep.add("error", "<graph>", f"{at}: unknown key(s) {unknown}; an acknowledgement is {{record, warning, "
                                            "reason}}")
            if missing:
                rep.add("error", "<graph>", f"{at}: an acknowledgement names {', '.join(missing)}")
            if a.get("record") and a["record"] not in recs:
                rep.add("error", "<graph>", f"{at}: {a['record']} is not among the records this check covers; a person "
                                            "acknowledges a warning on a record they checked")


def acknowledge(doc: dict, rep) -> None:
    """Move each warning an acknowledgement matches to ``rep.acknowledged``, with the check that acknowledged it;
    report an acknowledgement that matches no warning. Runs after every other check of the validation."""
    for i, c in enumerate(checks_of(doc.get("graph"))):
        acks = c.get("acknowledged")
        for j, a in enumerate(acks if isinstance(acks, list) else []):
            if not isinstance(a, dict) or not all(isinstance(a.get(k), str) and a[k] for k in ACK_KEYS):
                continue                                   # malformed: reported by check_document
            if a["record"] not in (c.get("records") or []):
                continue
            def matches(w: dict) -> bool:
                return w.get("record") == a["record"] and a["warning"] in str(w.get("message"))
            hits = [w for w in rep.warnings if matches(w)]
            if not hits:
                if not any(matches(w) for w in rep.acknowledged):      # another check acknowledged it already
                    rep.add("warning", "<graph>", f"checks[{i}].acknowledged[{j}]: no warning on {a['record']} contains "
                                                  f"{a['warning']!r} any more; remove the acknowledgement or update it")
                continue
            for w in hits:
                rep.warnings.remove(w)
                rep.acknowledged.append({**w, "reason": a["reason"], "checked_by": c.get("checked_by"),
                                         "checked_on": c.get("checked_on"), "check": i})


def prune(graph: dict, present: set[str]) -> tuple[dict, int]:
    """``graph`` with its checks kept to the records in ``present`` (and their acknowledgements); a check with no record
    left, or whose checker is not in ``present``, goes. Returns the graph and the number of references removed (a
    check that went counts its records)."""
    if not checks_of(graph):
        return graph, 0
    out, removed = [], 0
    for c in graph["checks"]:
        if not isinstance(c, dict):
            out.append(c)
            continue
        recs = [r for r in c.get("records") or [] if r in present]
        lost = len(c.get("records") or []) - len(recs)
        if not recs or c.get("checked_by") not in present:
            removed += len(c.get("records") or [])
            continue
        kept = dict(c, records=recs)
        if isinstance(c.get("acknowledged"), list):
            acks = [a for a in c["acknowledged"] if not isinstance(a, dict) or a.get("record") in recs]
            removed += len(c["acknowledged"]) - len(acks)
            if acks:
                kept["acknowledged"] = acks
            else:
                kept.pop("acknowledged")
        out.append(kept)
        removed += lost
    graph = dict(graph)
    if out:
        graph["checks"] = out
    else:
        graph.pop("checks")
    return graph, removed


__all__ = ["ACK_KEYS", "checks_of", "quality", "check_document", "acknowledge", "prune"]
