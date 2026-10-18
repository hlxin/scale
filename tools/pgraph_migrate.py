"""Move scale-catal documents along the version steps of the schema.

    scale graph migrate IN.json OUT.json

A schema change that raises the version registers its step here: ``STEPS[from] = (to, note)`` (``scale schema
bump`` writes the line). An additive step only raises ``schema_version``; a breaking change also registers a rule
in ``STEP_RULES[from] = (description, function)``, which rewrites the document and reports every change (or
reports that no document needs one). Every record keeps its id, and what cannot be inferred is not invented: a
rule that meets a case it cannot map stops with an error.

The schema starts at 0.1.0, with no steps; ``scale check`` requires the step of every change (schema_change.check).
"""

from __future__ import annotations

import copy
from typing import Callable

from .util import ScaleError

STEPS: dict[str, tuple[str, str]] = {
    # "<from version>": ("<to version>", "<note>"), one line per change that raises the version, oldest first
    # (none before the first change: the schema starts at 0.1.0)
    "0.1.0": ("0.2.0", 'the schema is renamed scale-graph -> scale-catal (kernel scale-graph-kernel -> scale-kernel); documents pin the new name'),
    "0.2.0": ("0.2.1", 'no change in meaning: the description of Preparation.steps names PART_OF with order (#34)'),
    "0.2.1": ("0.3.0", "breaking: quantity contracts (a value's unit by its kind's dimension; the contexts a comparison needs; normalized_by; HAS_COMPONENT.concentration)"),
}


def _rename_schema(doc: dict, spec: dict | None) -> list:
    """0.1.0 -> 0.2.0: the schema is renamed scale-graph -> scale-catal (the kernel scale-graph-kernel -> scale-kernel,
    which a document never names). The pin ``graph.schema`` is rewritten; no record changes."""
    g = doc["graph"]
    if g.get("schema") == "scale-graph":
        g["schema"] = "scale-catal"
        return ["graph.schema: scale-graph -> scale-catal"]
    return []                                   # already names the new schema: nothing to rewrite


def _quantity_contracts(doc: dict, spec: dict | None) -> list:
    """0.2.1 -> 0.3.0: the quantity contracts. A HAS_COMPONENT ``fraction`` whose unit is an amount (g, mol, L) moves to
    ``amount`` and one whose unit is a concentration (mol/L, g/m3) to the new ``concentration``, the value object whole
    (number, unit, uncertainty, evidence_ids, as_reported), with its ``fraction_basis`` dropped (the unit says what it
    counts); every other value whose unit is of another dimension than its
    property's quantity stops the step, which cannot map it (``quantities.move_component_quantities``). ``spec`` is the
    target schema, whose contracts read the units."""
    from .quantities import move_component_quantities
    return move_component_quantities(doc, spec)


STEP_RULES: dict[str, tuple[str, Callable[[dict, dict | None], list]]] = {
    "0.1.0": ("graph.schema renamed scale-graph -> scale-catal; every record, id and value kept", _rename_schema),
    "0.2.1": ("quantity contracts: a HAS_COMPONENT fraction in an amount unit moves to amount, one in a concentration unit "
              "to concentration (the value object whole, its fraction_basis dropped); a value of another dimension than its "
              "quantity stops the step; every record, id and other value kept", _quantity_contracts),
}


def route(have: str | None, to: str) -> list[tuple[str, str, str]] | None:
    """The steps (from, to, note) from version ``have`` to ``to``; None when the steps do not reach it."""
    out, seen = [], set()
    while have != to:
        if have not in STEPS or have in seen:
            return None
        seen.add(have)
        nxt, cs = STEPS[have]
        out.append((have, nxt, cs))
        have = nxt
    return out


def raise_version(doc: dict, to: str, spec: dict | None = None) -> tuple[dict, dict]:
    """Move a document step by step to version ``to``. ``spec`` is the target schema, which a step
    with a rule may need."""
    new = copy.deepcopy(doc)
    have = new["graph"].get("schema_version")
    steps = []
    while have != to:
        if have not in STEPS:
            raise ScaleError(f"no step from scale-catal {have} towards {to}")
        nxt, cs = STEPS[have]
        rule, fn = STEP_RULES.get(have, ("schema_version raised; meaning_preserving", None))
        step = {"from": have, "to": nxt, "note": cs, "rule": rule}
        if fn is not None:
            step["changes"] = fn(new, spec)
        steps.append(step)
        have = nxt
    new["graph"]["schema_version"] = to
    return new, {"steps": steps}
