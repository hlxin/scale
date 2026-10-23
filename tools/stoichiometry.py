"""Atom and charge balance of reactions and elementary steps, from their recorded participants (catalysis).

A Reaction or an ElementaryStep lists its participants with HAS_PARTICIPANT: each species with its role (a reactant or a
product; a catalyst, an intermediate or an inert takes no part in the net balance) and its stoichiometric coefficient.
With the composition of every reactant and product (its ``elemental_composition``, or a ``formula`` that can be read:
:func:`parse_formula`) and its ``charge`` (stated, never assumed), the participants balance in atoms when every element
is conserved, and in charge when the charges of the two sides add up to the same. Each check stands alone and says what
it lacks (:func:`assess`): a charge not stated leaves the charge balance not checkable and the atom balance as it is; a
free site or a coverage not recorded leaves both as they are, since a site carries no atoms and no charge (a site
balance is not assessed).

What the source says (``Reaction.balance_status``) is kept as it is and reported beside the computed assessment, never
replaced by it. :func:`check_document` reports, for the validator: an imbalance (a warning, naming the elements or
charges and what the source says), a formula that reads as another composition than the stated one (a warning), and the
assessment of every record with participants (``Report.balance``). Nothing is rewritten, and no equation text is parsed.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any

SIDES = {"reactant": "reactants", "product": "products"}        # the roles a net balance counts, and their side
ELEMENTS = set("""H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr
Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg
Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og
D T""".split())                                          # D and T: hydrogen isotopes, kept apart as an isotopic label is
PHASE = re.compile(r"\((?:g|l|s|aq|ads|sol|gas|liq|cr)\)", re.I)
SUPER = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
STATUS = ("balanced", "unbalanced", "not_checkable")
TOL = 1e-9


# ------------------------------------------------------------------------------------------ formulas
def parse_formula(text: Any, charge: int | None = None) -> tuple[dict | None, str | None]:
    """The elemental composition a formula states, or (None, why it cannot be read). A formula is read as chemists write
    one: element symbols with counts, parentheses or brackets with a count, a hydrate after a dot (·) with its count, an
    adsorption mark (*) and a phase in parentheses ((g), (aq), (ads)) set aside; an electron (e-) and a free site (*)
    have no atoms. A trailing charge is set aside first: written as a superscript (SO4^2-, SO4(2-), SO4²⁻) it is clear;
    written inline after the last count (NO3-, Cu2+), it is set aside as the species' stated ``charge`` says, and, when
    no charge is stated, only where no count comes right before the sign (OH-, H+): NO3- could be NO3 with charge -1 or
    NO with charge 3-, so it is not read."""
    if not isinstance(text, str) or not text.strip():
        return None, "it has no formula"
    t = unicodedata.normalize("NFC", text).strip()
    t = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+$", lambda m: "^" + m.group(0).translate(SUPER), t)     # a superscript charge
    t = PHASE.sub("", t).replace("*", "").replace(" ", "")
    m = re.search(r"(?:\^\{?([0-9]*[+-]|[+-][0-9]*)\}?|\(([0-9]*[+-]|[+-][0-9]*)\))$", t)
    sign = None
    if m:                                                 # written as a superscript: clear
        sign, t = m.group(1) or m.group(2), t[:m.start()]
    elif t.endswith(("+", "-")):
        body = t.rstrip("+-")
        run = t[len(body):]
        cands = []                                       # (the suffix set aside, the charge it states)
        if len(set(run)) == 1:
            cands.append((run, len(run) * (1 if run[0] == "+" else -1)))
        dm = re.search(r"([0-9]+)([+-])$", t)
        if dm and len(run) == 1:
            cands.append((dm.group(0), int(dm.group(1)) * (1 if dm.group(2) == "+" else -1)))
        if charge is not None:
            hit = [c for c in cands if c[1] == charge]
            if not hit:
                return None, f"its formula {text!r} ends in a charge its charge ({charge:+d}) does not state"
            t = t[:len(t) - len(hit[0][0])]
            sign = None
        elif body and body[-1].isdigit():
            return None, (f"its formula {text!r} ends in a count and a sign, which can be read two ways; state its charge "
                          "or its elemental_composition")
        else:
            t = body
    if sign is not None and charge is not None:
        mag = re.sub(r"[+-]", "", sign)
        stated = (int(mag) if mag else 1) * (1 if "+" in sign else -1)
        if stated != charge:
            return None, f"its formula {text!r} states charge {stated:+d}, its charge {charge:+d}"
    if charge is not None and sign is None and charge != 0 and t == text.strip():
        pass                                             # a charge stated apart from a formula that writes none: fine
    if t in ("e", ""):
        return {}, None                                  # an electron, or a free site: no atoms
    comp = _composition(t)
    if comp is None:
        return None, f"its formula {text!r} is not one that can be read (element symbols with counts)"
    return comp, None


def _composition(t: str) -> dict | None:
    """Element counts of a formula body: symbols, counts, nested (…) and […] with counts, hydrates after ·."""
    total: Counter = Counter()
    for k, part in enumerate(t.split("·")):
        mult = 1
        lead = re.match(r"^([0-9]+)", part)
        if lead and k > 0:
            mult, part = int(lead.group(1)), part[lead.end():]
        got = _group(part)
        if got is None or not part:
            return None
        for el, n in got.items():
            total[el] += n * mult
    return dict(total)


def _group(t: str) -> Counter | None:
    stack: list[Counter] = [Counter()]
    i = 0
    while i < len(t):
        ch = t[i]
        if ch in "([":
            stack.append(Counter())
            i += 1
        elif ch in ")]":
            if len(stack) == 1:
                return None
            inner = stack.pop()
            m = re.match(r"[0-9]+", t[i + 1:])
            n = int(m.group(0)) if m else 1
            i += 1 + (m.end() if m else 0)
            for el, c in inner.items():
                stack[-1][el] += c * n
        else:
            m = re.match(r"([A-Z][a-z]?)([0-9]*)", t[i:])
            if not m or m.group(1) not in ELEMENTS:
                return None
            stack[-1][m.group(1)] += int(m.group(2) or 1)
            i += m.end()
    return stack[0] if len(stack) == 1 else None


def composition_of(props: dict) -> tuple[dict | None, str | None]:
    """A species' composition: its ``elemental_composition`` when stated, else what its formula states."""
    ec = props.get("elemental_composition")
    if isinstance(ec, dict) and all(isinstance(v, int) and not isinstance(v, bool) for v in ec.values()):
        return {k: v for k, v in ec.items() if v}, None
    comp, why = parse_formula(props.get("formula"), charge_of(props))
    if comp is None:
        return None, f"no elemental_composition, and {why}"
    return comp, None


def charge_of(props: dict) -> int | None:
    """A species' charge, as stated (``charge``); None when it is not: a species is never taken as neutral."""
    c = props.get("charge")
    return c if isinstance(c, int) and not isinstance(c, bool) else None


# ------------------------------------------------------------------------------------------ assessment
def assess(doc: dict) -> dict:
    """The balance of every Reaction and ElementaryStep that has participants: {"records": [...], "without_participants":
    n}. Each record: its id, label, what the source says (``source_says``: its balance_status), and the ``atoms`` and
    ``charge`` checks, each {status: balanced | unbalanced | not_checkable, and the totals of the two sides (``reactants``,
    ``products``), or what it lacks (``missing``)}; participants a net balance does not count (a catalyst, an
    intermediate, an inert) are listed under ``not_counted``."""
    nodes = {n["id"]: n for n in doc.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)}
    parts: dict[str, list] = defaultdict(list)
    for e in doc.get("links") or []:
        if isinstance(e, dict) and e.get("type") == "HAS_PARTICIPANT" and e.get("source") in nodes:
            parts[e["source"]].append(e)
    out, bare = [], 0
    for rid, n in sorted(nodes.items()):
        if n.get("label") not in ("Reaction", "ElementaryStep"):
            continue
        if not parts.get(rid):
            bare += 1
            continue
        out.append(_assess_one(n, parts[rid], nodes))
    return {"records": out, "without_participants": bare}


def _assess_one(n: dict, links: list[dict], nodes: dict) -> dict:
    p = n.get("props") if isinstance(n.get("props"), dict) else {}
    rec = {"record": n["id"], "label": n.get("label"), "name": p.get("name"), "source_says": p.get("balance_status")}
    stated: dict[tuple, set] = defaultdict(set)          # (species, side) -> the coefficients its statements give
    lacks: list[str] = []                                # what both checks lack
    not_counted = []
    for e in sorted(links, key=lambda e: str(e.get("id"))):
        lp = e.get("props") if isinstance(e.get("props"), dict) else {}
        sp, role = e.get("target"), lp.get("role")
        if role not in SIDES:
            not_counted.append(f"{sp} ({role or 'no role'})")
            continue
        coef = lp.get("coefficient")
        if not isinstance(coef, (int, float)) or isinstance(coef, bool):
            lacks.append(f"the coefficient of {sp} (a {role}) is not stated")
            continue
        if role == "product" and coef < 0:
            lacks.append(f"{sp} is a product with a negative coefficient ({coef:g})")
            continue
        stated[(sp, SIDES[role])].add(abs(float(coef)))
    for (sp, side), cs in sorted(stated.items()):
        if len(cs) > 1:
            lacks.append(f"{sp} has {len(cs)} coefficients among the {side} ({', '.join(f'{c:g}' for c in sorted(cs))})")
    sides = {s for (_, s) in stated}
    if not lacks and sides != set(SIDES.values()):
        lacks.append("it records no " + ("reactant" if "reactants" not in sides else "product"))
    if not_counted:
        rec["not_counted"] = not_counted
    if lacks:
        rec["atoms"] = {"status": "not_checkable", "missing": list(lacks)}
        rec["charge"] = {"status": "not_checkable", "missing": list(lacks)}
        return rec
    terms = [(sp, side, next(iter(cs))) for (sp, side), cs in sorted(stated.items())]
    # atoms: every counted species' composition
    miss, totals = [], {"reactants": Counter(), "products": Counter()}
    for sp, side, coef in terms:
        comp, why = composition_of((nodes.get(sp) or {}).get("props") or {}) if sp in nodes else (None, "not in this graph")
        if comp is None:
            miss.append(f"the composition of {sp}: {why}")
            continue
        for el, k in comp.items():
            totals[side][el] += coef * k
    if miss:
        rec["atoms"] = {"status": "not_checkable", "missing": miss}
    else:
        els = sorted(set(totals["reactants"]) | set(totals["products"]))
        diff = {el: {"reactants": _round(totals["reactants"][el]), "products": _round(totals["products"][el])}
                for el in els if not math.isclose(totals["reactants"][el], totals["products"][el], abs_tol=TOL)}
        rec["atoms"] = {"status": "unbalanced" if diff else "balanced",
                        **({"difference": diff} if diff else {})}
    # charge: every counted species' stated charge
    miss, q = [], {"reactants": 0.0, "products": 0.0}
    for sp, side, coef in terms:
        c = charge_of((nodes.get(sp) or {}).get("props") or {}) if sp in nodes else None
        if c is None:
            miss.append(f"the charge of {sp} is not stated (a species is never taken as neutral)")
            continue
        q[side] += coef * c
    if miss:
        rec["charge"] = {"status": "not_checkable", "missing": miss}
    else:
        rec["charge"] = {"status": "balanced" if math.isclose(q["reactants"], q["products"], abs_tol=TOL) else "unbalanced",
                         "reactants": _round(q["reactants"]), "products": _round(q["products"])}
    return rec


def _round(x: float) -> float | int:
    r = round(x, 9)
    return int(r) if r == int(r) else r


def summary(res: dict) -> dict:
    """The counts of an assessment, by check and status, and the records it lists."""
    return {"checked": len(res["records"]), "without_participants": res["without_participants"],
            "atoms": dict(sorted(Counter(r["atoms"]["status"] for r in res["records"]).items())),
            "charge": dict(sorted(Counter(r["charge"]["status"] for r in res["records"]).items())),
            "records": res["records"]}


# ------------------------------------------------------------------------------------------ the validator's report
def check_document(doc: dict, rep) -> None:
    """The balance diagnostics of a document (the module docstring): warnings for an imbalance and for a formula that
    reads as another composition than the stated one, and the assessment in ``rep.balance`` (nothing when no reaction or
    step has participants)."""
    res = assess(doc)
    for r in res["records"]:
        says = r.get("source_says")
        kept = f"; the source says {says} (balance_status), which is kept" if says else ""
        a = r["atoms"]
        if a["status"] == "unbalanced":
            what = ", ".join(f"{el} {d['reactants']:g} in the reactants and {d['products']:g} in the products"
                             for el, d in a["difference"].items())
            rep.add("warning", r["record"], f"atom balance: its recorded participants do not balance ({what}){kept}; they "
                                            "stay as recorded")
        c = r["charge"]
        if c["status"] == "unbalanced":
            rep.add("warning", r["record"], f"charge balance: its recorded participants do not balance (charge "
                                            f"{c['reactants']:+g} in the reactants and {c['products']:+g} in the products)"
                                            f"{kept}; they stay as recorded")
    used = {e.get("target") for e in doc.get("links") or [] if isinstance(e, dict) and e.get("type") == "HAS_PARTICIPANT"}
    for n in doc.get("nodes") or []:
        if not isinstance(n, dict) or n.get("id") not in used:
            continue
        p = n.get("props") if isinstance(n.get("props"), dict) else {}
        ec = p.get("elemental_composition")
        if isinstance(ec, dict) and isinstance(p.get("formula"), str):
            comp, _ = parse_formula(p["formula"], charge_of(p))
            if comp is not None and comp != {k: v for k, v in ec.items() if v}:
                rep.add("warning", n["id"], f"its formula {p['formula']!r} reads as {_comp(comp)}, but its "
                                            f"elemental_composition is {_comp(ec)}; a balance uses the elemental_composition")
    if res["records"]:
        rep.balance = summary(res)


def _comp(c: dict) -> str:
    return " ".join(f"{el}{n if n != 1 else ''}" for el, n in sorted(c.items()) if n) or "no atoms"
