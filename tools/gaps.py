"""Representational gap reports and their routing to GitHub issues.

Gaps discovered during curation or querying are classified so that only a
genuinely missing concept leads to schema evolution:

=============================  ==============================================
kind                           action
=============================  ==============================================
missing_concept                schema change request (skills/evolve-schema)
extraction_error               re-extract / correct the record
absent_source_information      source review; other sources; no schema change
ambiguous_source_information   source review / author query; keep both values
missing_source_coverage        curate additional sources
=============================  ==============================================

A gap made from a query result carries the result's ``access`` (its level and note: where the whole queried
document may go). Its record ids, field names and question are drawn from that document, so a gap whose access is
not public goes only where the document may go: ``scale gap issue`` says so in the body and on stderr, and
``--submit`` refuses it (a person files it by hand within that audience, or makes the gap from a query of the public
view ``scale graph filter --public`` makes). A gap that states no access (written by hand, or by a ``scale gap
from-query`` that predates access) is read as :data:`UNSTATED_ACCESS`, institution, failing closed: a gap must
state ``access.level: public`` before ``--submit`` sends it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .util import ScaleError, sha256_text, write_canonical

ACTIONS = {
    "missing_concept": "Open a schema change request (skills/evolve-schema/SKILL.md). Do not extend the schema during curation.",
    "extraction_error": "Re-extract and correct the record against its source (skills/curate-source/SKILL.md).",
    "absent_source_information": "Review the source (SI, source-data files) or add sources. No schema change.",
    "ambiguous_source_information": "Review the source or query the authors. Keep every reported variant; do not reconcile silently.",
    "missing_source_coverage": "Curate additional sources into the declared collection.",
}
LABELS = {
    "missing_concept": ["gap:missing-concept", "schema-evolution"],
    "extraction_error": ["gap:extraction-error", "curation"],
    "absent_source_information": ["gap:absent-source-information", "curation"],
    "ambiguous_source_information": ["gap:ambiguous-source-information", "curation"],
    "missing_source_coverage": ["gap:missing-source-coverage", "curation"],
}


def gap_id(kind: str, record: str, about: str) -> str:
    return "GAP-" + sha256_text(f"{kind}|{record}|{about}")[:8].upper()


# a query result or a gap that states no access (one made before they carried it, or a gap written by hand) is read
# failing closed
UNSTATED_ACCESS = {"level": "institution", "note": "The query result states no access; read as institution, failing closed."}


def make_gap(kind: str, *, record: str, about: str, detected_by: str, schema: str | None,
             context: str = "", evidence: list | None = None, consequence: str = "",
             candidate_mappings: list | None = None, access: dict | None = None) -> dict:
    if kind not in ACTIONS:
        raise ScaleError(f"Unknown gap kind {kind!r}")
    return {
        "id": gap_id(kind, record, about),
        "kind": kind,
        "title": f"[{kind}] {about} ({record})",
        "status": "open",
        "detected_by": detected_by,
        "schema": schema,
        "records": [record],
        "about": about,
        "source_context": context,
        "evidence": evidence or [],
        "consequence": consequence,
        "candidate_mappings": candidate_mappings or [],
        "recommended_action": ACTIONS[kind],
        "labels": LABELS[kind],
        **({"access": {"level": access.get("level"), "note": access.get("note")}} if access is not None else {}),
    }


def not_public(gap: dict) -> str | None:
    """Why a gap may not go to a public tracker: its access, when that is not public (None only for a gap whose
    ``access.level`` is ``public``). A gap that states no access, a hand-written one included, is read as
    :data:`UNSTATED_ACCESS` (institution), failing closed: it states ``access.level: public`` to be filed publicly."""
    acc = gap.get("access")
    if isinstance(acc, dict) and acc.get("level") == "public":
        return None
    if acc is None:
        return ("access not stated: a gap that states none is read as institution, failing closed; give it "
                "access.level public only when its record ids, fields and question may all be public")
    level = acc.get("level") if isinstance(acc, dict) else None
    return (f"access {level or 'not stated'}: this gap was made from an answer whose document is not all public, so its "
            "record ids, fields and question go only where that document may go")


def gaps_from_query(result: dict, detected_by: str | None = None) -> list[dict]:
    """Gap reports from a scale-catal query result (``scale graph query``): a ``schema_gap`` names what
    the schema cannot express (a missing concept); ``no_matching_record`` asks for more sources; values
    the source does not report or reports ambiguously (``missing_context`` and ``excluded``) go to source
    review. Values not curated yet are curation backlog, not gaps; nor are values withheld from the view the query
    read (``withheld``: ``scale graph filter`` or an export left them out, the source reports them) or not
    extractable from the source. Every gap carries the result's ``access`` (:data:`UNSTATED_ACCESS` when it states
    none)."""
    by = detected_by or f"query: {result.get('question') or 'plan'}"
    access = result.get("access") if isinstance(result.get("access"), dict) else UNSTATED_ACCESS
    graph = result.get("graph_id") or "graph"
    version = f"scale-catal {result['schema_version']}" if result.get("schema_version") else None
    out = []
    if result.get("status") == "schema_gap":
        out += [make_gap("missing_concept", record=graph, about=g, detected_by=by, schema=version, access=access,
                         consequence="The question cannot be asked of any graph until the schema can express this.")
                for g in result.get("schema_gaps") or []]
    elif result.get("status") == "no_matching_record":
        out.append(make_gap("missing_source_coverage", record=graph, about=result.get("question") or "query",
                            detected_by=by, schema=version, access=access,
                            consequence="Nothing in this graph answers the question; it says nothing about the literature."))
    kinds = {"not_reported": "absent_source_information", "ambiguous_in_source": "ambiguous_source_information"}
    for item in (result.get("missing_context") or []) + (result.get("excluded") or []):
        kind = kinds.get(str(item.get("reason")))
        if kind:
            about = item.get("field") or (item.get("filter") or {}).get("prop") or "value"
            out.append(make_gap(kind, record=item["record"], about=str(about), detected_by=by, schema=version,
                                context=f"{item['record']}: {about} is {item['reason']}", access=access))
    seen: dict[str, dict] = {}
    for g in out:
        seen.setdefault(g["id"], g)
    return list(seen.values())


def render_issue(gap: dict) -> str:
    ev = "\n".join(f"- `{e}`" for e in gap.get("evidence") or []) or "- (none recorded)"
    maps = "\n".join(f"- {m}" for m in gap.get("candidate_mappings") or []) or "- (none proposed yet)"
    closed = not_public(gap)
    warn = f"> **Not for a public tracker.** {closed}.\n\n" if closed else ""
    return f"""<!-- scale-gap: {gap['id']} -->
{warn}**Gap kind:** `{gap['kind']}`  ·  **Detected by:** {gap['detected_by']}  ·  **Schema:** `{gap.get('schema') or gap.get('release')}`

### What could not be represented or recovered
{gap['about']}

### Source context
> {gap.get('source_context') or '(none)'}

### Affected records
{chr(10).join('- `' + r + '`' for r in gap['records'])}

### Evidence
{ev}

### Scientific consequence
{gap.get('consequence') or '(to be described)'}

### Candidate mappings to existing concepts
{maps}

### Recommended action
{gap['recommended_action']}

---
Classification guide: a *missing concept* is routed to schema evolution; an *extraction error*
to re-extraction; *absent* or *ambiguous source information* to source review. Only the first
changes the schema. Generated by `scale gap issue`.
"""


def write_gaps(gaps: list[dict], out_dir: str | Path) -> list[Path]:
    out = []
    for gp in gaps:
        p = Path(out_dir) / f"{gp['id']}.json"
        write_canonical(p, gp)
        out.append(p)
    return out


def submit_issue(gap: dict, repo: str | None = None, dry_run: bool = True) -> dict:
    """Create a GitHub issue with the ``gh`` CLI. Dry-run unless explicitly disabled. A gap whose access is not
    public (:func:`not_public`) is refused before anything is sent: it is filed by hand, within its audience."""
    closed = not_public(gap)
    if closed and not dry_run:
        raise ScaleError(f"{closed}; `scale gap issue --submit` files only public gaps. Render it without --submit and "
                         "file it by hand where that document may go, or make the gap from a query of the view "
                         "`scale graph filter --public` makes")
    cmd = ["gh", "issue", "create", "--title", gap["title"], "--body", render_issue(gap)]
    for lab in gap.get("labels", []):
        cmd += ["--label", lab]
    if repo:
        cmd += ["--repo", repo]
    if dry_run:
        return {"dry_run": True, "command": cmd[:6] + ["<body>"] + cmd[7:]}
    if shutil.which("gh") is None:
        raise ScaleError("gh CLI not found; install it or file the rendered issue manually")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ScaleError(f"gh issue create failed: {proc.stderr.strip()}")
    return {"dry_run": False, "url": proc.stdout.strip()}
