"""A frozen corpus manifest: every candidate source with its status, and counts that add up.

    scale corpus check MANIFEST [--included STATUS ...] [--frozen-at DATE] [--description TEXT]

Before curating, a corpus is frozen (the curate-source skill, step 1): which sources were candidates, by what rule,
and what became of each. The manifest is JSON or YAML::

    {"corpus": "what the corpus is", "cutoff": {"date": …, "rule": "published before …"}, "frozen_at": "2026-09-01",
     "counts": {"in_scope": 3, "not_retrieved": 1},
     "sources": [{"slug": "…", "status": "in_scope"}, {"slug": "…", "status": "not_retrieved"}, …]}

A source is named by ``slug`` (or ``id``) and carries a ``status``: an included status (by default ``in_scope`` or
``included``) or the reason it was left out (``not_retrieved``, ``off_scope``, ``after_cutoff``, …). A bare
``excluded`` names no reason, so it needs ``status_reason``. ``counts``, when the manifest has it, must equal the
statuses counted. The candidates are every source listed; a declared corpus is not a database search, so there are
no PRISMA identities (identified, deduplicated, screened) to check, only that every candidate is accounted for once.

:func:`check` returns the problems and the GALAXY ``corpus`` block (``description``, ``frozen_at``, ``n_screened``:
the candidates, ``n_included``), which ``scale graph export --to galaxy --corpus MANIFEST`` writes into bundle.json.
"""

from __future__ import annotations

from pathlib import Path

from .util import ScaleError, load_doc

INCLUDED = ("in_scope", "included")
NO_REASON = ("excluded", "out", "rejected")       # statuses that do not say why: they need status_reason


def load(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_file():
        raise ScaleError(f"{p}: no corpus manifest there")
    m = load_doc(p)
    if not isinstance(m, dict) or not isinstance(m.get("sources"), list):
        raise ScaleError(f"{p}: a corpus manifest is an object with a list of sources")
    return m


def check(manifest: dict, included: tuple[str, ...] | list[str] = INCLUDED, frozen_at: str | None = None,
          description: str | None = None) -> dict:
    """``{ok, problems, candidates, counts, included, corpus}`` for a manifest (see the module docstring)."""
    problems: list[str] = []
    counts: dict[str, int] = {}
    seen: dict[str, int] = {}
    for i, s in enumerate(manifest.get("sources") or []):
        if not isinstance(s, dict):
            problems.append(f"sources[{i}]: not an object")
            continue
        name = s.get("slug") or s.get("id")
        where = f"sources[{i}]" + (f" ({name})" if name else "")
        if not name:
            problems.append(f"{where}: names no slug or id")
        else:
            seen[str(name)] = seen.get(str(name), 0) + 1
        status = s.get("status")
        if not isinstance(status, str) or not status.strip():
            problems.append(f"{where}: has no status (included, or the reason it was left out)")
            continue
        if status in NO_REASON and not s.get("status_reason"):
            problems.append(f"{where}: status {status!r} says no reason; give status_reason")
        counts[status] = counts.get(status, 0) + 1
    problems += [f"{n}: listed {k} times (a candidate is accounted for once)" for n, k in sorted(seen.items()) if k > 1]
    declared = manifest.get("counts")
    total = sum(counts.values())
    if declared is not None:
        if not isinstance(declared, dict) or not all(isinstance(v, int) for v in declared.values()):
            problems.append("counts: not a map of status to a whole number")
        else:
            for st in sorted(set(declared) | set(counts)):
                if declared.get(st, 0) != counts.get(st, 0):
                    problems.append(f"counts: {st} says {declared.get(st, 0)}, the sources list {counts.get(st, 0)}")
            if sum(declared.values()) != total:
                problems.append(f"counts: add up to {sum(declared.values())}, the candidates are {total}")
    n_included = sum(v for k, v in counts.items() if k in included)
    if total and not n_included:
        problems.append(f"no source has an included status ({', '.join(included)})")
    cut = manifest.get("cutoff") if isinstance(manifest.get("cutoff"), dict) else {}
    desc = description or " ".join(x for x in (str(manifest.get("corpus") or manifest.get("description") or "").strip(),
                                               f"Rule: {cut['rule']}." if cut.get("rule") else "") if x)
    block = {"description": desc[:1000], "frozen_at": frozen_at or manifest.get("frozen_at") or manifest.get("frozen_on"),
             "n_screened": total, "n_included": n_included}
    return {"ok": not problems, "problems": problems, "candidates": total, "counts": dict(sorted(counts.items())),
            "included": list(included), "corpus": {k: v for k, v in block.items() if v not in (None, "")}}
