"""Value-to-evidence checks: is every reported number backed by its own record's evidence?

The verbatim check (``scale graph validate --source-text``) proves that each quote is in the source. It does not
prove that a number the curator recorded is the number the quote prints: a model that misreads a table cell, shifts a
row or copies the wrong column writes a valid record with a genuine quote and a wrong value. This module closes that
gap for every value object (``{status: present, value, unit, as_reported?}``) at any depth of a record's properties:

- ``value_vs_as_reported``: the recorded ``value`` is one of the readings of the printed ``as_reported`` text;
- ``value_vs_evidence``: the value (or its ``as_reported`` text) is printed in at least one quote or page-image
  transcription the record cites.

Each value gets one outcome: ``ok``; ``flag`` (a check failed: a person must look); or ``unverifiable`` (the number
is written in words, its quotes are withheld under the copyright cap, or the record cites no text), which a person
also checks when the review sheet lists it. The checks never change a record. They are deterministic and read only
the document, so CI and an agent get the same answer (``scale review values``).
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterator

from .sourcetext import numbers_in, values_in

_REL_TOL = 1e-6
_FIGURE = re.compile(r"\b(?:fig(?:ure)?s?\.?\s*\d|plotted|curve|abscissa|ordinate|read from (?:the )?(?:plot|graph))",
                     re.IGNORECASE)


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=_REL_TOL, abs_tol=1e-12)


_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                         "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i > 1}
_SCALES = {"hundred": 100, "thousand": 1000}


def _word_numbers(text: str) -> list[float]:
    """Numbers written in words ("two parts", "Two hundred and fifty", "forty-five"), as print often has them."""
    out, cur, total, seen = [], 0, 0, False
    for w in re.findall(r"[a-z]+", (text or "").casefold()) + ["."]:
        if w in _UNITS or w in _TENS:
            cur += _UNITS.get(w, 0) + _TENS.get(w, 0); seen = True
        elif w in _SCALES and seen:
            total += (cur or 1) * _SCALES[w] if w == "thousand" else 0
            cur = cur * 100 if w == "hundred" else 0; seen = True
        elif w == "and" and seen:
            continue
        else:
            if seen:
                out.append(float(total + cur))
            cur, total, seen = 0, 0, False
    return out


def readings(text: str) -> list[float]:
    """Every number a printed text can stand for, signs dropped: the readings of values_in, OCR look-alikes inside
    digit runs ("39O" for 390, "3, 560" for 3560), and numbers in words."""
    t = text or ""
    grouped = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)            # 125,000,000: thousands separators
    out = values_in(t) + values_in(grouped) + [float(n) for n in numbers_in(t, lenient=True)] + _word_numbers(t)
    return [abs(x) for x in out]


def _norm(text: str) -> str:
    """Whitespace collapsed, line-break hyphens joined, case folded: the form quotes are compared in."""
    t = re.sub(r"(\w)-\s+(\w)", r"\1\2", text or "")
    return re.sub(r"\s+", " ", t).strip().casefold()


def _is_value(v: Any) -> bool:
    return isinstance(v, dict) and v.get("status") == "present" and isinstance(v.get("value"), (int, float)) \
        and not isinstance(v.get("value"), bool)


def iter_values(props: dict, path: str = "") -> Iterator[tuple[str, dict]]:
    """Every present numeric value object in a record's properties, with its path (``conversion``,
    ``conditions[2].temperature``). Evidence items are not walked."""
    for k, v in (props or {}).items():
        if k == "evidence":
            continue
        p = f"{path}.{k}" if path else k
        if _is_value(v):
            yield p, v
        elif isinstance(v, dict):
            yield from iter_values(v, p)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                if _is_value(x):
                    yield f"{p}[{i}]", x
                elif isinstance(x, dict):
                    yield from iter_values(x, f"{p}[{i}]")


def _texts(evidence: list) -> tuple[list[str], int]:
    """The cited texts (quotes and page-image transcriptions) and how many items have their text withheld."""
    texts, withheld = [], 0
    for ev in evidence or []:
        if not isinstance(ev, dict):
            continue
        got = [t for t in (ev.get("quote"), ev.get("transcription")) if t]
        texts += got
        if not got and "withheld" in (ev.get("note") or ""):
            withheld += 1
    return texts, withheld


def check_value(value: dict, evidence: list) -> dict:
    """The outcome for one value object against the evidence of its record (or its own, when it carries some)."""
    ev = value.get("evidence") or evidence
    texts, withheld = _texts(ev)
    x = abs(float(value["value"]))
    rep = value.get("as_reported")
    problems, notes = [], []

    printed = readings(" ".join([rep or ""] + texts))
    from_figure = bool(_FIGURE.search(rep or "")) and not any(_close(x, r) for r in readings(rep or "")) or \
        any(isinstance(e, dict) and e.get("kind") == "figure" for e in ev or []) and not any(_close(x, r) for r in printed)
    if from_figure:      # a value read off a plot: no text prints it, a person checks it against the figure
        return {"outcome": "unverifiable", "checks_failed": [], "problems": [],
                "notes": ["read from a figure: check against the plot"]}

    if isinstance(rep, str) and rep.strip():
        got = readings(rep)
        if not got:
            notes.append("as_reported prints no number")
        elif not any(_close(x, r) for r in got):
            problems.append(("value_vs_as_reported", f"value {value['value']} is not a reading of as_reported {rep!r}"))

    if texts:
        joined = " | ".join(texts)
        in_text = any(_close(x, r) for r in readings(joined))
        rep_in_text = isinstance(rep, str) and rep.strip() and _norm(rep) in _norm(joined)
        if not (in_text or rep_in_text):
            problems.append(("value_vs_evidence", "neither the value nor its as_reported text is printed in the quotes "
                                                  "this record cites (cite the passage that states it)"))
    elif withheld:
        notes.append("quotes withheld under the copyright cap: check against the source")
    else:
        notes.append("the record cites no quoted text")

    outcome = "flag" if problems else ("unverifiable" if notes else "ok")
    return {"outcome": outcome, "checks_failed": [c for c, _ in problems], "problems": [m for _, m in problems],
            "notes": notes}


def check_document(doc: dict) -> dict:
    """Every numeric value of a scale-catal document checked against its record's evidence."""
    rows = []
    for kind, recs in (("node", doc.get("nodes") or []), ("link", doc.get("links") or [])):
        for r in recs:
            props = r.get("props") or {}
            for path, v in iter_values(props):
                res = check_value(v, props.get("evidence") or [])
                first = next((e for e in (v.get("evidence") or props.get("evidence") or []) if isinstance(e, dict)), {})
                rows.append({"record": r["id"], "kind": kind, "label": r.get("label") or r.get("type"),
                             "name": props.get("name"), "path": path, "value": v.get("value"),
                             "unit": v.get("unit"), "as_reported": v.get("as_reported"), "bound": v.get("bound"),
                             "locator": first.get("locator"), "quote": first.get("quote"), **res})
    counts = {k: sum(r["outcome"] == k for r in rows) for k in ("ok", "flag", "unverifiable")}
    failed = {c: sum(c in r["checks_failed"] for r in rows) for c in ("value_vs_as_reported", "value_vs_evidence")}
    return {"values": len(rows), "counts": counts, "checks_failed": failed, "rows": rows}


def _cell(x: Any, n: int = 90) -> str:
    s = "" if x is None else str(x)
    s = s.replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def review_sheet(result: dict, title: str = "Value review sheet", all_values: bool = True) -> str:
    """A markdown sheet for the person who reviews a curation: flagged values first, then those no tool can
    verify, then (optionally) every other value, each beside the text it rests on."""
    c = result["counts"]
    out = [f"# {title}", "",
           f"{result['values']} numeric values: **{c['flag']} flagged**, {c['unverifiable']} unverifiable by tools, "
           f"{c['ok']} backed by their quotes.", "",
           "Check every flagged and unverifiable value against the source (page, table, figure). Tick a row when the "
           "recorded value, unit and bound match what the source prints.", ""]
    order = [("flag", "Flagged: the recorded number is not backed by its quote"),
             ("unverifiable", "Unverifiable by tools: check by hand")] + ([("ok", "Backed by their quotes")]
                                                                          if all_values else [])
    for key, heading in order:
        rows = sorted((r for r in result["rows"] if r["outcome"] == key),     # alike problems together, to clear at once
                      key=lambda r: (r["checks_failed"] != ["value_vs_as_reported"], str(r["as_reported"]), r["record"]))
        if not rows:
            continue
        out += [f"## {heading} ({len(rows)})", "",
                "| ✓ | record | property | value | as reported | locator | quote | why |",
                "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            val = f"{'≤ ' if r['bound'] == 'upper' else '≥ ' if r['bound'] == 'lower' else ''}{r['value']} {r['unit'] or ''}"
            why = "; ".join(r["problems"] + r["notes"])
            out.append(f"| ☐ | {_cell(r['name'] or r['record'], 50)} | {r['path']} | {_cell(val, 30)} | "
                       f"{_cell(r['as_reported'], 40)} | {_cell(r['locator'], 20)} | {_cell(r['quote'])} | {_cell(why, 80)} |")
        out.append("")
    return "\n".join(out)
