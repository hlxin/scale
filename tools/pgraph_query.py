"""Queries over scale-graph documents: graph patterns, property filters, evidence search, dated paths.

A query plan (YAML or JSON)::

    question: What evidence supports retaining Cu for lower-temperature methanol synthesis?
    match: {label: CatalyticTest, as: test}           # the records the answer is about
    steps:                                             # follow edges; each binds a new variable
      - {from: test, edge: USES_CATALYST, to: CatalystSample, as: sample}
      - {from: sample, edge: HAS_FORMULATION, to: Catalyst, as: catalyst}
      - {from: catalyst, edge: HAS_COMPONENT, to: ChemicalSpecies, as: cu,
         where: [{prop: formula, op: eq, value: Cu}]}
      - {from: test, edge: OF_REACTION, to: Reaction, as: reaction, optional: true}
      - {from: test, edge: IN_STATE, to: CatalystState, as: state, edge_as: in_state}   # edge_as binds the link
    where:                                             # filters on bound records
      - {var: test, prop: temperature, op: le, value: 300, unit: "°C"}
      - {var: test, prop: "results.*[target=ex:t/species/methanol]", op: ge, value: 50, unit: "%", basis: carbon}
    text: {query: "copper catalyst lower temperature", vars: [test, catalyst], mode: hybrid, min_score: 0.2}
    published_before: "1959-01-01"                    # every cited source must be older
    include_retracted: false                          # true keeps rows resting only on retracted sources
    own_work_only: false                              # true leaves out rows resting only on second-hand evidence
    return: [test.name, test.temperature, test.pressure, catalyst.name, reaction.equation, in_state.status,
             "test.results.*[target=ex:t/species/methanol]"]
    evidence: true                                     # the rows' evidence (evidence_vars: which variables)
    order_by: [{var: test, prop: temperature}]
    limit: 50

A property may be a path into a map or a list of values: ``results.methanol_yield`` (a map entry by key),
``levels.0`` (a list entry by position), ``results.*`` (every entry), each optionally narrowed to the entries
whose value refers to a record, ``[target=<id>]``, or names a variable, ``[variable=<id>]``
(``results.*[target=ex:t/species/co]``; ``selectivity[target=…]`` on a single value). A filter on several
entries holds when one of them passes and fails when every one fails; when none passes and one cannot be
compared (missing, withheld, in another unit, a bound), the record is left out with that entry's reason, never
taken as failing. A returned path gives the entry, or the selected entries by key or in order.

Numeric filters (``lt``, ``le``, ``gt``, ``ge``, and ``eq``, ``ne`` with a number or ``in`` with numbers:
:func:`numeric_filter`) follow one rule on value objects (:func:`comparable`). The filter states its ``unit``, and
a value is compared only when it holds a number (``value``, or ``lower``/``upper``), its ``unit`` is text spelled
as the filter's, case included, once each run of whitespace counts as one space and the ends are trimmed (``mPa``
is not ``MPa``, ``°c`` is not ``°C``; never a synonym: ``mol%`` is not ``%``, ``barg`` is not ``bar``, ``1/h`` is
not ``h-1``), and its ``basis`` is the filter's (``basis``, compared the same way), or, as the filter's, absent.
Nothing is converted, and no basis is read from a unit, a reported text or a note. Any other value is left out with
the reason ``unit_unstated`` (the filter or the value states no unit: none, blank, or the placeholder ``not stated``
a curator writes for a number printed without one, read in any case and spacing),
``incompatible_unit`` (another unit, or a unit that is not text), ``other_basis`` (another basis, or a basis on one
side only) or ``not_a_number``, and counted in ``coverage``. ``eq`` holds for the number, or a reported range that
holds it, and ``ne`` when neither does. A one-sided bound (a value's ``bound``: at most, or at least, its number)
is never read as the number: it passes only when every number it allows does, fails when none does, and is left
out as ``one_sided_bound`` otherwise (:func:`against_bound`; ``eq`` and ``in`` never hold for a bound alone). A
plain number (a source's ``year``) has no unit: a filter without one compares it, one with a unit leaves it out
(``unit_unstated``). A numeric filter without a ``unit`` on a property the schema declares as a value is a plan
error; where the schema cannot tell (a step without ``to``), the value is left out as ``unit_unstated`` (on a
step's own ``where``, counted on the step and in ``coverage.not_evaluated_in_steps``, with the rows a required
step left out because no link passed and one could not be compared, ``rows_not_evaluated``). A unit or ``basis``
that is not non-empty text, a filter unit ``not stated`` (it states none), a ``basis`` on a filter that compares no
number in a unit, and ``convert`` (unit conversion is planned with the units proposal) are plan errors. A value that is not there, or not comparable,
goes to ``excluded`` with the reason (``not_reported``, ``not_curated``, ``ambiguous_in_source``, ``withheld``: a
value the view queried does not share, as ``scale graph filter`` leaves it, not the source being silent,
``not_extractable``, ``not_measured``, ``not_applicable``, ``unit_unstated``, ``incompatible_unit``,
``other_basis``, ``not_a_number``, ``one_sided_bound``, ``no_matching_entry``).

The result says what kind of answer it is:

* ``answered`` — rows were found;
* ``no_matching_record`` — nothing in the queried graph matches (not: nothing exists);
* ``missing_context`` — records match the pattern, but the values the filters (a required step's too) or the
  return need are missing or in an incompatible unit;
* ``schema_gap`` — the plan names a label, edge or property the schema does not declare.

Every row carries the records bound, the returned values as reported, and (with ``evidence``) the
evidence items with their sources and years: a dated path from source to record.

Every result carries ``access`` ({``level``, ``note``}: :func:`document_access`), and it fails closed: the least open
effective stewardship found anywhere in the queried document, its header and every node and link (notices, cited
sources and datasets included, whether or not a row shows them), as ``scale graph filter`` reads it (a missing
access is institution; an embargo is read on the plan's ``as_of``, an ISO date YYYY-MM-DD, or today (the earlier of
the local and the UTC date, :func:`pgraph.embargo_today`, as every path reads it), whichever is earlier: it counts as
lapsed only when it has lapsed on both, so a later ``as_of`` never opens one still in force,
and an ``as_of`` that is not such a date is a plan error). No part of an answer is given a more open access than the
whole document's: an answer drawn from a document that is not all public goes only where the whole document may go,
and a limitation says so and how to get a public answer: query the document ``scale graph filter`` makes for the
readers (``--public``, or ``--as <id>``), whose answers have that view's own access (a view declares its audience in
its header, so a public view answers publicly; the limitation never sends a public view back to the filter). A row's
second-hand note names its citing sources by title only when the document is all public, by id otherwise.

Each evidence item also carries its source's publication status (``source_status``, derived from the
notices recorded in the graph: retracted, withdrawn, partially_retracted, expression_of_concern,
corrected, updated or current_or_unknown; ``lifecycle``), its source's ``source_kind`` (article,
patent, thesis, preprint, report, dataset, …) and ``source_peer_reviewed`` (as recorded; None when not
recorded), and ``second_hand: true`` when its ``evidence_type`` is ECO:0000033 (author statement
supported by traceable reference: the source reports another work's result) or its child ECO:0000304. A
row whose evidence is all second-hand says so (``second_hand``: the citing sources); ``own_work_only:
true`` leaves it out (reason ``second_hand_only``). A row whose evidence rests only on retracted or
withdrawn sources is left out by default, to ``excluded`` with the reason
``rests_on_retracted_source``; ``include_retracted: true`` keeps it, labelled. A retraction never
deletes a record: the rows are there, flagged.

Every result carries ``coverage``: the candidates the match considered, each stage's rows in and out
(match, every step, where, the retraction and date rules, own_work_only, text, limit; a step also counts
what its filters could not evaluate, each link or record once per reason), the link types traversed, the
records left out by reason counted in full (``excluded`` lists the first 500; a record left out of several rows,
or by several filters, for one reason is one entry, and counted once), the values a numeric filter compared in its
unit (``compared_in_unit``, each value once, however many rows or filters read it, with a limitation: a basis
written only in a value's reported text or note is not read), ``unfiltered`` (the plan narrows nothing: the rows
are a listing) and, for a document ``scale graph filter`` made, its ``filtered_for``: a reference the filter
removed (a ref, a ref-list entry, a map entry keyed by a withheld id) reads there as not curated, which a
limitation says.

A filter on an optional variable that stayed unbound (``optional: true`` found nothing) holds for
``missing`` (the record is not there, so neither is its property) and fails for every other op: a
plan can ask for "tests with no retraction notice" by binding the notice optionally and filtering
``{var: notice, prop: id, op: missing}``. A ``where`` filter must name a variable that ``match`` or a
step declares (``as``, or ``edge_as`` for a filter on the link itself); a misspelled one is an error, never a
filter that every row passes.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from . import lifecycle, passages, pgraph
from .util import ScaleError, load_doc

SHARED_KINDS = {"ChemicalSpecies", "Reaction", "Material", "Person", "Institution", "Source", "Dataset"}
OPS = {"eq", "ne", "in", "contains", "lt", "le", "gt", "ge", "exists", "missing", "matches"}
NUMERIC_OPS = {"lt", "le", "gt", "ge"}
# ECO "author statement supported by traceable reference" and its child "… used in manual assertion": a source
# reporting another work's result
SECOND_HAND_ECO = {"ECO:0000033", "ECO:0000304"}
LEFT_OUT_ON_PURPOSE = ("rests_on_retracted_source", "second_hand_only")    # not missing context
DATE_REASONS = ("cites_later_source", "no_dated_source")
LISTED = 500                                                           # excluded and missing_context list this many
CONVERT_REFUSED = ("convert is not available: a numeric filter compares only values in the unit it states, spelled the "
                   "same, case included (only runs of whitespace count as one space), and on the basis it states; "
                   "nothing is converted (unit conversion is planned with the units proposal). Run one plan per unit "
                   "and basis, and report each apart.")
_PATH = re.compile(r"^(?P<prop>[^.\[\]\s]+)(?:\.(?P<entry>[^.\[\]\s]+))?(?:\[(?P<qual>target|variable)=(?P<id>[^\]\s]+)\])?$")


class Graph:
    """A document indexed for queries: its records by id, links by end and records by label, and what every query of
    the document needs whatever its plan (its digest, its access on a day, the publication statuses of its sources,
    the evidence quotes it holds), each computed once when first asked for. Build one per document and pass it to
    :func:`run` for every plan run on that document; the document must not change while the Graph is in use."""

    def __init__(self, doc: dict, spec: dict):
        self.doc, self.spec = doc, spec
        self.nodes = {n["id"]: n for n in doc["nodes"]}
        self.out: dict[str, list[dict]] = {}
        self.inc: dict[str, list[dict]] = {}
        for e in doc["links"]:
            self.out.setdefault(e["source"], []).append(e)
            self.inc.setdefault(e["target"], []).append(e)
        self.by_label: dict[str, list[str]] = {}
        for n in doc["nodes"]:
            for lab in [n["label"]] + (spec["nodes"].get(n["label"], {}).get("ancestors") or []):
                self.by_label.setdefault(lab, []).append(n["id"])
        self.year = {n["id"]: _year(n["props"]) for n in doc["nodes"] if n["label"] in ("Source", "Dataset")}
        self._digest = self._life = self._inclusion = self._held = None
        self._access: dict[str, dict] = {}

    @property
    def digest(self) -> str:
        if self._digest is None:
            self._digest = passages.graph_sha256(self.doc)
        return self._digest

    def access(self, as_of: str) -> dict:
        """:func:`document_access` on ``as_of`` (a copy, so that an answer's access never changes another's)."""
        if as_of not in self._access:
            self._access[as_of] = document_access(self.doc, as_of)
        return dict(self._access[as_of])

    @property
    def life(self) -> dict:
        if self._life is None:
            self._life = lifecycle.statuses(self.doc, self.spec)
        return self._life

    @property
    def inclusion(self) -> dict:
        if self._inclusion is None:
            self._inclusion = lifecycle.retracted_inclusions(self.doc, self.life, self.spec)
        return self._inclusion

    @property
    def held(self) -> set:
        """The evidence quotes the document holds, as (record, evidence position, text)."""
        if self._held is None:
            self._held = {(it["record"], it["evidence"], it["text"]) for it in passages.evidence_items(self.doc)}
        return self._held

    def is_a(self, nid: str, label: str) -> bool:
        n = self.nodes.get(nid)
        return bool(n) and (n["label"] == label or label in (self.spec["nodes"].get(n["label"], {}).get("ancestors") or []))


def _year(p: dict) -> int | None:
    """A Source's year (or, without one, the year of its published_on); a Dataset's year of issue."""
    if isinstance(p.get("year"), int):
        return p["year"]
    for k in ("published_on", "issued"):
        v = p.get(k)
        if isinstance(v, str) and re.match(r"^\d{4}", v):
            return int(v[:4])
    return None


# ------------------------------------------------------------------------------------------ values
def _is_number(x: Any) -> bool:
    """A finite number: an int or float, never a bool, NaN, an infinity or an int too large for a float."""
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return False
    try:
        return math.isfinite(x)
    except OverflowError:
        return False


def number(v: Any) -> tuple[float | None, float | None]:
    """(low, high) of a value object or a plain number; only a finite number counts (:func:`_is_number`)."""
    if _is_number(v):
        return float(v), float(v)
    if isinstance(v, dict):
        if _is_number(v.get("value")):
            return float(v["value"]), float(v["value"])
        lo, hi = v.get("lower"), v.get("upper")
        if _is_number(lo) or _is_number(hi):
            return (float(lo) if _is_number(lo) else None), (float(hi) if _is_number(hi) else None)
    return None, None


def unit_key(text: str) -> str:
    """A unit or basis as a filter compares it: whitespace runs as one space, none at either end, and nothing else.
    Case is kept (``mPa`` stays apart from ``MPa``, ``mmol`` from ``Mmol``), and so is every character (the Kelvin
    sign is not the letter K); no synonym (``mol%`` stays apart from ``%``, ``barg`` from ``bar``, ``1/h`` from
    ``h-1``)."""
    return " ".join(text.split())


def _stated(x: Any) -> bool:
    """Whether a unit or basis is stated: anything but None and text that is empty once trimmed."""
    return x is not None and not (isinstance(x, str) and not x.strip())


#: A filter in the placeholder a curator writes for a number printed without a unit: a plan error.
NOT_STATED_REFUSED = ("{what} is in the unit 'not stated', the placeholder a curator writes for a number the source "
                      "prints without a unit: it states no unit, so no filter compares in it (the numbers in it may "
                      "be in any unit; their values are left out as unit_unstated)")


def comparable(v: dict, unit: Any, basis: Any = None) -> str | None:
    """Why a value object cannot be compared with a numeric filter in ``unit`` (and on ``basis``), or None when it
    can. The one rule: the filter states its unit; the value holds a number (``value``, or ``lower``/``upper``), its
    unit is text spelled as the filter's, case included, whitespace runs aside (:func:`unit_key`), and its basis is
    the filter's, compared the same way, or absent as the filter's is. Reasons: ``unit_unstated`` (the filter or the
    value states no unit), ``not_a_number``, ``incompatible_unit`` (another unit, or one that is not text) and
    ``other_basis`` (another basis, or a basis on one side only). Nothing else is read: no conversion, and no basis
    from the unit, the reported text or the note. A value whose unit is the placeholder ``not stated`` (any case and
    spacing, :func:`pgraph.states_no_unit`) states none. A filter unit or basis that is not text, and a filter unit
    ``not stated``, are plan errors."""
    if not _stated(unit):
        return "unit_unstated (the filter states no unit: a numeric filter compares in the unit it states)"
    if not isinstance(unit, str) or not (basis is None or isinstance(basis, str)):
        raise ScaleError(f"a filter's unit and basis are text, not {type(unit).__name__} and {type(basis).__name__}")
    if pgraph.states_no_unit(unit):
        raise ScaleError(NOT_STATED_REFUSED.format(what="the filter"))
    if number(v) == (None, None):
        return "not_a_number (the value holds no number in value, lower or upper)"
    vu = v.get("unit")
    if pgraph.states_no_unit(vu):       # none, blank, or the placeholder "not stated" in any case and spacing
        return f"unit_unstated (the value states no unit; filter in {unit!r})"
    if not isinstance(vu, str):
        return f"incompatible_unit (the value's unit is not text: {type(vu).__name__}; filter in {unit!r})"
    if unit_key(vu) != unit_key(unit):
        return f"incompatible_unit ({vu!r}, filter in {unit!r})"
    vb = v.get("basis")
    if not _stated(vb) and not _stated(basis):
        return None
    if not isinstance(vb, str) and _stated(vb):
        return f"other_basis (the value's basis is not text: {type(vb).__name__})"
    if not _stated(vb):
        return f"other_basis (the value states no basis; filter on {basis!r})"
    if not _stated(basis):
        return f"other_basis (the value is on {vb!r}; the filter states no basis)"
    if unit_key(vb) != unit_key(basis):
        return f"other_basis ({vb!r}, filter on {basis!r})"
    return None


# why a not_reported value is missing, when the source is not silent: known but not shared with this view (a value
# ``scale graph filter`` or an export withheld), or there but not extracted
NOT_SILENT = ("withheld", "not_extractable")


def absent_reason(v: Any) -> str | None:
    """Why a value is not there: ``not_curated`` (nobody looked: no value, ``missing_reason: not_curated``, or a
    note saying so), ``ambiguous_in_source``, ``withheld`` or ``not_extractable`` (the source reports it, but this
    view does not show it or it could not be extracted: never the source being silent), or the value's status
    (``not_reported``, ``not_measured``, …)."""
    if v is None:
        return "not_curated"
    if isinstance(v, dict) and v.get("status") and v["status"] != "present":
        if v.get("missing_reason") in NOT_SILENT:
            return v["missing_reason"]
        note = v.get("note")
        note = note if isinstance(note, str) else ""          # a note that is not text says nothing
        if note.startswith("not curated") or v.get("missing_reason") == "not_curated":
            return "not_curated"
        if v.get("missing_reason") == "ambiguous_in_source":
            return "ambiguous_in_source"
        return v["status"]
    return None


def scalar(v: Any) -> Any:
    if isinstance(v, dict):
        for k in ("text_value", "boolean_value", "ref_value", "value"):
            if k in v:
                return v[k]
    return v


def reason_code(reason: str | None) -> str:
    """The code a reason starts with (``incompatible_unit`` of ``incompatible_unit ('atm', filter in 'MPa')``)."""
    m = re.match(r"[a-z_]+", str(reason or ""))
    return m.group(0) if m else str(reason)


# ------------------------------------------------------------------------------------------ property paths
def parse_path(path: Any) -> tuple[str, str | None, str | None, str | None]:
    """(property, entry, qualifier, record id) of a property path: ``temperature``, ``results.methanol_yield``,
    ``levels.0``, ``results.*``, ``results.*[target=ex:t/species/co]``, ``selectivity[variable=ex:t/var/x]``."""
    m = _PATH.match(str(path or ""))
    if not m:
        raise ScaleError(f"cannot read the property path {path!r}: a property, optionally .<key>, .<position> or .* "
                         "for an entry of a map or list, then optionally [target=<id>] or [variable=<id>]")
    return m["prop"], m["entry"], m["qual"], m["id"]


def lookup(rec: dict, path: str) -> tuple[Any, list[tuple[Any, Any]] | None]:
    """(the property's value, the entries the path selects); the entries are None for a plain property."""
    prop, entry, qual, qid = parse_path(path)
    v = rec.get(prop) if prop in ("id", "label", "type") else (rec.get("props") or {}).get(prop)
    if entry is None and qual is None:
        return v, None
    items: list[tuple[Any, Any]]
    if isinstance(v, dict) and "status" not in v:                  # a map
        if entry in (None, "*"):
            items = sorted(v.items(), key=lambda kv: str(kv[0]))
        else:
            items = [(entry, v[entry])] if entry in v else []
    elif isinstance(v, list):
        if entry in (None, "*"):
            items = list(enumerate(v))
        else:
            items = [(int(entry), v[int(entry)])] if entry.isdigit() and int(entry) < len(v) else []
    elif isinstance(v, dict) and entry is None:                     # a qualifier on a single value
        items = [(None, v)]
    else:
        items = []
    if qual:
        items = [(k, x) for k, x in items if isinstance(x, dict) and x.get(qual) == qid]
    return v, items


def returned(rec: dict, path: str) -> Any:
    """The value a returned path gives: the property, the one entry it names, or the entries it selects (by key
    for a map, in order for a list); None when nothing is selected."""
    v, items = lookup(rec, path)
    if items is None:
        return v
    _, entry, _, _ = parse_path(path)
    if not items:
        return None
    if entry not in (None, "*") or all(k is None for k, _ in items):
        return items[0][1]
    if isinstance(v, list):
        return [x for _, x in items]
    return {k: x for k, x in items}


# ------------------------------------------------------------------------------------------ filters
def numeric_filter(f: dict) -> bool:
    """Whether a filter compares numbers: ``lt``, ``le``, ``gt``, ``ge``, and ``eq``, ``ne`` with a number or ``in``
    with a list of numbers. On a value object such a filter compares in the unit it states."""
    op, want = f.get("op", "eq"), f.get("value")
    if op in NUMERIC_OPS:
        return True
    if op in ("eq", "ne"):
        return _is_number(want)
    return op == "in" and isinstance(want, list) and bool(want) and all(_is_number(x) for x in want)


def against_bound(side: str, b: float, op: str, want: Any) -> bool | None:
    """A numeric filter against a one-sided bound (the value object's ``bound``: the number is at most ``b``, side
    ``upper``, or at least ``b``, side ``lower``): True or False when every number the bound allows gives that
    answer, None when the bound cannot decide (``gt 0.5`` against at most 1). ``eq`` and ``in`` never hold for a
    bound alone; they fail only when every number asked for lies outside it."""
    xs = [_as_number(x) for x in (want if op == "in" else [want])]
    if side == "lower":                         # at least b is -value at most -b: mirror the filter
        b, xs = -b, [-x for x in xs]
        op = {"lt": "gt", "le": "ge", "gt": "lt", "ge": "le"}.get(op, op)
    x = xs[0]                                   # the value is at most b
    if op in ("lt", "le"):
        return True if (b < x if op == "lt" else b <= x) else None
    if op in ("gt", "ge"):
        return False if (b <= x if op == "gt" else b < x) else None
    outside = all(y > b for y in xs)
    if op == "ne":
        return True if outside else None
    return False if outside else None


def _as_number(x: Any) -> float:
    """A filter's number: a finite number, or text that reads as one (``"300"``); anything else is a plan error."""
    if _is_number(x):
        return float(x)
    if isinstance(x, str):
        try:
            y = float(x)
        except ValueError:
            y = None
        if y is not None and math.isfinite(y):
            return y
    raise ScaleError(f"a numeric filter compares with a number, not {x!r}")


def _numeric(v: Any, f: dict, op: str) -> tuple[bool | None, str | None]:
    """A numeric filter on a value object (:func:`comparable`) or a plain number: (result, None) or (None, reason)."""
    want = f.get("value")
    xs = [_as_number(x) for x in (want if op == "in" else [want])]
    unit = f.get("unit")
    if isinstance(v, dict):
        why = comparable(v, unit, f.get("basis"))
        if why:
            return None, why
        side = v.get("bound")
        if side in ("upper", "lower") and _is_number(v.get("value")):      # "did not exceed 1 %", "at least 2"
            r = against_bound(side, float(v["value"]), op, want)
            if r is None:
                return None, (f"one_sided_bound (the value is {'at most' if side == 'upper' else 'at least'} "
                              f"{v['value']} {v['unit']}".rstrip() + f"; {op} {want} cannot be decided)")
            return r, None
    elif not _is_number(v):
        return None, "not_a_number (the value is not a number)"
    elif _stated(unit):
        return None, f"unit_unstated (the value is a plain number with no unit; filter in {unit!r})"
    lo, hi = number(v)
    if op in NUMERIC_OPS:
        x = xs[0]
        return {"lt": (lo if lo is not None else hi) < x, "le": (lo if lo is not None else hi) <= x,
                "gt": (hi if hi is not None else lo) > x, "ge": (hi if hi is not None else lo) >= x}[op], None
    # eq: the number, or a reported range that holds it (in: one of the numbers); ne: not so
    low, high = (lo if lo is not None else hi), (hi if hi is not None else lo)
    held = any(low <= x <= high for x in xs)
    return (not held if op == "ne" else held), None


def _one(v: Any, f: dict, op: str) -> tuple[bool | None, str | None]:
    """One value against one filter: (result, None) or (None, reason)."""
    want = f.get("value")
    if op in ("exists", "missing"):
        why = absent_reason(v)
        if why == "withheld":              # known but not shared with this view: neither there nor missing
            return None, why
        return (why is None) == (op == "exists"), None
    why = absent_reason(v)
    if why:
        return None, why
    # a number in the filter's unit (:func:`comparable`): lt/le/gt/ge on anything, and eq/ne/in with numbers on a value
    # object or a plain number (text compared with a number is compared as it is below)
    if numeric_filter(f) and (op in NUMERIC_OPS or isinstance(v, dict) or _is_number(v)):
        return _numeric(v, f, op)
    s = scalar(v)
    if op == "eq":
        return (s == want) or (isinstance(s, str) and isinstance(want, str) and s.lower() == want.lower()), None
    if op == "ne":
        return s != want, None
    if op == "in":
        return s in (want or []), None
    if op == "contains":
        if isinstance(s, list):
            return want in s or any(isinstance(x, str) and isinstance(want, str) and want.lower() in x.lower() for x in s), None
        return isinstance(s, str) and str(want).lower() in s.lower(), None
    if op == "matches":
        text = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False)
        return bool(re.search(str(want), text, re.I)), None
    raise ScaleError(f"unknown filter op {op!r}; ops: {sorted(OPS)}")


def check(rec: dict, f: dict) -> tuple[bool | None, str | None]:
    """A filter on a record: (True or False, None), or (None, reason) when the value needed is missing or not
    comparable. A path selecting several entries holds when one of them passes and fails only when every one of them
    fails; when none passes and one could not be compared, the filter cannot be decided (the first such entry's
    reason): an entry that fails never hides one that might pass."""
    op = f.get("op", "eq")
    v, items = lookup(rec, f.get("prop"))
    if items is None:
        return _one(v, f, op)
    vals = [x for _, x in items]
    if op in ("exists", "missing"):        # one entry there, or every one missing; a withheld entry decides neither
        there = [absent_reason(x) is None for x in vals]
        held = any(absent_reason(x) == "withheld" for x in vals)
        if any(there):
            return op == "exists", None
        return (None, "withheld") if held else (op == "missing", None)
    if not vals:
        return None, ("not_curated" if v is None else f"no_matching_entry ({f.get('prop')})")
    first: str | None = None
    for x in vals:
        r, why = _one(x, f, op)
        if r:
            return True, None
        if r is None and first is None:
            first = why
    return (False, None) if first is None else (None, first)


def test(rec: dict, f: dict) -> tuple[bool | None, str | None]:
    """True/False, or (None, reason) when the value needed is missing or not comparable (:func:`check`)."""
    return check(rec, f)


# ------------------------------------------------------------------------------------------ plan checks
def _prop_def(spec: dict, label: str | None, prop: str, edge: bool = False) -> dict | None:
    if prop in ("id", "label", "type"):
        return {"type": "string"}
    c = spec["common"]["link" if edge else "node"]
    common = c.get("properties", c)
    if prop in common:
        return common[prop]
    if label is None:
        return None
    d = spec["edges" if edge else "nodes"].get(label) or {}
    return (d.get("properties") or {}).get(prop)


def _variables(plan: dict) -> tuple[dict[str, str | None], dict[str, str]]:
    """(node variable -> label, link variable -> edge type) as the plan declares them."""
    labels = {plan["match"]["as"] if "as" in plan["match"] else "self": plan["match"].get("label")}
    edge_vars: dict[str, str] = {}
    for st in plan.get("steps") or []:
        labels[st["as"]] = st.get("to")
        if st.get("edge_as"):
            edge_vars[st["edge_as"]] = st["edge"]
    return labels, edge_vars


def _filters(plan: dict) -> list[tuple[dict, str | None, bool]]:
    """Every filter of the plan with the label or edge type it reads and whether that is a link."""
    labels, edge_vars = _variables(plan)
    root = plan["match"].get("as", "self")
    out = [(f, plan["match"].get("label"), False) for f in plan["match"].get("where") or []]
    for st in plan.get("steps") or []:
        out += [(f, st.get("to"), False) for f in st.get("where") or []]
        out += [(f, st["edge"], True) for f in st.get("edge_where") or []]
    for f in plan.get("where") or []:
        var = f.get("var", root)
        if var in edge_vars and var not in labels:
            out.append((f, edge_vars[var], True))
        else:
            out.append((f, labels.get(var), False))
    return out


def check_plan(plan: dict, spec: dict) -> None:
    """Errors in a plan, raised: a property path that cannot be read, an entry of a property that is no map or
    list, a numeric filter (:func:`numeric_filter`: lt, le, gt, ge, and eq, ne or in with numbers) without a unit on
    a property the schema declares as a value, ``lt``, ``le``, ``gt`` or ``ge`` with a value that is not a number, a
    unit that is not non-empty text or is the placeholder ``not stated`` (:data:`NOT_STATED_REFUSED`), a ``basis``
    that is not non-empty text or on a filter that compares no number in a unit, and ``convert``
    (:data:`CONVERT_REFUSED`: nothing is converted)."""
    if plan.get("convert") not in (None, False):
        raise ScaleError(CONVERT_REFUSED)
    labels, edge_vars = _variables(plan)
    for f, label, edge in _filters(plan):
        what = f"the filter {f.get('prop')} {f.get('op')} {f.get('value')}"
        if f.get("convert") not in (None, False):
            raise ScaleError(f"{what}: {CONVERT_REFUSED}")
        unit = f.get("unit")
        if unit is not None and not (isinstance(unit, str) and unit.strip()):
            raise ScaleError(f"{what} states its unit as {unit!r}: a unit is text (MPa, °C, %), compared as it is spelled")
        if isinstance(unit, str) and pgraph.states_no_unit(unit):
            raise ScaleError(NOT_STATED_REFUSED.format(what=what))
        if "basis" in f and not (isinstance(f["basis"], str) and f["basis"].strip() and unit is not None
                                 and numeric_filter(f)):
            raise ScaleError(f"{what} states a basis ({f['basis']!r}): a basis is text, on a numeric filter that states "
                             f"its unit; it is compared with the value's basis as it is spelled (carbon, molar)")
        if f.get("op", "eq") in NUMERIC_OPS:
            _as_number(f.get("value"))
        prop, entry, qual, _ = parse_path(f.get("prop"))
        d = _prop_def(spec, label, prop, edge)
        if d is None:
            continue
        t = d.get("type")
        if entry is not None and t not in ("map", "list"):
            raise ScaleError(f"{label}.{prop} is not a map or list, so {f.get('prop')!r} names no entry")
        valued = t == "value" or (t in ("map", "list") and (entry is not None or qual)
                                  and (d.get("items") or {}).get("type") == "value")
        if numeric_filter(f) and t in ("map", "list") and entry is None and not qual \
                and (d.get("items") or {}).get("type") == "value":
            raise ScaleError(f"the filter {f.get('prop')} {f.get('op')} {f.get('value')} on {label} compares a whole "
                             f"{t} with a number: name its entries ({f.get('prop')}.* for every entry, .<key> or .<position> "
                             f"for one, optionally [target=<id>])")
        if numeric_filter(f) and valued and not f.get("unit"):
            raise ScaleError(f"the filter {f.get('prop')} {f.get('op')} {f.get('value')} on {label} states no unit: a "
                             f"numeric filter on a value object compares only values in the unit it states (add unit)")
    for r in plan.get("return") or []:
        var, _, path = r.partition(".")
        if path:
            prop, entry, _, _ = parse_path(path)
            edge = var in edge_vars and var not in labels
            d = _prop_def(spec, edge_vars[var] if edge else labels.get(var), prop, edge)
            if d is not None and entry is not None and d.get("type") not in ("map", "list"):
                raise ScaleError(f"{prop} is not a map or list, so the return {r!r} names no entry")
    for ob in plan.get("order_by") or []:
        parse_path(ob.get("prop"))


def schema_gaps(plan: dict, spec: dict) -> list[str]:
    gaps = []
    labels = {plan["match"]["as"] if "as" in plan["match"] else "self": plan["match"].get("label")}
    edge_vars: dict[str, str] = {}

    def has_prop(label: str | None, prop: str, edge: bool = False) -> bool:
        prop = parse_path(prop)[0]
        if prop in ("id", "label", "type"):
            return True
        c = spec["common"]["link" if edge else "node"]
        common = c.get("properties", c)
        if prop in common:
            return True
        if label is None:
            return True
        d = spec["edges" if edge else "nodes"].get(label) or {}
        return prop in (d.get("properties") or {})

    ml = plan["match"].get("label")
    if ml and ml not in spec["nodes"]:
        gaps.append(f"label {ml} is not declared")
    for st in plan.get("steps") or []:
        if st["edge"] not in spec["edges"]:
            gaps.append(f"edge type {st['edge']} is not declared")
        if st.get("to") and st["to"] not in spec["nodes"]:
            gaps.append(f"label {st['to']} is not declared")
        labels[st["as"]] = st.get("to")
        if st.get("edge_as"):
            edge_vars[st["edge_as"]] = st["edge"]
        for f in st.get("where") or []:
            if not has_prop(st.get("to"), f["prop"]):
                gaps.append(f"{st.get('to')}.{parse_path(f['prop'])[0]} is not declared")
        for f in st.get("edge_where") or []:
            if not has_prop(st["edge"], f["prop"], edge=True):
                gaps.append(f"{st['edge']}.{parse_path(f['prop'])[0]} is not declared")
    for f in (plan.get("where") or []) + (plan["match"].get("where") or []):
        var = f.get("var", plan["match"].get("as", "self"))
        if var in edge_vars and var not in labels:          # a filter on a link bound by edge_as
            if not has_prop(edge_vars[var], f["prop"], edge=True):
                gaps.append(f"{edge_vars[var]}.{parse_path(f['prop'])[0]} is not declared")
        elif not has_prop(labels.get(var), f["prop"]):
            gaps.append(f"{labels.get(var)}.{parse_path(f['prop'])[0]} is not declared")
    for r in plan.get("return") or []:
        var, _, prop = r.partition(".")
        if var in edge_vars:
            if prop and not has_prop(edge_vars[var], prop, edge=True):
                gaps.append(f"{edge_vars[var]}.{parse_path(prop)[0]} is not declared")
        elif prop and not has_prop(labels.get(var), prop):
            gaps.append(f"{labels.get(var)}.{parse_path(prop)[0]} is not declared")
    return sorted(set(gaps))


def unfiltered(plan: dict) -> bool:
    """Whether the plan narrows nothing: no match id, no filter of any kind, no text search, date or own-work rule,
    and no step that a row must find. Its rows are a listing, not an answer to a question that asks for a condition."""
    m = plan.get("match") or {}
    if m.get("id") or m.get("where") or plan.get("where") or plan.get("text") or plan.get("published_before") \
            or plan.get("own_work_only"):
        return False
    return all(st.get("optional") and not st.get("where") and not st.get("edge_where") for st in plan.get("steps") or [])


def _eco(t: Any) -> str:
    """An ECO id however it is written (ECO:0000033, ECO_0000033, an OBO IRI)."""
    m = re.search(r"ECO[:_](\d{7})", str(t or ""))
    return f"ECO:{m.group(1)}" if m else str(t or "")


# ------------------------------------------------------------------------------------------ execution
def run(doc: dict, spec: dict, plan: dict, evidence_index=None, graph: Graph | None = None) -> dict:
    """Run ``plan`` on ``doc``. ``graph``: the document's :class:`Graph`, when several plans run on one document (used
    only when it was built from this document and schema). The result shares no object with the document: a caller
    may change it without changing the document, or a later answer drawn from it."""
    return copy.deepcopy(_run(doc, spec, plan, evidence_index, graph))


def _run(doc: dict, spec: dict, plan: dict, evidence_index=None, graph: Graph | None = None) -> dict:
    g = graph if graph is not None and graph.doc is doc and graph.spec is spec else Graph(doc, spec)
    plan = json.loads(json.dumps(plan, default=_plain))
    m = plan.get("match") or {}
    if not m.get("label") and not m.get("id"):
        raise ScaleError("a plan needs match.label or match.id")
    root = m.get("as", "self")
    steps = plan.get("steps") or []
    edge_vars = {st["edge_as"] for st in steps if st.get("edge_as")} - {root} - {st.get("as") for st in steps}
    declared = {root} | {st.get("as") for st in steps} | edge_vars
    optional = {st.get("as") for st in steps if st.get("optional")} | {st.get("edge_as") for st in steps if st.get("optional")}
    for f in plan.get("where") or []:
        if f.get("var", root) not in declared:
            raise ScaleError(f"where names the variable {f.get('var')!r}, which neither match nor a step declares "
                             f"(declared: {', '.join(sorted(str(v) for v in declared))})")
    check_plan(plan, spec)
    base = {"question": plan.get("question"), "plan": plan, "graph_id": doc["graph"].get("graph_id"),
            "schema_version": doc["graph"].get("schema_version"), "graph_sha256": g.digest}
    link_types = list(dict.fromkeys(st["edge"] for st in steps))
    as_of = embargo_day(plan.get("as_of"), pgraph.embargo_today())    # the day an embargo is read on (one clock)
    access = g.access(as_of)                        # the whole document's: no part of an answer is more open
    gaps = schema_gaps(plan, spec)
    if gaps:
        return {**base, "status": "schema_gap", "schema_gaps": gaps, "rows": [], "access": access, "excluded": [],
                "coverage": {"ran": False, "link_types": link_types, "unfiltered": unfiltered(plan)},
                "limitations": ["The schema cannot express what the plan asks for; this is a representation gap, not an absence of evidence."]
                + _access_limitation(access, doc, as_of)}

    # values a numeric filter compared in its unit: each value (record and property path) once, however many rows or
    # filters read it
    compared: set = set()
    stages: list[dict] = []
    excluded: list[dict] = []
    excluded_at: dict[tuple, int] = {}      # (record, reason code) -> its entry: a record left out of several rows once

    def exclude(entry: dict) -> None:
        """Add a record left out, once per record and reason code (a record in several rows, or left out by several
        filters for one reason, is one entry, the first filter's: the sources and datasets of its rows merged)."""
        key = (entry["record"], reason_code(entry["reason"]))
        i = excluded_at.get(key)
        if i is None:
            excluded_at[key] = len(excluded)
            excluded.append(entry)
            return
        have = excluded[i]
        for k in ("sources", "datasets"):
            if entry.get(k):
                have[k] = sorted(set(have.get(k) or []) | set(entry[k]))

    def apply(rec: dict, filters: list[dict] | None, rid: str, sink) -> bool:
        """Whether a record passes every filter; a filter that cannot be evaluated goes to sink(filter, reason)."""
        for f in filters or []:
            r, why = check(rec, f)
            if r is None:
                sink(f, why)
                return False
            if numeric_filter(f) and _stated(f.get("unit")):     # a value object, compared in the filter's unit
                compared.add((rid, f.get("prop")))
            if not r:
                return False
        return True

    cands = ([m["id"]] if m["id"] in g.nodes else []) if m.get("id") else sorted(g.by_label.get(m["label"], []))
    rows = []
    for nid in cands:
        if apply(g.nodes[nid], m.get("where"), nid,
                 lambda f, why, nid=nid: exclude({"record": nid, "filter": f, "reason": why})):
            rows.append({root: nid, "_links": [], "_edges": {}})
    stages.append({"kind": "match", **({"label": m["label"]} if m.get("label") else {"id": m["id"]}),
                   "rows_in": len(cands), "rows_out": len(rows)})

    for st in steps:
        nxt = []
        src = st.get("from", root)
        direction = st.get("direction", "out")
        left: Counter = Counter()
        seen: set = set()                   # (link or record, reason code): each counted once, however many rows
        missed = [False]                    # this row: a comparison on one of its links could not be made

        def step_sink(f, why, rid, left=left, seen=seen, missed=missed):
            missed[0] = True
            if (rid, reason_code(why)) not in seen:
                seen.add((rid, reason_code(why)))
                left[reason_code(why)] += 1
        unbound = 0
        unevaluated = 0                     # rows this step left out though a comparison on their links could not be made
        for row in rows:
            here = row.get(src)
            found = False
            missed[0] = False
            if here is not None:
                edges = g.out.get(here, []) if direction == "out" else g.inc.get(here, [])
                for e in sorted(edges, key=lambda e: e["id"]):
                    if e["type"] != st["edge"]:
                        continue
                    other = e["target"] if direction == "out" else e["source"]
                    if st.get("to") and not g.is_a(other, st["to"]):
                        continue
                    if not apply(e, st.get("edge_where"), e["id"], lambda f, why, rid=e["id"]: step_sink(f, why, rid)):
                        continue
                    if apply(g.nodes[other], st.get("where"), other, lambda f, why, rid=other: step_sink(f, why, rid)):
                        edges_bound = {**row["_edges"], st["edge_as"]: e["id"]} if st.get("edge_as") else row["_edges"]
                        nxt.append({**row, st["as"]: other, "_links": row["_links"] + [e["id"]], "_edges": edges_bound})
                        found = True
            if not found and st.get("optional"):
                nxt.append({**row, st["as"]: None})
                unbound += 1
            elif not found and missed[0]:                   # no link passed, and one could not be compared
                unevaluated += 1
        stage = {"kind": "step", "edge": st["edge"], "direction": direction, "from": src, "to": st.get("to"), "as": st["as"],
                 "rows_in": len(rows), "rows_out": len(nxt)}
        if st.get("optional"):
            stage.update(optional=True, unbound=unbound)
        if left:
            stage["left_out_by_reason"] = dict(sorted(left.items()))
        if unevaluated:
            stage["rows_not_evaluated"] = unevaluated
        stages.append(stage)
        rows = nxt

    link_by_id = {e["id"]: e for e in doc["links"]}

    if plan.get("where"):
        kept = []
        for row in rows:
            ok = True
            for f in plan.get("where") or []:
                var = f.get("var", root)
                nid = row["_edges"].get(var) if var in edge_vars else row.get(var)   # a link bound by edge_as, or a node
                if nid is None:                 # an optional variable left unbound: its record, so its property, is missing
                    if f.get("op") == "missing" and var in optional:
                        continue
                    ok = False
                    break
                ok = apply(link_by_id[nid] if var in edge_vars else g.nodes[nid], [f], nid,
                           lambda f, why, nid=nid: exclude({"record": nid, "filter": f, "reason": why}))
                if not ok:
                    break
            if ok:
                kept.append(row)
        stages.append({"kind": "where", "rows_in": len(rows), "rows_out": len(kept)})
        rows = kept

    ev_vars = plan.get("evidence_vars")

    def cited(row: dict) -> list[dict]:
        """Evidence of the row's own records; shared kinds (species, reactions, materials, people) cite
        every source that mentions them, so they do not date a row unless evidence_vars names them."""
        out = []
        for var, nid in row.items():
            if var.startswith("_") or nid is None:
                continue
            if ev_vars is not None and var not in ev_vars:
                continue
            if ev_vars is None and g.nodes[nid]["label"] in SHARED_KINDS:
                continue
            for i, ev in enumerate(g.nodes[nid]["props"].get("evidence") or []):
                out.append({"var": var, "record": nid, "evidence": i, **ev, "source_year": g.year.get(ev.get("source"))})
        return out

    life, inclusion = g.life, g.inclusion

    def labelled(item: dict) -> dict:
        """The evidence item with its source's derived publication status (and, for a partial retraction
        recorded as a dataset, the retracted dataset that includes its record and comes from its source), its
        source's kind and peer review as recorded, and whether it is second-hand (ECO:0000033)."""
        item["source_status"] = lifecycle.status_of(life, item.get("source"))
        why = lifecycle.retracted_by(life, inclusion, item["record"], item.get("source"))
        if why and item["source_status"] not in lifecycle.RETRACTED:
            item["retracted_in_dataset"] = why[0]
        src = g.nodes.get(item.get("source")) or {}
        item["source_kind"] = (src.get("props") or {}).get("kind") or ("dataset" if src.get("label") == "Dataset" else None)
        item["source_peer_reviewed"] = (src.get("props") or {}).get("peer_reviewed")
        if _eco(item.get("evidence_type")) in SECOND_HAND_ECO:
            item["second_hand"] = True
        return item

    def all_evidence(row: dict) -> list[dict]:
        if "_ev" not in row:
            out = cited(row)
            for lid in row["_links"]:
                for i, ev in enumerate(link_by_id[lid]["props"].get("evidence") or []):
                    out.append({"var": link_by_id[lid]["type"], "record": lid, "evidence": i, **ev, "source_year": g.year.get(ev.get("source"))})
            row["_ev"] = [labelled(x) for x in out]
        return row["_ev"]

    def second_hand(row: dict) -> list[str]:
        """The sources of a row whose evidence is all second-hand; empty otherwise."""
        ev = all_evidence(row)
        if ev and all(x.get("second_hand") for x in ev):
            return sorted({x["source"] for x in ev if x.get("source")})
        return []

    retracted_rows = 0
    if life and not plan.get("include_retracted"):
        sound = []
        for row in rows:
            ev = all_evidence(row)
            gone = [x for x in ev if x["source_status"] in lifecycle.RETRACTED or x.get("retracted_in_dataset")]
            # a record a retracted dataset includes, though none of its evidence comes from the dataset's sources,
            # rests on the dataset itself: one more item of support, retracted
            alone = sorted({d for rid in {x["record"] for x in ev}
                            for d in lifecycle.unsourced_inclusions(inclusion, rid, {y.get("source") for y in ev if y["record"] == rid})})
            if ev and len(gone) == len(ev):
                retracted_rows += 1
                datasets = sorted({x["retracted_in_dataset"] for x in gone if x.get("retracted_in_dataset")} | set(alone))
                exclude({"record": row[root], "reason": "rests_on_retracted_source",
                         "sources": sorted({x["source"] for x in gone
                                            if x.get("source") and x["source_status"] in lifecycle.RETRACTED}),
                         **({"datasets": datasets} if datasets else {})})
            else:
                sound.append(row)
        stages.append({"kind": "retracted", "rows_in": len(rows), "rows_out": len(sound)})
        rows = sound

    before = plan.get("published_before")
    dated_out = 0
    if before:
        y = int(str(before)[:4])
        dated = []
        for row in rows:
            yrs = [ev["source_year"] for ev in all_evidence(row) if ev.get("source_year")]
            if yrs and max(yrs) < y:
                dated.append(row)
            else:
                dated_out += 1
                exclude({"record": row[root], "reason": (f"cites_later_source (cites a source from {max(yrs)}, not before {before})"
                                                         if yrs else f"no_dated_source (no dated source, not before {before})")})
        stages.append({"kind": "published_before", "rows_in": len(rows), "rows_out": len(dated)})
        rows = dated

    own_out = 0
    if plan.get("own_work_only"):
        own = []
        for row in rows:
            srcs = second_hand(row)
            if srcs:
                own_out += 1
                exclude({"record": row[root], "reason": "second_hand_only (all its evidence reports another work's "
                         "result: ECO:0000033)", "sources": srcs})
            else:
                own.append(row)
        stages.append({"kind": "own_work_only", "rows_in": len(rows), "rows_out": len(own)})
        rows = own

    tq = plan.get("text")
    if tq:
        if evidence_index is None:
            raise ScaleError("a text query needs the evidence index (scale graph index)")
        vars_ = tq.get("vars") or [root]
        # only the quotes this document holds choose rows: an index built from another document (a less open one, or
        # this one before an edit) never selects a row by text the document does not hold
        held = g.held
        hits = [h for h in evidence_index.search(tq["query"], k=tq.get("k", 500), mode=tq.get("mode", "hybrid"))
                if (h.get("record"), h.get("evidence"), h.get("text")) in held]
        score: dict[str, float] = {}
        for h in hits:
            if h["score"] >= tq.get("min_score", 0.0):
                score[h["record"]] = max(score.get(h["record"], 0.0), h["score"])
        scored = []
        for row in rows:
            ids = [row[v] for v in vars_ if row.get(v)] + [lid for lid in row["_links"]]
            s = max((score.get(i, 0.0) for i in ids), default=0.0)
            if s > 0:
                scored.append((s, row))
        scored.sort(key=lambda x: (-x[0], x[1][root]))
        stages.append({"kind": "text", "rows_in": len(rows), "rows_out": len(scored)})
        rows = [dict(r, _text_score=round(s, 4)) for s, r in scored]

    def name_of(sid: str) -> str:
        """A citing source as a second-hand note names it: its name or title when the whole document is public, else
        its id (a title says something about the source; the answer's access is the document's, and an id says no
        more than the evidence items do)."""
        if access["level"] != "public":
            return sid
        p = (g.nodes.get(sid) or {}).get("props") or {}
        return p.get("name") or p.get("title") or sid

    missing_ctx = []
    # (record, field): a record's missing field once, however many rows hold it and whichever variable binds it (a
    # record bound by two variables, test.pressure and test2.pressure, is listed under the first path that returns it)
    missing_at: set = set()
    out_rows = []
    second_hand_rows = 0
    for row in rows:
        vals = {}
        for r in plan.get("return") or []:
            var, _, prop = r.partition(".")
            nid = row["_edges"].get(var) if var in row["_edges"] else row.get(var)
            if nid is None:
                vals[r] = None
                continue
            rec = link_by_id[nid] if var in row["_edges"] else g.nodes[nid]
            v = returned(rec, prop) if prop else nid
            vals[r] = v
            why = absent_reason(v) if prop else None
            if why == "not_curated" and v is None and lookup(rec, prop)[1] is not None and lookup(rec, prop)[0] is not None:
                why = f"no_matching_entry ({prop})"      # the map or list is there; no entry is the one asked for
            at = ("link" if var in row["_edges"] else "node", nid, prop)
            if why and at not in missing_at:
                missing_at.add(at)
                missing_ctx.append({"record": nid, "field": r, "reason": why})
        srcs = second_hand(row)
        item = {"bound": {k: v for k, v in row.items() if not k.startswith("_")}, "links": row["_links"], "values": vals}
        if srcs:
            second_hand_rows += 1
            item["second_hand"] = {"cited_by": srcs, "note": f"second-hand (cited by {'; '.join(name_of(s) for s in srcs)})"}
        if "_text_score" in row:
            item["text_score"] = row["_text_score"]
        if plan.get("evidence"):
            ev = all_evidence(row)
            item["evidence"] = ev
            yrs = [e["source_year"] for e in ev if e.get("source_year")]
            item["earliest_source_year"] = min(yrs) if yrs else None
        out_rows.append(item)

    mixed_order: list[str] = []
    for ob in reversed(plan.get("order_by") or []):
        seen_units: set[str] = set()

        def key(it, ob=ob, seen_units=seen_units):
            nid = it["bound"].get(ob.get("var", root))
            v = returned(g.nodes[nid], ob["prop"]) if nid else None
            if isinstance(v, dict) and v.get("unit") and number(v) != (None, None):
                u = v["unit"]
                seen_units.add(u if isinstance(u, str) else f"(a unit that is not text: {type(u).__name__})")
            lo, hi = number(v)
            x = lo if lo is not None else hi
            return (x is None, x if x is not None else 0.0)
        out_rows.sort(key=key, reverse=bool(ob.get("desc")))
        if len(seen_units) > 1:
            mixed_order.append(f"{ob.get('var', root)}.{ob['prop']} ({', '.join(sorted(seen_units))})")
    total = len(out_rows)
    out_rows = out_rows[: plan.get("limit", 200)]
    stages.append({"kind": "limit", "rows_in": total, "rows_out": len(out_rows)})

    reasons = Counter(reason_code(x["reason"]) for x in excluded)
    lacking = len(excluded) - sum(reasons[r] for r in LEFT_OUT_ON_PURPOSE)      # left out for a missing or incomparable value
    in_steps: Counter = Counter()          # comparisons a step's filters could not make (a missing or incomparable value)
    for s in stages:
        in_steps.update(s.get("left_out_by_reason") or {})
    # rows a required step left out because a comparison could not be made (no link passed): like `lacking`. An
    # optional step's comparisons, and a step's on rows that pass or that later stages leave out, are only counted.
    step_rows = sum(s.get("rows_not_evaluated", 0) for s in stages)
    if out_rows:
        status = "answered"
    elif lacking or step_rows:             # the pattern reached records whose values the filters could not compare
        status = "missing_context"
    else:
        status = "no_matching_record"
    coverage = {"ran": True, "candidates": len(cands), "steps": stages, "link_types": link_types,
                "excluded": {"total": len(excluded), "listed": min(len(excluded), LISTED), "by_reason": dict(sorted(reasons.items()))},
                "compared_in_unit": len(compared), "retracted": retracted_rows, "published_before": dated_out,
                "second_hand_only": own_out, "second_hand_rows": second_hand_rows,
                "missing_context": {"total": len(missing_ctx), "listed": min(len(missing_ctx), LISTED)},
                "not_evaluated_in_steps": {"total": sum(in_steps.values()), "by_reason": dict(sorted(in_steps.items())),
                                           "rows": step_rows},
                "unfiltered": unfiltered(plan),
                **({"filtered_for": doc["graph"]["filtered_for"]} if doc["graph"].get("filtered_for") else {})}

    lim = ["An absence is an absence in this graph, not in the literature."]
    value_left = lacking - sum(reasons[r] for r in DATE_REASONS)
    if value_left:
        lim.append(f"{value_left} records were left out because a value the plan needs is missing, in another unit "
                   "or not comparable (each record once); see excluded and coverage.excluded.by_reason.")
    if in_steps:
        lim.append(f"{sum(in_steps.values())} comparisons in steps could not be made because a value is missing or not "
                   f"comparable ({', '.join(f'{k} {n}' for k, n in sorted(in_steps.items()))})"
                   + (f"; {step_rows} rows were left out by a required step because of them" if step_rows else "")
                   + "; see coverage.not_evaluated_in_steps and each step's left_out_by_reason.")
    bounds = reasons["one_sided_bound"] + in_steps["one_sided_bound"]
    if bounds:
        lim.append(f"{bounds} values are one-sided bounds (\"did not exceed\", \"at least\") that the filter could not decide, "
                   "and were left out (one_sided_bound); a bound is never read as the exact number.")
    unstated = reasons["unit_unstated"] + in_steps["unit_unstated"]
    if unstated:
        lim.append(f"{unstated} values were not compared because a unit is unstated: the filter's (a numeric filter states its "
                   "unit; give a step a `to` label so the plan check asks for one) or the value's (a value object without a "
                   "unit, or a plain number against a filter with one).")
    apart = {r: reasons[r] + in_steps[r] for r in ("incompatible_unit", "other_basis")}
    if any(apart.values()):
        lim.append(f"{sum(apart.values())} values were not compared for their unit or basis "
                   f"({', '.join(f'{k} {n}' for k, n in apart.items() if n)}): a filter compares only values in its own "
                   "unit, spelled the same, case included (mPa is not MPa, mol% is not %, barg is not bar), and on "
                   "the basis it states, or none as it states none; nothing is converted. Run one plan per unit and basis "
                   "(`scale graph stats` lists the units in use), and report each apart.")
    if dated_out:
        lim.append(f"{dated_out} rows were left out because they cite a source from {str(before)[:4]} or later, or no dated "
                   "source (published_before).")
    if retracted_rows:
        lim.append(f"{retracted_rows} rows rest only on retracted or withdrawn sources and were left out (rests_on_retracted_source; "
                   "include_retracted: true keeps them, labelled). A retraction does not make a finding false; it removes its support.")
    if own_out:
        lim.append(f"{own_out} rows rest only on second-hand evidence (ECO:0000033: a source reporting another work's result) "
                   "and were left out (own_work_only).")
    if second_hand_rows:
        lim.append(f"{second_hand_rows} rows rest only on second-hand evidence (ECO:0000033): say so and name the citing "
                   "source; cite the primary work where the graph holds it (own_work_only: true leaves such rows out).")
    if compared:
        lim.append(f"{len(compared)} values were compared in a filter's unit by their number, unit and stated basis alone: "
                   "nothing was converted, and a basis or condition written only in a value's reported text or note (gauge, "
                   "on hydrogen, per pass) was not read; return the value and read its as_reported and note before stating it.")
    if missing_ctx:
        lim.append(f"{len(missing_ctx)} returned fields are not reported or not curated (each record's field once); see "
                   "missing_context.")
    unseen = reasons["not_curated"] + reasons["no_matching_entry"] + in_steps["not_curated"] + in_steps["no_matching_entry"] \
        + sum(1 for x in missing_ctx if reason_code(x["reason"]) in ("not_curated", "no_matching_entry"))
    if doc["graph"].get("filtered_for") and unseen:
        lim.append(f"This document was filtered for a viewer (graph.filtered_for: {doc['graph']['filtered_for']}). A value the "
                   "filter withheld reads as withheld, but a reference it removed (a ref, a ref-list entry, a map entry keyed "
                   f"by a withheld id) reads as not there: {unseen} absences read as not_curated or no_matching_entry may be "
                   "withheld rather than not curated.")
    if len(excluded) > LISTED:
        lim.append(f"excluded lists the first {LISTED} of {len(excluded)} records left out; coverage.excluded.by_reason counts them all.")
    if coverage["unfiltered"] and out_rows:
        lim.append("The plan narrows nothing (coverage.unfiltered): the rows list every record the pattern reaches. A listing "
                   "is not an answer to a question that asks for a condition.")
    for o in mixed_order:
        lim.append(f"order_by {o} sorted values in several units as bare numbers; read each with its unit.")
    lim += _access_limitation(access, doc, as_of)
    return {**base, "status": status, "row_count": total, "rows": out_rows, "access": access, "excluded": excluded[:LISTED],
            "missing_context": missing_ctx[:LISTED], "coverage": coverage, "limitations": lim}


def document_access(doc: dict, as_of: str) -> dict:
    """The access of any answer drawn from ``doc``, failing closed: the least open effective stewardship found anywhere
    in the document, its header (``graph.stewardship``) and every node and link alike, notices, cited sources and
    datasets included, whether or not an answer shows them. Each is read as ``scale graph filter`` reads it
    (:func:`pgraph.effective_stewardship`, :func:`pgraph.openness`: an embargo on ``as_of`` (:func:`embargo_day`), a
    missing or malformed access is institution). Returns ``{level, note}``; the note says how many records are less
    open than public, and the date when an embargo was read."""
    graph = doc.get("graph") if isinstance(doc.get("graph"), dict) else {}
    header = pgraph.stewardship_of(graph.get("stewardship"))      # malformed: institution (fails closed)
    records = list(doc.get("nodes") or []) + list(doc.get("links") or [])
    sts = [pgraph.effective_stewardship(doc, r) for r in records]
    levels = [pgraph.openness(st, as_of) for st in sts]
    head = pgraph.openness(header, as_of)
    level = max([head, *levels], key=pgraph.OPENNESS.index)
    embargo = any(st.get("access") == "embargoed" for st in [header, *sts])
    on = f" (embargoes read on {as_of})" if embargo else ""
    if level == "public":
        return {"level": level, "note": f"Every record of the queried document, and its header, is public{on}: the answer "
                                         "carries no access limit of its own."}
    closed = sum(1 for lv in levels if lv != "public")
    what = (f"{closed} of its {len(levels)} records" + (" and its header" if head != "public" else "")) if closed else "its header"
    verb = "is" if (closed == 1 and head == "public") or not closed else "are"
    return {"level": level, "note": f"The queried document is not all public: {what} {verb} less open than public, the "
                                     f"least open {level}{on}. The answer may go only where the whole document may go."}


def embargo_day(as_of: Any, today: str) -> str:
    """The day a plan's embargoes are read on: its ``as_of`` (an ISO date, YYYY-MM-DD; anything else is a plan error)
    or ``today``, whichever is earlier. An embargo then counts as lapsed only when it has lapsed both on the plan's
    date and today: a later ``as_of`` never opens one still in force; an earlier one may keep one closed."""
    return pgraph.embargo_day(as_of, today, "as_of")     # the rule scale graph filter --date and the export follow


def _plain(x: Any) -> Any:
    """A date a YAML plan holds (``as_of: 2026-10-07`` unquoted) as its ISO text; nothing else is converted."""
    if isinstance(x, dt.date):
        return x.isoformat()
    raise TypeError(f"a plan holds only JSON values and dates, not {type(x).__name__}")


def _access_limitation(access: dict, doc: dict, as_of: str) -> list[str]:
    """The limitation line of an answer whose document is not all public (:func:`document_access`), with the way to a
    public answer: the public view ``scale graph filter`` makes, unless the document is that view already (then what
    keeps it closed: its header, which a view made before the filter declared its audience kept, or an embargo still
    in force on the day embargoes were read)."""
    if access["level"] == "public":
        return []
    line = (f"Access {access['level']}: the answer, every row, value, record named as left out and count of it, may go "
            "only where the whole queried document may go, to no person, host or model its stewardship does not admit "
            "(the least open of its header and records; no part of an answer is read as more open).")
    graph = doc.get("graph") if isinstance(doc.get("graph"), dict) else {}
    if pgraph.filtered_for_public(doc):
        header_closed = pgraph.openness(pgraph.stewardship_of(graph.get("stewardship")), as_of) != "public"
        line += (" This document is already the public view `scale graph filter --public` made (graph.filtered_for), so "
                 "filtering it again gives nothing more open: "
                 + ("its header is not public, as a view made before the filter declared its audience kept the original "
                    "document's header; make the public view again from the original document."
                    if header_closed else
                    f"it holds records under an embargo still in force on {as_of}, the day embargoes were read on (the "
                    "plan's as_of or today, whichever is earlier)."))
    elif graph.get("filtered_for"):
        line += (" This document is a view `scale graph filter` made for a reader (graph.filtered_for), and its answers go "
                 "only where it may go; for a public answer, query the view `scale graph filter --public` makes of the "
                 "original document.")
    else:
        line += (" For a public answer, run the query on the document `scale graph filter --public` makes (or `--as <id>` "
                 "for one reader): its answers have that view's own access.")
    return [line]


def load_plan(path: str | Path) -> dict:
    return load_doc(path)


def _render_value(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _render_coverage(cov: dict) -> list[str]:
    if not cov.get("ran"):
        return ["Coverage: the plan did not run."]
    lines = [f"Coverage: {cov['candidates']} candidates" + (" · **unfiltered**: a listing, not an answer to a condition"
                                                             if cov.get("unfiltered") else "")]
    for s in cov.get("steps") or []:
        if s["kind"] == "match":
            what = f"match {s.get('label') or s.get('id')}"
        elif s["kind"] == "step":
            arrow = "←" if s.get("direction") == "in" else "→"
            what = f"step {s['from']} {arrow}{s['edge']}{arrow} {s.get('to') or 'any'} ({s['as']}{', optional' if s.get('optional') else ''})"
        else:
            what = s["kind"]
        extra = ""
        if s.get("left_out_by_reason"):
            extra += " · not evaluated: " + ", ".join(f"{k} {n}" for k, n in s["left_out_by_reason"].items())
        if s.get("rows_not_evaluated"):
            extra += f" · rows left out unevaluated {s['rows_not_evaluated']}"
        if s.get("optional"):
            extra += f" · unbound {s.get('unbound', 0)}"
        lines.append(f"- {what}: {s['rows_in']} → {s['rows_out']}{extra}")
    ex = cov.get("excluded") or {}
    if ex.get("total"):
        lines.append(f"- left out by reason ({ex['listed']} of {ex['total']} listed): "
                     + ", ".join(f"{k} {n}" for k, n in ex["by_reason"].items()))
    if cov.get("compared_in_unit"):
        lines.append(f"- compared in a filter's unit (number, unit and stated basis; nothing converted): {cov['compared_in_unit']} values")
    if cov.get("second_hand_rows"):
        lines.append(f"- rows resting only on second-hand evidence: {cov['second_hand_rows']}")
    return lines


def render_markdown(res: dict) -> str:
    acc = res.get("access") or {}
    lines = [f"# {res.get('question') or 'Query'}", "", f"status: **{res['status']}** · rows: {res.get('row_count', 0)} · "
             f"graph {res['graph_id']} (scale-graph {res['schema_version']}, sha256 {res['graph_sha256'][:12]})"
             + (f" · access: **{acc['level']}**" if acc.get("level") else ""), ""]
    if acc.get("level") and acc["level"] != "public":
        lines += [f"Access: {acc['note']}", ""]
    if res.get("schema_gaps"):
        lines += ["Schema gaps:"] + [f"- {x}" for x in res["schema_gaps"]] + [""]
    for i, r in enumerate(res["rows"], 1):
        lines.append(f"## {i}. {r['bound']}")
        for k, v in r["values"].items():
            lines.append(f"- {k}: {_render_value(v)}")
        if r.get("second_hand"):
            lines.append(f"- **{r['second_hand']['note']}**")
        for ev in (r.get("evidence") or [])[:6]:
            q = f" — “{ev['quote']}”" if ev.get("quote") else ""
            tags = [str(ev.get("source_year"))]
            if ev.get("source_kind"):
                tags.append(ev["source_kind"])
            if ev.get("source_peer_reviewed") is False:
                tags.append("not peer reviewed")
            if ev.get("second_hand"):
                tags.append("second-hand")
            if ev.get("source_status") and ev["source_status"] != lifecycle.UNKNOWN:
                tags.append(ev["source_status"])
            lines.append(f"  - evidence ({', '.join(tags)}) {ev.get('source')}, {ev.get('locator')}{q}")
        lines.append("")
    if res.get("excluded"):
        lines.append(f"Excluded: {len(res['excluded'])} listed (first: {res['excluded'][0]})")
    if res.get("coverage"):
        lines += [""] + _render_coverage(res["coverage"])
    lines += ["", "Limitations:"] + [f"- {x}" for x in res["limitations"]]
    return "\n".join(lines) + "\n"
