"""Quantity contracts: the kind of quantity a value holds, the units that state it and the context a comparison needs.

The contracts are specification: the kernel's ``quantities:`` block (dimensions, the unit vocabulary, the contexts
and the kinds) and, on a property, ``quantity: <kind>`` with ``context: {<context>: <sibling property>}``. The schema
loader checks them (:func:`check_block`, :func:`check_bindings`); this module reads them. Nothing here converts a
number.

* **Units.** :meth:`Contracts.read_unit` reads a unit as the source prints it into a dimension (a product of the base
  dimensions L, M, T, I, Θ, N) and the contexts the unit itself states (``barg`` is gauge, ``V vs RHE`` is on the RHE
  scale, ``sccm`` counts gas at standard conditions). A unit holding a word the vocabulary does not hold is *unread*:
  its dimension is unknown, never guessed.
* **Contexts.** :meth:`Contracts.resolve` reads, for a value of a kind, every context its kind compares by
  (``compare_by``) from what the value states (its unit, ``basis``, ``definition``, ``target``, ``normalized_by``) and
  from the sibling property its binding names (``reference_scale``, ``current_normalization``, ``fraction_basis``).
  The statements must agree. When the value's own statements agree with each other and differ from the sibling's, the
  value counts as an evidenced conversion only if it is derived or computed (``origin``) by a named experiment
  (``produced_by``): it keeps its own context. Otherwise the context is contradictory. A context nothing states, or
  that is stated as ``other``/``not_reported``, is missing: never assumed.
* **Documents.** :func:`check_document` reports, for a document whose schema has contracts: a unit of another dimension
  (an error), a unit the vocabulary cannot read (one warning per property and unit), contradictory contexts and
  normalizations (warnings), a ``normalized_by`` on a kind without a denominator, or one that names no value of the
  denominator's dimension (errors), and an unusual reported percentage of a share (a fraction or an efficiency above
  100 % or below zero: a warning, the value stays as reported).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterator

from .util import ScaleError

BASES = ("L", "M", "T", "I", "Θ", "N")
READ_FROM = ("unit", "basis", "definition", "target", "normalized_by", "sibling")
UNSPECIFIED = "<unspecified>"           # a statement that names no value of the context (other, not_reported)
CONFLICT = "<conflict>"                 # one source naming two values of a context
EVIDENCED = ("derived", "computed")     # a value derived from its record's own by a named experiment (produced_by)
NUMBERED = ("present", "below_detection_limit", "below_quantification_limit")   # statuses that carry a number
VALUE_STATUS = {"present", "not_reported", "not_measured", "not_applicable", "below_detection_limit",
                "below_quantification_limit"}
BLOCK_KEYS = {"maturity", "description", "basis", "dimensions", "units", "contexts", "kinds"}
UNIT_KEYS = {"description", "prefixes", "prefixed", "unprefixed", "spellings", "stating"}
CONTEXT_KEYS = {"description", "read_from", "values", "unspecified", "refine", "open"}
KIND_KEYS = {"description", "dimensions", "compare_by", "denominator", "share", "maturity"}
_EXP = re.compile(r"^(?P<base>.*?)(?:\^|\*\*)?(?P<exp>[-+]?\d+)$")
_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_FORMULA = re.compile(r"^(?:[A-Z][a-z]?\d*)+[+-]?$")          # a species after a counted entity (atom per atom Cu)
_COUNTED = {"atom", "atoms", "molecule", "molecules", "site", "sites", "ion", "ions", "photon", "photons",
            "electron", "electrons"}


# ------------------------------------------------------------------------------------------ dimensions
def parse_dimension(formula: Any) -> tuple:
    """A dimension formula (``M L-1 T-2``; ``1`` for none) as a sorted tuple of (base, exponent)."""
    text = str(formula).strip()
    if text == "1":
        return ()
    out: dict[str, int] = {}
    for part in text.split():
        m = re.fullmatch(r"(L|M|T|I|Θ|N)(-?\d+)?", part)
        if not m:
            raise ScaleError(f"quantities: {formula!r} is not a dimension formula (bases {' '.join(BASES)}, integer "
                             "exponents, e.g. M L-1 T-2; 1 for none)")
        out[m[1]] = out.get(m[1], 0) + int(m[2] or 1)
    return tuple(sorted((b, e) for b, e in out.items() if e))


def _combine(a: tuple, b: tuple, sign: int = 1) -> tuple:
    out = dict(a)
    for base, e in b:
        out[base] = out.get(base, 0) + sign * e
    return tuple(sorted((k, v) for k, v in out.items() if v))


def _power(a: tuple, n: int) -> tuple:
    return tuple(sorted((k, v * n) for k, v in a if v * n))


def formula(vec: tuple) -> str:
    """A dimension as a formula (``M L-1 T-2``; ``1`` for none)."""
    if not vec:
        return "1"
    order = {b: i for i, b in enumerate(("M", "L", "T", "I", "Θ", "N"))}
    return " ".join(f"{b}{'' if e == 1 else e}" for b, e in sorted(vec, key=lambda x: order[x[0]]))


# ------------------------------------------------------------------------------------------ the block
def check_block(block: Any) -> None:
    """Refuse a ``quantities:`` block that is malformed or names what it does not declare (the schema loader calls it
    on the kernel's block)."""
    if not isinstance(block, dict):
        raise ScaleError("quantities: the block is a mapping")
    extra = set(block) - BLOCK_KEYS
    if extra:
        raise ScaleError(f"quantities: unknown keys {sorted(extra)} (keys: {sorted(BLOCK_KEYS)})")
    Contracts(block)                                   # compiling it checks every name it uses


@dataclass
class Reading:
    """A unit as :meth:`Contracts.read_unit` reads it: ``vector`` its dimension (None when unread), ``contexts`` what
    the unit itself states (context -> value, or :data:`CONFLICT`), ``unread`` the words the vocabulary does not
    hold."""
    text: str
    vector: tuple | None
    contexts: dict = field(default_factory=dict)
    unread: list = field(default_factory=list)

    @property
    def read(self) -> bool:
        return self.vector is not None


@dataclass
class Statement:
    source: str          # unit (what it states, or a dimension only one value fits), basis, definition, target,
    #                      normalized_by or sibling
    value: str           # a value of the context, UNSPECIFIED or CONFLICT
    said: str            # what was read, for the message


@dataclass
class Context:
    """One context of one value: ``value`` (a value of the context), or why not: ``missing`` (nothing names one, or
    what is stated names none) or ``contradiction`` (statements disagree); ``converted`` when an evidenced conversion
    kept the value's own over its record's."""
    name: str
    value: str | None = None
    missing: str | None = None
    contradiction: str | None = None
    converted: bool = False
    statements: list = field(default_factory=list)


class Contracts:
    """The compiled ``quantities:`` block of a schema: dimensions, the unit vocabulary, contexts and kinds."""

    def __init__(self, block: dict):
        self.block = block
        dims = block.get("dimensions") or {}
        if not isinstance(dims, dict) or not dims:
            raise ScaleError("quantities: dimensions is a mapping of names to formulas")
        self.dimensions = {str(k): parse_dimension(v) for k, v in dims.items()}
        self.names: dict[tuple, str] = {}
        for name, vec in self.dimensions.items():
            self.names.setdefault(vec, name)
        self._units(block.get("units") or {})
        self._contexts(block.get("contexts") or {})
        self._kinds(block.get("kinds") or {})
        self._cache: dict[tuple, Reading] = {}

    # ---- compiling
    def dim(self, name: Any, where: str) -> tuple:
        if name not in self.dimensions:
            raise ScaleError(f"quantities: {where} names the dimension {name!r}, which dimensions does not declare")
        return self.dimensions[name]

    def _units(self, u: dict) -> None:
        if set(u) - UNIT_KEYS:
            raise ScaleError(f"quantities.units: unknown keys {sorted(set(u) - UNIT_KEYS)}")
        self.prefixes = sorted({str(p) for p in u.get("prefixes") or []}, key=lambda p: (-len(p), p))
        self.atoms: dict[str, tuple[tuple, bool, dict]] = {}
        for prefixed, key in ((True, "prefixed"), (False, "unprefixed")):
            for sym, name in (u.get(key) or {}).items():
                self._atom(str(sym), self.dim(name, f"units.{key}.{sym}"), prefixed, {}, f"units.{key}")
        self.spellings: dict[str, tuple[tuple, dict]] = {}
        for name, texts in (u.get("spellings") or {}).items():
            for t in texts or []:
                self._spelling(str(t), self.dim(name, f"units.spellings.{name}"), {}, "units.spellings")
        self._stating = u.get("stating") or {}             # checked against the contexts below

    def _atom(self, sym: str, vec: tuple, prefixed: bool, ctx: dict, where: str) -> None:
        if sym in self.atoms:
            raise ScaleError(f"quantities: {where} declares the unit symbol {sym!r} twice")
        self.atoms[sym] = (vec, prefixed, ctx)

    def _spelling(self, text: str, vec: tuple, ctx: dict, where: str) -> None:
        key = normalize_unit(text)
        if key in self.spellings:
            raise ScaleError(f"quantities: {where} declares the spelling {text!r} twice")
        self.spellings[key] = (vec, ctx)

    def _contexts(self, cs: dict) -> None:
        self.contexts: dict[str, dict] = {}
        for name, c in cs.items():
            if not isinstance(c, dict) or set(c) - CONTEXT_KEYS:
                raise ScaleError(f"quantities.contexts.{name}: a mapping of {sorted(CONTEXT_KEYS)}")
            read = list(c.get("read_from") or [])
            if not read or set(read) - set(READ_FROM):
                raise ScaleError(f"quantities.contexts.{name}: read_from lists sources among {list(READ_FROM)}")
            values = c.get("values") or {}
            if c.get("open"):
                if values or read != ["target"]:
                    raise ScaleError(f"quantities.contexts.{name}: an open context reads target only and lists no values")
            elif not values:
                raise ScaleError(f"quantities.contexts.{name}: lists its values (or is open)")
            vals = {}
            for v, d in values.items():
                d = d or {}
                if set(d) - {"terms", "dimensions"}:
                    raise ScaleError(f"quantities.contexts.{name}.{v}: takes terms and dimensions")
                vals[str(v)] = {"terms": [str(t) for t in d.get("terms") or []],
                                "dimensions": [self.dim(x, f"contexts.{name}.{v}") for x in d.get("dimensions") or []]
                                if "dimensions" in d else None}
            refine = c.get("refine") or {}
            for v in refine:
                if v not in vals:
                    raise ScaleError(f"quantities.contexts.{name}.refine names {v!r}, not one of its values")
            self.contexts[name] = {"read_from": read, "values": vals, "unspecified": [str(x) for x in c.get("unspecified") or []],
                                   "refine": dict(refine), "open": bool(c.get("open")),
                                   "_terms": _term_patterns(vals)}
        for sym, d in self._stating.items():
            d = dict(d or {})
            vec = self.dim(d.pop("dimension", None), f"units.stating.{sym}")
            for k, v in d.items():
                if k not in self.contexts or v not in self.contexts[k]["values"]:
                    raise ScaleError(f"quantities.units.stating.{sym}: {k}: {v!r} is not a value of a declared context")
                if "unit" not in self.contexts[k]["read_from"]:
                    raise ScaleError(f"quantities.units.stating.{sym}: the context {k} is not read from units")
            if " " in str(sym) or "/" in str(sym):
                self._spelling(str(sym), vec, d, "units.stating")
            else:
                self._atom(str(sym), vec, False, d, "units.stating")
        self._annotations = {name: c["_terms"] for name, c in self.contexts.items() if "unit" in c["read_from"]}

    def _kinds(self, ks: dict) -> None:
        self.kinds: dict[str, dict] = {}
        if not isinstance(ks, dict) or not ks:
            raise ScaleError("quantities: kinds is a mapping of kind names to contracts")
        for name, k in ks.items():
            if not isinstance(k, dict) or set(k) - KIND_KEYS:
                raise ScaleError(f"quantities.kinds.{name}: a mapping of {sorted(KIND_KEYS)}")
            dims = [self.dim(x, f"kinds.{name}") for x in k.get("dimensions") or []]
            if not dims:
                raise ScaleError(f"quantities.kinds.{name}: names its dimensions")
            compare = []
            for i, c in enumerate(k.get("compare_by") or []):
                c = {"context": c} if isinstance(c, str) else dict(c or {})
                if set(c) - {"context", "when_dimension", "when"} or c.get("context") not in self.contexts:
                    raise ScaleError(f"quantities.kinds.{name}.compare_by[{i}]: names a declared context, optionally "
                                     "with when_dimension or when")
                c["when_dimension"] = [self.dim(x, f"kinds.{name}.compare_by") for x in c.get("when_dimension") or []]
                for other, vals in (c.get("when") or {}).items():
                    if other not in [x["context"] for x in compare] or set(vals) - set(self.contexts[other]["values"]):
                        raise ScaleError(f"quantities.kinds.{name}.compare_by[{i}].when: names an earlier context of "
                                         "compare_by and values of it")
                compare.append(c)
            den = k.get("denominator")
            if den is not None and (not isinstance(den, dict) or not den.get("dimensions")):
                raise ScaleError(f"quantities.kinds.{name}.denominator: names its dimensions")
            self.kinds[name] = {"dimensions": dims, "compare_by": compare, "share": bool(k.get("share")),
                                "denominator": [self.dim(x, f"kinds.{name}.denominator") for x in den["dimensions"]]
                                if den else None}

    # ---- units
    def read_unit(self, text: Any, contexts: tuple = ()) -> Reading:
        """``text`` read as a unit (a dimension and the contexts it states), extracting the words of ``contexts`` it
        holds first (``vs RHE``, ``(gauge)``, ``(STP)``). Cached."""
        key = (text if isinstance(text, str) else repr(text), tuple(contexts))
        if key not in self._cache:
            self._cache[key] = self._read(text, contexts)
        return self._cache[key]

    def _read(self, text: Any, contexts: tuple) -> Reading:
        if not isinstance(text, str) or not text.strip():
            return Reading(str(text), None, {}, ["(no unit)"])
        t = normalize_unit(text)
        stated: dict[str, str] = {}
        for c in contexts:
            pats = self._annotations.get(c)
            if not pats:
                continue
            t, found = _extract(t, pats)
            for v in found:
                stated[c] = v if stated.get(c, v) == v else CONFLICT
        t = " ".join(re.sub(r"(?<=[A-Za-z])\.(?=\s|/|\)|\*|$)", "", t).split())   # abbreviation dots: lb. -> lb
        if t in self.spellings:
            vec, ctx = self.spellings[t]
            return Reading(text, vec, _merge(stated, ctx))
        if t.casefold() in {k.casefold() for k in self.spellings if " " in k}:       # multiword spellings: any case
            k = next(k for k in self.spellings if k.casefold() == t.casefold())
            vec, ctx = self.spellings[k]
            return Reading(text, vec, _merge(stated, ctx))
        try:
            vec, ctx, unread = _Parser(self, t).parse()
        except _Unread as exc:
            return Reading(text, None, stated, [str(exc)])
        if unread:
            return Reading(text, None, stated, unread)
        return Reading(text, vec, _merge(stated, ctx))

    def atom(self, token: str) -> tuple[tuple, dict] | None:
        """A token of a unit as one symbol: itself, a word in any case, or a prefix and a prefixed symbol."""
        if token in self.atoms:
            vec, _, ctx = self.atoms[token]
            return vec, ctx
        low = token.lower()
        if len(token) > 3 and low in self.atoms and not self.atoms[low][1]:          # words: Hours, Days
            vec, _, ctx = self.atoms[low]
            return vec, ctx
        for p in self.prefixes:
            if token.startswith(p) and len(token) > len(p):
                rest = token[len(p):]
                if rest in self.atoms and self.atoms[rest][1]:
                    vec, _, ctx = self.atoms[rest]
                    return vec, ctx
        return None

    def dimension_name(self, vec: tuple | None) -> str:
        if vec is None:
            return "unread"
        return f"{self.names[vec]} ({formula(vec)})" if vec in self.names else formula(vec)

    # ---- contexts
    def statements_in_text(self, context: str, text: Any, vec: tuple | None) -> list[str]:
        """The values of ``context`` a text names (its terms, as whole words). A value that declares the dimensions it
        fits is kept only for a value of one of them; with an unread unit (``vec`` None), terms that name several such
        values decide nothing (GHSV is a gas volume per catalyst volume in h-1, per catalyst mass in mL/(g h))."""
        if not isinstance(text, str) or not text.strip():
            return []
        c = self.contexts[context]
        hits = sorted({v for v, pat in c["_terms"] if pat.search(text)})
        dims = {v: c["values"][v]["dimensions"] for v in hits}
        if vec is not None:
            narrowed = [v for v in hits if dims[v] is None or vec in dims[v]]
            return narrowed or hits
        if len(hits) > 1 and all(dims[v] is not None for v in hits):
            return []
        return hits

    def sibling_value(self, context: str, v: Any) -> str | None:
        """A sibling property's value (an enum value) as a value of the context: itself, UNSPECIFIED (other,
        not_reported), or a value whose terms name it; None for anything else."""
        if not isinstance(v, str):
            return None
        c = self.contexts[context]
        if v in c["values"]:
            return v
        if v in c["unspecified"]:
            return UNSPECIFIED
        hits = self.statements_in_text(context, v.replace("_", " "), None)
        return hits[0] if len(hits) == 1 else None

    def applies(self, entry: dict, vec: tuple | None, resolved: dict) -> bool:
        """Whether one ``compare_by`` entry applies to a value of dimension ``vec`` (None: unread), given the contexts
        resolved before it: ``when_dimension`` holds for a value of one of those dimensions (and for an unread unit,
        which cannot say), ``when`` for a value whose earlier context is one of the values named (or not resolved)."""
        if entry["when_dimension"] and vec is not None and vec not in entry["when_dimension"]:
            return False
        for k, vals in (entry.get("when") or {}).items():
            got = resolved.get(k)
            if got is not None and got.value is not None and got.value.split(":")[0] not in vals:
                return False
        return True

    def resolve(self, kind: str, v: dict, reading: Reading | None, sibling: dict | None = None,
                denominator_name: str | None = None) -> dict[str, Context]:
        """Every context a value of ``kind`` is compared by, read from the value and its record (``sibling``: context
        -> (the sibling property, its value), and ``refine:<field>`` -> (field, value))."""
        out: dict[str, Context] = {}
        vec = reading.vector if reading else None
        for entry in self.kinds[kind]["compare_by"]:
            if self.applies(entry, vec, out):
                out[entry["context"]] = self._resolve_one(entry["context"], v, reading, sibling or {}, denominator_name)
        return out

    def _resolve_one(self, name: str, v: dict, reading: Reading | None, sibling: dict, den: str | None) -> Context:
        c = self.contexts[name]
        vec = reading.vector if reading else None
        st: list[Statement] = []
        for src in c["read_from"]:
            if src == "unit" and reading is not None:
                said = reading.contexts.get(name)
                if said:
                    st.append(Statement("unit", said, str(v.get("unit"))))
                elif vec is not None:              # a dimension that only one value of the context allows
                    fits = [x for x, d in c["values"].items() if d["dimensions"] is not None and vec in d["dimensions"]]
                    loose = [x for x, d in c["values"].items() if d["dimensions"] is None]
                    if len(fits) == 1 and not loose:
                        st.append(Statement("unit", fits[0], f"{v.get('unit')}, {self.dimension_name(vec)}"))
            elif src in ("basis", "definition"):
                hits = self.statements_in_text(name, v.get(src), vec)
                if len(hits) == 1:
                    st.append(Statement(src, hits[0], str(v.get(src))))
                elif hits:
                    st.append(Statement(src, CONFLICT, f"{v.get(src)}, which names {' and '.join(hits)}"))
            elif src == "target" and isinstance(v.get("target"), str) and v["target"]:
                st.append(Statement("target", v["target"], v["target"]))
            elif src == "normalized_by" and den:
                hits = self.statements_in_text(name, den.replace("_", " "), None)
                if len(hits) == 1:
                    st.append(Statement("normalized_by", hits[0], den))
            elif src == "sibling" and name in sibling:
                prop, raw = sibling[name]
                mapped = self.sibling_value(name, raw)
                if mapped is not None:
                    st.append(Statement("sibling", mapped, f"{prop} {raw}"))
        ctx = Context(name, statements=st)
        bad = next((s for s in st if s.value == CONFLICT), None)
        if bad is not None:
            ctx.contradiction = f"its {bad.source} names more than one {name} ({bad.said})"
            return ctx
        named = [s for s in st if s.value != UNSPECIFIED]
        values = {s.value for s in named}
        if len(values) > 1:
            own = {s.value for s in named if s.source != "sibling"}
            if len(own) == 1 and evidenced(v) and any(s.source == "sibling" for s in named):
                ctx.value, ctx.converted = own.pop(), True        # an evidenced conversion keeps its own
            else:
                ctx.contradiction = "; ".join(f"its {s.source} ({s.said}) says {s.value}" for s in named)
                return ctx
        elif values:
            ctx.value = values.pop()
        else:
            if st:                                   # stated, as other or not_reported
                ctx.missing = "; ".join(f"its {s.source} ({s.said}) names no {name}" for s in st)
            else:
                srcs = [s for s in c["read_from"] if s != "sibling" or name in sibling]
                ctx.missing = f"nothing states its {name} (read from its {', '.join(srcs)})"
            return ctx
        if not c["open"]:
            dims = c["values"][ctx.value]["dimensions"]
            if dims is not None and vec is not None and vec not in dims:
                said = "; ".join(f"its {s.source} ({s.said})" for s in named if s.value == ctx.value)
                ctx.contradiction = (f"its unit {v.get('unit')} is {self.dimension_name(vec)}, but {said} says {ctx.value}, "
                                     f"which is {' or '.join(self.dimension_name(d) for d in dims) or 'no normalized quantity'}")
                ctx.value = None
                return ctx
            fld = c["refine"].get(ctx.value)
            if fld:
                ref = (sibling.get(f"refine:{fld}") or (None, None))[1]
                if not isinstance(ref, str) or not ref:
                    ctx.missing, ctx.value = f"{ctx.value} names no {fld} (what it is relative to)", None
                    return ctx
                ctx.value = f"{ctx.value}:{ref}"
        return ctx


def evidenced(v: dict) -> bool:
    """A value derived or computed from its record's own by a named experiment: an evidenced conversion."""
    return v.get("origin") in EVIDENCED and isinstance(v.get("produced_by"), str) and bool(v["produced_by"])


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = v if out.get(k, v) == v else CONFLICT
    return out


def _term_patterns(values: dict) -> list[tuple[str, re.Pattern]]:
    """(value, pattern) for every term of a context's values, longest first. A term in capitals (RHE, ECSA, STP) is
    matched as written; any other in any case. A term is a whole word: never part of a longer one."""
    out = []
    for v, d in values.items():
        for t in d["terms"]:
            flags = 0 if (t.upper() == t and any(ch.isalpha() for ch in t)) else re.I
            pat = re.escape(t).replace(r"\ ", r"\s+")
            left = r"(?<![A-Za-z0-9])" if t[0].isalnum() else ""
            right = r"(?![A-Za-z0-9])" if t[-1].isalnum() or t[-1] in "+." else ""
            out.append((v, re.compile(left + pat + right, flags), len(t)))
    out.sort(key=lambda x: -x[2])
    return [(v, p) for v, p, _ in out]


def _extract(text: str, pats: list[tuple[str, re.Pattern]]) -> tuple[str, list[str]]:
    """``text`` without the context words it holds (with a vs/versus/at before, parentheses or an underscore around),
    and the values they name."""
    found = []
    for v, pat in pats:
        while True:
            m = pat.search(text)
            if not m:
                break
            a, b = m.span()
            pre = re.search(r"(?:\b(?:vs\.?|versus|at)\s*|_)$", text[:a])
            if pre:
                a = pre.start()
            if text[:a].rstrip().endswith("(") and text[b:].lstrip().startswith(")"):
                a = text[:a].rstrip().rfind("(")
                b = b + (len(text[b:]) - len(text[b:].lstrip())) + 1
            text = (text[:a] + " " + text[b:]).strip()
            found.append(v)
    return text, found


def normalize_unit(text: str) -> str:
    """A unit as the reader reads it: compatibility forms (², µ, ℃, ⁻) as plain characters, one space between words,
    and the spellings of squares, cubes and percentages joined (sq. in. -> in2, cu. m -> m3, mol % -> mol%)."""
    t = unicodedata.normalize("NFKC", text).replace("−", "-").replace("µ", "μ")
    t = " ".join(t.split())
    t = re.sub(r"\bsq\.?\s*(in|ft|cm|mm|m)\b\.?", r"\g<1>2", t)
    t = re.sub(r"\bcu\.?\s*(in|ft|cm|mm|m)\b\.?", r"\g<1>3", t)
    t = re.sub(r"\b(?:lb|lbs)[\s-]*mol(?:e|es|s)?\b", "lbmol", t)
    t = re.sub(r"\bkg[\s-]*mol(?:e|es|s)?\b", "kmol", t)
    t = re.sub(r"\b(?:mm|cm|in)\.?\s*Hg\b", lambda m: m.group(0).split(".")[0].replace(" ", "") + "Hg"
               if "." in m.group(0) else m.group(0).replace(" ", ""), t)
    t = re.sub(r"\b(mol|mole|wt|vol|at|atomic|mass)\.?\s*%", lambda m: {"mole": "mol", "atomic": "at"}.get(m[1], m[1]) + "%", t)
    t = re.sub(r"%\s*\(?\s*w/w\s*\)?", "wt%", t)
    t = re.sub(r"%\s*\(?\s*v/v\s*\)?", "vol%", t)
    t = re.sub(r"%\s*\(\s*mol\s*\)", "mol%", t)
    t = re.sub(r"\bdeg\.?\s*(C|F)\b", r"deg\1", t)
    return t.strip()


class _Unread(Exception):
    pass


class _Parser:
    """A unit expression: products (space, *, ·, ×), quotients (/ and per, left to right), exponents, parentheses and
    numbers (g/100 m3)."""

    def __init__(self, contracts: Contracts, text: str):
        self.c = contracts
        spaced = re.sub(r"([()/*·×])", r" \1 ", text)
        self.tokens = [t for t in spaced.split() if t]
        self.i = 0
        self.unread: list[str] = []
        self.ctx: dict[str, str] = {}

    def parse(self) -> tuple[tuple, dict, list]:
        if not self.tokens:
            raise _Unread("(nothing left to read)")
        vec = self.expr()
        if self.i != len(self.tokens):
            raise _Unread(f"(cannot read {' '.join(self.tokens[self.i:])!r})")
        return vec, self.ctx, self.unread

    def peek(self) -> str | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def expr(self) -> tuple:
        vec = self.term()
        while self.peek() in ("/", "per"):
            self.i += 1
            vec = _combine(vec, self.term(), -1)
        return vec

    def term(self) -> tuple:
        vec = self.factor()
        while self.peek() not in (None, "/", "per", ")"):
            if self.peek() in ("*", "·", "×"):
                self.i += 1
            vec = _combine(vec, self.factor())
        return vec

    def factor(self) -> tuple:
        tok = self.peek()
        if tok is None:
            raise _Unread("(a unit ends in an operator)")
        self.i += 1
        if tok == "(":
            vec = self.expr()
            if self.peek() != ")":
                raise _Unread("(an unclosed parenthesis)")
            self.i += 1
            nxt = self.peek()
            if nxt and re.fullmatch(r"(?:\^|\*\*)?[-+]?\d+", nxt):
                self.i += 1
                vec = _power(vec, int(nxt.lstrip("^*")))
            return vec
        if _NUMBER.match(tok):
            return ()
        hit = self.c.atom(tok)
        if hit is None:
            m = _EXP.match(tok)
            if m and m["base"]:
                base = self.c.atom(m["base"])
                if base is not None:
                    vec, ctx = base
                    self._ctx(ctx)
                    return _power(vec, int(m["exp"]))
            if self.tokens[self.i - 2:self.i - 1] and self.tokens[self.i - 2] in _COUNTED and _FORMULA.match(tok):
                return ()                          # atom per atom Cu: the species counted
            self.unread.append(tok)
            return ()
        vec, ctx = hit
        self._ctx(ctx)
        return vec

    def _ctx(self, ctx: dict) -> None:
        for k, v in ctx.items():
            self.ctx[k] = v if self.ctx.get(k, v) == v else CONFLICT


# ------------------------------------------------------------------------------------------ a schema's contracts
_COMPILED: dict[str, Contracts] = {}


def contracts(spec: dict) -> Contracts | None:
    """The contracts of an assembled schema (None for a schema without them: every version before 0.3.0)."""
    block = spec.get("quantities") if isinstance(spec, dict) else None
    if not isinstance(block, dict):
        return None
    key = hashlib.sha256(json.dumps(block, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if key not in _COMPILED:
        _COMPILED[key] = Contracts(block)
    return _COMPILED[key]


def binding(spec: dict, record: dict, prop: str) -> tuple[str | None, dict]:
    """(the kind a record's property is bound to, its sibling contexts: context -> sibling property name) from the
    property's definition (``quantity``, ``context``)."""
    d = prop_def(spec, record, prop)
    if not isinstance(d, dict):
        return None, {}
    return d.get("quantity"), dict(d.get("context") or {})


def prop_def(spec: dict, record: dict, prop: str) -> dict | None:
    if not isinstance(record, dict):
        return None
    if "type" in record and "source" in record:
        owner, common = (spec.get("edges") or {}).get(record.get("type")) or {}, spec["common"]["link"]["properties"]
    else:
        owner, common = (spec.get("nodes") or {}).get(record.get("label")) or {}, spec["common"]["node"]["properties"]
    return (owner.get("properties") or {}).get(prop) or common.get(prop)


def siblings(c: Contracts, kind: str, record: dict, ctx_map: dict) -> dict:
    """The contexts a record's sibling properties state for a value of ``kind``: context -> (property, value), and the
    fields a context's value is refined by (``refine:<field>``)."""
    props = record.get("props") if isinstance(record.get("props"), dict) else {}
    out = {}
    for ctxname, sib in ctx_map.items():
        if sib in props:
            out[ctxname] = (sib, props[sib])
        for fld in c.contexts[ctxname]["refine"].values():
            out[f"refine:{fld}"] = (fld, props.get(fld))
    return out


def values_at(v: Any) -> Iterator[tuple[str, dict]]:
    """The value objects of a property: itself, or each entry of a list (with its position)."""
    if isinstance(v, dict) and v.get("status") in VALUE_STATUS:
        yield "", v
    elif isinstance(v, list):
        for i, x in enumerate(v):
            if isinstance(x, dict) and x.get("status") in VALUE_STATUS:
                yield f"[{i}]", x


def numbered(v: dict) -> bool:
    return v.get("status") in NUMBERED and any(isinstance(v.get(k), (int, float)) and not isinstance(v.get(k), bool)
                                               for k in ("value", "lower", "upper"))


def states_no_unit(u: Any) -> bool:
    return u is None or (isinstance(u, str) and " ".join(u.split()).casefold() in ("", "not stated"))


@dataclass
class Read:
    """A value read under its contract: its kind, its unit, its contexts and its denominator."""
    kind: str
    reading: Reading | None
    contexts: dict
    denominator: dict | None = None


def read_value(c: Contracts, spec: dict, record: dict, prop: str, v: dict, records: dict,
               variables: dict) -> Read | None:
    """A value object of a record's property read under its contract (the property's binding, else the quantity_kind
    of the Variable it names), or None when no contract applies."""
    kind, ctx_map = binding(spec, record, prop) if prop else (None, {})
    if kind is None:
        kind = variables.get(v.get("variable")) if isinstance(v.get("variable"), str) else None
        ctx_map = {}
        if kind not in c.kinds:
            return None
    names = tuple(x["context"] for x in c.kinds[kind]["compare_by"])
    reading = None if states_no_unit(v.get("unit")) else c.read_unit(v.get("unit"), names)
    den = denominator(v, records)
    sib = siblings(c, kind, record, ctx_map)
    return Read(kind, reading, c.resolve(kind, v, reading, sib, den["name"] if den else None), den)


def denominator(v: dict, records: dict) -> dict | None:
    """The record and value a value's ``normalized_by`` names: {record, path, name (the property it names), value (the
    value object, or None), found (whether the path resolves)}; None without one."""
    ref = v.get("normalized_by")
    if not isinstance(ref, dict) or not isinstance(ref.get("record"), str):
        return None
    rec = records.get(ref["record"])
    path = ref.get("path") if isinstance(ref.get("path"), str) else None
    out = {"record": ref["record"], "path": path, "name": None, "value": None, "found": rec is not None and path is None}
    if rec is None or path is None:
        return out
    parts = [p.replace("~1", "/").replace("~0", "~") for p in path.split("/")[1:]]
    cur: Any = rec.get("props") or {}
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        elif isinstance(cur, list) and p.isdigit() and int(p) < len(cur):
            cur = cur[int(p)]
        else:
            return out
    names = [p for p in parts if not p.isdigit()]
    out.update(found=True, name=names[-1] if names else None,
               value=cur if isinstance(cur, dict) and cur.get("status") in VALUE_STATUS else None)
    return out


def variable_kinds(doc: dict) -> dict:
    """Variable id -> its quantity_kind, for the Variables of a document."""
    return {n["id"]: (n.get("props") or {}).get("quantity_kind") for n in doc.get("nodes") or []
            if isinstance(n, dict) and n.get("label") == "Variable" and isinstance(n.get("id"), str)}


# ------------------------------------------------------------------------------------------ documents
def _values_anywhere(obj: Any, path: str = "") -> Iterator[tuple[str, dict]]:
    if isinstance(obj, dict):
        if obj.get("status") in VALUE_STATUS and path:
            yield path, obj
            return
        for k, x in obj.items():
            if k not in ("evidence", "stewardship"):
                yield from _values_anywhere(x, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            yield from _values_anywhere(x, f"{path}/{i}")


def check_document(doc: dict, spec: dict, rep) -> None:
    """The contract diagnostics of a document (the module docstring); nothing when its schema has no contracts."""
    c = contracts(spec)
    if c is None:
        return
    nodes = [n for n in doc.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)]
    links = [e for e in doc.get("links") or [] if isinstance(e, dict) and isinstance(e.get("id"), str)]
    records = {r["id"]: r for r in nodes + links}
    variables = variable_kinds(doc)
    unread: dict[tuple[str, str, str], int] = {}

    def owner(r: dict) -> str:
        return r.get("type") if "source" in r and "type" in r else r.get("label")

    for r in nodes + links:
        props = r.get("props") if isinstance(r.get("props"), dict) else {}
        rid = r["id"]
        for path, v in _values_anywhere(props):
            top = path.split("/")[1]
            bound = binding(spec, r, top)[0]
            direct = bound is not None and re.fullmatch(rf"/{re.escape(top)}(?:/\d+)?", path)
            prop = top if direct else ""
            got = read_value(c, spec, r, prop, v, records, variables)
            if got is None:
                if isinstance(v.get("normalized_by"), dict):
                    rep.add("error", rid, f"{path[1:]}: normalized_by names a denominator, but no quantity contract applies "
                                          "to this value (bind its property, or name a Variable whose quantity_kind has one)")
                continue
            where = path[1:].replace("/", ".")
            _check_value(c, rep, rid, where, got, v, records, unread, (owner(r), where.split(".")[0]))
    for n in nodes:
        p = n.get("props") if isinstance(n.get("props"), dict) else {}
        if n.get("label") == "Variable" and p.get("quantity_kind") in c.kinds and not states_no_unit(p.get("unit")):
            kind = p["quantity_kind"]
            reading = c.read_unit(p["unit"])
            if reading.read and reading.vector not in c.kinds[kind]["dimensions"]:
                rep.add("error", n["id"], f"unit: {p['unit']!r} is {c.dimension_name(reading.vector)}, not a dimension of "
                                          f"{kind} ({_dims(c, kind)}): the {kind} contract")
    for (own, prop, unit), k in sorted(unread.items()):
        rep.add("warning", "<graph>", f"{own}.{prop}: the unit {unit!r} ({k} value{'s' if k != 1 else ''}) is not one the "
                                      "quantity contracts can read, so its dimension is not checked and a scientific "
                                      "comparison leaves it out; write it in the units the vocabulary holds (core/graph/kernel.yaml, quantities.units)")


def _dims(c: Contracts, kind: str) -> str:
    return ", ".join(c.dimension_name(x) for x in c.kinds[kind]["dimensions"])


def _check_value(c: Contracts, rep, rid: str, where: str, got: Read, v: dict, records: dict, unread: dict,
                 at: tuple[str, str]) -> None:
    kind, reading = got.kind, got.reading
    if reading is not None and numbered(v):
        if not reading.read:
            unread[(at[0], at[1], str(v.get("unit")))] = unread.get((at[0], at[1], str(v.get("unit"))), 0) + 1
        elif reading.vector not in c.kinds[kind]["dimensions"]:
            rep.add("error", rid, f"{where}: unit {v.get('unit')!r} is {c.dimension_name(reading.vector)}, not a dimension "
                                  f"of {kind} ({_dims(c, kind)}): the {kind} contract")
    for ctx in got.contexts.values():
        if ctx.contradiction:
            rep.add("warning", rid, f"{where}: contradictory {ctx.name}: {ctx.contradiction}; it stays as reported, and a "
                                    "scientific comparison leaves it out until they agree")
    den = got.denominator
    if isinstance(v.get("normalized_by"), dict):
        allowed = c.kinds[kind]["denominator"]
        if allowed is None:
            rep.add("error", rid, f"{where}: normalized_by names a denominator, but {kind} is not divided by one (its "
                                  "contract declares no denominator)")
        elif den is not None and den["record"] in records and den["path"] is not None and den["found"]:
            if den["value"] is None:          # a path that does not resolve is reported by the record-path check
                rep.add("error", rid, f"{where}: normalized_by {den['record']}{den['path']} is not a value object")
            elif numbered(den["value"]) and not states_no_unit(den["value"].get("unit")):
                r2 = c.read_unit(den["value"]["unit"])
                if r2.read and r2.vector not in allowed:
                    rep.add("error", rid, f"{where}: normalized_by {den['record']}{den['path']} is "
                                          f"{c.dimension_name(r2.vector)} ({den['value']['unit']}), not a denominator of "
                                          f"{kind} ({', '.join(c.dimension_name(x) for x in allowed)})")
    if c.kinds[kind]["share"] and numbered(v) and reading is not None and reading.read and not reading.unread:
        _share_advisory(rep, rid, where, kind, v, at[1])


SHARE_NAMES = re.compile(r"(?:^|_)(?:selectivity|selectivities|conversion|yield|balance)(?:_|$)")   # pgraph.plausibility


def _share_advisory(rep, rid: str, where: str, kind: str, v: dict, prop: str) -> None:
    """A reported percentage of a share (a fraction, an efficiency) above 100 % or below zero: a warning; the value stays
    as reported. Only a percent unit is read (%, wt%, mol%): a number in the unit 1 may be a proportion (parts) as the
    source gives it. The names the plausibility advisory reads already (selectivity, conversion, yield, balance) are
    left to it."""
    unit = " ".join(str(v.get("unit")).split())
    if not unit.endswith("%") or SHARE_NAMES.search(prop.lower()):
        return
    nums = [v[k] for k in ("value", "lower", "upper") if isinstance(v.get(k), (int, float)) and not isinstance(v.get(k), bool)]
    if not nums:
        return
    least = None if v.get("bound") == "upper" else min(nums)
    most = None if v.get("bound") == "lower" else max(nums)
    if least is not None and least > 100:
        rep.add("warning", rid, f"{where}: {least} {unit} is above 100 % for a {kind}; check the reading (a sum over "
                                "products, another basis) — it stays as reported")
    elif most is not None and most < 0:
        rep.add("warning", rid, f"{where}: {most} {unit} is below zero for a {kind}; check the reading — it stays as "
                                "reported")


# ------------------------------------------------------------------------------------------ the loader's checks
def check_bindings(spec: dict) -> None:
    """Refuse a binding that names an undeclared kind, sits on a property that holds no value, or names a sibling that
    the record does not have or whose values the context cannot read (every enum value must name a value of the
    context, or be one it lists as unspecified)."""
    c = contracts(spec)
    for kind, block in (("nodes", spec.get("nodes") or {}), ("abstract", spec.get("abstract") or {}),
                        ("edges", spec.get("edges") or {})):
        for owner, d in block.items():
            props = {**(spec["common"]["link" if kind == "edges" else "node"]["properties"]), **(d.get("properties") or {})}
            for p, pd in (d.get("properties") or {}).items():
                if not isinstance(pd, dict) or ("quantity" not in pd and "context" not in pd):
                    continue
                where = f"{owner}.{p}"
                if c is None:
                    raise ScaleError(f"{where} names a quantity contract, but the kernel declares none (quantities:)")
                k = pd.get("quantity")
                if k not in c.kinds:
                    raise ScaleError(f"{where}: quantity {k!r} is not a kind the kernel declares ({sorted(c.kinds)})")
                holds = pd.get("type") == "value" or (pd.get("type") == "list" and (pd.get("items") or {}).get("type") == "value")
                if not holds:
                    raise ScaleError(f"{where}: a quantity contract binds a value property (or a list of values)")
                for ctx, sib in (pd.get("context") or {}).items():
                    if ctx not in [x["context"] for x in c.kinds[k]["compare_by"]] or "sibling" not in c.contexts[ctx]["read_from"]:
                        raise ScaleError(f"{where}: context {ctx!r} is not one {k} compares by and reads from a sibling")
                    sd = props.get(sib)
                    if not isinstance(sd, dict) or sd.get("type") != "enum":
                        raise ScaleError(f"{where}: the sibling {sib!r} of context {ctx} is not an enum property of {owner}")
                    bad = [x for x in sd.get("values") or [] if c.sibling_value(ctx, x) is None]
                    if bad:
                        raise ScaleError(f"{where}: {sib} values {bad} name no value of the context {ctx} (add them to its "
                                         "values, terms or unspecified)")
                    for val, fld in c.contexts[ctx]["refine"].items():
                        if val in (sd.get("values") or []) and fld not in props:
                            raise ScaleError(f"{where}: context {ctx} {val} is refined by {fld!r}, which {owner} does not have")


# ------------------------------------------------------------------------------------------ the schema diff
def diff(a: dict | None, b: dict | None, out: dict) -> None:
    """What a change of the ``quantities:`` block does (added, removed, changed, narrowed, loosened), into ``out`` (the
    shape of ``schema_change.diff_specs``). A kind's dimensions or a unit's dimension changing, a context its kind is
    compared by being added or a term moving to another value change what a value means or which values compare."""
    a, b = a or {}, b or {}
    if not a and not b:
        return
    if not a or not b:
        (out["added"] if b else out["removed"]).append("quantities")
        if not a:
            out["narrowed"].append("quantities: units are checked against each bound property's kind")
        return
    da, db = a.get("dimensions") or {}, b.get("dimensions") or {}
    for k in sorted(set(da) | set(db)):
        if k not in da:
            out["added"].append(f"quantities.dimensions.{k}")
        elif k not in db:
            out["removed"].append(f"quantities.dimensions.{k}")
        elif parse_dimension(da[k]) != parse_dimension(db[k]):
            out["changed"].append(f"quantities.dimensions.{k}: {da[k]} -> {db[k]}")
    ua, ub = _unit_index(a), _unit_index(b)
    for u in sorted(set(ua) | set(ub)):
        if u not in ua:
            out["loosened"].append(f"quantities.units: {u} is read ({ub[u]})")
        elif u not in ub:
            out["narrowed"].append(f"quantities.units: {u} is no longer read")
        elif ua[u] != ub[u]:
            out["changed"].append(f"quantities.units: {u} {ua[u]} -> {ub[u]}")
    pa, pb = set((a.get("units") or {}).get("prefixes") or []), set((b.get("units") or {}).get("prefixes") or [])
    out["loosened"] += [f"quantities.units.prefixes + {x}" for x in sorted(pb - pa)]
    out["narrowed"] += [f"quantities.units.prefixes - {x}" for x in sorted(pa - pb)]
    ca, cb = a.get("contexts") or {}, b.get("contexts") or {}
    for k in sorted(set(ca) | set(cb)):
        if k not in ca:
            out["added"].append(f"quantities.contexts.{k}")
            continue
        if k not in cb:
            out["removed"].append(f"quantities.contexts.{k}")
            continue
        xa, xb = ca[k] or {}, cb[k] or {}
        ra, rb = set(xa.get("read_from") or []), set(xb.get("read_from") or [])
        out["loosened"] += [f"quantities.contexts.{k} is read from {s}" for s in sorted(rb - ra)]
        out["narrowed"] += [f"quantities.contexts.{k} is no longer read from {s}" for s in sorted(ra - rb)]
        va, vb = xa.get("values") or {}, xb.get("values") or {}
        out["added"] += [f"quantities.contexts.{k} = {v}" for v in sorted(set(vb) - set(va))]
        out["removed"] += [f"quantities.contexts.{k} = {v}" for v in sorted(set(va) - set(vb))]
        ta = {t: v for v, d in va.items() for t in ((d or {}).get("terms") or [])}
        tb = {t: v for v, d in vb.items() for t in ((d or {}).get("terms") or [])}
        for t in sorted(set(ta) | set(tb)):
            if t not in ta:
                out["loosened"].append(f"quantities.contexts.{k}: {t!r} names {tb[t]}")
            elif t not in tb:
                out["narrowed"].append(f"quantities.contexts.{k}: {t!r} no longer names {ta[t]}")
            elif ta[t] != tb[t]:
                out["changed"].append(f"quantities.contexts.{k}: {t!r} names {ta[t]} -> {tb[t]}")
        for v in sorted(set(va) & set(vb)):
            if (va[v] or {}).get("dimensions") != (vb[v] or {}).get("dimensions"):
                out["changed"].append(f"quantities.contexts.{k}.{v}: dimensions {(va[v] or {}).get('dimensions')} -> "
                                      f"{(vb[v] or {}).get('dimensions')}")
        for key in ("unspecified", "refine", "open"):
            if xa.get(key) != xb.get(key):
                out["changed"].append(f"quantities.contexts.{k}: {key} {xa.get(key)!r} -> {xb.get(key)!r}")
    ka, kb = a.get("kinds") or {}, b.get("kinds") or {}
    for k in sorted(set(ka) | set(kb)):
        if k not in ka:
            out["added"].append(f"quantities.kinds.{k}")
            continue
        if k not in kb:
            out["removed"].append(f"quantities.kinds.{k}")
            continue
        xa, xb = ka[k] or {}, kb[k] or {}
        sa, sb = set(xa.get("dimensions") or []), set(xb.get("dimensions") or [])
        out["loosened"] += [f"quantities.kinds.{k} takes {x}" for x in sorted(sb - sa)]
        out["narrowed"] += [f"quantities.kinds.{k} no longer takes {x}" for x in sorted(sa - sb)]
        cmp_a, cmp_b = {_cmp_key(x): x for x in xa.get("compare_by") or []}, {_cmp_key(x): x for x in xb.get("compare_by") or []}
        out["narrowed"] += [f"quantities.kinds.{k} is compared by {x}" for x in sorted(set(cmp_b) - set(cmp_a))]
        out["loosened"] += [f"quantities.kinds.{k} is no longer compared by {x}" for x in sorted(set(cmp_a) - set(cmp_b))]
        for x in sorted(set(cmp_a) & set(cmp_b)):
            if cmp_a[x] != cmp_b[x]:
                out["changed"].append(f"quantities.kinds.{k}: compare_by {cmp_a[x]!r} -> {cmp_b[x]!r}")
        if (xa.get("denominator") or {}).get("dimensions") != (xb.get("denominator") or {}).get("dimensions"):
            out["changed"].append(f"quantities.kinds.{k}: denominator {(xa.get('denominator') or {}).get('dimensions')} -> "
                                  f"{(xb.get('denominator') or {}).get('dimensions')}")
        if bool(xa.get("share")) != bool(xb.get("share")):
            out["changed"].append(f"quantities.kinds.{k}: share {bool(xa.get('share'))} -> {bool(xb.get('share'))}")


def _cmp_key(x: Any) -> str:
    return x if isinstance(x, str) else str((x or {}).get("context"))


def _unit_index(block: dict) -> dict[str, str]:
    """Every symbol and spelling of a block's units with what it reads as (dimension, prefixed, contexts)."""
    u = block.get("units") or {}
    out = {}
    for key in ("prefixed", "unprefixed"):
        for sym, name in (u.get(key) or {}).items():
            out[str(sym)] = f"{name}{', prefixed' if key == 'prefixed' else ''}"
    for name, texts in (u.get("spellings") or {}).items():
        for t in texts or []:
            out[str(t)] = str(name)
    for sym, d in (u.get("stating") or {}).items():
        d = dict(d or {})
        dim = d.pop("dimension", None)
        out[str(sym)] = f"{dim}, " + ", ".join(f"{k} {v}" for k, v in sorted(d.items()))
    return out


def diff_binding(where: str, da: dict, db: dict, out: dict) -> None:
    """A property's binding (``quantity``, ``context``) against its earlier one."""
    qa, qb = da.get("quantity"), db.get("quantity")
    if qa != qb:
        if qa is None:
            out["narrowed"].append(f"{where} holds quantity {qb} (its unit must be of that kind's dimensions)")
        elif qb is None:
            out["loosened"].append(f"{where} no longer holds a quantity contract ({qa})")
        else:
            out["changed"].append(f"{where}: quantity {qa} -> {qb}")
    ca, cb = da.get("context") or {}, db.get("context") or {}
    for k in sorted(set(ca) | set(cb)):
        if ca.get(k) != cb.get(k):
            kind = "narrowed" if k not in ca else "loosened" if k not in cb else "changed"
            out[kind].append(f"{where}: context {k} from {ca.get(k)!r} -> {cb.get(k)!r}")


# ------------------------------------------------------------------------------------------ migration
def move_component_quantities(doc: dict, spec: dict | None) -> list[str]:
    """0.2.1 -> 0.3.0: a HAS_COMPONENT ``fraction`` whose unit is an amount (g, mol, L) moves to ``amount``, and one
    whose unit is a concentration (mol/L, g/m3) to ``concentration``, the value object whole; its ``fraction_basis``,
    which said what the fraction counted, goes with it (the change says so). Every other value whose unit is of another
    dimension than its contract's stops the step (it cannot be mapped). A fraction whose unit cannot be read stays a
    fraction. Returns the changes."""
    c = contracts(spec or {})
    if c is None:
        raise ScaleError("the step to the quantity contracts needs the target schema (its quantities block)")
    changes: list[str] = []
    amounts = {c.dimensions[n] for n in ("mass", "amount", "volume")}
    conc = {c.dimensions[n] for n in ("amount_concentration", "mass_concentration")}
    for e in doc.get("links") or []:
        if e.get("type") != "HAS_COMPONENT" or not isinstance(e.get("props"), dict):
            continue
        p = e["props"]
        v = p.get("fraction")
        if not isinstance(v, dict) or states_no_unit(v.get("unit")):
            continue
        r = c.read_unit(v["unit"], ("fraction_basis",))
        if not r.read or r.vector == ():
            continue
        to = "amount" if r.vector in amounts else "concentration" if r.vector in conc else None
        if to is None:
            continue                                   # left for the validator to name (another dimension)
        if to in p:
            raise ScaleError(f"{e.get('id')}: its fraction is in {v['unit']!r} ({c.dimension_name(r.vector)}), and it holds "
                             f"{to} already: the step cannot move it there; curate it by hand")
        p[to] = p.pop("fraction")
        basis = p.pop("fraction_basis", None)              # it said what the fraction counted; the unit says it now
        changes.append(f"{e.get('id')}: fraction {v.get('value', v.get('lower'))} {v['unit']} -> {to} "
                       f"({c.dimension_name(r.vector)})" + (f", fraction_basis {basis} dropped with it" if basis else ""))
    bad = []
    variables = variable_kinds(doc)
    records = {r["id"]: r for r in (doc.get("nodes") or []) + (doc.get("links") or []) if isinstance(r, dict)
               and isinstance(r.get("id"), str)}
    for r in records.values():
        props = r.get("props") if isinstance(r.get("props"), dict) else {}
        for k, x in props.items():
            kind = binding(spec, r, k)[0]
            for pos, v in values_at(x):
                got = read_value(c, spec, r, k, v, records, variables) if kind else None
                if got and got.reading and got.reading.read and numbered(v) and got.reading.vector not in c.kinds[kind]["dimensions"]:
                    bad.append(f"{r['id']}.{k}{pos}: {v.get('unit')!r} is {c.dimension_name(got.reading.vector)}, not {kind}")
    if bad:
        raise ScaleError("the step to the quantity contracts cannot map values whose unit is of another dimension than "
                         f"their property's quantity (curate them by hand, then migrate): {'; '.join(bad[:20])}"
                         + (f" (and {len(bad) - 20} more)" if len(bad) > 20 else ""))
    return changes


def describe_binding(c: Contracts, d: dict) -> str | None:
    """A property's contract as ``describe`` prints it: ``quantity <kind> [<dimensions>]; compared by <contexts>``."""
    k = d.get("quantity") if isinstance(d, dict) else None
    if k is None or c is None or k not in c.kinds:
        return None
    ctx = [x["context"] for x in c.kinds[k]["compare_by"]]
    sib = d.get("context") or {}
    by = ", ".join(f"{x} (also from {sib[x]})" if x in sib else x for x in ctx)
    den = c.kinds[k]["denominator"]
    return (f"quantity {k} [{', '.join(c.names.get(x, formula(x)) for x in c.kinds[k]['dimensions'])}]"
            + (f"; compared by {by}" if by else "")
            + (f"; divided by {' or '.join(c.names.get(x, formula(x)) for x in den)} (normalized_by)" if den else ""))
