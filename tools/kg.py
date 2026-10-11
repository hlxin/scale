"""``scale kg update``: move a knowledge-graph data repository to a newer schema version.

A data repository (any folder of curated documents, kept apart from this repository) holds scale-catal
documents that each pin the schema version they were curated under. When a schema change is merged in the schema repository, the domain's
head version moves on; ``scale kg update --data DIR`` then, for every scale-catal document of the domain
under DIR:

- moves it to the head (or ``--to``) version through the registered steps (``pgraph_migrate.STEPS``, and
  the rule of each step that has one), keeping every record id;
- validates it before and after, and reports errors, warnings and checklist conformance per document;
- writes it in place (canonical JSON) unless ``--dry-run``, and rebuilds the evidence index beside it
  (``<name>.evidence.jsonl`` / ``.i8`` / ``.terms``) when it has one.

What it does not change: a document a step rule cannot map is refused, reported and left untouched (the
rule says why; a curator fixes the record first); a document whose file name pins a version
(``*.scale-catal-0.2.0.graph.json``, or ``*.scale-graph-0.1.0.graph.json`` from before the rename) is a deliberate copy at that version and is kept; a document whose
migrated form has more validation errors than before is not written; sealed packages (a directory with a
``.scale-verbatim`` marker, such as kg-bundles) and local ``work/`` folders are not read. A document pinning a version this repository does
not hold is refused (``pgraph.pinned`` says why): its number names no schema here, so no step applies to it.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import layout
from .util import ScaleError, load_doc, write_canonical

SKIP_DIRS = {".git", ".github", ".venv", "__pycache__", "work", "scratchpad", "node_modules"}
PINNED_NAME = re.compile(r"\.scale-(?:catal|graph)-(\d+\.\d+\.\d+)\.")     # scale-graph: the name before 0.2.0


def _sealed(p: Path, root: Path) -> bool:
    return any((d / ".scale-verbatim").exists() for d in [p.parent, *p.parent.parents] if d == root or root in d.parents)


def documents(data: Path) -> list[Path]:
    """The scale-catal documents under ``data`` (JSON with ``graph.schema: scale-catal``), outside sealed
    packages and local work folders."""
    data = Path(data).resolve()
    out = []
    for p in sorted(data.rglob("*.json")):
        rel = p.relative_to(data)
        if SKIP_DIRS & set(rel.parts[:-1]) or _sealed(p, data):
            continue
        try:
            doc = load_doc(p)
        except Exception:                                    # not JSON we can read: not a document
            continue
        g = doc.get("graph") if isinstance(doc, dict) else None
        if isinstance(g, dict) and g.get("schema") in (layout.SCHEMA_NAME, layout.LEGACY_SCHEMA_NAME):
            out.append(p)
    return out


def _summary(rep) -> dict:
    conf = (rep.conformance or {}).get("profiles") or {}
    return {"valid": rep.ok, "errors": len(rep.errors), "warnings": len(rep.warnings),
            "conformance": {ref: len(c.get("violations") or []) for ref, c in conf.items()}}


def _index_stem(p: Path) -> Path:
    return p.with_name(p.name.removesuffix(".json").removesuffix(".graph") + ".evidence")


def update(repo: Path, data: Path, domain: str = "catalysis", to: str | None = None, dry_run: bool = False,
           reindex: bool = True) -> dict:
    """Update every scale-catal document of ``domain`` under ``data``; see the module docstring."""
    from . import pgraph
    from .pgraph_migrate import raise_version, route
    repo, data = Path(repo).resolve(), Path(data).resolve()
    if not data.is_dir():
        raise ScaleError(f"--data {data} is not a directory")
    mans = layout.graph_manifests(repo)
    if domain not in mans:
        raise ScaleError(f"no released domain {domain!r} with a schema manifest (have: {', '.join(sorted(mans)) or 'none'})")
    manifest = mans[domain]
    head = pgraph.load_spec(manifest)["version"]
    target = to or head
    tspec = pgraph.load_spec(pgraph.pinned(manifest, target))
    rows = []
    for p in documents(data):
        rel = p.relative_to(data).as_posix()
        doc = load_doc(p)
        have = doc["graph"].get("schema_version")
        row = {"document": rel, "from": have, "to": target}
        try:
            if pgraph.spec_path(repo, None, doc).resolve() != manifest.resolve():
                rows.append({**row, "status": "skipped", "why": f"follows another domain's schema, not {domain}'s"})
                continue
        except ScaleError as exc:
            rows.append({**row, "status": "skipped", "why": str(exc)})
            continue
        m = PINNED_NAME.search(p.name)
        if m:
            rows.append({**row, "status": "kept", "why": f"its file name pins scale-catal {m.group(1)}: a copy kept at that version"})
            continue
        try:
            before = _summary(pgraph.validate(doc, pgraph.load_spec(pgraph.pinned(manifest, have))))
        except ScaleError as exc:            # a version this repository does not hold (newer, or another numbering's)
            rows.append({**row, "status": "refused", "why": str(exc)})
            continue
        if have == target:
            rows.append({**row, "status": "current", "before": before, "after": before})
            continue
        steps = route(have, target)
        if steps is None:
            rows.append({**row, "status": "refused", "before": before,
                         "why": f"no registered steps lead from scale-catal {have} to {target}"})
            continue
        try:
            new, rep = raise_version(doc, target, tspec)
        except ScaleError as exc:
            rows.append({**row, "status": "refused", "before": before, "why": f"a step rule cannot migrate it: {exc}"})
            continue
        after = _summary(pgraph.validate(new, tspec))
        changes = sum(len(s.get("changes") or []) for s in rep["steps"])
        row.update(steps=[f"{s['from']} → {s['to']} ({s['note']})" for s in rep["steps"]], changes=changes,
                   before=before, after=after)
        if after["errors"] > before["errors"]:
            rows.append({**row, "status": "refused", "why": f"the migrated document has {after['errors']} validation "
                                                           f"errors (before: {before['errors']}); not written"})
            continue
        row["status"] = "would update" if dry_run else "updated"
        if not dry_run:
            write_canonical(p, new)
            stem = _index_stem(p)
            index = stem.with_name(stem.name + ".jsonl")
            if reindex and index.is_file():
                from .passages import Index, evidence_items, graph_sha256
                old = Index.load(stem)
                Index.build(evidence_items(new), old.embedder_id, graph_sha256(new)).save(stem)
                row["index"] = index.relative_to(data).as_posix()
        rows.append(row)
    ok = not any(r["status"] == "refused" for r in rows)
    return {"domain": domain, "head": head, "to": target, "data": str(data), "dry_run": dry_run, "ok": ok,
            "counts": {s: sum(r["status"] == s for r in rows) for s in sorted({r["status"] for r in rows})},
            "documents": rows}


def update_text(res: dict) -> str:
    """A short report, one line per document (the JSON report has every detail)."""
    lines = [f"scale kg update: {res['domain']} documents under {res['data']} → scale-catal {res['to']}"
             + (" (dry run: nothing written)" if res["dry_run"] else "")]
    for r in res["documents"]:
        b, a = r.get("before"), r.get("after")
        val = f"; errors {b['errors']} → {a['errors']}, warnings {b['warnings']} → {a['warnings']}" if b and a else ""
        conf = f"; checklist violations {sum(b['conformance'].values())} → {sum(a['conformance'].values())}" if b and a else ""
        lines.append(f"- {r['document']} ({r['from']}): {r['status']}"
                     + (f", {r['changes']} record changes" if "changes" in r else "") + val + conf
                     + (f" — {r['why']}" if r.get("why") else ""))
    if not res["documents"]:
        lines.append("- no scale-catal documents found")
    lines.append(("ok" if res["ok"] else "some documents were refused (see above); they are untouched") + f" {res['counts']}")
    return "\n".join(lines)
