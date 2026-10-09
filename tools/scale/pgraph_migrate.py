"""Move scale-graph documents along the version steps of the schema.

    scale graph migrate IN.json OUT.json

A proposal that raises the schema version registers its step here: ``STEPS[from] = (to, proposal
id)``. An additive step only raises ``schema_version``; a step that changes how records are written
also registers a rule in ``STEP_RULES[from] = (description, function)``, which rewrites the document
and reports every change. Every record keeps its id, and what cannot be inferred is not invented: a
rule that meets a case it cannot map stops with an error.

The schema starts at 0.1.0, with no steps. A step is registered here when its proposal is prepared, so
that ``scale proposal check`` can assess the migration; documents move along it only once the proposal is
applied (the head manifest is then at its target).
"""

from __future__ import annotations

import copy
from typing import Callable

from . import layout
from .util import ScaleError

STEPS: dict[str, tuple[str, str]] = {
    # "<from version>": ("<to version>", "<proposal id>"), one line per proposal that raises the version, oldest
    # first (none before the first proposal: the schema starts at 0.1.0)
}
STEP_RULES: dict[str, tuple[str, Callable[[dict, dict | None], list]]] = {}


def route(have: str | None, to: str) -> list[tuple[str, str, str]] | None:
    """The steps (from, to, proposal id) from version ``have`` to ``to``; None when the steps do not reach it."""
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
    with a rule may need. A target that names the proposals it was built from (``proposals``, and a
    candidate's own ``proposal``) must include each step's: another proposal's candidate at the same
    version is not what the steps lead to, and moving a document there is refused."""
    new = copy.deepcopy(doc)
    have = new["graph"].get("schema_version")
    built = set(layout.manifest_proposals(spec, "the target schema", own=True))
    steps = []
    while have != to:
        if have not in STEPS:
            raise ScaleError(f"no step from scale-graph {have} towards {to}")
        nxt, cs = STEPS[have]
        if built and cs not in built:
            raise ScaleError(f"the step scale-graph {have} -> {nxt} belongs to {cs}; the target {to} was built from "
                             f"{', '.join(sorted(built))}, so the steps do not lead to it (apply the proposals in order)")
        rule, fn = STEP_RULES.get(have, ("schema_version raised; meaning_preserving", None))
        step = {"from": have, "to": nxt, "proposal": cs, "rule": rule}
        if fn is not None:
            step["changes"] = fn(new, spec)
        steps.append(step)
        have = nxt
    new["graph"]["schema_version"] = to
    return new, {"steps": steps}
