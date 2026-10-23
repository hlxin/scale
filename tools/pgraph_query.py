"""Queries over scale-catal documents: graph patterns, property filters, evidence search, dated paths.

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
``levels.0`` (a list entry by position), ``result_values.meoh_yield_gc`` (a list entry by its id), ``results.*``
(every entry), each optionally narrowed to the entries whose value has every one of the fields it qualifies
(:data:`QUALIFIERS`: ``[target=<id>]``, ``[variable=<id>]``, ``[produced_by=<id>]``, ``[phase=gas]``, …;
``results.*[target=ex:t/species/co]``; ``selectivity[target=…]`` on a single value). A filter on several entries
holds when one of them passes and fails when every one fails; when none passes and one cannot be compared
(missing, withheld, in another unit, a bound), the record is left out with that entry's reason, never taken as
failing. The filters of one variable on one such path are held by one entry together (:func:`group`: two assays
never meet two conditions apart), and a returned path gives the entries that held them, else the entry, or the
selected entries by key or in order.

A step may bind one value entry instead of following an edge (docs/querying.md, "Results")::

    steps:
      - {from: test, entries: [result_values, yield], kind: product_yield, as: result}    # one row per entry
      - {from: result, field: target, to: ChemicalSpecies, as: product}                 # the record a field names
      - {from: result, field: produced_by, to: Experiment, as: assay, optional: true}

An ``entries`` step binds, per row, one entry of a value property of a node variable (of the quantity kinds
``kind`` names, its property's or its Variable's); a filter, a return and a ranking on it read ``value`` (the value
object itself), ``kind`` or a field of it, the row's ``bound`` names it as a record_ref (``record``, ``path``) and
the row cites the evidence it names (``evidence_ids``), never items of its record that only other entries cite. A
``field`` step follows one of its fields that names a record (``target``, ``variable``, ``produced_by``,
``calibration``, ``ref_value``, ``normalized_by``) to a record of the label ``to`` names; an ``unresolved_target``
is left out as such. Two entries of one record that nothing tells apart (:func:`results.repeated`) are flagged in
an ordinary answer (``ambiguous_repetition``) and left out of a scientific comparison, never averaged.

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

``comparison: scientific`` (scale-catal 0.3.0 on; :class:`Comparison`, docs/querying.md) also reads each value a numeric
filter or an ``order_by`` compares under its quantity contract: it is compared only in a unit of its kind's dimensions and
within one context of every context its kind is compared by (a potential's reference scale, a current density's
normalization, a pressure's convention, a volumetric flow's reference conditions, a share's species). A filter or a
ranking that states a context (``context: {potential_reference: rhe}``) checks it; one that states none groups the rows
(``comparison_group``, ``compared``, ``comparison.groups``), and a ranking orders rows within a group only. A value whose
context is not stated is left out as ``missing_context``, one whose statements disagree as ``incompatible_context``:
never assumed, never converted.

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

from . import lifecycle, passages, pgraph, quantities, results
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
_PATH = re.compile(r"^(?P<prop>[^.\[\]\s]+)(?:\.(?P<entry>[^.\[\]\s]+))?(?P<quals>(?:\[[a-z_]+=[^\]]+\])*)$")
_QUAL = re.compile(r"\[(?P<field>[a-z_]+)=(?P<value>[^\]]+)\]")
# the fields of a value object a path's qualifier selects entries by (all of them at once: one result's)
QUALIFIERS = ("target", "variable", "produced_by", "calibration", "phase", "stream", "id")


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

    @property
    def records(self) -> dict:
        """Every node and link by id (what a value's normalized_by names)."""
        if getattr(self, "_records", None) is None:
            self._records = {**{e["id"]: e for e in self.doc["links"] if isinstance(e.get("id"), str)}, **self.nodes}
        return self._records

    def is_a(self, nid: str, label: str) -> bool:
        n = self.nodes.get(nid)
        return bool(n) and (n["label"] == label or label in (self.spec["nodes"].get(n["label"], {}).get("ancestors") or []))

    def edge_types(self, edge: str) -> set:
        """An edge type and every edge type that specializes it, at any depth: a step on CONTROL_FOR follows
        DARK_CONTROL_FOR links too, as ``to: Experiment`` binds a CatalyticTest."""
        cache = self.__dict__.setdefault("_edge_types", {})
        if edge not in cache:
            out, grew = {edge}, True
            while grew:
                grew = False
                for name, d in (self.spec.get("edges") or {}).items():
                    if name not in out and d.get("specializes") in out:
                        out.add(name)
                        grew = True
            cache[edge] = out
        return cache[edge]


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


def comparable(v: dict, unit: Any, basis: Any = None, read_basis: bool = False) -> str | None:
    """Why a value object cannot be compared with a numeric filter in ``unit`` (and on ``basis``), or None when it
    can. The one rule: the filter states its unit; the value holds a number (``value``, or ``lower``/``upper``), its
    unit is text spelled as the filter's, case included, whitespace runs aside (:func:`unit_key`), and its basis is
    the filter's, compared the same way, or absent as the filter's is. Reasons: ``unit_unstated`` (the filter or the
    value states no unit), ``not_a_number``, ``incompatible_unit`` (another unit, or one that is not text) and
    ``other_basis`` (another basis, or a basis on one side only). Nothing else is read: no conversion, and no basis
    from the unit, the reported text or the note. A value whose unit is the placeholder ``not stated`` (any case and
    spacing, :func:`pgraph.states_no_unit`) states none. A filter unit or basis that is not text, and a filter unit
    ``not stated``, are plan errors. ``read_basis`` (a scientific comparison of a kind whose contexts read the value's
    basis): a filter that states no basis compares the value whatever its basis says, which its contexts have read."""
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
    if read_basis and not _stated(basis):
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
def parse_path(path: Any) -> tuple[str, str | None, tuple[tuple[str, str], ...]]:
    """(property, entry, qualifiers) of a property path: ``temperature``, ``results.methanol_yield``, ``levels.0``,
    ``results.*``, ``results.*[target=ex:t/species/co]``, ``selectivity[variable=ex:t/var/x]``,
    ``result_values.*[variable=ex:t/var/yield][target=ex:t/species/methanol][produced_by=ex:t/assay/gc]``: each
    qualifier a field of the value object (:data:`QUALIFIERS`), and an entry selected only when it has every one."""
    m = _PATH.match(str(path or ""))
    if not m:
        raise ScaleError(f"cannot read the property path {path!r}: a property, optionally .<key>, .<position> or .* "
                         "for an entry of a map or list, then optionally qualifiers [<field>=<value>] "
                         f"({', '.join(QUALIFIERS)})")
    quals = tuple((q["field"], q["value"]) for q in _QUAL.finditer(m["quals"] or ""))
    bad = [f for f, _ in quals if f not in QUALIFIERS]
    if bad:
        raise ScaleError(f"the property path {path!r} qualifies entries by {bad}: a qualifier is one of {list(QUALIFIERS)}")
    return m["prop"], m["entry"], quals


def selects_entries(path: Any) -> bool:
    """Whether a path selects entries of a map or list (or qualifies a value), rather than naming a property."""
    _, entry, quals = parse_path(path)
    return entry is not None or bool(quals)


def lookup(rec: dict, path: str) -> tuple[Any, list[tuple[Any, Any]] | None]:
    """(the property's value, the entries the path selects); the entries are None for a plain property."""
    prop, entry, quals = parse_path(path)
    v = rec.get(prop) if prop in ("id", "label", "type") else (rec.get("props") or {}).get(prop)
    if entry is None and not quals:
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
            i = results.item(v, entry)                                   # a position, or the id of one item
            items = [(i, v[i])] if i is not None else []
    elif isinstance(v, dict) and entry is None:                     # a qualifier on a single value
        items = [(None, v)]
    else:
        items = []
    for field, want in quals:
        items = [(k, x) for k, x in items if isinstance(x, dict) and x.get(field) == want]
    return v, items


def returned(rec: dict, path: str, keys: list | None = None) -> Any:
    """The value a returned path gives: the property, the one entry it names, or the entries it selects (by key
    for a map, in order for a list); None when nothing is selected. ``keys``: the entries the row's filters bound
    on this path (one result passing them all), which are then the only ones it gives."""
    v, items = lookup(rec, path)
    if items is None:
        return v
    _, entry, _ = parse_path(path)
    if keys is not None:
        items = [(k, x) for k, x in items if k in keys]
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


LIMIT_STATUSES = {"below_detection_limit": "detection", "below_quantification_limit": "quantification"}


def limit_as_bound(v: Any) -> Any:
    """A value below its detection or quantification limit (``value`` the limit) can only lie below it: read as an
    upper bound at the limit (``bound: upper``, status ``present``), with ``_limit`` naming what it was. Anything else
    is returned as it is, so a limit status without a number stays absent."""
    if isinstance(v, dict) and v.get("status") in LIMIT_STATUSES and _is_number(v.get("value")) and not v.get("bound"):
        return {**v, "status": "present", "bound": "upper", "_limit": LIMIT_STATUSES[v["status"]]}
    return v


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


def _numeric(v: Any, f: dict, op: str, read_basis: bool = False) -> tuple[bool | None, str | None]:
    """A numeric filter on a value object (:func:`comparable`) or a plain number: (result, None) or (None, reason)."""
    want = f.get("value")
    xs = [_as_number(x) for x in (want if op == "in" else [want])]
    unit = f.get("unit")
    if isinstance(v, dict):
        why = comparable(v, unit, f.get("basis"), read_basis)
        if why:
            return None, why
        side = v.get("bound")
        if side in ("upper", "lower") and _is_number(v.get("value")):      # "did not exceed 1 %", "at least 2"
            r = against_bound(side, float(v["value"]), op, want)
            if r is None:
                what = (f"below the {v['_limit']} limit" if v.get("_limit")
                        else f"the value is {'at most' if side == 'upper' else 'at least'}")
                return None, (f"one_sided_bound ({what} "
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
    if numeric_filter(f):
        v = limit_as_bound(v)           # below a limit: at most the limit
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


# ------------------------------------------------------------------------------------------ scientific comparison
COMPARISONS = ("ordinary", "scientific")
CONTEXT_REASONS = ("missing_context", "incompatible_context")


class Comparison:
    """How a plan's numeric filters and ranking compare values (``comparison``).

    ``ordinary`` (the default) compares a value as reported: a number in the filter's unit and on its basis, as
    :func:`comparable` says. ``scientific`` also reads each value under its quantity contract (``quantities``): a value
    is compared only when its unit is read as one of its kind's dimensions, and only within one context of every
    context its kind is compared by (a potential's reference scale, a current density's normalization, a pressure's
    convention, a volumetric flow's reference conditions, an efficiency's product). A filter or a ranking that states
    a context (``context: {potential_reference: rhe}``) checks it: a value on another one is left out as
    ``incompatible_context``. One that states none groups: each row carries the unit and contexts of the values it was
    compared on (``comparison_group``), and a ranking orders rows within a group only. A value whose context is not
    stated, or is stated as other or not reported, is left out as ``missing_context``: never assumed; one whose
    statements disagree (its basis and its record's sibling) as ``incompatible_context``, unless it is an evidenced
    conversion (derived or computed, with produced_by). A value whose ``normalized_by`` names a value that is not
    reported, or that the view withholds, is left out as ``missing_context``; one divided by a one-sided bound is
    compared as reported, its row's denominator showing the bound (a rate divided by at most N sites is at least the
    quotient). A value whose kind says how it was calculated (a turnover frequency) is compared as reported whatever its
    basis says (per exposed atom, per site of a kind), its basis and denominator kept in its row. Nothing is
    converted."""

    def __init__(self, plan: dict, spec: dict, g: Graph):
        mode = plan.get("comparison", "ordinary")
        if mode not in COMPARISONS:
            raise ScaleError(f"comparison is one of {list(COMPARISONS)}, not {mode!r}")
        self.scientific = mode == "scientific"
        self.c = quantities.contracts(spec)
        if self.scientific and self.c is None:
            raise ScaleError(f"comparison: scientific reads values under their quantity contracts, which this schema "
                             f"(scale-catal {spec.get('version')}) does not have; migrate the document (scale graph migrate)")
        self.spec, self.g = spec, g
        self.variables = quantities.variable_kinds(g.doc) if self.c is not None else {}
        self.across: dict[str, Counter] = {}       # ordinary mode: path -> the contexts its compared values were on

    def read(self, rec: dict, path: str, x: Any) -> quantities.Read | None:
        """A value read under its contract: a property's (its binding, else its Variable's quantity_kind), or, for a
        bound entry (:data:`ENTRY`), the contract of the property it is an entry of, with that record's siblings."""
        if self.c is None or not isinstance(x, dict):
            return None
        e = rec.get("_entry")
        if e is not None:
            return quantities.read_value(self.c, self.spec, e["owner"], e["prop"], x, self.g.records, self.variables)
        return quantities.read_value(self.c, self.spec, rec, parse_path(path)[0], x, self.g.records, self.variables)

    def kind(self, owner: dict, prop: str, x: dict) -> str | None:
        """The quantity kind of an entry of ``owner``'s ``prop``: the property's binding, else its Variable's."""
        if self.c is None:
            return None
        k = quantities.binding(self.spec, owner, prop)[0]
        if k is None and isinstance(x.get("variable"), str):
            k = self.variables.get(x["variable"])
        return k if k in self.c.kinds else None

    def reads_basis(self, kind: str) -> bool:
        """Whether a value's basis is read, not compared as text: its kind's contexts read it, or it says how the value
        was calculated (a kind whose denominator is marked unstated: a turnover frequency's per exposed atom)."""
        return bool(self.c.kinds[kind].get("denominator_unstated")) or \
            any("basis" in self.c.contexts[e["context"]]["read_from"] for e in self.c.kinds[kind]["compare_by"])

    def _context(self, path: str, got: quantities.Read, want: dict, wanted_unit: Any = None) -> str | None:
        """Why a value read under its contract cannot be compared on ``want`` (and in ``wanted_unit``), or None."""
        kind, r = got.kind, got.reading
        if r is not None and not r.read:
            return (f"incompatible_unit ({r.text!r} is not a unit the quantity contracts read ({' '.join(r.unread)}), so "
                    f"its dimension as a {kind} is unknown)")
        if r is not None and r.vector not in self.c.kinds[kind]["dimensions"]:
            return f"incompatible_unit ({r.text!r} is {self.c.dimension_name(r.vector)}, not a dimension of {kind})"
        for name, ctx in got.contexts.items():
            if ctx.contradiction:
                return f"incompatible_context ({path} {name}: contradictory: {ctx.contradiction})"
            if ctx.missing:
                return f"missing_context ({path} {name}: {ctx.missing})"
            if name in want and ctx.value not in (want[name],) and ctx.value.split(":")[0] != want[name]:
                return f"incompatible_context ({path} {name} {ctx.value}; compared on {want[name]})"
        for name in want:
            if name not in got.contexts:
                return f"incompatible_context ({path}: a {kind} here is not compared by {name})"
        den = got.denominator
        if den is not None and den["path"] is not None:
            dv = den["value"]
            if not den["found"] or dv is None:
                return f"missing_context ({path}: its normalized_by {den['record']}{den['path']} names no value here)"
            why = absent_reason(dv)
            if why or not quantities.numbered(dv):
                return f"missing_context ({path}: its normalized_by {den['record']}{den['path']} is {why or 'not a number'})"
        elif den is not None and not den["found"]:
            return f"missing_context ({path}: its normalized_by {den['record']} is not in this graph (withheld or never curated))"
        if wanted_unit is not None and _stated(wanted_unit) and r is not None and unit_key(r.text) != unit_key(str(wanted_unit)):
            return f"incompatible_unit ({r.text!r}; the ranking is in {wanted_unit!r})"
        return None

    def tag(self, got: quantities.Read | None, x: dict) -> dict:
        """The unit, kind and contexts a value was compared on (and its denominator, with what the named value says of
        its origin; whether it is an evidenced conversion; what its producer states of the properties its kind shows)."""
        out = {"unit": unit_key(x["unit"]) if isinstance(x.get("unit"), str) else None}
        if got is not None:
            out["kind"] = got.kind
            if got.contexts:
                out["context"] = {n: ctx.value for n, ctx in sorted(got.contexts.items())}
            shown = {k: (v if v is not None else quantities.NOT_STATED) for k, v in got.shown.items()
                     if v is not None or k in self.c.warned(got.kind)}         # what is stated, and what should be
            if shown:
                out["shows"] = shown
            conv = sorted(n for n, ctx in got.contexts.items() if ctx.converted)
            if conv:
                out["converted"] = conv
            den = got.denominator
            if den is not None:
                dv = den["value"] or {}
                out["denominator"] = {"record": den["record"], **({"path": den["path"]} if den["path"] else {}),
                                      **({"origin": dv["origin"]} if isinstance(dv.get("origin"), str) else {}),
                                      **({"bound": dv["bound"]} if dv.get("bound") in ("upper", "lower") else {})}
        return out

    def check(self, rec: dict, f: dict) -> tuple[bool | None, str | None, dict | None]:
        """A numeric filter in scientific mode: (result, None, the tag of the value it passed on) or (None, reason,
        None). A path selecting several entries holds when one passes, as :func:`check` says."""
        v, items = lookup(rec, f.get("prop"))
        vals = [v] if items is None else [x for _, x in items]
        if items is not None and not vals:
            return None, ("not_curated" if v is None else f"no_matching_entry ({f.get('prop')})"), None
        first = None
        for x in vals:
            r, why, tag = self.check_one(rec, f, x)
            if r:
                return True, None, tag
            if r is None:
                first = first or why
        return (False, None, None) if first is None else (None, first, None)

    def check_one(self, rec: dict, f: dict, x: Any) -> tuple[bool | None, str | None, dict | None]:
        """One value (a property, or one entry the path selects) against a numeric filter in scientific mode. On a
        bound entry (:data:`ENTRY`) a filter in a unit of another dimension than the entry's kind leaves the entry out
        (incompatible_unit: entries of several kinds may be bound); on a property it is a plan error."""
        op = f.get("op", "eq")
        want = f.get("context") or {}
        x = limit_as_bound(x)
        why = absent_reason(x)
        if why:
            return None, why, None
        got = self.read(rec, f["prop"], x)
        if got is None:
            if want:
                return None, (f"missing_context ({f['prop']}: no quantity contract says which "
                              f"{', '.join(sorted(want))} it is on)"), None
            r, why = _numeric(x, f, op) if isinstance(x, dict) or _is_number(x) else (None, "not_a_number")
            return r, why, (self.tag(None, x) if r and isinstance(x, dict) else None)
        fr = self.c.read_unit(f.get("unit"))
        dims = self.c.kinds[got.kind]["dimensions"]
        if fr.read and fr.vector not in dims:
            said = (f"the filter {f.get('prop')} {op} {f.get('value')} {f.get('unit')} compares a {got.kind} in "
                    f"{self.c.dimension_name(fr.vector)}, not one of its dimensions "
                    f"({', '.join(self.c.dimension_name(d) for d in dims)})")
            if rec.get("_entry") is not None:
                return None, f"incompatible_unit ({said})", None
            raise ScaleError(said)
        why = self._context(f["prop"], got, want)
        if why is not None:
            return None, why, None
        r, why = _numeric(x, f, op, read_basis=self.reads_basis(got.kind))
        return r, why, (self.tag(got, x) if r else None)

    def rank(self, rec: dict, ob: dict, keys: list | None = None) -> tuple[dict | None, str | None]:
        """A ranking value in scientific mode: (its tag, None) or (None, why it cannot be ranked). ``keys``: the entries
        the row's filters bound on the ranked path."""
        prop = ob.get("prop")
        v = returned(rec, prop, keys) if rec is not None else None
        if isinstance(v, list) and len(v) == 1:                 # a path selecting one entry ranks it
            v = v[0]
        if isinstance(v, list):
            return None, f"missing_context ({prop} selects {len(v)} values; a ranking names one: an entry or [target=...])"
        v = limit_as_bound(v)
        why = absent_reason(v)
        if why:
            return None, why
        if not isinstance(v, dict) or number(v) == (None, None):
            return None, f"not_a_number ({prop} holds no number to rank)"
        if v.get("bound") in ("upper", "lower"):
            what = f"below its {v['_limit']} limit" if v.get("_limit") else f"{'at most' if v['bound'] == 'upper' else 'at least'} its number"
            return None, f"one_sided_bound ({prop} is {what}; a bound is not ranked)"
        if pgraph.states_no_unit(v.get("unit")):
            return None, f"unit_unstated ({prop} states no unit)"
        got = self.read(rec, prop, v)
        if got is None:
            if ob.get("context"):
                return None, f"missing_context ({prop}: no quantity contract says which {', '.join(sorted(ob['context']))} it is on)"
            if _stated(ob.get("unit")) and unit_key(str(v.get("unit"))) != unit_key(str(ob["unit"])):
                return None, f"incompatible_unit ({v.get('unit')!r}; the ranking is in {ob['unit']!r})"
            return self.tag(None, v), None
        why = self._context(prop, got, ob.get("context") or {}, ob.get("unit"))
        return (None, why) if why else (self.tag(got, v), None)

    def observe(self, rec: dict, path: str) -> None:
        """Ordinary mode: the contexts of the values a numeric filter or a ranking compared, for the advisory that
        names comparisons made across contexts (:meth:`limitations`)."""
        if self.c is None or self.scientific:
            return
        v, items = lookup(rec, path)
        for x in ([v] if items is None else [x for _, x in items]):
            got = self.read(rec, path, x)
            if got is None or not got.contexts:
                continue
            sig = "; ".join([f"kind {got.kind}"] + [f"{n} {ctx.value or ('contradictory' if ctx.contradiction else 'not stated')}"
                                                     for n, ctx in sorted(got.contexts.items())])
            self.across.setdefault(path, Counter())[sig] += 1

    def limitations(self) -> list[str]:
        out = []
        for path, sigs in sorted(self.across.items()):
            if len(sigs) > 1 or any("not stated" in k or "contradictory" in k for k in sigs):
                out.append(f"{path} was compared across contexts its quantity contract keeps apart ("
                           + ", ".join(f"{k}: {n}" for k, n in sorted(sigs.items()))
                           + "); `comparison: scientific` compares and ranks values only within one context, and leaves "
                             "out those whose context is not stated (docs/querying.md).")
        return out


# ------------------------------------------------------------------------------------------ plan checks
ENTRY = "(a value entry)"           # the label of a variable an entries step binds: one value object, not a record
LINK_ENDS = ("source", "target")    # the end of a link a field step that follows one binds
ENTRY_PROPS = ("value", "kind")     # what a filter, a return or a ranking reads of an entry besides its value's fields


def step_kind(st: dict) -> str:
    """``edge`` (follow links), ``entries`` (bind one value entry of a record's property) or ``field`` (follow a field
    of a bound entry to the record it names)."""
    kinds = [k for k in ("edge", "entries", "field") if k in st]
    if len(kinds) != 1:
        raise ScaleError(f"a step follows an edge, binds entries or follows a field (one of edge, entries, field), not "
                         f"{kinds or 'none'}: {st}")
    return kinds[0]


def _entry_def(spec: dict, prop: str) -> dict | None:
    """What a filter or a return reads of a bound entry: ``value`` (the value object itself), ``kind`` (its quantity
    kind) or one of its fields."""
    if prop == "value":
        return {"type": "value"}
    if prop == "kind":
        return {"type": "string"}
    return ((spec.get("value") or {}).get("fields") or {}).get(prop)


def _prop_def(spec: dict, label: str | None, prop: str, edge: bool = False) -> dict | None:
    if label == ENTRY:
        return _entry_def(spec, prop)
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
    """(node variable -> label, link variable -> edge type) as the plan declares them; a variable an entries step binds
    has the label :data:`ENTRY`."""
    labels = {plan["match"]["as"] if "as" in plan["match"] else "self": plan["match"].get("label")}
    edge_vars: dict[str, str] = {}
    for st in plan.get("steps") or []:
        labels[st["as"]] = ENTRY if step_kind(st) == "entries" else st.get("to")
        if st.get("edge_as") and step_kind(st) == "edge":
            edge_vars[st["edge_as"]] = st["edge"]
        elif st.get("edge_as") and step_kind(st) == "field" and st.get("link"):
            edge_vars[st["edge_as"]] = st["link"]
    return labels, edge_vars


def entry_vars(plan: dict) -> dict[str, dict]:
    """The variables entries steps bind, with their steps."""
    return {st["as"]: st for st in plan.get("steps") or [] if step_kind(st) == "entries"}


def _filters(plan: dict) -> list[tuple[dict, str | None, bool]]:
    """Every filter of the plan with the label or edge type it reads and whether that is a link."""
    labels, edge_vars = _variables(plan)
    root = plan["match"].get("as", "self")
    out = [(f, plan["match"].get("label"), False) for f in plan["match"].get("where") or []]
    for st in plan.get("steps") or []:
        out += [(f, labels[st["as"]], False) for f in st.get("where") or []]
        out += [(f, st["edge"], True) for f in st.get("edge_where") or []] if step_kind(st) == "edge" else []
        out += [(f, st["link"], True) for f in st.get("edge_where") or []] \
            if step_kind(st) == "field" and st.get("link") else []
    for f in plan.get("where") or []:
        var = f.get("var", root)
        if var in edge_vars and var not in labels:
            out.append((f, edge_vars[var], True))
        else:
            out.append((f, labels.get(var), False))
    return out


def _value_prop(spec: dict, label: str | None, prop: str, edge: bool = False) -> bool | None:
    """Whether a property holds values (one value, a list or a map of them); None when the schema does not say."""
    d = _prop_def(spec, label, prop, edge)
    if d is None:
        return None
    return d.get("type") == "value" or (d.get("type") in ("list", "map") and (d.get("items") or {}).get("type") == "value")


def _check_steps(plan: dict, spec: dict, qc: quantities.Contracts | None) -> None:
    """An entries step binds a value property's entries of a node variable (optionally of quantity kinds the contracts
    declare); a field step follows a field that names a record (:data:`results.REF_FIELDS`) from a variable an entries
    step binds; an edge step never starts from an entry."""
    labels, edge_vars = _variables(plan)
    entries = entry_vars(plan)
    for st in plan.get("steps") or []:
        kind, src = step_kind(st), st.get("from", plan["match"].get("as", "self"))
        if kind == "edge" and src in entries:
            raise ScaleError(f"the step {st['edge']} from {src}: {src} is a value entry, which has no links; follow one of "
                             f"its fields with a field step ({', '.join(results.REF_FIELDS)})")
        if kind == "entries":
            stray = sorted(set(st) & {"to", "edge_where", "edge_as", "direction"})
            if stray or src in entries or (src in edge_vars and src not in labels):
                raise ScaleError(f"the entries step {st['as']} binds one value entry of a property of a node variable "
                                 f"(from {src}){'; it takes no ' + ', '.join(stray) if stray else ''}")
            props = st["entries"] if isinstance(st["entries"], list) else [st["entries"]]
            if not props or not all(isinstance(x, str) and x for x in props):
                raise ScaleError(f"the entries step {st['as']}: entries names a value property (or a list of them)")
            for prop in props:
                if _value_prop(spec, labels.get(src), prop) is False:
                    raise ScaleError(f"the entries step {st['as']}: {prop} holds no values (an entries step binds the "
                                     "value, the items of a list of values or the entries of a map of values)")
            for k in ([st["kind"]] if isinstance(st.get("kind"), str) else st.get("kind") or []):
                if qc is None or k not in qc.kinds:
                    raise ScaleError(f"the entries step {st['as']}: kind {k!r} is not a quantity kind this schema declares"
                                     + (f" ({', '.join(sorted(qc.kinds))})" if qc else " (quantity contracts: 0.3.0 on)"))
        if kind == "field":
            if src not in entries:
                raise ScaleError(f"the field step {st['as']} follows a field of a value entry: from names a variable an "
                                 f"entries step binds, not {src!r}")
            if st["field"] not in results.REF_FIELDS:
                raise ScaleError(f"the field step {st['as']} follows {st['field']!r}; a field that names a record is one of "
                                 f"{list(results.REF_FIELDS)}")
            stray = sorted(set(st) & ({"direction"} if st.get("link") else {"edge_where", "edge_as", "direction", "end"}))
            if stray:
                raise ScaleError(f"the field step {st['as']} takes no {', '.join(stray)}"
                                 + ("" if st.get("link") else " (edge_as, edge_where and end follow a link: name its type "
                                                                "with link)"))
            if st.get("link") and st.get("end") not in LINK_ENDS:
                raise ScaleError(f"the field step {st['as']} follows a {st['link']} link: end says which of its ends it "
                                 f"binds ({' or '.join(LINK_ENDS)})")
            if st.get("link") and st["field"] != "normalized_by":
                raise ScaleError(f"the field step {st['as']}: only normalized_by names a link (a record_ref); "
                                 f"{st['field']} names a node")


def check_plan(plan: dict, spec: dict) -> None:
    """Errors in a plan, raised: a property path that cannot be read, an entry of a property that is no map or
    list, a numeric filter (:func:`numeric_filter`: lt, le, gt, ge, and eq, ne or in with numbers) without a unit on
    a property the schema declares as a value, ``lt``, ``le``, ``gt`` or ``ge`` with a value that is not a number, a
    unit that is not non-empty text or is the placeholder ``not stated`` (:data:`NOT_STATED_REFUSED`), a ``basis``
    that is not non-empty text or on a filter that compares no number in a unit, ``convert``
    (:data:`CONVERT_REFUSED`: nothing is converted), and a step that is not an edge, entries or field step as
    :func:`_check_steps` says."""
    if plan.get("convert") not in (None, False):
        raise ScaleError(CONVERT_REFUSED)
    mode = plan.get("comparison", "ordinary")
    if mode not in COMPARISONS:
        raise ScaleError(f"comparison is one of {list(COMPARISONS)}, not {mode!r}")
    qc = quantities.contracts(spec)
    _check_steps(plan, spec, qc)
    labels, edge_vars = _variables(plan)
    for f, label, edge in _filters(plan):
        what = f"the filter {f.get('prop')} {f.get('op')} {f.get('value')}"
        if f.get("convert") not in (None, False):
            raise ScaleError(f"{what}: {CONVERT_REFUSED}")
        if "context" in f:
            if mode != "scientific":
                raise ScaleError(f"{what} states a context, which only `comparison: scientific` reads")
            _check_context(f["context"], qc, what)
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
        prop, entry, quals = parse_path(f.get("prop"))
        d = _prop_def(spec, label, prop, edge)
        if d is None:
            continue
        t = d.get("type")
        if entry is not None and t not in ("map", "list"):
            raise ScaleError(f"{label}.{prop} is not a map or list, so {f.get('prop')!r} names no entry")
        valued = t == "value" or (t in ("map", "list") and (entry is not None or quals)
                                  and (d.get("items") or {}).get("type") == "value")
        if numeric_filter(f) and t in ("map", "list") and entry is None and not quals \
                and (d.get("items") or {}).get("type") == "value":
            raise ScaleError(f"the filter {f.get('prop')} {f.get('op')} {f.get('value')} on {label} compares a whole "
                             f"{t} with a number: name its entries ({f.get('prop')}.* for every entry, .<key> or .<position> "
                             f"for one, optionally [target=<id>]), or bind one entry with an entries step")
        if numeric_filter(f) and valued and not f.get("unit"):
            raise ScaleError(f"the filter {f.get('prop')} {f.get('op')} {f.get('value')} on {label} states no unit: a "
                             f"numeric filter on a value object compares only values in the unit it states (add unit)")
        kind = d.get("quantity") if mode == "scientific" and qc is not None else None   # a value, or a list of values
        if kind in (qc.kinds if qc else {}) and numeric_filter(f):
            _check_compared(f, kind, qc, f"{what} on {label}.{prop}")
    for r in plan.get("return") or []:
        var, _, path = r.partition(".")
        if path:
            prop, entry, _ = parse_path(path)
            edge = var in edge_vars and var not in labels
            d = _prop_def(spec, edge_vars[var] if edge else labels.get(var), prop, edge)
            if d is not None and entry is not None and d.get("type") not in ("map", "list"):
                raise ScaleError(f"{prop} is not a map or list, so the return {r!r} names no entry")
    for ob in plan.get("order_by") or []:
        parse_path(ob.get("prop"))
        if ("context" in ob or "unit" in ob) and mode != "scientific":
            raise ScaleError(f"order_by {ob.get('prop')} states a context or a unit, which only `comparison: scientific` reads "
                             "(an ordinary ranking orders the numbers as reported)")
        if "context" in ob:
            _check_context(ob["context"], qc, f"order_by {ob.get('prop')}")
        if "unit" in ob and (not isinstance(ob["unit"], str) or pgraph.states_no_unit(ob["unit"])):
            raise ScaleError(f"order_by {ob.get('prop')} ranks in the unit {ob.get('unit')!r}: a unit is text, never 'not stated'")


def _check_context(ctx: Any, qc: quantities.Contracts | None, what: str) -> None:
    """A stated context: a mapping of declared contexts to one of their values (any record id for an open one)."""
    if qc is None:
        raise ScaleError(f"{what} states a context, but this schema declares no quantity contracts (scale-catal 0.3.0 on)")
    if not isinstance(ctx, dict) or not ctx:
        raise ScaleError(f"{what}: context is a mapping of contexts to values, e.g. {{potential_reference: rhe}}")
    for name, val in ctx.items():
        c = qc.contexts.get(name)
        if c is None:
            raise ScaleError(f"{what}: {name!r} is not a context the quantity contracts declare ({sorted(qc.contexts)})")
        if not isinstance(val, str) or not val.strip() or (not c["open"] and val.split(":")[0] not in c["values"]):
            raise ScaleError(f"{what}: {name} {val!r} is not one of its values ({sorted(c['values']) or 'a record id'})")


def _check_compared(f: dict, kind: str, qc: quantities.Contracts, what: str) -> None:
    """A scientific filter on a bound property: its unit of one of the kind's dimensions, its contexts the kind's, and
    no basis where the kind's contexts read the basis (state the context instead)."""
    r = qc.read_unit(f.get("unit"))
    dims = qc.kinds[kind]["dimensions"]
    if r.read and r.vector not in dims:
        raise ScaleError(f"{what} compares a {kind} in {f.get('unit')!r}, which is {qc.dimension_name(r.vector)}, not one of "
                         f"its dimensions ({', '.join(qc.dimension_name(x) for x in dims)})")
    named = [e["context"] for e in qc.kinds[kind]["compare_by"]]
    extra = sorted(set(f.get("context") or {}) - set(named))
    if extra:
        raise ScaleError(f"{what} states the context {', '.join(extra)}, which a {kind} is not compared by "
                         f"({', '.join(named) or 'none'})")
    if "basis" in f and any("basis" in qc.contexts[n]["read_from"] for n in named):
        raise ScaleError(f"{what} states a basis; in a scientific comparison a {kind}'s basis is read as its context "
                         f"({', '.join(named)}): state context instead")


def schema_gaps(plan: dict, spec: dict, values: bool = False) -> list[str]:
    """What a plan names that the schema does not declare: a label, an edge type, a property. With ``values``, also a
    filter that asks a property of a vocabulary (an enum, or a list of one) only for values the vocabulary does not hold
    (eq, in or contains; compared as eq compares, ignoring case): a document of that schema cannot state it, so the
    plan's answer would be a schema gap, not an absence (``scale trace-ai`` reads its plans so)."""
    gaps = []
    labels = {plan["match"]["as"] if "as" in plan["match"] else "self": plan["match"].get("label")}
    edge_vars: dict[str, str] = {}

    def has_prop(label: str | None, prop: str, edge: bool = False) -> bool:
        prop = parse_path(prop)[0]
        if label == ENTRY:
            return _entry_def(spec, prop) is not None
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

    def where_of(label: str | None, prop: str) -> str:
        return f"{'a value entry' if label == ENTRY else label}.{parse_path(prop)[0]}"

    def value_gap(label: str | None, f: dict, edge: bool = False) -> None:
        """Record a gap when ``f`` asks a vocabulary only for what it does not hold, as the filter compares (with
        ``values``): eq a value ignoring case, or a list item by item as written; in one of its values as written;
        contains a part of a value, ignoring case. An entry of a list of a vocabulary is one of its values."""
        op = f.get("op", "eq")
        if not values or label in (None, ENTRY) or op not in ("eq", "in", "contains"):
            return
        prop, entry, quals = parse_path(f["prop"])
        if quals:
            return
        c = spec["common"]["link" if edge else "node"]
        d = (c.get("properties", c)).get(prop) or ((spec["edges" if edge else "nodes"].get(label) or {})
                                                    .get("properties") or {}).get(prop)
        if not isinstance(d, dict):
            return
        if d.get("type") == "enum" and entry is None:
            members, many = d.get("values"), False
        elif d.get("type") == "list" and isinstance(d.get("items"), dict) and d["items"].get("type") == "enum":
            members, many = d["items"].get("values"), entry is None        # the list itself, or one entry of it
        else:
            return
        if not isinstance(members, list) or not members:
            return
        want, low = f.get("value"), [str(m).lower() for m in members]
        if op == "eq" and many:                 # the list equals a list, item by item, as written
            ok = not isinstance(want, list) or all(w in members for w in want)
            asked = want if isinstance(want, list) else []
        elif op == "eq":                        # a value, ignoring case
            ok = not isinstance(want, str) or want.lower() in low
            asked = [want]
        elif op == "in":                        # one of the values, as written
            ok = many or not isinstance(want, list) or any(w in members for w in want)
            asked = want if isinstance(want, list) else []
        else:                                   # contains: a part of a value (of an item of a list), ignoring case
            ok = not isinstance(want, str) or any(want.lower() in m for m in low)
            asked = [f"containing {want}"]
        if not ok:
            gaps.append(f"{label}.{prop} has no value {', '.join(map(str, asked))}")

    ml = plan["match"].get("label")
    if ml and ml not in spec["nodes"]:
        gaps.append(f"label {ml} is not declared")
    for st in plan.get("steps") or []:
        kind = step_kind(st)
        if kind == "edge" and st["edge"] not in spec["edges"]:
            gaps.append(f"edge type {st['edge']} is not declared")
        if kind != "entries" and st.get("to") and st["to"] not in spec["nodes"]:
            gaps.append(f"label {st['to']} is not declared")
        if kind == "entries":
            src = st.get("from", plan["match"].get("as", "self"))
            edge = src in edge_vars and src not in labels
            for prop in st["entries"] if isinstance(st["entries"], list) else [st["entries"]]:
                if not has_prop(edge_vars[src] if edge else labels.get(src), prop, edge):
                    gaps.append(f"{edge_vars[src] if edge else labels.get(src)}.{prop} is not declared")
        if kind == "field" and st.get("link") and st["link"] not in spec["edges"]:
            gaps.append(f"edge type {st['link']} is not declared")
        labels[st["as"]] = ENTRY if kind == "entries" else st.get("to")
        if st.get("edge_as") and kind == "edge":
            edge_vars[st["edge_as"]] = st["edge"]
        elif st.get("edge_as") and kind == "field" and st.get("link"):
            edge_vars[st["edge_as"]] = st["link"]
        for f in st.get("where") or []:
            if not has_prop(labels[st["as"]], f["prop"]):
                gaps.append(f"{where_of(labels[st['as']], f['prop'])} is not declared")
            else:
                value_gap(labels[st["as"]], f)
        link = st.get("edge") if kind == "edge" else st.get("link")
        for f in st.get("edge_where") or []:
            if link in spec["edges"] and not has_prop(link, f["prop"], edge=True):
                gaps.append(f"{link}.{parse_path(f['prop'])[0]} is not declared")
            elif link in spec["edges"]:
                value_gap(link, f, edge=True)
    for f in (plan.get("where") or []) + (plan["match"].get("where") or []):
        var = f.get("var", plan["match"].get("as", "self"))
        if var in edge_vars and var not in labels:          # a filter on a link bound by edge_as
            if not has_prop(edge_vars[var], f["prop"], edge=True):
                gaps.append(f"{edge_vars[var]}.{parse_path(f['prop'])[0]} is not declared")
            else:
                value_gap(edge_vars[var], f, edge=True)
        elif not has_prop(labels.get(var), f["prop"]):
            gaps.append(f"{where_of(labels.get(var), f['prop'])} is not declared")
        else:
            value_gap(labels.get(var), f)
    for r in plan.get("return") or []:
        var, _, prop = r.partition(".")
        if var in edge_vars:
            if prop and not has_prop(edge_vars[var], prop, edge=True):
                gaps.append(f"{edge_vars[var]}.{parse_path(prop)[0]} is not declared")
        elif prop and not has_prop(labels.get(var), prop):
            gaps.append(f"{where_of(labels.get(var), prop)} is not declared")
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
    cmp = Comparison(plan, spec, g)
    base = {"question": plan.get("question"), "plan": plan, "graph_id": doc["graph"].get("graph_id"),
            "schema_version": doc["graph"].get("schema_version"), "graph_sha256": g.digest}
    link_types = list(dict.fromkeys(st["edge"] if "edge" in st else st["link"] for st in steps
                                    if "edge" in st or ("field" in st and st.get("link"))))
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

    def one(rec: dict, f: dict, x: Any) -> tuple[bool | None, str | None, dict | None]:
        """One value (or one entry a path selects) against one filter."""
        if cmp.scientific and numeric_filter(f):
            return cmp.check_one(rec, f, x)
        r, why = _one(x, f, f.get("op", "eq"))
        return r, why, None

    def group(rec: dict, fs: list[dict]) -> tuple[bool | None, str | None, dict | None, dict | None, list]:
        """Filters on one path that selects entries, held by one entry together: (result, reason, the filter whose
        reason it is, the tag of the first entry that passed, the keys of every entry that passed). An entry passes
        when every filter holds for it, and fails when one fails; a record passes when an entry does, and is
        undecided (the first undecided entry's reason) when none passes and one could not be compared, never taken as
        failing. So two filters are never held by two entries: an assay at 40 % and one at 80 % never pass >= 70 and
        <= 50 together."""
        path = fs[0].get("prop")
        v, items = lookup(rec, path)
        if not items:
            if any(f.get("op", "eq") == "exists" for f in fs):     # no entry is there: exists fails, as it always did
                return False, None, None, None, []
            return None, ("not_curated" if v is None else f"no_matching_entry ({path})"), fs[0], None, []
        passed, tag, first = [], None, None
        for key, x in items:
            held, und, t = True, None, None
            for f in fs:
                r, why, tg = one(rec, f, x)
                if r is False:
                    held, und = False, None
                    break
                if r is None:
                    held, und = False, und or (f, why)
                elif tg is not None and t is None:
                    t = tg
            if held:
                passed.append(key)
                tag = tag if tag is not None else t
            elif und is not None and first is None:
                first = und
        if passed:
            return True, None, None, tag, passed
        if first is not None:
            return None, first[1], first[0], None, []
        return False, None, None, None, []

    def apply(rec: dict, filters: list[dict] | None, rid: str, sink, tags: dict | None = None, var: str = "",
              bound: dict | None = None) -> bool:
        """Whether a record passes every filter; a filter that cannot be evaluated goes to sink(filter, reason). The
        filters on one path that selects entries (``results.*[target=…]``, ``faradaic_efficiency.*``) are held by one
        entry together (:func:`group`), and ``bound`` gets the keys of the entries that held them, keyed
        ``(<variable>, <path>)``: what a return of that path gives, and whose evidence the row cites. In a scientific
        comparison a numeric filter reads the value under its quantity contract (:class:`Comparison`) and ``tags`` gets
        the unit and contexts of the value each filter passed on, keyed ``<variable>.<path>``."""
        done: set = set()
        for f in filters or []:
            path = f.get("prop")
            if f.get("op", "eq") != "missing" and selects_entries(path):
                if path in done:
                    continue
                done.add(path)
                fs = [h for h in filters if h.get("prop") == path and h.get("op", "eq") != "missing"]
                r, why, at, tag, keys = group(rec, fs)
                if r is None:
                    sink(at, why)
                    return False
                for h in fs:
                    if numeric_filter(h) and _stated(h.get("unit")):
                        compared.add((rid, path))
                        if not cmp.scientific:
                            cmp.observe(rec, path)
                if not r:
                    return False
                if bound is not None:
                    bound[(var, path)] = keys
                if tag is not None and tags is not None:
                    tags[f"{var}.{path}"] = tag
                continue
            tag = None
            if cmp.scientific and numeric_filter(f):
                r, why, tag = cmp.check(rec, f)
            else:
                r, why = check(rec, f)
                if r is not None and numeric_filter(f) and _stated(f.get("unit")):
                    cmp.observe(rec, f.get("prop"))
            if r is None:
                sink(f, why)
                return False
            if numeric_filter(f) and _stated(f.get("unit")):     # a value object, compared in the filter's unit
                compared.add((rid, f.get("prop")))
            if not r:
                return False
            if tag is not None and tags is not None:
                tags[f"{var}.{f.get('prop')}"] = tag
        return True

    def entry_record(owner: dict, prop: str, key: Any, x: dict) -> dict:
        """A value entry as a filter, a return and a ranking read it (:data:`ENTRY`): its fields, ``value`` the value
        object itself and ``kind`` its quantity kind; ``_entry`` says whose and where (a record_ref: record, path)."""
        kind = cmp.kind(owner, prop, x)
        ptr = results.pointer(prop, key, x)
        return {"id": x["id"] if isinstance(x.get("id"), str) else ptr, "label": ENTRY,
                "props": {**x, "value": x, "kind": kind},
                "_entry": {"record": owner["id"], "path": ptr, "prop": prop, "key": key, "kind": kind, "owner": owner}}

    link_by_id = {e["id"]: e for e in doc["links"]}
    cands = ([m["id"]] if m["id"] in g.nodes else []) if m.get("id") else sorted(g.by_label.get(m["label"], []))
    rows = []
    for nid in cands:
        tags: dict = {}
        mbound: dict = {}
        if apply(g.nodes[nid], m.get("where"), nid,
                 lambda f, why, nid=nid: exclude({"record": nid, "filter": f, "reason": why}), tags, root, mbound):
            rows.append({root: nid, "_links": [], "_edges": {}, "_cmp": tags, "_bound": mbound, "_entries": {}})
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
        kind = step_kind(st)
        props_ = (st["entries"] if isinstance(st["entries"], list) else [st["entries"]]) if kind == "entries" else []
        kinds = set([st["kind"]] if isinstance(st.get("kind"), str) else st.get("kind") or [])
        for row in rows:
            here = row.get(src)
            found = False
            missed[0] = False
            if here is not None and kind == "edge":
                edges = g.out.get(here, []) if direction == "out" else g.inc.get(here, [])
                types = g.edge_types(st["edge"])
                for e in sorted(edges, key=lambda e: e["id"]):
                    if e["type"] not in types:
                        continue
                    other = e["target"] if direction == "out" else e["source"]
                    if st.get("to") and not g.is_a(other, st["to"]):
                        continue
                    etags: dict = {}
                    ntags: dict = {}
                    ebound: dict = {}
                    if not apply(e, st.get("edge_where"), e["id"], lambda f, why, rid=e["id"]: step_sink(f, why, rid),
                                 etags, st.get("edge_as") or st["edge"], ebound):
                        continue
                    if apply(g.nodes[other], st.get("where"), other, lambda f, why, rid=other: step_sink(f, why, rid),
                             ntags, st["as"], ebound):
                        edges_bound = {**row["_edges"], st["edge_as"]: e["id"]} if st.get("edge_as") else row["_edges"]
                        nxt.append({**row, st["as"]: other, "_links": row["_links"] + [e["id"]], "_edges": edges_bound,
                                    "_cmp": {**row["_cmp"], **etags, **ntags}, "_bound": {**row["_bound"], **ebound}})
                        found = True
            elif here is not None and kind == "entries":     # one row per value entry: every filter on it is its own
                owner = g.nodes[here]
                for prop in props_:
                    items = list(results.entries((owner.get("props") or {}).get(prop)))
                    by_key = dict(items)
                    twins = {k: keys for keys in results.repeated(items) for k in keys}
                    for key, x in items:
                        erec = entry_record(owner, prop, key, x)
                        if kinds and erec["_entry"]["kind"] not in kinds:
                            continue
                        handle = f"{here}#{erec['_entry']['path']}"
                        others = [results.pointer(prop, k, by_key[k]) for k in twins.get(key, []) if k != key]
                        if others and cmp.scientific:            # two results nothing tells apart: never compared
                            step_sink(None, f"ambiguous_repetition ({erec['_entry']['path']} and {', '.join(others)}: one "
                                            "variable, target, producer, phase, stream, basis and normalization)", handle)
                            continue
                        ntags = {}
                        nbound: dict = {}
                        if apply(erec, st.get("where"), handle, lambda f, why, rid=handle: step_sink(f, why, rid), ntags,
                                 st["as"], nbound):
                            nxt.append({**row, st["as"]: handle, "_cmp": {**row["_cmp"], **ntags},
                                        "_bound": {**row["_bound"], **nbound},
                                        "_entries": {**row["_entries"], st["as"]: {**erec["_entry"], "from": src, "value": x,
                                                                                    "rec": erec, "twins": others}}})
                            found = True
            elif here is not None and kind == "field" and st.get("link"):    # a link a bound entry's field names
                e = row["_entries"].get(src)
                x = e["value"] if e else {}
                ref = x.get(st["field"])
                ref = ref.get("record") if isinstance(ref, dict) else None
                lk = link_by_id.get(ref) if isinstance(ref, str) else None
                at = e["path"] if e else src
                if lk is None:
                    if isinstance(ref, str) and ref in g.nodes:
                        step_sink(None, f"names_a_node ({at}: its {st['field']} names {ref}, a record, not a "
                                        f"{st['link']} link)", here)
                    elif results.withheld(x):
                        step_sink(None, "withheld", here)
                    else:
                        step_sink(None, f"not_curated ({at} names no {st['field']} in this graph)", here)
                elif lk["type"] not in g.edge_types(st["link"]):
                    step_sink(None, f"names_another_link ({at}: its {st['field']} names a {lk['type']} link, not a "
                                    f"{st['link']})", here)
                else:
                    other = lk["source"] if st["end"] == "source" else lk["target"]
                    if not st.get("to") or g.is_a(other, st["to"]):
                        etags: dict = {}
                        ntags: dict = {}
                        ebound: dict = {}
                        if apply(lk, st.get("edge_where"), lk["id"], lambda f, why, rid=lk["id"]: step_sink(f, why, rid),
                                 etags, st.get("edge_as") or st["link"], ebound) \
                                and apply(g.nodes[other], st.get("where"), other,
                                          lambda f, why, rid=other: step_sink(f, why, rid), ntags, st["as"], ebound):
                            edges_bound = {**row["_edges"], st["edge_as"]: lk["id"]} if st.get("edge_as") else row["_edges"]
                            nxt.append({**row, st["as"]: other, "_links": row["_links"] + [lk["id"]],
                                        "_edges": edges_bound, "_cmp": {**row["_cmp"], **etags, **ntags},
                                        "_bound": {**row["_bound"], **ebound}})
                            found = True
            elif here is not None and kind == "field":       # the record a bound entry's field names
                e = row["_entries"].get(src)
                x = e["value"] if e else {}
                ref = x.get(st["field"])
                if st["field"] == "normalized_by":
                    ref = ref.get("record") if isinstance(ref, dict) else None
                if isinstance(ref, str) and ref in link_by_id:
                    step_sink(None, f"names_a_link ({e['path'] if e else src}: its {st['field']} names a "
                                    f"{link_by_id[ref]['type']} link, {ref}; follow it with link and end)", here)
                elif not isinstance(ref, str) or ref not in g.nodes:
                    if st["field"] == "target" and isinstance(x.get("unresolved_target"), str):
                        step_sink(None, f"unresolved_target ({x['unresolved_target']}: the source does not identify the "
                                        "product, which is never taken for one species)", here)
                    elif results.withheld(x):
                        step_sink(None, "withheld", here)
                    else:
                        step_sink(None, f"not_curated ({e['path'] if e else src} names no {st['field']} in this graph)", here)
                elif not st.get("to") or g.is_a(ref, st["to"]):
                    ntags = {}
                    nbound = {}
                    if apply(g.nodes[ref], st.get("where"), ref, lambda f, why, rid=ref: step_sink(f, why, rid), ntags,
                             st["as"], nbound):
                        nxt.append({**row, st["as"]: ref, "_cmp": {**row["_cmp"], **ntags}, "_bound": {**row["_bound"], **nbound}})
                        found = True
            if not found and st.get("optional"):
                nxt.append({**row, st["as"]: None})
                unbound += 1
            elif not found and missed[0]:                   # no link passed, and one could not be compared
                unevaluated += 1
        stage = {"kind": "step", **({"edge": st["edge"], "direction": direction} if kind == "edge" else
                                    {"entries": props_, **({"of_kind": sorted(kinds)} if kinds else {})} if kind == "entries"
                                    else {"field": st["field"], **({"link": st["link"], "end": st["end"]}
                                                                    if st.get("link") else {})}),
                 "from": src, "to": st.get("to"), "as": st["as"], "rows_in": len(rows), "rows_out": len(nxt)}
        if st.get("optional"):
            stage.update(optional=True, unbound=unbound)
        if left:
            stage["left_out_by_reason"] = dict(sorted(left.items()))
        if unevaluated:
            stage["rows_not_evaluated"] = unevaluated
        stages.append(stage)
        rows = nxt

    if plan.get("where"):
        kept = []
        by_var: dict[str, list[dict]] = {}          # one variable's filters together: those on one path bind one entry
        for f in plan.get("where") or []:
            by_var.setdefault(f.get("var", root), []).append(f)
        for row in rows:
            ok = True
            row["_cmp"] = dict(row["_cmp"])          # rows of one parent share none of their tags
            row["_bound"] = dict(row["_bound"])
            for var, fs in by_var.items():
                nid = row["_edges"].get(var) if var in edge_vars else row.get(var)   # a link bound by edge_as, or a node
                if nid is None:                 # an optional variable left unbound: its record, so its property, is missing
                    if var in optional and all(f.get("op") == "missing" for f in fs):
                        continue
                    ok = False
                    break
                e = row["_entries"].get(var)
                if e is not None:               # a bound entry: left out as its record's, at its path
                    ok = apply(e["rec"], fs, nid, lambda f, why, e=e: exclude({"record": e["record"], "entry": e["path"],
                                                                               "filter": f, "reason": why}),
                               row["_cmp"], var, row["_bound"])
                else:
                    ok = apply(link_by_id[nid] if var in edge_vars else g.nodes[nid], fs, nid,
                               lambda f, why, nid=nid: exclude({"record": nid, "filter": f, "reason": why}), row["_cmp"], var,
                               row["_bound"])
                if not ok:
                    break
            if ok:
                kept.append(row)
        stages.append({"kind": "where", "rows_in": len(rows), "rows_out": len(kept)})
        rows = kept

    ev_vars = plan.get("evidence_vars")

    def scope(row: dict, var: str, rec: dict) -> tuple[set[int], dict[int, str]]:
        """What of a record's evidence a row cites when it binds entries of the record's properties (an entries step,
        or filters on a path that selects entries): (the items that only entries the row does not bind cite, which it
        leaves out; the items an entry it binds with an entries step cites, by that step's variable). An item no value
        cites, or one another value of the record cites too, stays the record's."""
        chosen: dict[str, set] = {}
        by_var: dict[tuple[str, Any], str] = {}
        for (v, path), keys in (row.get("_bound") or {}).items():
            if v == var:
                chosen.setdefault(parse_path(path)[0], set()).update(keys)
        for ev_var, e in (row.get("_entries") or {}).items():
            if e.get("from") == var and row.get(ev_var) is not None:
                chosen.setdefault(e["prop"], set()).add(e["key"])
                by_var[(e["prop"], e["key"])] = ev_var
        if not chosen:
            return set(), {}
        props = rec.get("props") or {}
        citing: dict[str, set] = {}
        for prop, v in props.items():
            if prop in ("evidence", "stewardship"):
                continue
            pairs = [((prop, key), x) for key, x in results.entries(v)] if prop in chosen \
                else [("other", x) for _, x in results.values_in({prop: v})]
            for who, x in pairs:
                for eid in x.get("evidence_ids") or []:
                    if isinstance(eid, str):
                        citing.setdefault(eid, set()).add(who)
        omit: set[int] = set()
        attributed: dict[int, str] = {}
        for i, ev in enumerate(props.get("evidence") or []):
            who = citing.get(ev.get("id")) if isinstance(ev, dict) and isinstance(ev.get("id"), str) else None
            if not who:
                continue
            if all(w != "other" and w[1] not in chosen[w[0]] for w in who):
                omit.add(i)
                continue
            mine = sorted(by_var[w] for w in who if w != "other" and w in by_var)
            if mine:
                attributed[i] = mine[0]
        return omit, attributed

    def cited(row: dict) -> list[dict]:
        """Evidence of the row's own records; shared kinds (species, reactions, materials, people) cite
        every source that mentions them, so they do not date a row unless evidence_vars names them. A row that binds an
        entry cites the evidence that entry cites (its evidence_ids) as the entry's, never the items only other
        entries cite (:func:`scope`)."""
        out = []
        bound_entries = row.get("_entries") or {}
        for var, nid in row.items():
            if var.startswith("_") or nid is None or var in bound_entries:
                continue
            node = g.nodes[nid]
            mine = (var in ev_vars) if ev_vars is not None else node["label"] not in SHARED_KINDS
            theirs = {v for v, e in bound_entries.items() if e.get("from") == var and row.get(v) is not None
                      and (ev_vars is None or v in ev_vars)}
            if not mine and not theirs:
                continue
            omit, attributed = scope(row, var, node)
            for i, ev in enumerate(node["props"].get("evidence") or []):
                if i in omit:
                    continue
                who = attributed.get(i)
                if who in theirs:
                    out.append({"var": who, "record": nid, "entry": bound_entries[who]["path"], "evidence": i, **ev,
                                "source_year": g.year.get(ev.get("source"))})
                elif mine:
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
        # only the evidence of the records the rows still hold competes for the hits: ranked among themselves (an
        # rrf fusion, a k), the quotes of rows a filter (published_before, retractions, a where) left out never
        # crowd out those of the rows it kept
        def record_of(row: dict, v: str) -> str | None:     # a bound entry's evidence is its record's
            e = row["_entries"].get(v)
            return e["record"] if e is not None and row.get(v) is not None else row.get(v)
        eligible = {record_of(row, v) for row in rows for v in vars_ if row.get(v)} | {lid for row in rows for lid in row["_links"]}
        hits = evidence_index.search(tq["query"], k=tq.get("k", 500), mode=tq.get("mode", "hybrid"),
                                     where=lambda it: it.get("record") in eligible
                                     and (it.get("record"), it.get("evidence"), it.get("text")) in held)
        score: dict[str, float] = {}
        for h in hits:
            if h["score"] >= tq.get("min_score", 0.0):
                score[h["record"]] = max(score.get(h["record"], 0.0), h["score"])
        scored = []
        for row in rows:
            ids = [record_of(row, v) for v in vars_ if row.get(v)] + [lid for lid in row["_links"]]
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
    ambiguous_rows = 0
    for row in rows:
        vals = {}
        for r in plan.get("return") or []:
            var, _, prop = r.partition(".")
            nid = row["_edges"].get(var) if var in row["_edges"] else row.get(var)
            if nid is None:
                vals[r] = None
                continue
            e = row["_entries"].get(var)
            if e is not None:                # a bound entry: the value itself, or one of its fields
                rec = e["rec"]
                v = returned(rec, prop) if prop else e["value"]
                why = absent_reason(v) if prop in ("", "value") else None
                at = ("entry", nid, prop)
            else:
                rec = link_by_id[nid] if var in row["_edges"] else g.nodes[nid]
                v = returned(rec, prop, row["_bound"].get((var, prop))) if prop else nid
                why = absent_reason(v) if prop else None
                if why == "not_curated" and v is None and lookup(rec, prop)[1] is not None and lookup(rec, prop)[0] is not None:
                    why = f"no_matching_entry ({prop})"      # the map or list is there; no entry is the one asked for
                at = ("link" if var in row["_edges"] else "node", nid, prop)
            vals[r] = v
            if why and at not in missing_at:
                missing_at.add(at)
                missing_ctx.append({"record": e["record"] if e is not None else nid, "field": r, "reason": why,
                                    **({"entry": e["path"]} if e is not None else {})})
        srcs = second_hand(row)
        bound = {}
        for k, v in row.items():
            if k.startswith("_"):
                continue
            e = row["_entries"].get(k)
            bound[k] = {"record": e["record"], "path": e["path"], **({"kind": e["kind"]} if e.get("kind") else {})} \
                if e is not None and v is not None else v
        item = {"bound": bound, "links": row["_links"], "values": vals, "_cmp": dict(row.get("_cmp") or {}),
                "_row": row}
        twins = {k: e["twins"] for k, e in row["_entries"].items() if e.get("twins") and row.get(k) is not None}
        if twins:                            # ordinary mode: a result that nothing tells apart from another, flagged
            ambiguous_rows += 1
            item["ambiguous_repetition"] = twins
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

    def ranked_on(it: dict, var: str, prop: str) -> tuple[dict | None, list | None]:
        """The record a ranking reads for a row's variable (a bound entry as :data:`ENTRY`), and the keys of the
        entries the row's filters bound on that path."""
        row = it["_row"]
        if row.get(var) is None and row["_edges"].get(var) is None:      # a link bound by edge_as ranks too
            return None, None
        e = row["_entries"].get(var)
        if e is not None:
            return e["rec"], None
        nid = row["_edges"].get(var) if var in row["_edges"] else row.get(var)
        return (link_by_id[nid] if var in row["_edges"] else g.nodes[nid]), row["_bound"].get((var, prop))

    mixed_order: list[str] = []
    if cmp.scientific and plan.get("order_by"):
        # a ranking compares like with like: each row's value under its contract, in one unit and context; a row whose
        # value cannot be ranked so is left out with its reason (the ordinary ranking orders bare numbers)
        ranked = []
        for it in out_rows:
            ok = True
            for ob in plan["order_by"]:
                var = ob.get("var", root)
                rec, keys = ranked_on(it, var, ob["prop"])
                tag, why = cmp.rank(rec, ob, keys)
                if why:
                    e = it["_row"]["_entries"].get(var)
                    exclude({"record": e["record"] if e and it["_row"].get(var) else (it["bound"].get(var) or it["bound"].get(root)),
                             **({"entry": e["path"]} if e and it["_row"].get(var) else {}), "order_by": ob, "reason": why})
                    ok = False
                    break
                it["_cmp"][f"{var}.{ob['prop']}"] = tag
            if ok:
                ranked.append(it)
        stages.append({"kind": "comparison", "rows_in": len(out_rows), "rows_out": len(ranked)})
        out_rows = ranked
    elif plan.get("order_by"):
        for it in out_rows:
            for ob in plan["order_by"]:
                rec, _ = ranked_on(it, ob.get("var", root), ob["prop"])
                if rec is not None:
                    cmp.observe(rec, ob["prop"])
    for ob in reversed(plan.get("order_by") or []):
        seen_units: set[str] = set()

        def key(it, ob=ob, seen_units=seen_units):
            rec, keys = ranked_on(it, ob.get("var", root), ob["prop"])
            v = returned(rec, ob["prop"], keys) if rec is not None else None
            if cmp.scientific and isinstance(v, list) and len(v) == 1:     # the one entry a ranked path selects
                v = v[0]
            if isinstance(v, dict) and v.get("unit") and number(v) != (None, None):
                u = v["unit"]
                seen_units.add(u if isinstance(u, str) else f"(a unit that is not text: {type(u).__name__})")
            lo, hi = number(v)
            x = lo if lo is not None else hi
            return (x is None, x if x is not None else 0.0)
        out_rows.sort(key=key, reverse=bool(ob.get("desc")))
        if len(seen_units) > 1 and not cmp.scientific:
            mixed_order.append(f"{ob.get('var', root)}.{ob['prop']} ({', '.join(sorted(seen_units))})")
    groups: list[dict] = []
    if cmp.scientific:                      # rows grouped by the unit and context of every value compared, ranked within
        keyed = {}                          # a group; what else a value says (a conversion, its denominator) is the row's
        for it in out_rows:
            on = {k: {"unit": t.get("unit"), **({"kind": t["kind"]} if t.get("kind") else {}),
                      **({"context": t["context"]} if t.get("context") else {})}
                  for k, t in sorted(it["_cmp"].items())}
            k = json.dumps(on, sort_keys=True, ensure_ascii=False)
            if k not in keyed:
                keyed[k] = len(keyed)
                groups.append({"group": keyed[k], "compared_on": on, "rows": 0})
            groups[keyed[k]]["rows"] += 1
            it["comparison_group"] = keyed[k]
            it["compared"] = it["_cmp"]
        out_rows.sort(key=lambda it: it["comparison_group"])      # stable: a group's ranking is kept
    for it in out_rows:
        it.pop("_cmp", None)
        it.pop("_row", None)
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
    if cmp.scientific:
        coverage["comparison"] = {"mode": "scientific", "groups": len(groups),
                                  "left_out": {r: reasons[r] + in_steps[r] for r in CONTEXT_REASONS + ("ambiguous_repetition",)
                                               if reasons[r] + in_steps[r]}}

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
    if ambiguous_rows:
        lim.append(f"{ambiguous_rows} row{'s bind' if ambiguous_rows != 1 else ' binds'} a result that nothing tells apart from "
                   "another of its record (ambiguous_repetition: one variable, target, producer, phase, stream, basis and "
                   "normalization): two results, never averaged; say so when stating either, and a scientific comparison "
                   "leaves them out until each names its assay (produced_by).")
    twins_out = reasons["ambiguous_repetition"] + in_steps["ambiguous_repetition"]
    if twins_out:
        lim.append(f"{twins_out} result{'s were' if twins_out != 1 else ' was'} left out of the comparison as an ambiguous "
                   "repetition (another result of its record that nothing tells apart): never averaged, never compared.")
    unresolved = reasons["unresolved_target"] + in_steps["unresolved_target"]
    if unresolved:
        lim.append(f"{unresolved} result{'s name' if unresolved != 1 else ' names'} no product species (unresolved_target: "
                   "the source does not identify it): kept as reported, never taken for one species.")
    lim += cmp.limitations()
    out = {}
    if cmp.scientific:
        lim += _comparison_limitations(groups, total, reasons, in_steps, out_rows)
        out["comparison"] = {"mode": "scientific", "groups": groups}
    lim += _access_limitation(access, doc, as_of)
    return {**base, "status": status, "row_count": total, "rows": out_rows, "access": access, "excluded": excluded[:LISTED],
            "missing_context": missing_ctx[:LISTED], "coverage": coverage, **out, "limitations": lim}


def _comparison_limitations(groups: list[dict], total: int, reasons: Counter, in_steps: Counter, rows: list[dict]) -> list[str]:
    """What a scientific comparison's answer says of its groups and of the values it left out for their context."""
    out = []
    if len(groups) > 1:
        out.append(f"The {total} rows fall into {len(groups)} comparison groups, each one unit and one context of every value "
                   "compared (comparison.groups; each row's comparison_group): values are compared, and rows ranked, within "
                   "a group only; there is no ranking across groups.")
    ctx = {r: reasons[r] + in_steps[r] for r in CONTEXT_REASONS if reasons[r] + in_steps[r]}
    if ctx:
        n = sum(ctx.values())
        out.append(f"{n} value{'s were' if n != 1 else ' was'} left out for {'their' if n != 1 else 'its'} context "
                   f"({', '.join(f'{k} {x}' for k, x in ctx.items())}):"
                   " a scientific comparison compares a value only on a context the value or its record states (a potential's "
                   "reference scale, a current density's normalization, a pressure's convention, a volumetric flow's reference "
                   "conditions, the species a share or an efficiency is counted for, a computed energy's reaction, level "
                   "of theory and charge treatment), never an assumed one, and not where its "
                   "statements disagree; read "
                   "each value's as_reported and note, and curate the context where the source states it.")
    conv = sum(1 for it in rows if any(t.get("converted") for t in (it.get("compared") or {}).values()))
    if conv:
        out.append(f"{conv} row{'s were' if conv != 1 else ' was'} compared on an evidenced conversion (a value derived or "
                   "computed by the experiment its produced_by names, on another context than its record's; the row's "
                   "compared says which): name the conversion when stating it.")
    assumed = sum(1 for it in rows if any((t.get("denominator") or {}).get("origin") == "assumed"
                                          for t in (it.get("compared") or {}).values()))
    if assumed:
        out.append(f"{assumed} row{'s were' if assumed != 1 else ' was'} compared on a value divided by an assumed denominator "
                   "(its normalized_by names a value of origin assumed): say so when stating it.")
    # what the producers state of the properties a kind shows, not compared by: a group whose rows state them differently
    shown: dict[tuple, set] = {}
    for it in rows:
        for path, t in sorted((it.get("compared") or {}).items()):
            for prop, val in (t.get("shows") or {}).items():
                shown.setdefault((it.get("comparison_group"), path, prop), set()).add(str(val))
    mixed = [f"group {g}, {path} {prop}: {', '.join(sorted(vals))}" for (g, path, prop), vals in sorted(
        shown.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], kv[0][2])) if len(vals) > 1]
    if mixed:
        out.append("Rows of one comparison group were computed with settings the comparison shows but does not keep apart "
                   f"({'; '.join(mixed)}): each row's compared says what its computation states; say so when comparing "
                   "them.")
    return out


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
        elif s["kind"] == "step" and "entries" in s:
            kinds = f" of kind {', '.join(s['of_kind'])}" if s.get("of_kind") else ""
            what = (f"step {s['from']} entries of {', '.join(s['entries'])}{kinds} "
                    f"({s['as']}{', optional' if s.get('optional') else ''})")
        elif s["kind"] == "step" and "field" in s:
            what = (f"step {s['from']}.{s['field']} → {s.get('to') or 'any'} "
                    f"({s['as']}{', optional' if s.get('optional') else ''})")
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
             f"graph {res['graph_id']} (scale-catal {res['schema_version']}, sha256 {res['graph_sha256'][:12]})"
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
        for var, twins in (r.get("ambiguous_repetition") or {}).items():
            lines.append(f"- **{var}: an ambiguous repetition of {', '.join(twins)}** (nothing tells them apart; never averaged)")
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
