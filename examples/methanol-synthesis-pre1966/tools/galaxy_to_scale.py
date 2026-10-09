"""Convert the GALAXY bundle ``methanol-synthesis`` 1.0.0 into a SCALE catalysis-schema document.

The bundle is a verified curation of 60 historical sources on methanol synthesis (1927-1965):
every substantive edge carries a verbatim quote and a PDF page. This script restates it in the
catalysis schema 0.1.0 (release legacy/v0.3.0) without adding scientific content. The record format is
retired (decision record 0012), so only the record-format tools of the earlier releases read the result:

* values are restored to the units the source printed (``as_reported``); the bundle's SI
  conversions are not carried over, because the schema performs no unit conversion;
* what the schema cannot express (ranges, bounds, role-only reaction participants) is kept in
  ``extensions["scale:unmodeled_context"]`` and routed as a gap, never approximated;
* run structure (Experiment, CatalyticSystem, Sample) is assembled only from explicit bundle
  edges; ambiguous links become Claims instead of structure.

Deterministic: the same bundle gives the same bytes (write with ``scale fmt`` conventions).

Usage::

    python galaxy_to_scale.py BUNDLE_DIR OUT.json [--report REPORT.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
sys.dont_write_bytecode = True  # keep examples/ free of compiled files
import unicodedata
from collections import defaultdict
from pathlib import Path

try:  # canonical JSON as written by `scale fmt` (docs/style.md)
    from scale.util import dump_canonical
except ImportError:  # pragma: no cover - outside a SCALE installation
    def dump_canonical(data) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

P = "ex:msyn"

# --------------------------------------------------------------------------- helpers


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9.]+", "-", t).strip("-.")
    return t or "x"


def short_hash(*parts: str, n: int = 12) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:n]


def node_slug(nid: str) -> str:
    return slug(nid.split(":", 1)[1])


def human(prop: str) -> str:
    return prop.replace("_", " ")


# --------------------------------------------------------------------------- reported values

_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_NUM = re.compile(r"(?<![\d.,])[-−]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:\s*[×xX]\s*10\s*[-−]?\s*\d+)?")
_WORDS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "fifty": 50,
          "hundred": 100}
_APPROX = re.compile(r"\b(about|approx|approximately|ca\.|circa|roughly|nearly|etwa)\b|(^|\s)~\s*\d|約|≈", re.I)
TEMP_UNITS = [(re.compile(r"°\s*F|deg\.?\s*F|degrees?\s*F", re.I), "°F"),
              (re.compile(r"°\s*C|℃|deg\.?\s*C|degrees?\s*(C|cent)|度|Grad|\d\s*C\b\.?", re.I), "°C"),
              (re.compile(r"°\s*K|\bK\b"), "K"),
              (re.compile(r"°"), "°C")]
PRESS_UNITS = [(re.compile(r"kg\.?\s*/\s*(sq\.?\s*)?cm|kg\.?\s*per\s*(sq\.?\s*)?cm|kg/cm", re.I), "kg/cm2"),
               (re.compile(r"\batm|atmospheres?|Atm\.?|気圧", re.I), "atm"),
               (re.compile(r"\bpsi|p\.s\.i|lb\.?\s*(per|/)\s*sq|pounds?\s*per\s*sq|\blbs?\b\.?|pounds", re.I), "psi"),
               (re.compile(r"\d\s*at\b"), "at"),
               (re.compile(r"\bbar\b", re.I), "bar"),
               (re.compile(r"\bMPa\b"), "MPa"),
               (re.compile(r"mm\.?\s*(Hg|of mercury)|\d\s*mm\b", re.I), "mmHg")]
VOL_UNITS = [(re.compile(r"\blit(er|re)s?\b|\bl\.?\b|\bL\b", re.I), "L"),
             (re.compile(r"\bm3\b|m³|cubic met", re.I), "m3"),
             (re.compile(r"\bcc\b|c\.c\.|\bml\b|\bmL\b|cm3|cm³", re.I), "mL"),
             (re.compile(r"cu\.?\s*ft|cubic f", re.I), "ft3")]
LEN_UNITS = [(re.compile(r"\bmm\b"), "mm"), (re.compile(r"\bcm\b"), "cm"),
             (re.compile(r"\bin(ch(es)?)?\b\.?|\"|″", re.I), "in"), (re.compile(r"\bft\b|feet|foot", re.I), "ft"),
             (re.compile(r"\bm\b"), "m")]
MASS_UNITS = [(re.compile(r"short tons?|\btons?\b", re.I), "short ton"), (re.compile(r"\bkg\b", re.I), "kg"),
              (re.compile(r"\bg\b|grams?|\bgm\b", re.I), "g"), (re.compile(r"\blb", re.I), "lb")]


def numbers(text: str) -> list[float]:
    t = text.translate(_SUP).replace("−", "-")
    out = []
    for m in _NUM.finditer(t):
        s = m.group(0).replace(" ", "")
        # a comma before exactly three digits groups thousands; otherwise it is a decimal comma
        s = re.sub(r",(?=\d{3}(?!\d))", "", s).replace(",", ".")
        mm = re.match(r"^(-?[\d.]+)[×xX]10(-?\d+)$", s)
        try:
            out.append(float(mm.group(1)) * 10 ** int(mm.group(2)) if mm else float(s))
        except ValueError:
            continue
    return out


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)


def _unit_from(text: str, table) -> str | None:
    for rx, unit in table:
        if rx.search(text):
            return unit
    return None


# Reported strings the parser cannot read, restored by hand from the bundle's as_reported text:
# (bundle node, property) -> (value, unit as printed, reading note). A value of None marks a bound.
KCAL = "kcal/mol"
OVERRIDES = {
    ("Catalyst:basf-chromium-manganese-oxide-worked-example-contact", "chromium_oxide_manganese_oxide_ratio"): (1, "1", "'equal molecular proportions' read as 1"),
    ("Catalyst:tsuchiya-shiba-adsorption-synthesis-catalyst", "total_surface_area"): (1.0e7, "cm2", None),
    ("ReactantFeed:equimolar-carbon-dioxide-hydrogen-feed", "hydrogen_carbon_dioxide_ratio"): (1, "1", "'equal volumes' read as 1"),
    ("ReactantFeed:equimolar-carbon-monoxide-hydrogen-feed", "hydrogen_carbon_monoxide_ratio"): (1, "1", "'equal volumes' read as 1"),
    ("ReactionCondition:basf-disclosed-mixed-oxide-operating-envelope", "minimum_hydrogen_carbon_oxides_ratio"): (None, None, None),
    ("ReactionCondition:frolich-catalyst-cycle-highest-bath-temperature", "space_velocity"): (28, "L gas/h per 3 mL catalyst", None),
    ("ReactionCondition:frolich-catalyst-cycle-initial-bath-temperature", "space_velocity"): (28, "L gas/h per 3 mL catalyst", None),
    ("ReactionCondition:frolich-catalyst-cycle-intermediate-bath-temperature", "space_velocity"): (28, "L gas/h per 3 mL catalyst", None),
    ("ReactionCondition:kawamura-pressure-glow-experiments", "space_velocity"): (1000, "h-1", "unit not printed"),
    ("ReactionCondition:ogino-oba-uchida-ternary-catalyst-synthesis-series", "space_velocity"): (1.0e4, "h-1", "printed '1.10⁴', read as 1 × 10⁴; unit not printed"),
    ("ReactionCondition:tsuchiya-shiba-mixed-adsorption-experiment", "temperature"): (300, "°C", "'3OO”C' is an OCR reading of 300 °C"),
    ("ThermodynamicQuantity:ideal-gas-pressure-quotient-inferred-from-brown-galloway-conversion", "equilibrium_pressure_quotient"): (1.98e-5, "atm-2", "'~' read as a minus sign; pressures in atm per the source"),
    ("ThermodynamicQuantity:newton-dodge-combined-methanol-equilibrium-estimate", "equilibrium_pressure_quotient"): (4e-3, "atm-2", "'~' read as a minus sign; pressures in atm per the source"),
    ("ThermodynamicQuantity:newton-dodge-lower-temperature-observed-equilibrium-constant", "equilibrium_pressure_quotient"): (0.00608, "atm-2", None),
    ("ThermodynamicQuantity:newton-dodge-mean-formaldehyde-hydrogenation-equilibrium-constant", "equilibrium_inverse_pressure_constant"): (2090, "atm-1", "unit not printed with the value"),
    ("ThermodynamicQuantity:newton-dodge-middle-temperature-observed-equilibrium-constant", "equilibrium_pressure_quotient"): (0.00232, "atm-2", None),
    ("ThermodynamicQuantity:newton-dodge-upper-temperature-observed-equilibrium-constant", "equilibrium_pressure_quotient"): (0.00088, "atm-2", None),
    ("ThermodynamicQuantity:ogino-oba-uchida-state-a-apparent-activation-energy", "activation_energy"): (16.6, KCAL, None),
    ("ThermodynamicQuantity:ogino-oba-uchida-state-b-apparent-activation-energy", "activation_energy"): (21.9, KCAL, None),
    ("ThermodynamicQuantity:smith-branting-calculated-reaction-gibbs-energy", "gibbs_energy"): (16070, "cal/mol", "printed 'cal.'"),
    ("ThermodynamicQuantity:smith-branting-directly-measured-methanol-equilibrium-constant", "equilibrium_pressure_quotient"): (5.57e-4, "atm-2", "probable error ±5% as printed"),
    ("ThermodynamicQuantity:smith-branting-high-temperature-calculated-methanol-equilibrium-constant", "equilibrium_pressure_quotient"): (2.07e-5, "atm-2", None),
    ("ThermodynamicQuantity:smith-hirst-apparent-methanol-reaction-quotient", "apparent_pressure_quotient"): (3.68e-4, "atm-2", "'~' read as a minus sign"),
    ("ThermodynamicQuantity:thomas-portalski-elevated-temperature-reaction-enthalpy", "enthalpy"): (-23750, "cal/mol", None),
    ("ThermodynamicQuantity:thomas-portalski-standard-gibbs-energy-change", "gibbs_energy"): (-5870, "cal/mol", None),
    ("ThermodynamicQuantity:thomas-portalski-standard-reaction-enthalpy", "enthalpy"): (-21700, "cal/mol", "printed 'cal.'"),
    ("ThermodynamicQuantity:thomas-portalski-standard-reaction-entropy", "entropy"): (-53.12, "cal/(mol K)", "printed 'EU' (entropy units)"),
    ("ThermodynamicQuantity:tomita-computed-methanol-equilibrium-constant", "equilibrium_pressure_quotient"): (3.25e-4, "atm-2", None),
    ("ThermodynamicQuantity:tomita-formaldehyde-water-reaction-free-energy", "free_energy"): (-1908, "cal/mol", None),
    ("PerformanceMetric:corrected-methanol-conversion-for-audibert-raineau-sample-863", "temperature"): (275, "°C", "unit not printed with the value"),
    ("PerformanceMetric:ipatieff-monroe-experiment-22-formaldehyde-to-methanol", "yield"): (0.79, "1", "mol CH3OH per mol HCHO charged"),
    ("PerformanceMetric:kawamura-main-deoxygenation-activation-energy", "activation_energy"): (37.4, KCAL, "printed 'kcal'"),
    ("PerformanceMetric:ogino-single-tube-exchanger-productivity-improvement", "relative_space_time_yield"): (2, "1", "'as much as twice'"),
    ("PerformanceMetric:peet-example-ii-distilled-methanol-production", "volumetric_production"): (2770, "bbl/day", None),
    ("PerformanceMetric:total-bet-surface-area-of-tsuchiya-shiba-catalyst-sample", "surface_area"): (7.0e6, "cm2", "'lo6 cm*' is an OCR reading of 10⁶ cm²"),
    ("PerformanceMetric:uchida-oba-araki-a-3-apparent-activation-energy", "activation_energy"): (21, KCAL, None),
    ("PerformanceMetric:uchida-oba-araki-a-3-synthesis-rate-constant", "rate_constant"): (0.179, "atm-2 L h-1", None),
    ("PerformanceMetric:uchida-oba-araki-b-3-synthesis-rate-constant", "rate_constant"): (0.152, "atm-2 L h-1", None),
    ("PerformanceMetric:uchida-ogino-apparent-synthesis-activation-energy", "activation_energy"): (26.1, KCAL, None),
    ("PerformanceMetric:uchida-reactor-derived-apparent-activation-energy", "activation_energy"): (15, KCAL, None),
}
# Recurring printed units, matched on the as_reported text: pattern -> unit as printed.
PRINTED_UNITS = [
    (re.compile(r"kg\./l\. hr\."), "kg/(L h)"),
    (re.compile(r"(lbs?\.|pounds) (CH3OH|methanol) per cubic foot catalyst per 24 hours"), "lb/(ft3 catalyst 24 h)"),
    (re.compile(r"ml CH3OH/Std; Für 1000 ml Kontaktpastillen"), "mL/h per 1000 mL catalyst pellets"),
    (re.compile(r"cc H2 adsorbed per 100 g catalyst"), "mL H2/(100 g catalyst)"),
]


def reported_quantity(q: dict, prop: str, nid: str = "") -> tuple[dict | None, dict | None]:
    """Return (Quantity in reported units, unmodeled-context note) for a bundle quantity.

    A Quantity is None when the schema cannot express the reported value (a range or bound).
    """
    ar = str(q.get("as_reported", "")).strip()
    gv, gu = q["value"], q["unit"]
    unc = q.get("uncertainty") or {}
    if unc.get("kind") == "range" or re.search(r"(upper|lower)_bound$", prop):
        what = "a range" if unc.get("kind") == "range" else "a bound"
        return None, {"about": f"attributes.{prop}", "gap_kind": "missing_concept",
                      "text": f"{human(prop)} reported as {what}: '{ar}'. A Quantity holds one value; "
                              f"the bundle's value {gv:g} {gu} is not carried over."}
    nums = numbers(ar)
    value = unit = None
    reading = None
    if (nid, prop) in OVERRIDES:
        value, unit, reading = OVERRIDES[(nid, prop)]
        if value is None:
            return None, {"about": f"attributes.{prop}", "gap_kind": "missing_concept",
                          "text": f"{human(prop)} reported as a bound: '{ar}'. A Quantity holds one value; "
                                  f"the bundle's value {gv:g} {gu} is not carried over."}
    elif nums and any(rx.search(ar) for rx, _ in PRINTED_UNITS):
        value, unit = nums[0], next(u for rx, u in PRINTED_UNITS if rx.search(ar))
    elif any(_close(n, gv) for n in nums):
        value, unit = next(n for n in nums if _close(n, gv)), gu
    elif nums:
        n = nums[0]
        table = None
        if gu == "K":
            table = TEMP_UNITS
        elif gu in ("MPa",):
            table = PRESS_UNITS
        elif gu in ("mL", "L/h", "Nm3/h", "m3/day", "mL/h"):
            table = VOL_UNITS
        elif gu in ("mm", "m"):
            table = LEN_UNITS
        elif gu in ("kg/day", "kg/h", "g"):
            table = MASS_UNITS
        u = _unit_from(ar, table) if table else None
        if u is not None:
            value, unit = n, _compound_unit(ar, gu, u)
        elif gu.endswith("h") and re.search(r"分|min", ar):
            value = n
            unit = "mmol/min" if re.search(r"m\.?\s*mol", ar) else re.sub(r"h$", "min", gu)
    if value is None and nums and gu == "1" and reading is None:
        # a ratio printed as two numbers ("Zn:Cr=1:2", "CuZn3") is restated as their quotient
        value, unit = gv, "1"
    if value is None and re.search(r"atmospheric|常圧", ar, re.I):
        value, unit = 1, "atm"
    if value is None and not nums:
        w = _word_number(ar)
        if w is not None:
            if _close(w, gv) or gu == "1":
                value, unit = gv, gu
            else:
                u = _unit_from(ar, VOL_UNITS + MASS_UNITS)
                value, unit = (w, u) if u else (None, None)
    if value is None:
        return None, {"about": f"attributes.{prop}", "gap_kind": "extraction_error",
                      "text": f"{human(prop)} reported as '{ar}'; the reported number and unit could not be "
                              f"restored automatically (bundle value {gv:g} {gu} not carried over)."}
    if unit == "%" and re.search(r"\bparts?\b", ar, re.I):
        unit = "parts by weight" if re.search(r"weight|wt", ar, re.I) else "parts"
    out: dict = {"status": "present", "value": int(value) if float(value).is_integer() and abs(value) < 1e15 else value,
                 "unit": unit}
    if _APPROX.search(ar):
        out["qualifier"] = "approximate"
    notes = []
    if ar and ar != f"{out['value']} {unit}" and ar != str(out["value"]):
        notes.append(f"reported as '{ar}'")
    if unc.get("kind") and unc.get("kind") != "range":
        pm = unc.get("plus_minus")
        notes.append(f"reported uncertainty ±{pm:g} (meaning not stated)" if pm is not None else f"uncertainty as reported: {unc}")
    if unit == gu and gu in {"h-1", "1", "%"} and ar and not re.search(r"[a-zA-Z%]", ar.translate(_SUP)):
        notes.append(f"the reported text is a bare number; unit {gu} is from the source curation (e.g. a table heading)")
    if reading:
        notes.append(reading)
    if notes:
        out["note"] = "; ".join(notes)
    return out, None


def _word_number(text: str) -> float | None:
    """'Two hundred and fifty' -> 250, 'six hours' -> 6, 'a gram' -> 1; None when no number word."""
    total, seen = 0, False
    for tok in re.findall(r"[a-z]+", text.lower()):
        if tok not in _WORDS:
            if seen and tok != "and":
                break
            continue
        if tok == "hundred":
            total = (total or 1) * 100
        else:
            total += _WORDS[tok]
        seen = True
    return float(total) if seen else None


def _compound_unit(ar: str, gu: str, base: str) -> str:
    """For rates, keep the time base the source used (per hour / per day)."""
    if gu in ("L/h", "Nm3/h", "mL/h", "kg/h"):
        per = "day" if re.search(r"per\s*day|/\s*day|daily|24\s*h", ar, re.I) else "h"
        return f"{base}/{per}"
    if gu in ("m3/day", "kg/day"):
        per = "h" if re.search(r"per\s*h|/\s*h", ar, re.I) else "day"
        return f"{base}/{per}"
    return base


# --------------------------------------------------------------------------- vocabulary tables

SPECIES = {  # curated identities for common species (formula from the name, not from the source)
    "hydrogen": ("H2", {"H": 2}), "carbon monoxide": ("CO", {"C": 1, "O": 1}),
    "carbon dioxide": ("CO2", {"C": 1, "O": 2}), "methanol": ("CH3OH", {"C": 1, "H": 4, "O": 1}),
    "water": ("H2O", {"H": 2, "O": 1}), "methane": ("CH4", {"C": 1, "H": 4}),
    "formaldehyde": ("CH2O", {"C": 1, "H": 2, "O": 1}), "nitrogen": ("N2", {"N": 2}),
    "oxygen": ("O2", {"O": 2}), "ethanol": ("C2H5OH", {"C": 2, "H": 6, "O": 1}),
    "dimethyl ether": ("CH3OCH3", {"C": 2, "H": 6, "O": 1}), "methyl formate": ("HCOOCH3", {"C": 2, "H": 4, "O": 2}),
    "formic acid": ("HCOOH", {"C": 1, "H": 2, "O": 2}), "acetaldehyde": ("CH3CHO", {"C": 2, "H": 4, "O": 1}),
}
FEED_COMPONENTS = {"hydrogen_fraction": "hydrogen", "carbon_monoxide_fraction": "carbon monoxide",
                   "carbon_dioxide_fraction": "carbon dioxide", "nitrogen_fraction": "nitrogen",
                   "methane_fraction": "methane", "water_fraction": "water", "oxygen_fraction": "oxygen",
                   "formaldehyde_fraction": "formaldehyde", "inert_fraction": "inert gas",
                   "inert_gas_fraction": "inert gas"}
# catalyst composition fields: property -> (component, fraction basis)
COMPOSITION = {
    "cuo_mass_fraction": ("CuO", "mass"), "copper_oxide_fraction": ("CuO", "mass"),
    "zno_mass_fraction": ("ZnO", "mass"), "zinc_oxide_fraction": ("ZnO", "mass"),
    "al2o3_mass_fraction": ("Al2O3", "mass"), "alumina_mass_fraction": ("Al2O3", "mass"),
    "aluminium_oxide_fraction": ("Al2O3", "mass"), "mno2_mass_fraction": ("MnO2", "mass"),
    "mgo_mass_fraction": ("MgO", "mass"), "magnesia_mass_fraction": ("MgO", "mass"),
    "v2o5_mass_fraction": ("V2O5", "mass"), "cr2o3_mass_fraction": ("Cr2O3", "mass"),
    "chromia_mass_fraction": ("Cr2O3", "mass"), "zro2_mass_fraction": ("ZrO2", "mass"),
    "tio2_mass_fraction": ("TiO2", "mass"), "tho2_mass_fraction": ("ThO2", "mass"),
    "sio2_mass_fraction": ("SiO2", "mass"), "silica_mass_fraction": ("SiO2", "mass"),
    "copper_mass_fraction": ("Cu", "mass"), "chromium_fraction": ("Cr", "mass"),
    "cerium_oxide_mass_fraction": ("cerium oxide", "mass"), "manganese_oxide_mass_fraction": ("manganese oxide", "mass"),
    "vanadium_oxide_mass_fraction": ("vanadium oxide", "mass"), "chromium_oxide_mass_fraction": ("chromium oxide", "mass"),
    "copper_mole_fraction": ("Cu", "mole"), "zinc_mole_fraction": ("Zn", "mole"),
    "chromium_mole_fraction": ("Cr", "mole"), "manganese_mole_fraction": ("Mn", "mole"),
    "barium_carbonate_mole_fraction": ("BaCO3", "mole"), "zinc_oxide_mole_fraction": ("ZnO", "mole"),
    "chromia_mole_fraction": ("Cr2O3", "mole"), "zinc_atomic_fraction": ("Zn", "atom"),
    "chromium_atomic_fraction": ("Cr", "atom"),
}
FORMULA_ELEMENTS = {"CuO": {"Cu": 1, "O": 1}, "ZnO": {"Zn": 1, "O": 1}, "Al2O3": {"Al": 2, "O": 3},
                    "MnO2": {"Mn": 1, "O": 2}, "MgO": {"Mg": 1, "O": 1}, "V2O5": {"V": 2, "O": 5},
                    "Cr2O3": {"Cr": 2, "O": 3}, "ZrO2": {"Zr": 1, "O": 2}, "TiO2": {"Ti": 1, "O": 2},
                    "ThO2": {"Th": 1, "O": 2}, "SiO2": {"Si": 1, "O": 2}, "Cu": {"Cu": 1}, "Cr": {"Cr": 1},
                    "Zn": {"Zn": 1}, "Mn": {"Mn": 1}, "BaCO3": {"Ba": 1, "C": 1, "O": 3}}
# run-level condition fields inside bundle PerformanceMetric nodes
PM_CONDITIONS = {"temperature", "pressure", "duration", "space_velocity", "hydrogen_carbon_monoxide_ratio",
                 "hydrogen_carbon_dioxide_ratio", "additive_mass"}
PM_TEXT = ["run", "run_id", "catalyst_code", "run_direction", "irradiation", "additive", "basis",
           "calculation_basis", "gas_volume_basis", "value_qualifier", "outcome", "result", "trend", "bound"]
# performance figures of a run: property -> (quantity kind, normalization basis, definition)
PM_METRICS = {
    "conversion": ("scale:conversion", "reactant_fed", "Conversion as reported by the source"),
    "initial_conversion": ("scale:conversion", "reactant_fed", "Conversion at the start of the run, as reported"),
    "final_conversion": ("scale:conversion", "reactant_fed", "Conversion at the end of the run, as reported"),
    "methanol_conversion": ("scale:conversion", "reactant_fed", "Methanol conversion (decomposition direction), as reported"),
    "yield": ("scale:yield", "not_reported", "Yield as reported by the source"),
    "space_time_yield": ("msyn:space_time_yield", "custom", "Methanol produced per unit volume and time, as reported"),
    "volumetric_productivity": ("msyn:space_time_yield", "custom", "Product volume per catalyst volume and time, as reported"),
    "mass_productivity": ("msyn:space_time_yield", "custom", "Product mass per catalyst volume and time, as reported"),
    "methanol_mass_flow": ("msyn:production_rate", "none", "Methanol produced per unit time, as reported"),
    "methanol_mass_rate": ("msyn:production_rate", "none", "Methanol produced per unit time, as reported"),
    "methanol_volume_rate": ("msyn:production_rate", "none", "Methanol produced per unit time, as reported"),
    "production_rate": ("msyn:production_rate", "none", "Product formed per unit time, as reported"),
    "volumetric_production": ("msyn:production_rate", "none", "Product formed per unit time, as reported"),
    "rate": ("msyn:specific_rate", "catalyst_mass", "Rate per catalyst mass, as reported"),
}
PM_TARGET = {"methanol_conversion": "methanol", "space_time_yield": "methanol", "methanol_mass_flow": "methanol",
             "methanol_mass_rate": "methanol", "methanol_volume_rate": "methanol"}
CONDITION_FIELDS = {"temperature": "temperature", "pressure": "pressure", "duration": "duration"}
FLOW_FIELDS = ("gas_flow_rate", "gas_flow", "feed_rate")
STATEMENT_TO_RELATION = {"observation": "asserted", "conclusion": "asserted", "hypothesis": "hypothesized",
                         "assumption": "hypothesized"}
STATEMENT_TO_CLAIM = {"observation": "supported", "conclusion": "proposed", "hypothesis": "proposed",
                      "assumption": "proposed"}
STATEMENT_LIMITS = {"conclusion": "The authors' conclusion, not a direct measurement.",
                    "hypothesis": "A hypothesis stated by the authors.",
                    "assumption": "An assumption stated by the authors."}


# --------------------------------------------------------------------------- converter


class Converter:
    def __init__(self, bundle: Path):
        self.bundle_dir = bundle
        g = json.loads((bundle / "kg/graph.json").read_text(encoding="utf-8"))
        self.manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
        self.nodes = {n["id"]: n for n in g["nodes"]}
        missing = sorted(k for k in OVERRIDES if k[0] not in self.nodes or k[1] not in self.nodes[k[0]]["props"])
        if missing:
            raise SystemExit(f"override keys not in the bundle: {missing}")
        self.links = g["links"]
        self.entities: dict[str, dict] = {}
        self.relations: dict[str, dict] = {}
        self.report: dict = defaultdict(int)
        self.unrestored: list[dict] = []
        self.out = defaultdict(list)
        self.inc = defaultdict(list)
        for e in self.links:
            if e["type"] != "REPORTED_IN":
                self.out[e["source"]].append(e)
                self.inc[e["target"]].append(e)
        self.papers_of = defaultdict(set)
        for e in self.links:
            if e["type"] == "REPORTED_IN":
                self.papers_of[e["source"]].add(e["target"])
        self.pub_by_key = {}
        for n in self.nodes.values():
            if n["label"] == "Publication":
                pr = n["props"]
                self.pub_by_key[pr.get("doi") or pr.get("source_id")] = n["id"]
        self.handled: set[str] = set()

    # ---------------------------------------------------------------- records
    def ent(self, eid: str, etype: str, label: str, attrs: dict, origin: str = "reported",
            evidence: set | list | None = None, note: str | None = None, unmodeled: list | None = None,
            external: list | None = None) -> dict:
        if eid in self.entities:
            e = self.entities[eid]
            if evidence:
                e["provenance"].setdefault("evidence_refs", [])
                e["provenance"]["evidence_refs"] = sorted(set(e["provenance"]["evidence_refs"]) | set(evidence))
            return e
        prov = {"origin": origin, "extraction_method": "agent"}
        if evidence:
            prov["evidence_refs"] = sorted(set(evidence))
        if note:
            prov["note"] = note
        e = {"id": eid, "type": etype, "label": label, "record_version": 1, "provenance": prov,
             "attributes": {k: v for k, v in attrs.items() if v not in (None, "", [], {})}}
        if unmodeled:
            e["extensions"] = {"scale:unmodeled_context": unmodeled}
        if external:
            e["external_identifiers"] = external
        self.entities[eid] = e
        self.report[f"entities.{etype}"] += 1
        return e

    def rel(self, rtype: str, source: str, target: str, origin: str = "reported", evidence=None,
            epistemic: str | None = None, qualifiers: dict | None = None, context: list | None = None,
            note: str | None = None) -> dict:
        key = (rtype, source, target, json.dumps(qualifiers or {}, sort_keys=True))
        rid = f"{P}/rel/{rtype.replace('_', '-')}-{short_hash(*map(str, key))}"
        if rid in self.relations:
            r = self.relations[rid]
            if evidence:
                r["provenance"]["evidence_refs"] = sorted(set(r["provenance"].get("evidence_refs", [])) | set(evidence))
            return r
        prov = {"origin": origin}
        if evidence:
            prov["evidence_refs"] = sorted(set(evidence))
        if note:
            prov["note"] = note
        r = {"id": rid, "type": rtype, "source": source, "target": target, "record_version": 1, "provenance": prov}
        if epistemic:
            r["epistemic_status"] = epistemic
        if qualifiers:
            r["qualifiers"] = qualifiers
        if context:
            r["context_refs"] = sorted(set(context))
        self.relations[rid] = r
        self.report[f"relations.{rtype}"] += 1
        return r

    # ---------------------------------------------------------------- sources and evidence
    def source_id(self, pub_node: str) -> str:
        return f"{P}/source/{node_slug(pub_node)}"

    def sources(self) -> None:
        for n in sorted((n for n in self.nodes.values() if n["label"] == "Publication"), key=lambda n: n["id"]):
            pr = n["props"]
            kind = pr["record_kind"]
            ext, desc = [], []
            if pr.get("journal"):
                desc.append(f"{pr['journal']}, {pr['year']}.")
            else:
                desc.append({"patent": "United States patent", "thesis": "Thesis"}.get(kind, kind) + f", {pr['year']}.")
            lic = pr.get("license")
            if lic == "Fair Use":
                desc.append("Licence: no verified publisher licence; short verbatim excerpts are quoted as evidence "
                            "under fair use. The text is not redistributed.")
            else:
                desc.append(f"Licence: {lic} ({pr.get('license_source', 'source notice')}). The text is not redistributed.")
            desc.append(f"Metadata: {pr['metadata_status']}.")
            url = None
            if pr.get("doi"):
                ext.append({"scheme": "doi", "value": pr["doi"], "uri": f"https://doi.org/{pr['doi']}"})
            if pr.get("source_id", "").startswith("patent:"):
                num = pr["source_id"].split(":", 1)[1].upper()
                url = f"https://patents.google.com/patent/{num}"
                ext.append({"scheme": "patent", "value": num, "uri": url})
            attrs = {"source_kind": "article" if kind == "article" else "other", "title": pr["title"],
                     "doi": pr.get("doi"), "url": url, "description": " ".join(desc)}
            label = f"{pr['title']} ({pr.get('journal') or kind}, {pr['year']})"
            self.ent(self.source_id(n["id"]), "Source", label, attrs, origin="curated", external=ext)

    def evidence(self, edge: dict) -> list[str]:
        ids = []
        for ev in edge["props"].get("_evidence", []):
            pub = self.pub_by_key[ev["source_id"]]
            page = ev["locator"]["page"]
            eid = f"{P}/ev/{short_hash(ev['source_id'], str(page), ev['quote'])}"
            if eid not in self.entities:
                self.ent(eid, "Evidence", f"{self.nodes[pub]['props']['title'][:60]}, PDF p. {page}",
                         {"source_ref": self.source_id(pub), "evidence_kind": "reported_text",
                          "locator": f"PDF page {page} (one-based; printed pagination may differ)",
                          "excerpt": ev["quote"]}, origin="curated")
            ids.append(eid)
        return ids

    def edge_prov(self, edge: dict) -> tuple[list[str], str, str]:
        self.handled.add(edge["id"])
        ev = self.evidence(edge)
        st = edge["props"].get("_statement", "observation")
        conf = edge["props"].get("_confidence")
        note = f"Bundle statement kind: {st}" + (f"; curator confidence {conf:g}" if conf is not None else "")
        return ev, st, note

    def paper_of_edge(self, edge: dict) -> str:
        return self.pub_by_key[edge["props"]["source_paper_ids"][0]]

    def cite(self, pub: str) -> str:
        pr = self.nodes[pub]["props"]
        return f"{pr.get('journal') or pr['record_kind']} {pr['year']} ({pr.get('doi') or pr.get('source_id')})"

    # ---------------------------------------------------------------- nodes
    def primary_id(self, nid: str) -> str:
        kind = self.nodes[nid]["label"]
        folder = {"Catalyst": "material", "Component": "material", "Support": "material",
                  "ChemicalSpecies": "species", "Reaction": "reaction", "ReactionCondition": "conditions",
                  "ReactantFeed": "feed", "Reactor": "reactor", "SynthesisMethod": "protocol",
                  "KineticModel": "model", "Organization": "agent", "Person": "agent",
                  "DeactivationPhenomenon": "claim", "ThermodynamicQuantity": "analysis",
                  "PerformanceMetric": "metric", "Publication": "source"}[kind]
        prefix = {"Component": "component-", "Support": "support-"}.get(kind, "")
        return f"{P}/{folder}/{prefix}{node_slug(nid)}"

    def quantities(self, nid: str, props: dict, skip=(), origins: dict | None = None) -> tuple[dict, list]:
        """Reported quantities of a node: {prop: Quantity} plus unmodeled-context notes.

        ``origins`` names the bundle node a property came from when props of several nodes are merged.
        """
        qs, um = {}, []
        for k, v in sorted(props.items()):
            if k in skip or not (isinstance(v, dict) and "unit" in v):
                continue
            src = (origins or {}).get(k, nid)
            q, note = reported_quantity(v, k, src)
            if note:
                um.append(note)
                self.report["unmodeled." + note["gap_kind"]] += 1
                if note["gap_kind"] == "extraction_error":
                    self.unrestored.append({"node": src, "property": k, "bundle_value": v})
            if q:
                qs[k] = q
        return qs, um

    def text_props(self, props: dict, keys) -> str:
        return "; ".join(f"{human(k)}: {props[k]}" for k in keys if isinstance(props.get(k), str) and props.get(k))

    def species_by_name(self) -> dict:
        m = {}
        for n in self.nodes.values():
            if n["label"] == "ChemicalSpecies":
                m.setdefault(n["props"]["name"].strip().lower(), n["id"])
        return m

    def species_ref(self, name: str, ev=None) -> str:
        """Entity id for a species or pseudo-component named in a feed or composition."""
        eid = self._species_ref(name)
        if ev:
            self.ent(eid, self.entities[eid]["type"], "", {}, evidence=ev)
        return eid

    def _species_ref(self, name: str) -> str:
        nid = self._species_names.get(name.lower())
        if nid:
            return self.primary_id(nid)
        if name in FORMULA_ELEMENTS:
            eid = f"{P}/species/{slug(name)}"
            self.ent(eid, "ChemicalSpecies", name, {"formula": name, "elemental_composition": FORMULA_ELEMENTS[name]},
                     origin="curated", note="Composition component named by a catalyst composition field of the bundle.")
            return eid
        if name in SPECIES:
            f, el = SPECIES[name]
            eid = f"{P}/species/{slug(name)}"
            self.ent(eid, "ChemicalSpecies", name, {"formula": f, "elemental_composition": el, "charge": 0,
                                                    "species_kind": "molecule"},
                     origin="curated", note="Feed component named by a feed composition field of the bundle.")
            return eid
        eid = f"{P}/material/{slug(name)}"
        self.ent(eid, "Material", name, {"material_family": "not_reported"}, origin="curated",
                 note="Composition or feed component named by a bundle field; identity not further specified by the source.")
        return eid

    def convert_nodes(self) -> None:
        self._species_names = self.species_by_name()
        for nid in sorted(self.nodes):
            n = self.nodes[nid]
            kind, pr = n["label"], n["props"]
            fn = getattr(self, f"node_{kind}", None)
            if fn:
                fn(nid, pr)

    def ev_of(self, nid: str) -> list[str]:
        out = set()
        for e in self.out[nid] + self.inc[nid]:
            out |= set(self.evidence(e))
        return sorted(out)

    def node_ChemicalSpecies(self, nid, pr):
        name = pr["name"]
        attrs = {}
        known = SPECIES.get(name.lower())
        if pr.get("formula"):
            attrs["formula"] = pr["formula"]
        elif known:
            attrs["formula"] = known[0]
        if known:
            attrs.update({"elemental_composition": known[1], "charge": 0, "species_kind": "molecule"})
        note = self.text_props(pr, ["description", "identification", "electronic_state"]) or None
        if known and not pr.get("formula"):
            note = "; ".join(filter(None, [note, "formula and composition added in conversion from the species name"]))
        self.ent(self.primary_id(nid), "ChemicalSpecies", name, attrs, evidence=self.ev_of(nid), note=note)

    def node_Catalyst(self, nid, pr):
        qs, um = self.quantities(nid, pr)
        comp, other = [], {}
        basis_note = self.text_props(pr, ["composition_basis", "support_loading_basis", "basis", "composition_status"])
        for k, q in qs.items():
            if k in COMPOSITION:
                name, fb = COMPOSITION[k]
                if basis_note:
                    q = dict(q, note="; ".join(filter(None, [q.get("note"), basis_note])))
                comp.append({"component_ref": self.species_ref(name, self.ev_of(nid)), "role": "other", "fraction": q, "fraction_basis": fb})
            else:
                other[k] = q
        desc = self.text_props(pr, ["description", "phase_assignment"]) or None
        mid = self.primary_id(nid)
        ev = self.ev_of(nid)
        if basis_note and not comp:
            um.append({"about": "attributes", "gap_kind": "missing_concept",
                       "text": f"Context of the reported composition: {basis_note}"})
        self.ent(mid, "Material", pr["name"], {"composition": comp, "structure_description": desc}, evidence=ev,
                 unmodeled=um or None)
        for k, q in sorted(other.items()):
            self.observation(f"{mid}/obs/{slug(k)}", mid, k, q, ev, label=f"{pr['name']}: {human(k)}")

    def observation(self, oid, subject, prop, q, ev, label, generated_by=None, description=None):
        kind = "scale:activation_energy" if prop == "activation_energy" else f"msyn:{prop}"
        self.ent(oid, "Observation", label, {"quantity_kind": kind, "quantity": q, "description": description},
                 evidence=ev)
        self.rel("observation_of", oid, subject, origin="reported", evidence=ev)
        if generated_by:
            self.rel("generated_by", oid, generated_by, origin="reported", evidence=ev)

    def node_Component(self, nid, pr):
        self.ent(self.primary_id(nid), "Material", pr["name"],
                 {"structure_description": pr.get("description")}, evidence=self.ev_of(nid))

    def node_Support(self, nid, pr):
        self.ent(self.primary_id(nid), "Material", pr["name"], {}, evidence=self.ev_of(nid))

    def node_Reaction(self, nid, pr):
        # Reactions are shared across sources, and the sources name reactants and products without
        # stoichiometry; each source's CONSUMES/PRODUCES statement is kept as its own Claim instead of
        # participants with invented coefficients.
        self.ent(self.primary_id(nid), "Reaction", pr["name"], {"balance_status": "not_checked"},
                 evidence=self.ev_of(nid))

    def node_ReactionCondition(self, nid, pr):
        self.condition_set(self.primary_id(nid), pr["name"], nid, pr,
                           ["run_id", "operation", "operation_scope", "pressure_basis", "space_velocity_basis",
                            "gas_protocol", "basis", "source_inconsistency"], self.ev_of(nid))

    def condition_set(self, cid, label, nid, pr, text_keys, ev, extra_desc=None, origins=None):
        qs, um = self.quantities(nid, pr, origins=origins)
        attrs: dict = {"role": "not_reported"}
        other = {}
        for k, q in qs.items():
            if k in CONDITION_FIELDS and CONDITION_FIELDS[k] not in attrs:
                attrs[CONDITION_FIELDS[k]] = q
            elif k in FLOW_FIELDS and "flow_rate" not in attrs:
                attrs["flow_rate"] = q
                other_note = f"flow_rate is the source's {human(k)}"
                attrs["flow_rate"] = dict(q, note="; ".join(filter(None, [q.get("note"), other_note])))
            else:
                other[k] = q
        if other:
            attrs["other_conditions"] = other
        desc = "; ".join(filter(None, [extra_desc, self.text_props(pr, text_keys)]))
        if not qs and not desc:
            desc = "No operating values recorded for these conditions in the source curation."
        attrs["description"] = desc or None
        return self.ent(cid, "ConditionSet", label, attrs, evidence=ev, unmodeled=um or None)

    def node_ReactantFeed(self, nid, pr):
        qs, um = self.quantities(nid, pr)
        fid = self.primary_id(nid)
        ev = self.ev_of(nid)
        comps = []
        for k, q in sorted(qs.items()):
            if k in FEED_COMPONENTS:
                ar = (pr[k].get("as_reported") or "").lower()
                fb = "mole" if re.search(r"mol|m%", ar) else "volume" if re.search(r"vol|v%", ar) else "not_reported"
                comps.append({"component_ref": self.species_ref(FEED_COMPONENTS[k], ev), "role": "other",
                              "fraction": q, "fraction_basis": fb})
        self.ent(fid, "Environment", pr["name"], {"environment_kind": "gas_feed", "components": comps,
                                                  "description": pr.get("description")},
                 evidence=ev, unmodeled=um or None)
        for k, q in sorted(qs.items()):
            if k not in FEED_COMPONENTS:
                self.observation(f"{fid}/obs/{slug(k)}", fid, k, q, ev, label=f"{pr['name']}: {human(k)}")

    def node_Reactor(self, nid, pr):
        qs, um = self.quantities(nid, pr)
        rid = self.primary_id(nid)
        ev = self.ev_of(nid)
        name = pr["name"]
        low = name.lower() + " " + str(pr.get("description", "")).lower()
        kind = ("batch" if re.search(r"autoclave|bomb|batch|static", low) else
                "fixed_bed" if re.search(r"fixed.bed|catalyst bed|packed", low) else
                "flow" if re.search(r"flow|converter|tube|tubular|continuous", low) else "other")
        attrs = {"reactor_kind": kind, "volume": qs.pop("volume", None),
                 "description": self.text_props(pr, ["description", "material", "heat_exchange", "basis"]) or None}
        note = ("reactor_kind not classified: the name does not state the reactor type" if kind == "other" else
                f"reactor_kind {kind} assigned in conversion from the reactor's name or description")
        self.ent(rid, "Reactor", name, attrs, evidence=ev, note=note, unmodeled=um or None)
        for k, q in sorted(qs.items()):
            self.observation(f"{rid}/obs/{slug(k)}", rid, k, q, ev, label=f"{name}: {human(k)}")

    def node_SynthesisMethod(self, nid, pr):
        pid = self.primary_id(nid)
        ev = self.ev_of(nid)
        steps = [pr["procedure"]] if pr.get("procedure") else None
        desc = self.text_props(pr, ["description", "gas", "reducing_gas"]) or None
        self.ent(pid, "Protocol", pr["name"], {"protocol_kind": "synthesis", "availability": "documented",
                                               "steps": steps, "description": desc}, evidence=ev)
        qs = [k for k, v in pr.items() if isinstance(v, dict) and "unit" in v]
        if qs:
            self.condition_set(f"{pid}/conditions", f"Conditions of {pr['name']}", nid, pr, [], ev)

    def node_KineticModel(self, nid, pr):
        qs, um = self.quantities(nid, pr)
        self.ent(self.primary_id(nid), "Model", pr["name"],
                 {"model_kind": "kinetic", "version": "as published",
                  "equations": [pr["equation"]] if pr.get("equation") else None,
                  "parameters": qs or None,
                  "description": self.text_props(pr, ["model_type", "rate_determining_step"]) or None},
                 evidence=self.ev_of(nid), unmodeled=um or None)

    def node_Organization(self, nid, pr):
        self.ent(self.primary_id(nid), "Agent", pr["name"], {"agent_kind": "organization", "name": pr["name"]},
                 evidence=self.ev_of(nid))

    def node_Person(self, nid, pr):
        self.ent(self.primary_id(nid), "Agent", pr["name"],
                 {"agent_kind": "person", "name": pr["name"], "role": pr.get("role")}, evidence=self.ev_of(nid))

    def node_ThermodynamicQuantity(self, nid, pr):
        aid = self.primary_id(nid)
        ev = self.ev_of(nid)
        method = self.text_props(pr, ["basis", "equation", "model", "relation", "extraction_note"]) or \
            "Thermodynamic quantity reported by the source; method not recorded in the source curation."
        self.ent(aid, "Analysis", pr["name"], {"method": method, "status": "completed"}, evidence=ev)
        cond_keys = {k: v for k, v in pr.items() if k in ("temperature", "pressure")}
        if cond_keys:
            cs = self.condition_set(f"{aid}/conditions", f"Conditions of {pr['name']}", nid, cond_keys, [], ev)
            self.rel("operated_under", aid, cs["id"], evidence=ev)
        qs, um = self.quantities(nid, {k: v for k, v in pr.items() if k not in ("temperature", "pressure")})
        if um:
            self.entities[aid]["extensions"] = {"scale:unmodeled_context": um}
        subjects = [self.primary_id(e["source"]) for e in self.inc[nid] if e["type"] == "GOVERNED_BY"]
        for k, q in sorted(qs.items()):
            oid = f"{aid}/obs/{slug(k)}"
            self.ent(oid, "Observation", f"{pr['name']}: {human(k)}",
                     {"quantity_kind": "scale:activation_energy" if k == "activation_energy" else f"msyn:{k}",
                      "quantity": q}, evidence=ev)
            self.rel("generated_by", oid, aid, evidence=ev)
            for s in subjects:
                gov = [e for e in self.inc[nid] if e["type"] == "GOVERNED_BY" and self.primary_id(e["source"]) == s]
                gev, st, note = self.edge_prov(gov[0])
                self.rel("observation_of", oid, s, evidence=gev, epistemic=STATEMENT_TO_RELATION[st], note=note)

    def node_DeactivationPhenomenon(self, nid, pr):
        edges = [e for e in self.inc[nid] if e["type"] == "EXHIBITS"]
        qtext = "; ".join(f"{human(k)} {v['as_reported']}" for k, v in sorted(pr.items())
                          if isinstance(v, dict) and "as_reported" in v)
        statement = pr["name"] + (f". {pr['description']}" if pr.get("description") else "") + \
            (f" ({qtext})" if qtext else "")
        sts = [e["props"].get("_statement", "observation") for e in edges]
        status = "supported" if "observation" in sts else "proposed"
        cid = self.primary_id(nid)
        pubs = sorted({self.paper_of_edge(e) for e in edges}) or sorted(self.papers_of[nid])
        limits = "; ".join(sorted({STATEMENT_LIMITS[s] for s in sts if s in STATEMENT_LIMITS})) or None
        if pr.get("interpretation"):
            limits = "; ".join(filter(None, [limits, f"interpretation: {pr['interpretation']}"]))
        self.ent(cid, "Claim", pr["name"],
                 {"statement": statement, "claim_kind": "performance", "epistemic_status": status,
                  "scope": "Deactivation behaviour as reported in " + ", ".join(self.cite(p) for p in pubs),
                  "limitations": limits}, evidence=self.ev_of(nid))
        for e in edges:
            ev, st, note = self.edge_prov(e)
            self.rel("about", cid, self.primary_id(e["source"]), evidence=ev, epistemic=STATEMENT_TO_RELATION[st], note=note)
            for x in ev:
                self.rel("supports", x, cid, origin="curated", note=note)

    # ---------------------------------------------------------------- runs
    def sample_for(self, cat: str, pub: str, ev) -> str:
        """One specimen record per catalyst and source; identity beyond that is not asserted."""
        sid = f"{P}/sample/{node_slug(cat)}/{node_slug(pub)}"
        pr = self.nodes[cat]["props"]
        code = pr.get("catalyst_code") or pr.get("run_id")
        if sid not in self.entities:
            self.ent(sid, "Sample", f"{pr['name']} — specimen in {self.cite(pub)}",
                     {"sample_kind": "other", "preparation_status": "not_reported",
                      "batch_identifier": f"catalyst {code} (as labelled in the source)" if code else None},
                     evidence=ev,
                     note="Specimen record created so that runs can reference the catalyst. The source does not "
                          "establish whether different runs used one batch.")
            self.rel("has_formulation", sid, self.primary_id(cat), origin="curated", evidence=ev)
            self.rel("reported_in", sid, self.source_id(pub), origin="curated")
        else:
            self.ent(sid, "Sample", "", {}, evidence=ev)
        return sid

    def run_for(self, key: tuple, label: str, pub: str, cat: str | None, ev, description=None) -> str:
        xid = f"{P}/run/{short_hash(*map(str, key))}"
        if xid not in self.entities:
            self.ent(xid, "Experiment", label,
                     {"run_kind": "catalytic_test" if cat else "other", "status": "completed",
                      "description": description}, evidence=ev)
            sys_id = f"{xid}/system"
            regime = "not_determined" if cat and re.search(r"carbonyl|soluble|homogeneous", self.nodes[cat]["props"]["name"], re.I) \
                else "heterogeneous"
            self.ent(sys_id, "CatalyticSystem", f"System of {label}",
                     {"phase_regime": regime, "catalyst_forms": ["extended_solid" if regime == "heterogeneous" else "not_reported"],
                      "activation_modes": ["thermal"]}, origin="curated", evidence=ev,
                     note="Assembled from the bundle's explicit links for this run; phase regime from the catalyst description.")
            self.rel("has_system", xid, sys_id, origin="curated", evidence=ev)
            self.rel("reported_in", xid, self.source_id(pub), origin="curated")
            if cat:
                self.rel("has_catalyst", sys_id, self.sample_for(cat, pub, ev), origin="reported", evidence=ev)
            self.runs_by_paper[pub].append(xid)
            if cat:
                self.runs_by_cat[(cat, pub)].append(xid)
        else:
            self.ent(xid, "Experiment", "", {}, evidence=ev)
        return xid

    def operate(self, xid: str, cs: str, ev, st="observation", note=None) -> None:
        self.rel("operated_under", xid, cs, evidence=ev, epistemic=STATEMENT_TO_RELATION[st], note=note)
        self.runs_by_cond[cs].add(xid)

    def placeholder_conditions(self, xid: str, ev) -> str:
        cid = f"{xid}/conditions"
        self.ent(cid, "ConditionSet", "Conditions not linked",
                 {"role": "not_reported",
                  "description": "not curated: the source curation links no operating conditions to this result"},
                 origin="curated", evidence=ev)
        return cid

    def build_runs(self) -> None:
        self.runs_by_paper = defaultdict(list)
        self.runs_by_cat = defaultdict(list)
        self.runs_by_cond = defaultdict(set)
        pms = sorted(n for n in self.nodes if self.nodes[n]["label"] == "PerformanceMetric")
        for pm in pms:
            pr = self.nodes[pm]["props"]
            ach = [e for e in self.inc[pm] if e["type"] == "ACHIEVES"][0]
            cat = ach["source"]
            pub = self.paper_of_edge(ach)
            aev, ast, anote = self.edge_prov(ach)
            meas = [e for e in self.out[pm] if e["type"] == "MEASURED_UNDER"]
            local = {k: v for k, v in pr.items() if k in PM_CONDITIONS and isinstance(v, dict)}
            fp = json.dumps(local, sort_keys=True)
            cond = meas[0]["target"] if meas else None
            key = (cat, cond, fp, pub) if (cond or local) else ("pm", pm)
            label = pr["name"] if key[0] == "pm" or not cond else \
                f"{self.nodes[cat]['props']['name']} under {self.nodes[cond]['props']['name']}"
            desc = self.text_props(pr, ["run", "run_id", "catalyst_code", "run_direction", "irradiation", "additive"])
            ev = sorted(set(aev) | {x for e in meas for x in self.evidence(e)})
            xid = self.run_for(key, label, pub, cat, ev, description=desc or None)
            if cond and local:
                # one complete condition set per run: the shared conditions with this run's own values
                mev, mst, mnote = self.edge_prov(meas[0])
                merged = dict(self.nodes[cond]["props"], **local)
                cs = self.condition_set(f"{xid}/conditions", f"Run conditions: {pr['name']}", pm, merged,
                                        ["run_id", "operation", "operation_scope", "pressure_basis",
                                         "space_velocity_basis", "gas_protocol", "basis", "source_inconsistency"],
                                        sorted(set(mev) | set(aev)),
                                        extra_desc=f"{self.nodes[cond]['props']['name']}, with the values this run reports",
                                        origins={k: (pm if k in local else cond) for k in merged})
                self.operate(xid, cs["id"], sorted(set(mev) | set(aev)), mst, mnote)
                self.runs_by_cond[self.primary_id(cond)].add(xid)
            elif cond:
                mev, mst, mnote = self.edge_prov(meas[0])
                self.operate(xid, self.primary_id(cond), mev, mst, mnote)
            elif local:
                cs = self.condition_set(f"{xid}/conditions", f"Run conditions: {pr['name']}", pm, local, [], aev)
                self.operate(xid, cs["id"], aev, ast, anote)
            else:
                self.operate(xid, self.placeholder_conditions(xid, aev), aev, ast, anote)
            self.metrics(pm, pr, xid, aev, ast, anote)

        for e in sorted(self.links, key=lambda e: e["id"]):
            t = e["type"]
            if t == "TESTED_UNDER" and self.nodes[e["source"]]["label"] == "Catalyst":
                cat, cond, pub = e["source"], e["target"], self.paper_of_edge(e)
                ev, st, note = self.edge_prov(e)
                existing = [x for x in self.runs_by_cat[(cat, pub)] if x in self.runs_by_cond[self.primary_id(cond)]]
                if not existing:
                    xid = self.run_for((cat, cond, "{}", pub), f"{self.nodes[cat]['props']['name']} under "
                                       f"{self.nodes[cond]['props']['name']}", pub, cat, ev,
                                       description="Test reported without a result linked in the source curation")
                    self.operate(xid, self.primary_id(cond), ev, st, note)
                else:
                    for x in existing:
                        linked = [r for r in self.relations.values() if r["type"] == "operated_under" and r["source"] == x]
                        for r in linked:
                            r["provenance"]["evidence_refs"] = sorted(set(r["provenance"].get("evidence_refs", [])) | set(ev))

        for e in sorted(self.links, key=lambda e: e["id"]):
            t, s, tg = e["type"], e["source"], e["target"]
            if t == "TESTED_UNDER" and self.nodes[s]["label"] == "Reactor":
                self.attach(e, "has_reactor", self.runs_by_cond[self.primary_id(tg)] & set(self.runs_by_paper[self.paper_of_edge(e)]),
                            f"{self.nodes[s]['props']['name']} was operated under {self.nodes[tg]['props']['name']}", "Reactor")
            elif t == "TESTED_IN":
                pub = self.paper_of_edge(e)
                sibling = [x for x in self.out[s] if x["type"] == "TESTED_IN" and self.paper_of_edge(x) == pub]
                runs = set(self.runs_by_cat[(s, pub)]) if len(sibling) == 1 else set()
                if not runs and not self.runs_by_cat[(s, pub)]:
                    ev, st, note = self.edge_prov(e)
                    xid = self.run_for((s, None, "{}", pub), f"{self.nodes[s]['props']['name']} in "
                                       f"{self.nodes[tg]['props']['name']}", pub, s, ev,
                                       description="Test reported without conditions or a result linked in the source curation")
                    self.operate(xid, self.placeholder_conditions(xid, ev), ev, st, note)
                    runs = {xid}
                self.attach(e, "has_reactor", runs,
                            f"{self.nodes[s]['props']['name']} was tested in {self.nodes[tg]['props']['name']}", "Reactor")
            elif t == "FED_WITH":
                pub = self.paper_of_edge(e)
                if self.nodes[s]["label"] == "ReactionCondition":
                    runs = self.runs_by_cond[self.primary_id(s)] & set(self.runs_by_paper[pub])
                else:
                    sibling = [x for x in self.out[s] if x["type"] == "FED_WITH" and self.paper_of_edge(x) == pub]
                    runs = set(self.runs_by_cat[(s, pub)]) if len(sibling) == 1 else set()
                self.attach(e, "has_environment", runs,
                            f"{self.nodes[s]['props']['name']} used the feed {self.nodes[tg]['props']['name']}", "Environment")

    def attach(self, e: dict, rtype: str, runs: set, statement: str, what: str) -> None:
        ev, st, note = self.edge_prov(e)
        if runs:
            for x in sorted(runs):
                self.rel(rtype, f"{x}/system", self.primary_id(e["target"]), evidence=ev,
                         epistemic=STATEMENT_TO_RELATION[st], note=note)
            self.report[f"attached.{e['type']}"] += 1
        else:
            self.claim(e, statement, "other", [e["source"], e["target"]],
                       limitation=f"The source curation does not identify which run used this {what.lower()}.")

    def metrics(self, pm: str, pr: dict, xid: str, ev, st, note) -> None:
        mid = self.primary_id(pm)
        qs, um = self.quantities(pm, {k: v for k, v in pr.items() if k not in PM_CONDITIONS})
        text = self.text_props(pr, PM_TEXT)
        basis = self.text_props(pr, ["basis", "calculation_basis", "gas_volume_basis"])
        if um and len(qs) > 1:
            # several figures from one bundle node: the unexpressible ones are kept on the run
            run = self.entities[xid]
            run.setdefault("extensions", {}).setdefault("scale:unmodeled_context", []).extend(
                dict(u, about=f"{mid}: {u['about']}") for u in um)
        if not qs:
            # A result stated only in words (e.g. "entirely inactive") stays a Claim about the run.
            statement = f"{pr['name']}" + (f": {text}" if text else "")
            cid = f"{mid}"
            self.ent(cid, "Claim", pr["name"], {"statement": statement, "claim_kind": "performance",
                                                 "epistemic_status": STATEMENT_TO_CLAIM[st],
                                                 "scope": "Run reported in " + self.cite(self.paper_of_run(xid)),
                                                 "limitations": STATEMENT_LIMITS.get(st)},
                     evidence=ev, note=note, unmodeled=um or None)
            self.rel("about", cid, xid, evidence=ev, epistemic=STATEMENT_TO_RELATION[st], note=note)
            for x in ev:
                self.rel("supports", x, cid, origin="curated", note=note)
            return
        many = len(qs) > 1
        for k, q in sorted(qs.items()):
            rid = f"{mid}/{slug(k)}" if many else mid
            label = f"{pr['name']}: {human(k)}" if many else pr["name"]
            if k in PM_METRICS:
                kind, nb, definition = PM_METRICS[k]
                norm = {"basis": nb}
                if nb == "custom":
                    norm["description"] = f"Normalized as the reported unit states ({q['unit']})"
                if basis and nb in ("not_reported", "custom", "reactant_fed"):
                    norm["description"] = "; ".join(filter(None, [norm.get("description"), basis]))
                attrs = {"quantity_kind": kind, "quantity": q, "definition": definition, "normalization": norm,
                         "description": text or None}
                tgt = PM_TARGET.get(k)
                if tgt:
                    attrs["target_species_ref"] = self.species_ref(tgt, ev)
                self.ent(rid, "PerformanceMetric", label, attrs, evidence=ev, note=note,
                         unmodeled=um if (um and not many) else None)
                self.rel("metric_of", rid, xid, evidence=ev, epistemic=STATEMENT_TO_RELATION[st], note=note)
            else:
                self.ent(rid, "Observation", label,
                         {"quantity_kind": "scale:activation_energy" if k == "activation_energy" else f"msyn:{k}",
                          "quantity": q, "description": text or None}, evidence=ev, note=note,
                         unmodeled=um if (um and not many) else None)
                self.rel("observation_of", rid, xid, evidence=ev, epistemic=STATEMENT_TO_RELATION[st], note=note)
            self.rel("generated_by", rid, xid, origin="curated")

    def paper_of_run(self, xid: str) -> str:
        for pub, xs in self.runs_by_paper.items():
            if xid in xs:
                return pub
        raise KeyError(xid)

    # ---------------------------------------------------------------- claims from edges
    CLAIM_EDGES = {
        "CATALYZES": ("performance", "{s} catalyzes {t}"),
        "COMPARED_WITH": ("comparative", "{s} is compared with {t}"),
        "CONSUMES": ("other", "{s} consumes {t}"),
        "PRODUCES": ("other", "{s} produces {t}"),
        "INHIBITED_BY": ("causal", "{s} is inhibited by {t}"),
        "DEVELOPED_BY": ("other", "{s} was developed by {t}"),
        "PROCEEDS_VIA": ("mechanistic", "{s} proceeds via {t}"),
        "MODELED_BY": ("other", "The rate of {s} is described by {t}"),
    }

    def claim(self, e: dict, statement: str, kind: str, about: list[str], limitation: str | None = None) -> None:
        ev, st, note = self.edge_prov(e)
        cid = f"{P}/claim/{e['type'].lower().replace('_', '-')}-{short_hash(e['id'])}"
        pub = self.paper_of_edge(e)
        basis = e["props"].get("basis")
        limits = "; ".join(filter(None, [STATEMENT_LIMITS.get(st), limitation]))
        self.ent(cid, "Claim", statement[:120],
                 {"statement": statement, "claim_kind": kind,
                  "epistemic_status": STATEMENT_TO_CLAIM[st],
                  "scope": f"As reported in {self.cite(pub)}" + (f"; basis: {basis}" if basis else ""),
                  "limitations": limits or None}, evidence=ev, note=note)
        for a in about:
            self.rel("about", cid, self.primary_id(a), evidence=ev, note=note)
        for x in ev:
            self.rel("supports", x, cid, origin="curated", note=note)
        self.rel("reported_in", cid, self.source_id(pub), origin="curated")
        self.report[f"claims.{e['type']}"] += 1

    def convert_edges(self) -> None:
        for e in sorted(self.links, key=lambda e: e["id"]):
            t, s, tg = e["type"], e["source"], e["target"]
            sn, tn = self.nodes[s], self.nodes[tg]
            if t == "REPORTED_IN":
                src = self.primary_id(s)
                if sn["label"] == "PerformanceMetric" and src not in self.entities:
                    src = next(k for k in self.entities if k.startswith(src + "/"))
                self.rel("reported_in", src, self.source_id(tg), origin="curated")
            elif t in ("HAS_ACTIVE_COMPONENT", "HAS_PROMOTER", "HAS_SUPPORT", "HAS_PHASE"):
                ev, st, note = self.edge_prov(e)
                role = {"HAS_ACTIVE_COMPONENT": "active_component", "HAS_PROMOTER": "promoter",
                        "HAS_SUPPORT": "support", "HAS_PHASE": "phase"}[t]
                self.rel("has_component", self.primary_id(s), self.primary_id(tg), evidence=ev,
                         epistemic=STATEMENT_TO_RELATION[st], qualifiers={"role": role}, note=note)
            elif t == "SYNTHESIZED_BY":
                ev, st, note = self.edge_prov(e)
                pub = self.paper_of_edge(e)
                sid = self.sample_for(s, pub, ev)
                prep = f"{P}/preparation/{node_slug(s)}/{node_slug(pub)}/{node_slug(tg)}"
                self.ent(prep, "Preparation", f"Preparation of {sn['props']['name']} by {tn['props']['name']}",
                         {"method": tn["props"]["name"], "status": "not_reported"}, evidence=ev, note=note)
                self.rel("prepared_by", sid, prep, evidence=ev, epistemic=STATEMENT_TO_RELATION[st], note=note)
                self.rel("follows_protocol", prep, self.primary_id(tg), evidence=ev, note=note)
                csid = f"{self.primary_id(tg)}/conditions"
                if csid in self.entities:
                    self.rel("operated_under", prep, csid, evidence=ev, note=note)
            elif t == "MEASURED_UNDER" and sn["label"] == "ThermodynamicQuantity":
                ev, st, note = self.edge_prov(e)
                self.rel("operated_under", self.primary_id(s), self.primary_id(tg), evidence=ev,
                         epistemic=STATEMENT_TO_RELATION[st], note=note)
            elif t == "GOVERNED_BY":
                aid = self.primary_id(tg)
                if not any(r["type"] == "observation_of" and r["target"] == self.primary_id(s)
                           and r["source"].startswith(aid + "/") for r in self.relations.values()):
                    # no reported value to bind: the relation is stated as a claim about both records
                    self.claim(e, f"{sn['props']['name']} is described by {tn['props']['name']}", "other", [s, tg])
                else:
                    self.edge_prov(e)
            elif t in self.CLAIM_EDGES:
                kind, tpl = self.CLAIM_EDGES[t]
                if t in ("CONSUMES", "PRODUCES") and sn["label"] == "Catalyst":
                    kind = "performance"
                stmt = tpl.format(s=sn["props"]["name"], t=tn["props"]["name"])
                if t == "INHIBITED_BY" and e["props"].get("negated"):
                    stmt = f"{sn['props']['name']} is not inhibited by {tn['props']['name']}"
                self.claim(e, stmt, kind, [s, tg])

    # ---------------------------------------------------------------- document
    def build(self, dataset: Path | None = None, excerpts: dict | None = None) -> dict:
        self.sources()
        self.convert_nodes()
        self.build_runs()
        self.convert_edges()
        if dataset:
            from dataset_to_scale import DatasetConverter
            DatasetConverter(self, dataset, excerpts or {}).run()
        substantive = sorted(e["id"] for e in self.links if e["type"] != "REPORTED_IN")
        self.unhandled = [i for i in substantive if i not in self.handled]
        self.report["bundle_edges.substantive"] = len(substantive)
        self.report["bundle_edges.carried"] = len(substantive) - len(self.unhandled)
        m = self.manifest
        ents = sorted(self.entities.values(), key=lambda e: (e["type"], e["id"]))
        rels = sorted(self.relations.values(), key=lambda r: r["id"])
        return {
            "schema_version": "0.1.0",
            "vocabulary_version": "0.1.0",
            "graph_id": f"{P}/collection",
            "title": (f"Methanol synthesis, historical literature 1927-1965 ({m['counts']['papers']} sources): the "
                      f"GALAXY bundle {m['bundle_id']} {m['version']} restated in the SCALE catalysis schema"
                      + (", with the pre-1965 data table (549 rows) and its equilibrium screen" if dataset else "")
                      + ". Scope: source-specific catalyst, preparation, operating-condition and outcome claims; "
                      "document-structure relations excluded."),
            "data_status": "research_data",
            "profiles": ["core", "heterogeneous", "thermal"],
            "entities": ents,
            "relations": rels,
        }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bundle", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--dataset", type=Path, help="corpus directory holding the pre-1965 data table")
    ap.add_argument("--excerpts", type=Path, help="verified table excerpts (dataset-excerpts.json)")
    a = ap.parse_args(argv)
    c = Converter(a.bundle)
    excerpts = json.loads(a.excerpts.read_text(encoding="utf-8")) if a.excerpts else None
    doc = c.build(a.dataset, excerpts)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(dump_canonical(doc), encoding="utf-8")
    if a.report:
        rep = {"counts": dict(sorted(c.report.items())), "unrestored_values": c.unrestored,
               "unhandled_bundle_edges": c.unhandled,
               "bundle": {"id": c.manifest["bundle_id"], "version": c.manifest["version"],
                          "graph_sha256": c.manifest["graph_sha256"]}}
        a.report.write_text(dump_canonical(rep), encoding="utf-8")
    print(f"{len(doc['entities'])} entities, {len(doc['relations'])} relations, "
          f"{len(c.unrestored)} values not restored, {len(c.unhandled)} bundle edges not carried over",
          file=sys.stderr)
    return 1 if c.unhandled or c.unrestored else 0


if __name__ == "__main__":
    sys.exit(main())
