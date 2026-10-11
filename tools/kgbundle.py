"""Export a scale-graph document as a knowledge-graph bundle (kg-bundle format 1.1.0).

    scale graph export GRAPH --to kg-bundle --out DIR [--bundle-id ID] [--version 1.0.0] [--text slug=file ...]
                        [--previous DIR | --ids-from DIR] [--replaced FILE] [--corpus MANIFEST]

The mapping, and what it cannot carry:

* Nodes become ``<Label>:<key>`` with key = slug of the name plus a short hash of the scale-graph
  id (unique); the scale-graph id is kept in ``scale_id``. With a previous release, a record it
  contained keeps its id there, even if its name changed (ids are frozen at first release). Source nodes become
  ``Publication:<doi or source id>``.
* A node is reported in (REPORTED_IN) every source its own evidence or its links' evidence quotes. A reading
  of a page image is cited by its transcription, marked ``"reading": "vision_ocr"``.
* A source's byline (AUTHORED_BY links, which carry no quote) becomes the Publication's ``authors``
  and ``assignees`` in byline order; the Person and Institution nodes are reported in that source.
* Links become edges with the canonical id ``e:sha256(type|source|target|source_id)[:16]``. The format
  requires every edge except REPORTED_IN to carry verbatim evidence from one source: a link
  with quotes from several sources is split into one edge per source; a link with no quote is
  not exported and is listed in the export report. Two links of one type between the same records with evidence
  from one source share that edge id: with the same values the second adds its evidence; with other values (a
  second addition of a reagent in another amount) the second is not exported and is listed in the export report
  (``parallel_links_not_exported``: by type, and each link left out with the one kept), so no value is merged under
  another's. A quote withheld under the copyright cap (its digest and length
  in the evidence note) is evidence in format 1.1.0: ``quote_withheld`` ``{sha256, chars, normalization:
  scale-match-text-1, reason: copyright}`` (a withheld transcription likewise), so a link resting only on withheld
  quotes is still an edge; one longer than the format's 600 characters is left out (``withheld_too_long``), and a source
  whose text the bundle ships is quoted, never withheld. The exception are the source-lifecycle links
  (RETRACTS, UPDATES): a notice is bibliographic metadata, so such a link without a
  quote is exported with ``metadata_only: true`` and the notice's title as its evidence (locator: title),
  the notice being its source, and a Dataset it reaches is reported in the notice (so the link keeps both
  ends); a notice without a title cannot be cited and its link is listed as not exported. Every link that
  loses an end (a node no source reports is not exported) is listed as not exported too, and
  ``lifecycle_links_metadata_only`` counts only the notice links the bundle holds; so do the counts of
  conversions (``values_as_text``, ``ranges_as_midpoint``, ``kept_apart_by_basis``,
  ``pressure_basis_unclear``, ``split_links``). A document of sources alone declares no REPORTED_IN.
* A Publication that a notice reaches carries its derived publication status in ``source_status``
  (retracted, withdrawn, partially_retracted, expression_of_concern, corrected, updated; see
  ``lifecycle``), and a record or edge whose evidence rests on retracted sources carries
  ``rests_on_retracted_source`` or ``partially_rests_on_retracted_source`` there. Nothing is dropped
  for it: a retracted source's records stay, flagged. Both properties are declared in the bundle schema
  (the format reserves names that begin with an underscore for the format and rejects undeclared ones).
* Value objects become quantities in one canonical unit per property (K, MPa, h, h-1, %),
  converted with the factors in CANONICAL; the reported text stays in ``as_reported``. A value
  in a unit that cannot be converted, a range reported as text, or a value that is not reported
  is not a quantity: it is kept as text in ``<property>_as_reported`` (and a missing value is left
  out, as the format asks). Conversions never change a value's basis:
  - a gauge pressure (``psig``, ``barg``, ``bar(g)``, ``20 bar (gauge)``, a unit, basis or reported text that
    says gauge) is exported as ``pressure_gauge`` (MPa above ambient), never as an absolute ``pressure``; the
    value's own unit and stated basis come first, a basis marker right after the value (``(gauge)``, ``(g)``,
    ``(abs)``) is the value's own, and a gauge equivalent given in parentheses does not make an absolute
    value gauge (``178 atmospheres absolute (2600 pounds per square inch gage)`` stays ``pressure``); a
    reported text that names both a gauge and an absolute pressure outside parentheses, with no basis
    stated, is not converted: it is kept in ``pressure_as_reported`` with ``pressure_note`` saying why;
  - a space velocity whose unit names a gas basis other than the feed (``vol H2/vol catalyst/h``,
    exit gas) goes to its own property (``space_velocity_h2``, ``space_velocity_exit_gas``); only
    the time unit is converted, and a basis the value states in words is kept in
    ``<property>_basis``;
  - a reported range is exported as its midpoint with the range in ``uncertainty`` (kind range, low,
    high); the property's schema entry says so and the export report counts them
    (``ranges_as_midpoint``). An uncertainty is converted with the value (for temperature, without
    the offset).
* Maps and lists of value objects become JSON text.
* ``_statement`` is the link's ``statement_kind`` (observation, conclusion, hypothesis, assumption) when the document
  records one (a planned kernel property). Otherwise it is inferred, and the export report counts
  the inferences (``statement_inferred``): a hypothesized, disputed or refuted link is a hypothesis (contested or
  rejected, it is never exported as a plain observation or conclusion), a SUPPORTS, CONCLUDES, ABOUT, CONTRADICTS,
  ADDRESSES, DERIVES or TESTS link a conclusion, any other an observation. The link's ``status`` itself is kept as
  ``scale_status`` (declared in the bundle schema), so a disputed or refuted link says so whatever its kind.
* A result a source cites from another work is not that source's finding (the format's principle 4): where all of a link's
  evidence from one source is second-hand (``evidence_type`` ECO:0000033, or its child ECO:0000304), that source's
  edge is not exported, so it is never an ``observation`` of the citing source; ``second_hand_not_exported`` counts
  such edges by link type. The cited work's own edge is exported where the graph holds evidence from it, and the
  records the link joins stay reported in the citing source.

Provenance and value detail the kg-bundle format has a place for:

* A link's ``confidence`` (the curator's confidence in the extraction, 0 to 1) becomes ``_confidence``, the format's
  extraction fidelity. The bundle's ``producer`` names SCALE's curation agents; no person is named: SCALE records no
  curator attribution here.
* An evidence item keeps its ``evidence_type`` (an ECO id: ECO:0000033 for a result the source cites from another
  work). Its locator gives the page and the rest as ``section``, the table or figure the locator names when the
  evidence is a table or figure reading (``kind``), and, for a source whose text the bundle ships under ``text/``,
  ``char_start`` and ``char_end`` of the quote in that text (exactly, or under the verbatim checker's
  normalization).
* A value that is a one-sided bound exports ``<property>_bound`` (upper: at most; lower: at least), and an
  approximate one ``<property>_qualifier`` (approximate), beside the quantity or its text; the export report counts
  both (``bounds``, ``approximate_values``).
* A Publication carries the source's ``published_on``, ``date_basis``, ``priority_date``, ``text_version`` and
  ``retrieved_from`` when they are recorded.
* A label or edge type whose ``maps_to`` names an absolute IRI (http or https) gets it as the type's ``iri``.

* Typed absences (format 1.1.0): a value ``not_reported`` (with its ``missing_reason``), ``not_measured``,
  ``not_applicable``, ``below_detection_limit`` or ``below_quantification_limit`` has no value in the bundle and is
  listed in the record's ``_value_status`` under the property its value would have been exported as (the property
  declared), counted by status (``absences``); a detection limit is not carried.

What the kg-bundle format cannot carry, and stays only in the scale-graph document:

* intervals (``interval_lower``/``interval_upper``, ``coverage_factor``, ``confidence_level``), ``replicates``,
  a value's ``origin``, ``target``, ``variable``, ``definition``, ``produced_by``,
  ``calibration``, ``evidence_ids`` and ``note``: only the reported text survives;
* the source lifecycle beyond derived statuses (notices with their scope and dates), ``status_check``, evidence
  passages, regions, transcriptions' agreement and second readings.

A host that needs these (an answer that reports missing context, the lifecycle of a source) should import the
scale-graph document natively and read it with SCALE's rules. Platform-owned names (:data:`PLATFORM_OWNED`: trust,
scope, project, …) are exported as ``scale_<name>``, since the platform sets its own at import.

Release lineage (``previous``, ``ids_from``, ``replaced``; ``scale graph export --to kg-bundle --previous DIR``,
``--ids-from DIR``, ``--replaced FILE``): node ids are frozen at first release; a later release names its predecessor
(``previous`` in bundle.json, with the id changes) and carries its changelog forward; a retired record's released id is
listed in its survivor's ``replaced_ids``.

The schema (``kg/schema.json``) is the vocabulary of the scale-graph version the graph pins (:func:`vocabulary`), never
derived from the graph: every label and edge type, with every property a bundle of that version can carry (a value's
canonical quantity and its ``_as_reported``, ``_bound``, ``_qualifier`` and ``_basis``; the access, status and
lifecycle properties). Every bundle of a version therefore declares the same schema, named ``scale-<domain>`` with the
scale-graph version (``scale-catal 0.1.0`` for catalysis; ``scale-kernel`` for a kernel-only graph). A value not of its
property's declared type is kept as text in ``<property>_as_reported``; property names are the format's snake_case
(``pH`` is ``ph``). Every exported record is checked against the schema before anything is written (``_conforms``).

Identity and access, which the kg-bundle format has no field for:

* The bundle schema's ``extends`` names the scale-graph schema by version **and digest**
  (``{schema_id: scale-graph, version, sha256}``, the sha256 of the version's spec document,
  :func:`pgraph.spec_sha256`, as ``scale graph spec`` writes it), since a bare version number names a schema only
  within one numbering; a document is exported only with the schema of the version it pins.
* ``bundle.json`` carries ``scale_header``: the graph's ``data_status``, ``schema_version``,
  ``schema_sha256``, ``follows_domains``, the bundle's stewardship (``access``, ``project``,
  ``embargo_until``, ``access_after_embargo``, ``licence``: the graph's, or public with the graph's licence for
  an export filtered for the public or a viewer's audience for one made for that viewer (``scale graph export
  --as``); ``contributed_by`` too when the bundle is an institution's; always an ``access``, ``institution`` where
  the stewardship states none, and an ``access_after_embargo`` for an embargo), the access level it grants on the export
  date (``access_at_export``, with ``less_open_kept``, by level, when ``keep_less_open`` kept records part of that
  audience may not see) and ``filtered_for`` when the document was filtered. The export date, on which every embargo
  is read, is the bundle's ``created`` day or today, whichever is earlier (:func:`pgraph.embargo_day`; today is the
  earlier of the local and the UTC date, :func:`pgraph.embargo_today`, as on every path): a later ``created`` stamps
  the bundle but never opens an embargo still in force; one that is not an ISO date is refused.
* A bundle holds only what everyone its stewardship admits may see: a record that some least-privileged viewer
  of that audience may not see (an institution's record in a project bundle, another project's, one under an
  embargo; in an institution bundle, a project's or the consortium's record when the institution takes no part
  in it) is withheld, with its links and the evidence citing it (``pgraph.restrict_to``: the rules of ``scale
  graph filter`` for every such viewer, ``pgraph.audience``), and counted in the export report;
  ``keep_less_open`` exports it instead. A reference a kept record makes to a record left out (a ref property, a
  map entry keyed by it) is removed with it and counted (``references``); a value that names one (its
  ``ref_value``, ``target``, ``variable``, ``produced_by`` or ``calibration``) is withheld whole in its place (a
  property, a list entry keeping its position, a map entry its key) as not reported with missing_reason
  ``withheld``, so no withheld id stays in the bundle; a record_ref into a kept record follows what was removed
  from it (a list position moves up behind an entry removed; one to a part removed or withheld goes, counted), and
  a value's ``evidence_ids`` no longer name an evidence item removed (a value stated only by removed evidence is
  withheld whole, counted). On a record that lost evidence, a value without ``evidence_ids`` cannot be traced to
  the evidence left and is withheld in its place too (fail closed: never cited to a source that may not state it);
  the kept records that lost evidence are counted (``evidence_cut``). A shipped text whose source the bundle does not hold stays out too
  (``texts_not_shipped``), and a text an earlier export left in the folder is removed (only plain file names its
  manifest gives: anything else stops the export). Every record whose own audience differs from the bundle's
  carries ``scale_access`` (the level on the export date) and, for a project's
  record, ``scale_access_project`` (the project), for an institution's (or one under an embargo in force)
  ``scale_access_institutions`` (its contributing institutions), all declared in the bundle schema, so a host can
  keep each such record within its own audience. A bundle that is not public says so in the export report
  (``access_warning``): share it, and send its content to a person, host or model, only within that audience. One
  that kept records part of its audience may not see says that instead: each such record goes only to its own
  audience, and the bundle as a whole only to those who may see every record in it.
* A ``synthetic_example`` or ``mixed`` graph says so in the bundle's topic and scope.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from . import lifecycle, pgraph, rights
from .pgraph_query import SECOND_HAND_ECO, _eco
from .util import ScaleError

FORMAT_ID = "galaxy-kg-bundle"         # the identifier the format requires in bundle.json, verbatim
FORMAT_VERSION = "1.1.0"
NORMALIZATION = "scale-match-text-1"   # the verbatim checker's match_text, as the format names it
WITHHELD_MAX = 600                     # the format's longest quote, withheld or not
ABSENCE_STATUSES = {"not_reported", "not_measured", "not_applicable", "below_detection_limit",
                    "below_quantification_limit"}           # the format's typed absences (_value_status)
MISSING_REASONS = {"not_stated_in_source", "not_curated", "ambiguous_in_source", "withheld", "not_extractable"}
# access levels a record may carry in a bundle (scale_access): the level on the export date
SCALE_ACCESS = {"type": "enum", "values": list(pgraph.OPENNESS),
                "description": "who may see this record under its SCALE stewardship, on the export date, where that differs "
                               "from the bundle's access (bundle.json scale_header): public, consortium, project or "
                               "institution (an embargo in force counts as institution); scale_access_project or "
                               "scale_access_institutions name who, for a project's or an institution's record"}
SCALE_ACCESS_PROJECT = {"type": "string", "description": "the project whose members may see this record (scale_access "
                                                         "project), where the bundle's audience is another one"}
SCALE_ACCESS_INSTITUTIONS = {"type": "string[]",
                             "description": "the institutions that may see this record (scale_access institution, or an "
                                            "embargo in force: its contributed_by), where the bundle's audience is another "
                                            "one; absent when the record names none, and then SCALE shows it to no one"}
ACCESS_PROPS = {"scale_access": SCALE_ACCESS, "scale_access_project": SCALE_ACCESS_PROJECT,
                "scale_access_institutions": SCALE_ACCESS_INSTITUTIONS}
STEWARDSHIP_KEYS = ("access", "project", "embargo_until", "access_after_embargo", "licence")
# the stewardship keys that say who may see a record; a declared access replaces them all, and keeps the others (licence)
AUDIENCE_KEYS = ("access", "project", "contributed_by", "embargo_until", "access_after_embargo")
SYNTHETIC_TEXT = {
    "synthetic_example": ("(synthetic example)", "Synthetic example data (data_status synthetic_example): invented to "
                                                 "illustrate the format, not evidence about the world."),
    "mixed": ("(includes synthetic examples)", "Mixed data (data_status mixed): research data together with synthetic "
                                               "examples; records whose origin is synthetic are invented, not evidence about "
                                               "the world."),
}
# The bundle's title (bundle.json ``topic``): a host shows it as the graph's name on import,
# so it is a short name. A graph's own title states its scope in full and may run long; the bundle takes it when it is
# short and its leading words otherwise (``concise_title``), unless the export names one (``title``).
TITLE_MAX = 40


def concise_title(title: str, limit: int = TITLE_MAX) -> str:
    """``title`` when it has at most ``limit`` characters (whitespace collapsed); otherwise its leading words, cut at a
    word boundary before ``limit``, without a parenthesis left open or a trailing clause mark, ending in an ellipsis."""
    t = " ".join((title or "").split())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0] if " " in t[:limit] else t[:limit - 1]
    if cut.count("(") > cut.count(")"):
        cut = cut[:cut.rfind("(")]
    return cut.rstrip(" ,;:-\u2013\u2014") + "\u2026"


# Set by the platform at import; a scale-graph property of that name is exported as scale_<name>.
PLATFORM_OWNED = {"trust", "created_by", "scope", "project", "source_node_id", "source_edge_id", "bundle_source", "bundle_id",
                  "bundle_version", "graph_id", "tenant_id"}
_GREEK = dict(zip("αβγδεζηθικλμνξοπρστυφχψω", ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota",
                                                "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi", "rho", "sigma", "sigma",
                                                "tau", "upsilon", "phi", "chi", "psi", "omega"]))


def slug_key(text: str) -> str:
    """As the format's validator computes it."""
    spelled = "".join(f" {_GREEK[c]} " if c in _GREEK else c for c in text.lower())
    spaced = re.sub(r"[\W_]+", " ", spelled)
    ascii_text = unicodedata.normalize("NFKD", spaced).encode("ascii", "ignore").decode()
    key = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return key[:96].rstrip("-") or "unnamed"


def canonical_edge_id(etype: str, source: str, target: str, source_id: str) -> str:
    return "e:" + hashlib.sha256(f"{etype}|{source}|{target}|{source_id}".encode()).hexdigest()[:16]


# property -> (canonical unit, {reported unit: function to canonical})
_T = {"°C": lambda x: x + 273.15, "C": lambda x: x + 273.15, "deg C": lambda x: x + 273.15, "K": lambda x: x,
      "°F": lambda x: (x - 32) * 5 / 9 + 273.15, "F": lambda x: (x - 32) * 5 / 9 + 273.15}
_P = {"MPa": lambda x: x, "atm": lambda x: x * 0.101325, "bar": lambda x: x * 0.1, "kPa": lambda x: x / 1000, "Pa": lambda x: x / 1e6,
      "kg/cm2": lambda x: x * 0.0980665, "kg/cm²": lambda x: x * 0.0980665, "at": lambda x: x * 0.0980665,
      "psi": lambda x: x * 0.00689475729, "psia": lambda x: x * 0.00689475729, "lb/in2": lambda x: x * 0.00689475729,
      "lbf/in2": lambda x: x * 0.00689475729, "lb/sq in": lambda x: x * 0.00689475729,
      "mmHg": lambda x: x * 0.000133322368, "mm Hg": lambda x: x * 0.000133322368, "torr": lambda x: x * 0.000133322368,
      "cm Hg": lambda x: x * 0.00133322368, "ata": lambda x: x * 0.0980665}  # ata: technical atmospheres absolute (kgf/cm2)
_H = {"h": lambda x: x, "hr": lambda x: x, "hours": lambda x: x, "min": lambda x: x / 60, "s": lambda x: x / 3600,
      "d": lambda x: x * 24, "day": lambda x: x * 24, "days": lambda x: x * 24, "weeks": lambda x: x * 168}
# Space velocity: a volume of gas per volume of catalyst per unit time, however the source spells it.
# A space velocity in these units is a volume of gas per volume of catalyst per unit time; the unit says on which gas
# the volume is counted when it says so (None: the feed gas, or not stated). Only the time unit is converted.
_SV_UNITS = {"h-1": (1, None), "1/h": (1, None), "hr-1": (1, None), "h^-1": (1, None), "min-1": (60, None),
             "vol gas/vol catalyst/h": (1, None), "vol/(h·vol catalyst)": (1, None), "cc/hr/cc": (1, None),
             "ft3/(ft3·h)": (1, None), "ft3 gas/(ft3 catalyst h) at N.T.P.": (1, None),
             "ft3 gas/(ft3 catalyst·h) at N.T.P.": (1, None), "cc/cc/min": (60, None),
             "vol H2/vol catalyst/h": (1, "h2"), "L exit gas (std. cond.) per L catalyst per h": (1, "exit_gas")}
_SV = {u: (lambda x, k=k: x * k) for u, (k, _) in _SV_UNITS.items()}
SV_BASIS = {u: b for u, (_, b) in _SV_UNITS.items() if b}
_PCT = {"%": lambda x: x}
UNCLEAR_PRESSURE = ("not converted: the reported text names both a gauge and an absolute pressure, and the value's own "
                    "basis is not stated")
# derived source-lifecycle properties, declared in the bundle schema wherever they are set
RESTING = ("rests_on_retracted_source", "partially_rests_on_retracted_source")
SOURCE_STATUS = {"type": "enum", "values": [*lifecycle.STATUSES[:-1], *RESTING],
                 "description": "derived from notice links (RETRACTS, UPDATES): a source's or dataset's publication status, "
                                "or, on a record or link, whether its evidence rests on retracted sources (all of it or part)"}
METADATA_ONLY = {"type": "boolean", "description": "a notice link that carries no quote in the scale-graph document (a notice is "
                                                   "bibliographic metadata): its evidence is the notice's title"}
CANONICAL = {"temperature": ("K", _T), "pressure": ("MPa", _P), "duration": ("h", _H), "time_on_stream": ("h", _H),
             "lifetime": ("h", _H), "space_velocity": ("h-1", _SV), "conversion": ("%", _PCT), "yield": ("%", _PCT),
             "selectivity": ("%", _PCT)}
# properties a conversion may not merge into their canonical one: another basis, the same unit
SPLIT = {"pressure_gauge": ("MPa", "gauge pressure (above ambient), converted in its unit only; never an absolute pressure"),
         "space_velocity_h2": ("h-1", "space velocity counted on the hydrogen fed, not on the whole feed"),
         "space_velocity_exit_gas": ("h-1", "space velocity counted on the exit gas, not on the feed")}
_GAUGE_UNITS = {"psig": "psi", "barg": "bar", "atü": "at", "atu": "at", "kg/cm2g": "kg/cm2", "kg/cm2 g": "kg/cm2"}
_GAUGE_TEXT = re.compile(r"\b(gauge|gage|psig|barg)\b|\bp\.s\.i\.g\b|atü", re.I)
_ABSOLUTE_TEXT = re.compile(r"\b(absolute|abs|psia|ata)\b", re.I)
_NEGATED = re.compile(r"\bnot\s+(gauge|gage|absolute|abs)\b", re.I)   # "absolute, not gauge" names one basis
_ASIDE = re.compile(r"\([^()]*\)")          # a parenthetical: an equivalent in another unit, not the value's own
_PUNIT = r"(?:bar|psi|atm|at|kpa|mpa|pa|kg/cm2|kg/cm²|kgf/cm2|kgf/cm²|lb/in2|lbf/in2)"
# a basis marker that belongs to the value: a parenthetical holding only the basis ("20 bar (gauge)", "20 bar(g)")
_OWN_GAUGE = re.compile(r"\(\s*(?:gauge|gage)\s*\)|\b" + _PUNIT + r"\s*\(\s*g\s*\)", re.I)
_OWN_ABSOLUTE = re.compile(r"\(\s*(?:absolute|abs\.?)\s*\)|\b" + _PUNIT + r"\s*\(\s*a\s*\)", re.I)
_UNIT_GAUGE = re.compile(r"\s*(?:\(\s*(?:gauge|gage|g)\s*\)|\b(?:gauge|gage)\b)\s*$", re.I)
_UNIT_ABSOLUTE = re.compile(r"\s*\(\s*(?:absolute|abs\.?|a)\s*\)\s*$", re.I)


def _gauge(v: dict, unit: str) -> tuple[str, str]:
    """(the value's pressure basis, the unit to convert with). The basis is ``gauge``, ``absolute``, ``unstated``
    (exported as ``pressure``, as the source gives it) or ``unclear`` (not converted). The value's own unit decides
    first (``psig``, ``bar(g)``, ``lbf/in2 (gauge)`` are gauge; ``psia``, ``ata``, ``bar(a)`` absolute), then its stated
    ``basis``, then the reported text and note. In the text, a parenthetical that holds only a basis (``20 bar (gauge)``,
    ``20 bar(g)``) is the value's own; any other parenthetical is an equivalent in another unit and is left out
    (``178 atmospheres absolute (2600 pounds per square inch gage)`` is absolute). A text that says only absolute is
    absolute, one that says only gauge is gauge, one that says both (``2600 psi gauge, i.e. 178 atm absolute``) is
    unclear, and one that says neither is unstated; a negated basis (``absolute, not gauge``) does not count."""
    if unit in _GAUGE_UNITS:
        return "gauge", _GAUGE_UNITS[unit]
    base = _UNIT_GAUGE.sub("", unit)
    if base != unit:
        return "gauge", base
    base = _UNIT_ABSOLUTE.sub("", unit)
    if base != unit:
        return "absolute", base
    if _ABSOLUTE_TEXT.search(unit):
        return "absolute", unit
    basis = v.get("basis") if isinstance(v.get("basis"), str) else ""
    if _ABSOLUTE_TEXT.search(basis):
        return "absolute", unit
    if _GAUGE_TEXT.search(basis):
        return "gauge", unit
    said = " ".join(str(v.get(k) or "") for k in ("as_reported", "note"))
    said = _OWN_GAUGE.sub(" gauge ", said)
    said = _OWN_ABSOLUTE.sub(" absolute ", said)
    said = _NEGATED.sub(" ", _ASIDE.sub(" ", said))
    gauge, absolute = bool(_GAUGE_TEXT.search(said)), bool(_ABSOLUTE_TEXT.search(said))
    if gauge and absolute:
        return "unclear", unit
    return ("gauge" if gauge else "absolute" if absolute else "unstated"), unit


def pressure_basis(v: dict) -> str:
    """The basis :func:`target` reads from a pressure value object: gauge, absolute, unstated or unclear."""
    return _gauge(v, (v.get("unit") or "").strip())[0] if isinstance(v, dict) else "unstated"


STATEMENT_KINDS = ("observation", "conclusion", "hypothesis", "assumption")    # the format's principle 2
CONCLUDING = ("SUPPORTS", "CONCLUDES", "ABOUT", "CONTRADICTS", "ADDRESSES", "DERIVES", "TESTS")
NOT_ESTABLISHED = ("hypothesized", "disputed", "refuted")                    # never a plain observation or conclusion
BOUND = {"type": "enum", "values": ["upper", "lower"],
         "description": "the value is a one-sided bound as reported: upper = at most this, lower = at least this"}
QUALIFIER = {"type": "enum", "values": ["approximate"], "description": "the source gives the value as approximate"}
# Source properties a Publication carries when they are recorded, with their bundle types
PUBLICATION_DATES = {"published_on": "date", "date_basis": "string", "priority_date": "date", "text_version": "string",
                     "retrieved_from": "string"}
_IRI = re.compile(r"^https?://\S+$")
_TABLE = re.compile(r"\b(?:Table|Tab\.)\s*[A-Z]?(?:\d+|[IVXLC]+)[a-z]?\b")
# a figure's number, with a panel letter only right after it ("Fig. 3b") or in parentheses ("Fig. 1(a)", "Figure 2 (c)"):
# never the first letter of the next word ("Fig. 2 inset")
_FIGURE = re.compile(r"\b(?:Figure|Fig\.)\s*[A-Z]?\d+(?:[a-z]\b|\s*\([a-z]\))?", re.I)


def scale_status(spec: dict) -> dict:
    """The bundle schema entry of ``scale_status``: the link status values of the bound scale-graph schema."""
    values = list(((spec.get("common") or {}).get("link") or {}).get("properties", {}).get("status", {}).get("values")
                  or ["asserted", "hypothesized", "supported", "disputed", "refuted"])
    return {"type": "enum", "values": values,
            "description": "the link's status in the scale-graph document: how firmly the source states the relationship "
                           "(asserted, hypothesized, supported, disputed or refuted); a disputed or refuted link is "
                           "contested or rejected, whatever its _statement"}


def iri_of(d: dict) -> str | None:
    """The first absolute IRI a label's or edge type's ``maps_to`` names (most name a vocabulary term in words)."""
    return next((m.strip() for m in d.get("maps_to") or [] if isinstance(m, str) and _IRI.match(m.strip())), None)


def quantity(prop: str, v: dict) -> tuple[dict | None, str | None]:
    """(bundle quantity, None) or (None, reported text) for a scale-graph value object. The quantity is that of
    :func:`target` (``pressure_gauge`` for a gauge pressure, …)."""
    return _quantity(prop, v)[1:]


def target(prop: str, v: dict) -> str:
    """The bundle property a value is exported under: its own, or the one of its basis (:data:`SPLIT`)."""
    return _quantity(prop, v)[0]


def _absent_target(prop: str, v: object) -> str:
    """The bundle property a value with no number (a typed absence) belongs to: as for a present value, by its unit
    and stated basis (a gauge pressure not measured is still pressure_gauge), never by a note, which says why it is
    missing."""
    if not isinstance(v, dict):
        return prop
    unit = (v.get("unit") or "").strip() if isinstance(v.get("unit"), str) else ""
    if prop == "pressure":
        basis, _ = _gauge({"basis": v["basis"]} if isinstance(v.get("basis"), str) else {}, unit)
        return "pressure_gauge" if basis == "gauge" else prop
    if prop == "space_velocity" and unit in SV_BASIS:
        return f"space_velocity_{SV_BASIS[unit]}"
    return prop


def _quantity(prop: str, v: dict) -> tuple[str, dict | None, str | None]:
    if not isinstance(v, dict) or v.get("status", "present") != "present":
        return _absent_target(prop, v), None, None
    reported = v.get("as_reported") or " ".join(str(x) for x in (v.get("value", ""), v.get("unit", "")) if x != "").strip()
    if v.get("lower") is not None and v.get("upper") is not None and not reported:
        reported = f"{v['lower']}–{v['upper']} {v.get('unit', '')}".strip()
    canon = CANONICAL.get(prop)
    unit = (v.get("unit") or "").strip()
    out = prop
    if prop == "pressure":
        basis, unit = _gauge(v, unit)
        if basis == "unclear":                     # gauge or absolute: converting either way could be wrong
            return prop, None, reported or None
        out = "pressure_gauge" if basis == "gauge" else prop
    elif prop == "space_velocity" and unit in SV_BASIS:
        out = f"space_velocity_{SV_BASIS[unit]}"
    if not canon or unit not in canon[1]:
        return out, None, reported or None
    f = canon[1][unit]
    if isinstance(v.get("value"), (int, float)):
        q = {"value": round(f(float(v["value"])), 6), "unit": canon[0], "as_reported": reported or f"{v['value']} {unit}"}
        if isinstance(v.get("uncertainty"), (int, float)):          # a difference: the offset of °C and °F cancels
            q["uncertainty"] = {"kind": "std" if v.get("uncertainty_kind") == "standard_deviation" else "reported",
                                "plus_minus": round(f(float(v["uncertainty"])) - f(0.0), 6)}
        return out, q, None
    lo, hi = v.get("lower"), v.get("upper")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        a, b = round(f(float(lo)), 6), round(f(float(hi)), 6)
        return out, {"value": round((a + b) / 2, 6), "unit": canon[0], "as_reported": reported,
                     "uncertainty": {"kind": "range", "low": a, "high": b}}, None
    return out, None, reported or None


# the scale-graph properties a bundle record never carries as properties (they are its evidence, stewardship and
# statement, carried in the format's own fields, or bookkeeping the format has no place for)
NOT_PROPERTIES = ("evidence", "stewardship", "origin", "record_version", "recorded_at", "conforms_to", "status", "basis",
                  "confidence", "statement_kind")
RANGE_NOTE = ("a reported range is exported as its midpoint (value), with the range in uncertainty (kind range, low, "
              "high) and the reported text in as_reported")


SCHEMA_SHORT = {"catalysis": "catal"}           # a domain's short name in its bundle schema's id


def schema_name(doc_or_spec: dict) -> str:
    """The bundle schema's id: scale-<short name of the domain> for a graph that follows a domain's checklist
    (``scale-catal`` for catalysis, :data:`SCHEMA_SHORT`), else scale-kernel. Its version is the scale-graph version;
    like any version number it names a schema only within this repository's numbering, and ``extends.sha256`` names it
    everywhere."""
    g = doc_or_spec.get("graph") if "graph" in doc_or_spec else None
    domains = list((g or {}).get("follows_domains") or [])
    return f"scale-{SCHEMA_SHORT.get(domains[0], domains[0])}" if domains else "scale-kernel"


def bundle_prop(k: str) -> str:
    """A scale-graph property's name in a bundle: the format's snake_case (``pH`` is ``ph``), platform-owned names
    prefixed ``scale_``."""
    k = re.sub(r"[^a-z0-9_]+", "_", k.lower()).strip("_") or "property"
    return f"scale_{k}" if k in PLATFORM_OWNED else k


def _value_variants(k: str) -> list[str]:
    """The property names a value property ``k`` can be exported under (kept apart by basis)."""
    if k == "pressure":
        return ["pressure", "pressure_gauge"]
    if k == "space_velocity":
        return ["space_velocity", *sorted({f"space_velocity_{b}" for b in SV_BASIS.values()})]
    return [k]


def _type_props(defs: dict, is_edge: bool, status_def: dict) -> dict:
    """The bundle properties of one label or edge type, from its scale-graph property definitions alone."""
    out: dict[str, dict] = {"scale_id": {"type": "string", "description": "The record's id in the scale-graph document."}}
    if not is_edge:
        out["name"] = {"type": "string", "required": True}
    for k, pdef in sorted(defs.items()):
        if k in NOT_PROPERTIES or k.startswith("_") or k == "name":
            continue
        k2 = bundle_prop(k)
        if pdef.get("type") == "value":
            for tk in _value_variants(k2):
                if k in CANONICAL:
                    unit, why = SPLIT.get(tk, (CANONICAL[k][0], None))
                    out[tk] = {"type": "quantity", "unit": unit, "description": "; ".join(x for x in (why, RANGE_NOTE) if x)}
                    out[f"{tk}_basis"] = {"type": "string", "description": f"the basis of {tk} as reported"}
                out[f"{tk}_as_reported"] = {"type": "string", "description": f"{tk} as reported (not converted)"}
                out[f"{tk}_bound"] = BOUND
                out[f"{tk}_qualifier"] = QUALIFIER
            if k == "pressure":
                out["pressure_note"] = {"type": "string", "description": "why a pressure was not converted"}
            continue
        gt = _ptype(pdef)
        out[k2] = gt
        if gt["type"] != "string":            # a value not of the declared type goes here, as text
            out[f"{k2}_as_reported"] = {"type": "string", "description": f"{k2} as reported (not of the declared type)"}
    out.update({k: ACCESS_PROPS[k] for k in ACCESS_PROPS})
    out["source_status"] = SOURCE_STATUS
    if is_edge:
        out["scale_status"] = status_def
        out["metadata_only"] = METADATA_ONLY
    return out


def vocabulary(spec: dict) -> tuple[dict, dict]:
    """``(node_types, edge_types)``: the bundle schema of a scale-graph version, every label and edge type with every
    property a bundle of that version can carry, from the schema alone (never from a document), so that every bundle of
    the version declares the same schema. A Source is a Publication; an endpoint label stands for itself and every
    label that is_a it."""
    status_def = scale_status(spec)
    common_n = (spec.get("common") or {}).get("node", {}).get("properties") or {}
    common_l = (spec.get("common") or {}).get("link", {}).get("properties") or {}
    node_types: dict[str, dict] = {}
    for lab, d in sorted(spec["nodes"].items()):
        if lab == "Source":
            continue
        node_types[lab] = {"description": (d.get("description") or lab).strip()[:2000],
                           **({"iri": iri_of(d)} if iri_of(d) else {}),
                           "properties": _type_props({**common_n, **(d.get("properties") or {})}, False, status_def)}
    pub = {"title": {"type": "string", "required": True}, "doi": {"type": "string"}, "source_id": {"type": "string"},
           "year": {"type": "integer"}, "license": {"type": "string"}, "kind": {"type": "string"},
           "venue": {"type": "string"}, "url": {"type": "string"},
           "authors": {"type": "string[]", "description": "Authors or inventors, in byline order."},
           "assignees": {"type": "string[]", "description": "Patent assignees."},
           "scale_id": {"type": "string"}, "source_status": SOURCE_STATUS, **{k: ACCESS_PROPS[k] for k in ACCESS_PROPS}}
    for k, t in PUBLICATION_DATES.items():
        pub[k] = {"type": t}
        if t != "string":
            pub[f"{k}_as_reported"] = {"type": "string", "description": f"{k} as given (not a date)"}
    node_types["Publication"] = {"description": "A source document: article, patent, thesis or report.", "properties": pub}

    def ends(labels: list) -> list[str]:
        out = set()
        for lab in labels or []:
            if not isinstance(lab, str):
                continue
            for name, d in spec["nodes"].items():
                if name == lab or lab in (d.get("ancestors") or []):
                    out.add("Publication" if name == "Source" else name)
        return sorted(x for x in out if x in node_types)

    edge_types: dict[str, dict] = {}
    for et, d in sorted(spec["edges"].items()):
        if et == "REPORTED_IN":
            continue
        frm, to = ends(d.get("from")), ends(d.get("to"))
        if not frm or not to:
            continue
        edge_types[et] = {"description": (d.get("description") or et).strip()[:2000], "from": frm, "to": to,
                          **({"iri": iri_of(d)} if iri_of(d) else {}),
                          "properties": _type_props({**common_l, **(d.get("properties") or {})}, True, status_def)}
    edge_types["REPORTED_IN"] = {"description": "An entity -> the source that reports it.",
                                 "from": sorted(x for x in node_types if x != "Publication"), "to": ["Publication"],
                                 "properties": {}}
    return node_types, edge_types


FORMAT_FIELDS = {"source_paper_ids", "replaced_ids"}        # the format's own fields, never declared in a schema


def _conforms(node_types: dict, edge_types: dict, nodes: list[dict], links: list[dict], schema_id: str) -> None:
    """Every exported record within the vocabulary: its label or type declared, each property declared on it, each
    edge between labels its type allows. A miss is a gap in :func:`vocabulary`, never something to export anyway."""
    problems = []
    label_of = {n["id"]: n["label"] for n in nodes}
    for n in nodes:
        t = node_types.get(n["label"])
        if t is None:
            problems.append(f"node {n['id']}: label {n['label']} is not in {schema_id}")
            continue
        problems += [f"node {n['id']}: {k} is not declared on {n['label']}" for k in n["props"]
                     if not k.startswith("_") and k not in FORMAT_FIELDS and k not in t["properties"]]
    for e in links:
        t = edge_types.get(e["type"])
        if t is None:
            problems.append(f"edge {e['id']}: type {e['type']} is not in {schema_id}")
            continue
        s, o = label_of.get(e["source"]), label_of.get(e["target"])
        if s and s not in t["from"] or o and o not in t["to"]:
            problems.append(f"edge {e['id']}: {e['type']} from {s} to {o} is not allowed in {schema_id}")
        problems += [f"edge {e['id']}: {k} is not declared on {e['type']}" for k in e["props"]
                     if not k.startswith("_") and k not in FORMAT_FIELDS and k not in t["properties"]]
    if problems:
        raise ScaleError(f"the bundle does not fit {schema_id} ({len(problems)}): " + "; ".join(problems[:5]))


def _ptype(d: dict) -> dict:
    t = d.get("type")
    if t in ("text", "string", "datetime"):
        return {"type": "string"}
    if t == "integer":
        return {"type": "integer"}
    if t == "number":
        return {"type": "number"}
    if t == "boolean":
        return {"type": "boolean"}
    if t == "date":
        return {"type": "date"}
    if t == "enum":
        return {"type": "enum", "values": list(d.get("values") or [])}
    if t == "list" and (d.get("items") or {}).get("type") in ("text", "string"):
        return {"type": "string[]"}
    return {"type": "string"}          # maps, refs, lists of values: JSON text


def statement(e: dict) -> tuple[str, bool]:
    """(the link's bundle ``_statement``, whether it was inferred). The link's ``statement_kind`` when it records
    one; otherwise inferred from its status and type: a hypothesized, disputed or refuted link is a hypothesis
    (never a plain observation or conclusion), a link of an inferential type a conclusion, any other an observation."""
    p = e.get("props") or {}
    if p.get("statement_kind") in STATEMENT_KINDS:
        return p["statement_kind"], False
    if p.get("status") in NOT_ESTABLISHED:
        return "hypothesis", True
    return ("conclusion" if e["type"] in CONCLUDING else "observation"), True


def _statement(e: dict) -> str:
    return statement(e)[0]


def _locator(loc: str | None, kind: str | None = None) -> dict:
    """the format's locator from a scale-graph one: the page (``p. N``), the rest as ``section``, and, for a table or
    figure reading (the evidence's ``kind``), the table or figure the locator names."""
    m = re.match(r"^p\. ?(\d+)", loc or "")
    out = {"page": int(m.group(1))} if m else {}
    rest = (loc or "")[m.end():].strip(" ,;") if m else (loc or "")
    if rest:
        out["section"] = rest[:200]
    if kind in ("table", "figure"):
        t = (_TABLE if kind == "table" else _FIGURE).search(loc or "")
        if t:
            out[kind] = t.group(0).strip()
    return out or {"section": loc or "not stated"}


def _normalized(text: str) -> tuple[str, list[int]]:
    """The text under the verbatim checker's normalization, character by character, with the position in the text
    each normalized character comes from (so a match maps back to offsets in the text)."""
    from .util import normalize_for_match
    chars, where = [], []
    for i, ch in enumerate(text):
        for c in normalize_for_match(ch):
            chars.append(c)
            where.append(i)
    return "".join(chars), where


def char_span(text: str, quote: str, norm: tuple[str, list[int]] | None = None) -> tuple[int, int] | None:
    """(char_start, char_end) of a quote in a text, 0-based and end-exclusive: exactly, or else under the verbatim
    checker's normalization (whitespace, case, dashes, compatibility forms); None when it is not there."""
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    from .util import normalize_for_match
    n, where = norm or _normalized(text)
    q = "".join(normalize_for_match(c) for c in quote)
    j = n.find(q) if q else -1
    return (where[j], where[j + len(q) - 1] + 1) if j >= 0 else None


def export(doc: dict, spec: dict, out: Path, bundle_id: str, version: str = "1.0.0", texts: dict[str, str] | None = None,
           created: str | None = None, scope: str | None = None, corpus: dict | None = None, changelog: str | None = None,
           previous: Path | None = None, replaced: dict[str, str] | None = None, ids_from: Path | None = None,
           access: dict | None = None, keep_less_open: bool = False, unshipped: list[str] | None = None,
           title: str | None = None) -> dict:
    """Write the bundle folder; ``title`` names the bundle (its ``topic``, which a host shows as the graph's name;
    default: the graph's title when short, else its leading words, :func:`concise_title`); with ``previous`` (an earlier release folder) record it and the id changes.
    ``ids_from`` (an earlier build, e.g. one made before the first public release) keeps its ids,
    replaced ids and schema properties as ``previous`` does, without recording it as the previous release.

    ``replaced`` maps a retired scale-graph id to the record it was merged into; with ``previous``, the
    survivor lists the retired record's released id in ``replaced_ids``. The schema keeps every
    property the previous release declared on a type it still has (a schema never shrinks).

    ``access`` declares the bundle's audience (default: the graph's stewardship): its audience keys (access, project,
    contributed_by, embargo) replace the graph's, whose other keys (licence) the bundle keeps. Records less open than
    it are withheld unless ``keep_less_open``; so are the shipped ``texts`` of sources the bundle does not hold
    (see the module docstring), whose keys are added to ``unshipped`` when it is given (bundle.json counts them only).
    The texts an earlier export left in ``out/text`` (those its manifest names) are removed first; a file there that
    no manifest names stops the export, which then writes nothing.

    With ``previous`` the version must come after the previous release's, and without ``changelog`` the bundle's
    CHANGELOG.md gets an entry for this version above the previous release's changelog."""
    bundle_title = " ".join((title or "").split())        # the parameter; ``title`` is reused below
    pinned = (doc.get("graph") or {}).get("schema_version") if isinstance(doc, dict) else None
    if pinned != spec.get("version"):
        raise ScaleError(f"the document pins scale-graph {pinned}; the schema given is {spec.get('version')}: a "
                         "kg-bundle names its schema by the version and digest the document pins, so it is not exported")
    if previous:
        pv = json.loads((Path(previous) / "bundle.json").read_text()).get("version")
        if not _semver_after(version, pv):
            raise ScaleError(f"version {version} does not come after the previous release's {pv}: give a later version")
    created = created or pgraph.clock().astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(created, str):
        raise ScaleError(f"created must be an ISO timestamp, YYYY-MM-DDThh:mm:ssZ (got {created!r})")
    # embargoes are read on the bundle's day or today (the earlier of the local and UTC dates, as every path reads
    # them: pgraph.embargo_today), whichever is earlier: a later created never opens one in force
    today = pgraph.embargo_day(created[:10], pgraph.embargo_today(), "created (its day)")
    g0 = doc.get("graph") or {}
    own = dict(pgraph.stewardship_of(g0.get("stewardship")))   # malformed: institution, as every reader reads it
    declared = own if access is None else {**{k: v for k, v in own.items() if k not in AUDIENCE_KEYS}, **access}
    withheld = {"nodes": 0, "links": 0}
    if not keep_less_open:                 # only what everyone the bundle's stewardship admits may see
        doc, withheld = pgraph.restrict_to(doc, declared, today)
    bundle_key = pgraph.access_key(declared, today)
    out = Path(out)
    for name, prior_dir in (("previous", previous), ("ids_from", ids_from)):
        if prior_dir is not None:          # read before anything is written: never export into the release it follows
            a, b = out.resolve(), Path(prior_dir).resolve()
            if a == b or a in b.parents or b in a.parents:
                raise ScaleError(f"the bundle would be written over {name} ({prior_dir}), which it reads; write it to "
                                 "a folder of its own")
    _check_text_names(texts)               # a shipped text is a plain file directly in text/, before anything is written
    report = {"not_exported_links": {}, "split_links": 0, "values_as_text": {}, "nodes_without_report": 0,
              "ranges_as_midpoint": {}, "kept_apart_by_basis": {}}
    status_def = scale_status(spec)
    by_access: dict[str, int] = {}          # exported records by their level on the export date
    # kept by keep_less_open although part of the bundle's audience may not see them (what restrict_to withholds)
    viewers, less_open_ids = (pgraph.audience(doc, declared, today) if keep_less_open else []), set()

    def own_access(rec: dict, declared_in: dict) -> dict:
        """The record's audience where it differs from the bundle's (``{}`` where it is the bundle's): scale_access
        (the level), with the project (scale_access_project) or the institutions (scale_access_institutions) that bound
        it, since the level alone would read as the bundle's own project or institutions. Each key is declared in
        ``declared_in`` (a type's properties)."""
        st = pgraph.effective_stewardship(doc, rec)
        key = pgraph.access_key(st, today)
        if key == bundle_key:
            return {}
        if keep_less_open and pgraph.less_open(st, viewers, today):
            less_open_ids.add(rec["id"])
        acc = {"scale_access": key[0]}
        if key[0] == "project" and key[1]:
            acc["scale_access_project"] = key[1]
        elif key[0] == "institution" and key[1]:
            acc["scale_access_institutions"] = list(key[1])
        for k in acc:
            declared_in[k] = ACCESS_PROPS[k]
        return acc
    done: dict[tuple, dict[tuple, int]] = {}   # (node|link, id) -> {(report key, property): n}: what a conversion did,
    #                                            added to the report only for what the bundle holds

    def tally(owner: tuple, key: str, prop: str | None = None) -> None:
        c = done.setdefault(owner, {})
        c[(key, prop)] = c.get((key, prop), 0) + 1
    sources = {n["id"]: n for n in doc["nodes"] if n["label"] in ("Source",)}
    life = lifecycle.statuses(doc, spec)                       # derived publication statuses (none without notices)
    rest = lifecycle.resting(doc, spec, life)

    def _pub_key(n: dict) -> str:
        p = n["props"]
        if p.get("doi"):
            return p["doi"].lower()
        if (p.get("identifiers") or {}).get("patent"):
            return f"patent:{p['identifiers']['patent'].lower()}"
        return "scale:" + n["id"].rsplit("/", 1)[-1]

    gid: dict[str, str] = {}
    frozen: dict[str, str] = {}             # ids are frozen at first release: reuse the previous release's id
    kept_replaced: dict[str, list[str]] = {}  # replaced_ids stay on the survivor in later releases
    prior = previous or ids_from
    if prior:
        pm = json.loads((Path(prior) / "bundle.json").read_text())
        for n in json.loads((Path(prior) / pm.get("graph_file", "kg/graph.json")).read_text())["nodes"]:
            if n.get("props", {}).get("scale_id"):
                frozen[n["props"]["scale_id"]] = n["id"]
            if n.get("props", {}).get("replaced_ids"):
                kept_replaced[n["id"]] = n["props"]["replaced_ids"]

    # a source without a DOI or patent number is keyed by the last segment of its id, or the key an earlier release
    # gave it, which stays; a new source whose segment another source holds (ex:a/source/1, ex:b/source/1), or
    # that a released source's key holds, is keyed by its whole id. Two sources with one DOI or patent number are
    # two records of one publication, which the bundle cannot tell apart: refused
    pub_keys: dict[str, str] = {}
    by_key: dict[str, list[str]] = {}
    for sid in sorted(sources):
        k = _pub_key(sources[sid])
        released = frozen.get(sid, "")
        if k.startswith("scale:") and released.startswith("Publication:scale:"):
            pub_keys[sid] = released.removeprefix("Publication:")
        else:
            by_key.setdefault(k, []).append(sid)
    taken = set(pub_keys.values())
    for k, sids in sorted(by_key.items()):
        if len(sids) > 1 and not k.startswith("scale:"):
            raise ScaleError(f"sources {', '.join(sids)} share the identifier {k}: one publication is one Source record "
                             "(merge them), or give each its own identifier")
        for sid in sids:
            pub_keys[sid] = k if len(sids) == 1 and k not in taken else f"scale:{sid}"
    if len(set(pub_keys.values())) != len(pub_keys):
        raise ScaleError("two sources would share a Publication id; give one of them a DOI or a patent number")

    def pub_key(n: dict) -> str:
        return pub_keys[n["id"]]

    fresh = []
    for n in sorted(doc["nodes"], key=lambda n: n["id"]):
        if n["id"] in frozen and n["label"] != "Source" and frozen[n["id"]].split(":", 1)[0] == n["label"]:
            gid[n["id"]] = frozen[n["id"]]
        elif n["label"] == "Source":
            gid[n["id"]] = f"Publication:{pub_key(n)}"
        else:
            fresh.append(n)
    # a new record's id is its name's slug and a short digest of its scale-graph id; where two records' ids would
    # meet (one name, digests sharing six characters, or a released id), the digest grows, so no two records share
    # an id and no id seen before changes
    taken = set(gid.values()) | set(frozen.values())
    for n in fresh:
        key = slug_key(n["props"].get("name") or n["id"].rsplit("/", 1)[-1])[:80].rstrip("-")
        digest = hashlib.sha256(n["id"].encode()).hexdigest()
        for width in (6, 16, 64):
            candidate = f"{n['label']}:{key}-{digest[:width]}"
            if candidate not in taken:
                break
        gid[n["id"]] = candidate
        taken.add(candidate)
    if len(set(gid.values())) != len(gid):
        clash = sorted(v for v in set(gid.values()) if list(gid.values()).count(v) > 1)
        raise ScaleError(f"two records would share a bundle id: {clash[:3]}")
    src_of = {sid: pub_key(n) for sid, n in sources.items()}
    if texts:                   # a text named by the source's scale-graph id is its publication's: one key from here on
        named: dict[str, str] = {}
        for k in sorted(texts):
            pk = src_of.get(k, k)
            if pk in named:
                raise ScaleError(f"two texts are given for one publication ({named[pk]} and {k}, both {pk})")
            named[pk] = k
        texts = {pk: texts[k] for pk, k in named.items()}
    names = {n["id"]: n["props"].get("name") for n in doc["nodes"] if n["label"] in ("Person", "Institution")}
    bylines: dict[str, dict[str, list]] = {}   # Source id -> authors / assignees, in byline order
    for e in doc["links"]:
        if e["type"] == "AUTHORED_BY" and e["source"] in sources and names.get(e["target"]):
            ep = e.get("props") or {}
            key = "assignees" if ep.get("role") == "assignee" else "authors"
            bylines.setdefault(e["source"], {}).setdefault(key, []).append((ep.get("position") or 0, names[e["target"]]))

    used_labels = sorted({n["label"] for n in doc["nodes"] if n["label"] != "Source"})
    node_types: dict[str, dict] = {}
    edge_types: dict[str, dict] = {}

    def declare(table: dict, name: str, prop: str, pdef: dict) -> None:
        props = table[name]["properties"]
        if prop not in props:
            props[prop] = pdef

    for lab in used_labels:
        d = spec["nodes"][lab]
        node_types[lab] = {"description": (d.get("description") or lab).strip()[:2000],
                           **({"iri": iri_of(d)} if iri_of(d) else {}),
                           "properties": {"name": {"type": "string", "required": True},
                                          "scale_id": {"type": "string", "description": "The record's id in the scale-graph document."}}}
    node_types["Publication"] = {"description": "A source document: article, patent, thesis or report.",
                                 "properties": {"title": {"type": "string", "required": True}, "doi": {"type": "string"},
                                                "source_id": {"type": "string"}, "year": {"type": "integer"}, "license": {"type": "string"},
                                                "kind": {"type": "string"}, "venue": {"type": "string"}, "url": {"type": "string"},
                                                "authors": {"type": "string[]", "description": "Authors or inventors, in byline order."},
                                                "assignees": {"type": "string[]", "description": "Patent assignees."},
                                                "scale_id": {"type": "string"}}}

    def value_flags(label_or_type: str, name: str, v: dict, table: dict, owner: tuple, outp: dict) -> None:
        """A one-sided bound and an approximate value say so beside the exported quantity or text."""
        if v.get("bound") in ("upper", "lower"):
            declare(table, label_or_type, f"{name}_bound", BOUND)
            outp[f"{name}_bound"] = v["bound"]
            tally(owner, "bounds", name)
        if v.get("qualifier") == "approximate":
            declare(table, label_or_type, f"{name}_qualifier", QUALIFIER)
            outp[f"{name}_qualifier"] = "approximate"
            tally(owner, "approximate_values", name)

    def conv_props(label_or_type: str, props: dict, is_edge: bool, owner: tuple) -> dict:
        d = (spec["edges"] if is_edge else spec["nodes"]).get(label_or_type, {})
        defs = dict(d.get("properties") or {})
        table = edge_types if is_edge else node_types
        outp = {}
        for k, v in props.items():
            if k in NOT_PROPERTIES or k.startswith("_"):
                continue
            pdef = defs.get(k) or {"type": "text"}
            k = bundle_prop(k)
            if pdef.get("type") == "value":
                tk, q, text = _quantity(k, v)
                if isinstance(v, dict) and v.get("status", "present") != "present":     # a typed absence (format 1.1.0)
                    status = v.get("status")
                    if status in ABSENCE_STATUSES:
                        key = tk if k in CANONICAL else f"{tk}_as_reported"   # the property a value would have used
                        if key in outp:
                            continue
                        if k in CANONICAL:              # declared as a present value of that property would be
                            unit, why = SPLIT.get(tk, (CANONICAL[k][0], None))
                            declare(table, label_or_type, key, {"type": "quantity", "unit": unit,
                                                                **({"description": why} if why else {})})
                        else:
                            declare(table, label_or_type, key,
                                    {"type": "string", "description": f"{tk} as reported (not converted)"})
                        entry = {"status": status}
                        if status == "not_reported" and v.get("missing_reason") in MISSING_REASONS:
                            entry["missing_reason"] = v["missing_reason"]
                        outp.setdefault("_value_status", {})[key] = entry
                        tally(owner, "absences", status)
                    else:
                        tally(owner, "absences_not_exported", str(status))
                elif q or text:
                    value_flags(label_or_type, tk, v, table, owner, outp)
                if isinstance(v, dict) and v.get("status", "present") == "present" and isinstance(v.get("basis"), str) \
                        and (q or text) and k in CANONICAL:      # the basis the source states, kept beside the value
                    declare(table, label_or_type, f"{tk}_basis", {"type": "string", "description": f"the basis of {tk} as reported"})
                    outp[f"{tk}_basis"] = v["basis"]
                if q:
                    unit, why = SPLIT.get(tk, (CANONICAL[k][0], None))
                    desc = [why] if why else []
                    if q.get("uncertainty", {}).get("kind") == "range":
                        desc.append("a reported range is exported as its midpoint (value), with the range in uncertainty "
                                    "(kind range, low, high) and the reported text in as_reported")
                        tally(owner, "ranges_as_midpoint", tk)
                    declare(table, label_or_type, tk, {"type": "quantity", "unit": unit})
                    pd = table[label_or_type]["properties"][tk]
                    for d in desc:                       # the schema says what a conversion did
                        if d not in pd.get("description", ""):
                            pd["description"] = f"{pd['description']}; {d}" if pd.get("description") else d
                    if tk != k:
                        tally(owner, "kept_apart_by_basis", tk)
                    outp[tk] = q
                elif text:
                    declare(table, label_or_type, f"{tk}_as_reported",
                            {"type": "string", "description": f"{tk} as reported (not converted)"})
                    outp[f"{tk}_as_reported"] = text
                    tally(owner, "values_as_text", tk)
                    if k == "pressure" and pressure_basis(v) == "unclear":     # say why it was not converted
                        declare(table, label_or_type, "pressure_note",
                                {"type": "string", "description": "why a pressure was not converted"})
                        outp["pressure_note"] = UNCLEAR_PRESSURE
                        tally(owner, "pressure_basis_unclear")
                continue
            if isinstance(v, dict) and "status" in v and pdef.get("type") != "map":
                continue
            gt = _ptype(pdef) if k not in ("name",) else {"type": "string"}
            fits = {"string": True, "string[]": isinstance(v, list) and all(isinstance(x, str) for x in v),
                    "enum": v in gt.get("values", ()), "integer": isinstance(v, int) and not isinstance(v, bool),
                    "number": isinstance(v, (int, float)) and not isinstance(v, bool), "boolean": isinstance(v, bool),
                    "date": isinstance(v, (str, int)) and bool(re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", str(v)))}[gt["type"]]
            if gt["type"] == "string" and not isinstance(v, str):
                v = json.dumps(v, ensure_ascii=False, sort_keys=True)
            if not fits:                    # not of the declared type: kept as text beside it, the type unchanged
                outp[f"{k}_as_reported"] = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)
                tally(owner, "values_as_text", k)
                continue
            if k != "name":
                declare(table, label_or_type, k, gt)
            outp[k] = v
        return outp

    shipped_text = {sid: t for sid, (_, t, _) in (texts or {}).items()}     # publication id -> the text under text/
    norms: dict[str, tuple[str, list[int]]] = {}

    def evidence(ev_list: list[dict]) -> dict[str, list[dict]]:
        by: dict[str, list[dict]] = {}
        for ev in ev_list or []:
            # a reading of a page image cites its transcription, the printed text as read on the image (it
            # corrects the OCR text shipped with the bundle, so the format's text check may not find it verbatim)
            text = ev.get("quote") or ev.get("transcription")
            if ev.get("source") not in src_of:
                continue
            sid = src_of[ev["source"]]
            if text:
                item = {"quote": text[:600], "source_id": sid, "locator": _locator(ev.get("locator"), ev.get("kind"))}
            else:       # a quote withheld under the copyright cap: its digest and length (format 1.1.0)
                held = sorted((f != "quote", f, h, n) for f, h, n in rights.withheld(ev) if f in ("quote", "transcription"))
                if not held or sid in shipped_text:     # a shipped text is quoted, never withheld
                    continue
                _, field, h, n = held[0]
                if not 1 <= n <= WITHHELD_MAX:
                    report["withheld_too_long"] = report.get("withheld_too_long", 0) + 1
                    continue
                item = {"quote_withheld": {"sha256": h, "chars": n, "normalization": NORMALIZATION, "reason": "copyright"},
                        "source_id": sid, "locator": _locator(ev.get("locator"), ev.get("kind"))}
                text = None
            if not ev.get("quote") and ev.get("reading"):
                item["reading"] = ev["reading"]
            if ev.get("evidence_type"):
                item["evidence_type"] = ev["evidence_type"]
            if sid in shipped_text and ev.get("quote") and "quote" in item:     # offsets into the text the bundle ships
                if sid not in norms:
                    norms[sid] = _normalized(shipped_text[sid])
                span = char_span(shipped_text[sid], item["quote"], norms[sid])
                if span:
                    item["locator"]["char_start"], item["locator"]["char_end"] = span
            by.setdefault(sid, []).append(item)
        return by

    nodes, links, reported = [], {}, {}
    for n in sorted(doc["nodes"], key=lambda n: gid[n["id"]]):
        p = n["props"]
        if n["label"] == "Source":
            props = {"title": p.get("title") or p.get("name"), "kind": p.get("kind"), "year": p.get("year"),
                     "license": p.get("licence"), "venue": p.get("venue"), "url": p.get("url"), "scale_id": n["id"]}
            for k, t in PUBLICATION_DATES.items():          # the dates and the text read
                if isinstance(p.get(k), (str, int)) and str(p[k]):
                    val = str(p[k])
                    if t == "date" and not re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", val):
                        props[f"{k}_as_reported"] = val            # not a date: kept as given, beside it
                        continue
                    props[k] = val
            key = pub_key(n)
            props["doi" if p.get("doi") else "source_id"] = key if p.get("doi") else key
            for role, people in sorted(bylines.get(n["id"], {}).items()):
                props[role] = [name for _, name in sorted(people, key=lambda x: x[0])]
            if lifecycle.status_of(life, n["id"]) != lifecycle.UNKNOWN:
                props["source_status"] = lifecycle.status_of(life, n["id"])
                declare(node_types, "Publication", "source_status", SOURCE_STATUS)
            props.update(own_access(n, node_types["Publication"]["properties"]))     # declared wherever it is set
            nodes.append({"id": gid[n["id"]], "label": "Publication", "props": {k: v for k, v in props.items() if v is not None}})
            continue
        props = {"name": p.get("name") or n["id"].rsplit("/", 1)[-1], "scale_id": n["id"],
                 **conv_props(n["label"], p, False, ("node", gid[n["id"]]))}
        props.update(own_access(n, node_types[n["label"]]["properties"]))
        if n["id"] in rest:
            props["source_status"] = _resting(rest[n["id"]])
        elif lifecycle.status_of(life, n["id"]) != lifecycle.UNKNOWN:          # a dataset a notice reaches
            props["source_status"] = lifecycle.status_of(life, n["id"])
        if "source_status" in props:
            node_types[n["label"]]["properties"]["source_status"] = SOURCE_STATUS   # derived; overrides any of that name
        ev = evidence(p.get("evidence"))
        if ev:
            props["_evidence"] = [x for k in sorted(ev) for x in ev[k]]
            props["source_paper_ids"] = sorted(ev)
        nodes.append({"id": gid[n["id"]], "label": n["label"], "props": props})
        cited = set(ev) | {src_of[e["source"]] for e in p.get("evidence") or [] if e.get("source") in src_of}
        reported[gid[n["id"]]] = cited

    for e in doc["links"]:
        if e["type"] == "REPORTED_IN":
            if e["target"] in src_of:
                reported.setdefault(gid[e["source"]], set()).add(src_of[e["target"]])
            continue
        if e["type"] == "AUTHORED_BY" and e["source"] in src_of:
            reported.setdefault(gid[e["target"]], set()).add(src_of[e["source"]])
        ev = evidence((e.get("props") or {}).get("evidence"))
        for end in (e["source"], e["target"]):          # a node is reported in the sources its links quote
            if end in gid and end not in sources:
                reported.setdefault(gid[end], set()).update(ev)
        second = [sid for sid, items in ev.items() if all(_eco(x.get("evidence_type")) in SECOND_HAND_ECO for x in items)]
        for sid in second:            # another work's result, cited: not this source's finding (the format's principle 4)
            del ev[sid]
            by_type = report.setdefault("second_hand_not_exported", {})
            by_type[e["type"]] = by_type.get(e["type"], 0) + 1
        if second and not ev:
            continue
        if not ev and e["type"] == "AUTHORED_BY" and e["source"] in sources:
            report["authors_as_properties"] = report.get("authors_as_properties", 0) + 1
            continue
        notice = sources.get(e["source"], {}).get("props") or {}
        title = notice.get("title") or notice.get("name")
        metadata_only = not ev and e["type"] in lifecycle.LIFECYCLE_EDGES and e["source"] in src_of and bool(title)
        if metadata_only:            # a notice: bibliographic metadata, cited by its title (the format wants a quote on every edge)
            ev = {src_of[e["source"]]: [{"quote": title[:600], "source_id": src_of[e["source"]], "locator": {"section": "title"}}]}
            if e["target"] in gid and e["target"] not in sources:     # a dataset the notice reaches is reported in it
                reported.setdefault(gid[e["target"]], set()).update(ev)
        if not ev:
            report["not_exported_links"][e["type"]] = report["not_exported_links"].get(e["type"], 0) + 1
            continue
        if len(ev) > 1:
            tally(("link", e["id"]), "split_links")
        s, t = gid[e["source"]], gid[e["target"]]
        if e["type"] not in edge_types:
            d = spec["edges"][e["type"]]
            edge_types[e["type"]] = {"description": (d.get("description") or e["type"]).strip()[:2000], "from": [], "to": [],
                                     **({"iri": iri_of(d)} if iri_of(d) else {}),
                                     "properties": {"scale_id": {"type": "string"}}}
        et = edge_types[e["type"]]
        for end, nid in (("from", s), ("to", t)):
            lab = nid.split(":", 1)[0]
            if lab not in et[end]:
                et[end].append(lab)
        ep = e.get("props") or {}
        base = conv_props(e["type"], ep, True, ("link", e["id"]))
        if ep.get("status") in status_def["values"]:          # how firmly the source states it, kept as such
            base["scale_status"] = ep["status"]
            et["properties"]["scale_status"] = status_def
        if isinstance(ep.get("confidence"), (int, float)) and 0 <= ep["confidence"] <= 1:
            base["_confidence"] = ep["confidence"]           # extraction fidelity, as the format's _confidence means it
        kind, inferred = statement(e)
        if inferred:
            tally(("link", e["id"]), "statement_inferred", kind)
        base.update(own_access(e, et["properties"]))
        if metadata_only:
            et["properties"]["metadata_only"] = METADATA_ONLY
        if e["id"] in rest:
            et["properties"]["source_status"] = SOURCE_STATUS
        for sid in sorted(ev):
            eid = canonical_edge_id(e["type"], s, t, sid)
            props = {**base, "scale_id": e["id"], "_evidence": ev[sid], "source_paper_ids": [sid], "_statement": kind,
                     **({"metadata_only": True} if metadata_only else {}),
                     **({"source_status": _resting(rest[e["id"]])} if e["id"] in rest else {})}
            if eid in links:
                # one edge per type, ends and source: a second link there with the same values adds its evidence; one
                # with other values (a second addition of a reagent, another amount) cannot be carried beside the
                # first, so it is left out and listed, never merged under the first one's values
                have = links[eid]["props"]
                if _values(have) == _values(props):
                    have["_evidence"] += [x for x in ev[sid] if x not in have["_evidence"]]
                else:
                    par = report.setdefault("parallel_links_not_exported", {"by_type": {}, "links": []})
                    par["by_type"][e["type"]] = par["by_type"].get(e["type"], 0) + 1
                    par["links"].append({"left_out": e["id"], "kept": have["scale_id"], "source_id": sid})
                continue
            links[eid] = {"id": eid, "type": e["type"], "source": s, "target": t, "props": props}
    pubs = {n["props"].get("doi") or n["props"].get("source_id"): n["id"] for n in nodes if n["label"] == "Publication"}
    for nid, cited in sorted(reported.items()):
        if not cited:
            report["nodes_without_report"] += 1
        for sid in sorted(cited):
            eid = canonical_edge_id("REPORTED_IN", nid, pubs[sid], sid)
            links[eid] = {"id": eid, "type": "REPORTED_IN", "source": nid, "target": pubs[sid], "props": {}}
    reporters = sorted({nid.split(":", 1)[0] for nid in reported})
    if reporters:                                  # a document of sources alone reports nothing (the format wants a non-empty from)
        edge_types["REPORTED_IN"] = {"description": "An entity -> the source that reports it.", "from": reporters,
                                     "to": ["Publication"], "properties": {}}
    for et in edge_types.values():
        et["from"].sort()
        et["to"].sort()
    retired: dict[str, list[str]] = {k: list(v) for k, v in kept_replaced.items()}
    for old_id, new_id in (replaced or {}).items():
        if old_id in frozen and new_id in gid and old_id not in gid:
            retired.setdefault(gid[new_id], []).append(frozen[old_id])
    for n in nodes:
        if n["id"] in retired:
            n["props"]["replaced_ids"] = sorted(set(retired[n["id"]]))   # a format property, not declared in the schema
    kept_nodes = [n for n in nodes if n["label"] == "Publication" or reported.get(n["id"])]
    dropped = len(nodes) - len(kept_nodes)
    if dropped:
        report["nodes_not_exported_no_source"] = dropped
        keep = {n["id"] for n in kept_nodes}
        lost = {}                                  # a link whose end is not exported is not exported either: say so
        for v in links.values():
            if not (v["source"] in keep and v["target"] in keep):
                lost.setdefault(v["props"].get("scale_id") or v["id"], v["type"])
        for t in lost.values():
            report["not_exported_links"][t] = report["not_exported_links"].get(t, 0) + 1
        links = {k: v for k, v in links.items() if v["source"] in keep and v["target"] in keep}
    held = {("node", n["id"]) for n in kept_nodes} | {("link", v["props"].get("scale_id")) for v in links.values()}
    for owner in sorted(done.keys() & held):        # conversions are counted for the records the bundle holds
        for (key, prop), k in sorted(done[owner].items(), key=str):
            if prop is None:
                report[key] = report.get(key, 0) + k
            else:
                bucket = report.setdefault(key, {})
                bucket[prop] = bucket.get(prop, 0) + k
    if life:                                       # statuses and resting records of what the bundle holds
        ids = {n["props"].get("scale_id") for n in kept_nodes} | {v["props"].get("scale_id") for v in links.values()}
        summary = lifecycle.summary({k: v for k, v in life.items() if k in ids}, {k: v for k, v in rest.items() if k in ids})
        if summary:
            report["source_lifecycle"] = summary
    for k in ("ranges_as_midpoint", "kept_apart_by_basis"):   # reported only when something was done
        if not report[k]:
            del report[k]
    if replaced:                                   # what the merge map did: retired ids listed on their survivors
        applied = sum(1 for o, nw in replaced.items() if o in frozen and nw in gid and o not in gid)
        report["replaced"] = {"listed": len(replaced), "applied": applied}
    meta = {v["props"]["scale_id"] for v in links.values() if v["props"].get("metadata_only")}
    if meta:                                       # counted as exported only when the bundle holds them
        report["lifecycle_links_metadata_only"] = len(meta)
    # access: what the bundle holds, by level, and what it withheld; a bundle that is not public says so, and one
    # that kept records less open than its audience (keep_less_open) says that it is not for all of that audience
    level = bundle_key[0]
    less_kept: dict[str, int] = {}                 # records part of the audience may not see, by their level
    for rec in kept_nodes + list(links.values()):
        if rec.get("type") != "REPORTED_IN":          # REPORTED_IN is derived from the evidence of the others
            k = rec["props"].get("scale_access") or level
            by_access[k] = by_access.get(k, 0) + 1
            if rec["props"].get("scale_id") in less_open_ids:
                less_kept[k] = less_kept.get(k, 0) + 1
    less_kept = dict(sorted(less_kept.items()))
    report["access"] = {"bundle": level, "records_by_access": dict(sorted(by_access.items())),
                        **({"withheld_less_open": withheld} if any(withheld.values()) else {}),
                        **({"less_open_kept": less_kept or True} if keep_less_open else {})}
    who = None                                     # the audience by name: the project, or the institutions
    if level == "project":
        who = declared.get("project") if isinstance(declared.get("project"), str) else "no project named"
    elif level == "institution":
        who = ", ".join(pgraph.institutions(declared)) or "no institution named"
    audience = f"access {level!r}" + (f" ({who})" if who else "")
    if less_kept:
        counts = ", ".join(f"{n} {k}" for k, n in less_kept.items())
        report["access_warning"] = (f"not for all of its audience: this bundle, for {audience}, also holds records some "
                                    f"of that audience may not see ({counts}; kept by keep_less_open); send each of "
                                    "them, to a person, host or model, only within its own audience (scale_access, "
                                    "scale_access_project, scale_access_institutions), and the bundle as a whole only to "
                                    "those who may see every record in it")
    elif level != "public":
        report["access_warning"] = (f"not public: this bundle holds records for the audience of {audience}; share it, "
                                    "and send its content to a person, host or model, only within that audience "
                                    "(scale_header.stewardship; scale_access, scale_access_project and "
                                    "scale_access_institutions on records whose audience differs)")
    schema_sha = pgraph.spec_sha256(spec)
    data_status = g0.get("data_status")
    full_title = " ".join((doc["graph"].get("title") or "").split())
    topic = bundle_title or concise_title(full_title)
    if not bundle_title and topic != full_title:      # the graph's title kept in full in the scope
        report["title_shortened"] = {"title": topic, "graph_title": full_title}
    scope_text = scope or doc["graph"].get("description", "")[:1000]
    if topic != full_title and full_title and full_title not in scope_text:
        scope_text = f"{full_title}. {scope_text}".strip()[:1000]
    if data_status in SYNTHETIC_TEXT:      # synthetic examples are not evidence about the world: the bundle says so
        tag, note = SYNTHETIC_TEXT[data_status]
        topic = f"{topic[:300 - len(tag) - 1]} {tag}".strip()
        scope_text = f"{note} {scope_text}".strip()[:1000]
    header = {"lineage": pgraph.SPEC_LINEAGE, "graph_id": g0.get("graph_id"), "data_status": data_status,
              "schema_version": g0.get("schema_version"), "schema_sha256": schema_sha,
              "follows_domains": list(g0.get("follows_domains") or []),
              "stewardship": _header_stewardship(declared, level),
              "access_at_export": {"level": level, "date": today,                # and what part of it may not see
                                   **({"less_open_kept": less_kept} if less_kept else {})},
              **({"filtered_for": g0["filtered_for"]} if g0.get("filtered_for") else {})}
    # the schema is the vocabulary of the scale-graph version the graph pins, the same in every bundle of that version
    # (named scale-<domain> with that version), never derived from the graph; every record is checked against it
    schema_id, schema_version = schema_name(doc), str(doc["graph"].get("schema_version"))
    vocab_nodes, vocab_edges = vocabulary(spec)
    _conforms(vocab_nodes, vocab_edges, kept_nodes, list(links.values()), schema_id)
    schema = {"schema_id": schema_id, "version": schema_version, "title": f"{schema_id} {schema_version}",
              "scope": (f"The {(list(doc['graph'].get('follows_domains') or ['kernel']))[0]} vocabulary of SCALE's scale-graph {schema_version} "
                        f"(spec sha256 {schema_sha}), every label and edge type with every property a bundle can carry; "
                        "a version number names a schema only within SCALE's numbering, the digest everywhere."),
              "extends": {"schema_id": "scale-graph", "version": doc["graph"].get("schema_version"), "sha256": schema_sha},
              "node_types": vocab_nodes, "edge_types": vocab_edges}
    graph = {"directed": True, "multigraph": True,
             "graph": {"bundle_id": bundle_id, "version": version, "schema_id": schema_id, "schema_version": schema_version,
                       "topic": topic},
             "nodes": kept_nodes, "links": sorted(links.values(), key=lambda e: e["id"])}
    gbytes = (json.dumps(graph, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
    # everything is checked and the release followed is read before the folder is touched: a refused export changes
    # nothing, and no file is written through a link or into the release it follows
    lineage = _previous(previous, graph)
    _check_destinations(out, [x for x in (previous, ids_from) if x], texts)
    _clear_texts(out)                      # an earlier export's texts are not this bundle's (nor sealed with it)
    (out / "kg").mkdir(parents=True, exist_ok=True)
    (out / "kg" / "graph.json").write_bytes(gbytes)
    (out / "kg" / "schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    shipped, shipped_licences = 0, set()
    # a text is named by its publication's key (DOI, patent:…, scale:…); one named by the source's id was renamed
    in_bundle = {k for n in kept_nodes if n["label"] == "Publication"
                 for k in (n["props"].get("scale_id"), n["props"].get("doi"), n["props"].get("source_id")) if k}
    unheld = sorted(sid for sid in texts or {} if sid not in in_bundle)
    if unheld:                  # a source the bundle withheld (or never held): its text and id stay out too
        report["texts_not_shipped"] = len(unheld)
        if unshipped is not None:
            unshipped.extend(unheld)
    if texts and len(unheld) < len(texts):
        (out / "text").mkdir(exist_ok=True)
        files = {}
        for sid, (fname, text, licence) in sorted(texts.items()):
            if sid in in_bundle:
                dest = out / "text" / fname
                if dest.is_symlink() or (dest.exists() and not dest.is_file()):
                    raise ScaleError(f"text/{fname} is a link or a folder; a shipped text is written only as a plain file")
                dest.write_text(text)
                files[sid] = {"file": fname, "license": licence, "attribution": sid}
        (out / "text" / "_manifest.json").write_text(json.dumps({"files": files}, indent=1, sort_keys=True) + "\n")
        shipped, shipped_licences = len(files), {f["license"] for f in files.values()}
    subst = sum(1 for e in graph["links"] if e["type"] != "REPORTED_IN")
    lic: dict[str, int] = {}
    for n in kept_nodes:
        if n["label"] == "Publication":
            lic[n["props"].get("license", "not stated")] = lic.get(n["props"].get("license", "not stated"), 0) + 1
    producer = {"agent": "SCALE curation agents (curate-source skill)", "models": [], "prompt_version": "curate-source"}
    if shipped:
        n_off = sum(1 for x in kept_nodes + list(links.values()) for ev in x["props"].get("_evidence") or []
                    if "char_start" in ev["locator"])
        if n_off:
            report["evidence_with_char_offsets"] = n_off
    manifest = {"format": FORMAT_ID, "format_version": FORMAT_VERSION, "bundle_id": bundle_id, "version": version,
                "created": created, "topic": topic, "scope": scope_text, "scale_header": header,
                "graph_file": "kg/graph.json", "graph_sha256": hashlib.sha256(gbytes).hexdigest(),
                "graph_sha256_is_of": "the uncompressed graph.json bytes", "schema_file": "kg/schema.json",
                "schema_id": schema_id, "schema_version": schema_version, **lineage,
                "counts": {"papers": sum(1 for n in kept_nodes if n["label"] == "Publication"), "nodes": len(kept_nodes),
                           "edges": len(graph["links"]), "substantive_edges": subst},
                "corpus": corpus or {}, "publication_licences": dict(sorted(lic.items())), "redistributable_publications": shipped,
                "licence_policy": {"note": (f"Source texts ship under text/ only with the licence each states in "
                                            f"text/_manifest.json ({'; '.join(sorted(shipped_licences))}). Other sources "
                                            "are cited by short verbatim quotes only.") if shipped else
                                   "No source texts are shipped; sources are cited by short verbatim quotes only."},
                "pipeline_version": f"scale-graph {doc['graph'].get('schema_version')} export",
                "producer": producer,
                "export_report": report}
    (out / "bundle.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    (out / "CHANGELOG.md").write_text(changelog or _changelog(doc, version, previous, lineage))
    return manifest


def _header_stewardship(declared: dict, level: str) -> dict:
    """The bundle's stewardship as ``scale_header`` states it: the :data:`STEWARDSHIP_KEYS` the declared stewardship
    sets, as SCALE reads them, failing closed (an ``access`` or ``access_after_embargo`` that is not a level is
    written as institution, a ``project`` that is not an id is left out), and for an institution bundle the
    institutions it names (``contributed_by``: who it is for). The header always states an access: one the
    stewardship leaves out, or states as null or empty, is written as the institution SCALE reads it as, and so is
    the access after an embargo that names none, so no reader has to know how SCALE reads an absence."""
    st = {k: declared[k] for k in STEWARDSHIP_KEYS if declared.get(k)}
    st.setdefault("access", "institution")
    if st["access"] == "embargoed":
        st.setdefault("access_after_embargo", "institution")
    for k, levels in (("access", (*pgraph.OPENNESS, "embargoed")), ("access_after_embargo", pgraph.OPENNESS)):
        if k in st and not (isinstance(st[k], str) and st[k] in levels):
            st[k] = "institution"
    if "project" in st and not isinstance(st["project"], str):
        del st["project"]
    if level == "institution" and pgraph.institutions(declared):
        st["contributed_by"] = pgraph.institutions(declared)
    return st


BUNDLE_FILES = ("kg", "kg/graph.json", "kg/schema.json", "text", "text/_manifest.json", "bundle.json", "CHANGELOG.md",
                "SHA256SUMS", "validation.json")


def _check_destinations(out: Path, priors: list, texts: dict | None) -> None:
    """Every path the export writes (and sealing adds) is checked before the first write: none may be a link, and none
    may lie in the release it follows or the build whose ids it keeps, whatever links lead there."""
    roots = [Path(x).resolve() for x in priors]
    rels = [*BUNDLE_FILES, *(f"text/{e[0]}" for e in (texts or {}).values())]
    for rel in rels:
        dest = Path(out) / rel
        if dest.is_symlink():
            raise ScaleError(f"{dest} is a link; a bundle is written only as plain files and folders: export into a "
                             "folder of its own")
        real = dest.resolve()
        if any(real == r or r in real.parents for r in roots):
            raise ScaleError(f"{dest} lies in the release the bundle follows ({real}); write it to a folder of its own")


def _clear_texts(out: Path) -> None:
    """Remove the texts an earlier export wrote into ``out/text`` (the files its ``_manifest.json`` names, and the
    manifest), so that a text this export does not ship is not left in the bundle and sealed with it. Only plain file
    names in ``out/text`` are removed: every entry is checked first, and a manifest that names anything else (a path,
    an absolute name, ``..``, a directory, a link) stops the export, as does a file there that no manifest names,
    before anything is removed or written."""
    tdir = out / "text"
    if tdir.is_symlink():
        raise ScaleError(f"{tdir} is a link, not a bundle's text folder: export into an empty folder")
    if not tdir.is_dir():
        return
    man = tdir / "_manifest.json"
    named = set()
    if man.is_file():
        try:
            named = {f["file"] for f in json.loads(man.read_text())["files"].values()}
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ScaleError(f"{man} is not a bundle's text manifest ({exc}): export into an empty folder") from exc
    root = tdir.resolve()
    bad = sorted(str(f) for f in named if not _plain_file(tdir, root, f))
    if bad:
        raise ScaleError(f"{man} names {', '.join(bad[:5])}{', …' if len(bad) > 5 else ''}, not a file of {tdir}: "
                         "export into an empty folder")
    other = sorted(p.name for p in tdir.iterdir() if p.name != "_manifest.json" and p.name not in named)
    if other:
        raise ScaleError(f"{tdir} holds files no earlier export shipped ({', '.join(other[:5])}"
                         f"{', …' if len(other) > 5 else ''}): export into an empty folder")
    for p in [*(tdir / f for f in sorted(named)), man]:
        p.unlink(missing_ok=True)
    tdir.rmdir()


def _check_text_names(texts: dict | None) -> None:
    """Every shipped text names a plain file of its own directly in text/: no separator, not absolute, not ``.``,
    ``..`` or the manifest, and no two texts with one name (letter case aside)."""
    seen: dict[str, str] = {}
    for sid, entry in sorted((texts or {}).items()):
        fname = entry[0] if isinstance(entry, (tuple, list)) and entry else None
        bad = (not isinstance(fname, str) or fname in ("", ".", "..", "_manifest.json") or "/" in fname
               or "\\" in fname or "\0" in fname or Path(fname).is_absolute() or Path(fname).name != fname)
        if bad:
            raise ScaleError(f"the text of {sid} is named {fname!r}: a shipped text is a plain file name in text/ "
                             "(no folder, not the manifest)")
        if fname.lower() in seen:
            raise ScaleError(f"the texts of {seen[fname.lower()]} and {sid} are both named {fname!r}")
        seen[fname.lower()] = sid


def _plain_file(tdir: Path, root: Path, name: object) -> bool:
    """Whether a name from an earlier text manifest is a plain file name in ``tdir`` (whose resolved path is
    ``root``): no separator, not absolute, not ``.`` or ``..``, and, when it exists, a regular file (not a link or a
    directory) directly in that folder. A name that does not exist is harmless (nothing to remove)."""
    if not isinstance(name, str) or name in ("", ".", "..") or "/" in name or "\\" in name or "\0" in name:
        return False
    if Path(name).is_absolute() or Path(name).name != name:
        return False
    p = tdir / name
    if not (p.exists() or p.is_symlink()):
        return True
    return p.is_file() and not p.is_symlink() and p.resolve().parent == root


def _semver_after(a: str, b: str | None) -> bool:
    """Whether version a comes after b (MAJOR.MINOR.PATCH; a pre-release or build suffix is not compared)."""
    def key(v):
        m = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(v or ""))
        return tuple(int(x) for x in m.groups()) if m else None
    ka, kb = key(a), key(b)
    return ka is not None and (kb is None or ka > kb)


def _values(props: dict) -> dict:
    """What an edge states, apart from its evidence and the record it comes from."""
    return {k: v for k, v in props.items() if k not in ("_evidence", "source_paper_ids", "scale_id")}


def _changelog(doc: dict, version: str, previous: Path | None, lineage: dict) -> str:
    """The default CHANGELOG.md: an entry for this version, then the previous release's entries as they were."""
    g = doc.get("graph") or {}
    head = f"# Changelog\n\n## {version}\n\n"
    if not previous:
        return head + f"First release, exported from scale-graph {g.get('schema_version')} ({g.get('graph_id')}).\n"
    prev, ch = lineage["previous"], lineage["changes"]
    entry = (f"Exported from scale-graph {g.get('schema_version')} ({g.get('graph_id')}); previous release {prev['version']}. "
             f"Nodes: {ch['nodes_added']} added, {ch['nodes_removed']} removed, {ch['nodes_changed']} changed; edges: "
             f"{ch['edges_added']} added, {ch['edges_removed']} removed, {ch['edges_changed']} changed.\n")
    old = Path(previous) / "CHANGELOG.md"
    text = old.read_text(encoding="utf-8") if old.exists() else ""
    i = text.find("\n## ")
    return head + entry + ("\n" + text[i + 1:].lstrip("\n") if i >= 0 else "")


def _resting(r: dict) -> str:
    return RESTING[0] if r["rests"] == "all" else RESTING[1]


def _previous(prev: Path | None, graph: dict) -> dict:
    if not prev:
        return {"previous": None, "changes": None}
    pm = json.loads((Path(prev) / "bundle.json").read_text())
    pg = json.loads((Path(prev) / pm.get("graph_file", "kg/graph.json")).read_text())
    old_n = {n["id"]: json.dumps(n, sort_keys=True) for n in pg["nodes"]}
    new_n = {n["id"]: json.dumps(n, sort_keys=True) for n in graph["nodes"]}
    old_e = {e["id"]: json.dumps(e, sort_keys=True) for e in pg["links"]}
    new_e = {e["id"]: json.dumps(e, sort_keys=True) for e in graph["links"]}
    return {"previous": {"version": pm["version"], "graph_sha256": pm["graph_sha256"]},
            "changes": {"nodes_added": len(new_n.keys() - old_n.keys()), "nodes_removed": len(old_n.keys() - new_n.keys()),
                        "nodes_changed": sum(1 for k in new_n.keys() & old_n.keys() if new_n[k] != old_n[k]),
                        "edges_added": len(new_e.keys() - old_e.keys()), "edges_removed": len(old_e.keys() - new_e.keys()),
                        "edges_changed": sum(1 for k in new_e.keys() & old_e.keys() if new_e[k] != old_e[k])}}


def seal(out: Path) -> None:
    """Write SHA256SUMS over every file except itself and validation.json."""
    out = Path(out)
    lines = []
    for p in sorted(x for x in out.rglob("*") if x.is_file() and x.name not in ("SHA256SUMS", "validation.json")):
        lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out).as_posix()}")
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise ScaleError(msg)
