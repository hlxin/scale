"""Advisory warnings on a feed's gas ratio (issue #107, a follow-up of #90): the comparable form of a feed's ratio is
``ratio`` on the HAS_COMPONENT edge of the numerator gas (target the denominator); ``Feed.ratios`` keeps the printed
form. Two warnings, never errors, and nothing is stored or converted:

- a Feed whose ``ratios`` holds a gas ratio (a key such as ``h2_co`` or ``ph2_pco_ratio``, or a value whose
  ``as_reported``, ``note`` or ``definition`` names two gases) while no HAS_COMPONENT edge of the feed carries a ``ratio``;
- a Feed with the fractions (by mole or volume) of two reactant gases (HAS_COMPONENT role ``reactant``, two different
  components) while no edge of the feed carries a ``ratio``: the ratio is implied by the source. A diluent, an inert
  gas or a component with another role is not a reactant, so a feed of one reactant in N2 or Ar is not warned about.

A feed with no HAS_COMPONENT edge, a document without Feed records and a feed whose edge carries a ``ratio`` are never
warned about."""

from __future__ import annotations

import re

GASES = {"H2", "CO", "CO2", "H2O", "CH4", "O2", "N2", "NH3", "NO", "NO2", "N2O", "C2H2", "C2H4", "C2H6", "C3H6", "C3H8",
         "C4H10", "H2S", "SO2", "O3", "Ar", "He", "Ne", "Kr", "Xe", "CH3OH", "HCl"}
GAS_LOWER = {g.lower(): g for g in GASES}
WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
BASES = {"mole", "volume"}
AMBIGUOUS_IN_KEYS = {"no", "he", "ne"}     # also English words or abbreviations: matched only as formulas in text


def _gas(token: str, exact: bool) -> str | None:
    """The gas a token names (``H2``, ``pCO``, ``ph2`` in a key), or None."""
    for t in (token, token[1:] if token[:1] in "pP" else ""):
        if not exact and t.lower() in AMBIGUOUS_IN_KEYS:
            continue
        if t and (t in GASES or (not exact and t.lower() in GAS_LOWER)):
            return GAS_LOWER.get(t.lower(), t)
    return None


def gases_named(key: str, value) -> set[str]:
    """The gases a ``ratios`` entry names: in its key (lower-case tokens split at non-alphanumerics) or, failing that,
    in the value's printed text, ``note`` or ``definition`` (formulas as written)."""
    found = {g for t in re.split(r"[^A-Za-z0-9]+", str(key)) if t and (g := _gas(t, False))}
    if len(found) >= 2 or not isinstance(value, dict):
        return found
    for f in ("as_reported", "note", "definition"):
        text = value.get(f)
        if isinstance(text, str):
            found |= {g for t in WORD.findall(text) if (g := _gas(t, True))}
    return found


def check_document(doc: dict, rep) -> None:
    feeds = {str(n.get("id")): n.get("props") or {} for n in doc.get("nodes") or [] if n.get("label") == "Feed"}
    if not feeds:
        return
    edges: dict[str, list[dict]] = {}
    for lk in doc.get("links") or []:
        if lk.get("type") == "HAS_COMPONENT" and str(lk.get("source")) in feeds:
            edges.setdefault(str(lk["source"]), []).append(lk)
    for fid, props in feeds.items():
        comps = edges.get(fid, [])
        if any(isinstance(((c.get("props") or {}).get("ratio")), list) and (c.get("props") or {}).get("ratio")
               for c in comps):
            continue
        ratios = props.get("ratios")
        gas_keys = sorted(str(k) for k, v in ratios.items() if len(gases_named(k, v)) >= 2) \
            if isinstance(ratios, dict) else []
        if gas_keys:
            rep.add("warning", fid, f"feed ratio only in ratios ({', '.join(gas_keys)}): no HAS_COMPONENT edge of this "
                    "feed carries a ratio; state it on the edge of the numerator gas (target the denominator, basis "
                    "mole, volume or partial_pressure), and keep the printed form in ratios beside it")
        reactants = set()
        for c in comps:
            p = c.get("props") or {}
            f = p.get("fraction")
            if (p.get("role") == "reactant" and p.get("fraction_basis") in BASES and isinstance(f, dict)
                    and f.get("status") == "present"):
                reactants.add(str(c.get("target")))
        if len(reactants) >= 2:
            rep.add("warning", fid, f"feed with the fractions of {len(reactants)} reactant gases and no ratio: no "
                    "HAS_COMPONENT edge of this feed carries a ratio; if the source gives or implies a gas ratio "
                    "(H2/CO), state it on the edge of the numerator gas (target the denominator, origin curated for "
                    "an implied one)")
