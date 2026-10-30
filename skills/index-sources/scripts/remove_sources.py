"""Take sources out of the index at the user's request (e.g. every record not in English), the way a merged duplicate
leaves it: each row, its topics and DOIs are logged in full first (.scripts/logs/removed_log.jsonl, enough to restore
it), its PDF and SI move to .scripts/removed/<kind>/ (never deleted), then the ledger rows go; the export at the end
takes them out of index.db and the vector store drops their passages.

  python3 -I remove_sources.py --non-english [--keep-topic <topic>] [--dry-run]
  python3 -I remove_sources.py --ids FILE --reason "<why>" [--dry-run]

--non-english picks every record whose title or abstract is in another language (_lang.py); a downloaded source whose
PDF reads as English stays. --keep-topic (repeatable) spares a topic's sources, e.g. a curated corpus. Prints one
JSON object.
"""
import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pdf as C  # noqa: E402
from _common import Project, add_project_arg, die, jsonl_append, log, now_iso  # noqa: E402
from _lang import NON_LATIN, _latin_votes, non_english  # noqa: E402
from _ledger import Ledger  # noqa: E402
from _vectors import after_step  # noqa: E402


def pdf_reads_english(proj, path):
    """The first pages of a downloaded PDF: English unless mostly another script or another language's words."""
    first, _ = C.extract_text(proj.root / path)
    text = (first or "")[:6000] or C.poppler_text(proj.root / path)[:6000]
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    if sum(1 for c in letters if NON_LATIN.match(c)) / len(letters) >= 0.3:
        return False
    _, hits, en = _latin_votes(text)
    return hits <= en


def pick_non_english(proj, led, keep_topics):
    """{source id: reason} for every record in another language, sparing kept topics and English PDFs."""
    kept = {r[0] for t in keep_topics for r in led.q("SELECT source_id FROM source_topics WHERE topic=?", (t,))}
    out, spared = {}, Counter()
    scan = sqlite3.connect(f"file:{proj.ledger_db}?mode=ro", uri=True)    # streamed: millions of rows
    for pid, title, abstract, downloaded in scan.execute("SELECT id, title, abstract, downloaded FROM sources"):
        why = non_english(title, abstract)
        if not why:
            continue
        if pid in kept:
            spared["kept_topic"] += 1
            continue
        if downloaded:
            paths = [r[0] for r in led.q("SELECT path FROM source_topics WHERE source_id=? AND path IS NOT NULL", (pid,))]
            if paths and pdf_reads_english(proj, paths[0]):
                spared["pdf_reads_english"] += 1
                continue
        out[pid] = f"not English: {why}"
    scan.close()
    return out, spared


def remove(proj, led, pid, reason, kind):
    """Log the source in full, move its files under .scripts/removed/<kind>/, delete its ledger rows."""
    row = led.get(pid)
    if not row:
        return None
    topics = led.topics_of(pid)
    moved, dst_dir = [], proj.scr / "removed" / kind
    for t in topics:
        for f in [t.get("path")] + json.loads(t.get("si_paths") or "[]"):
            if f and (proj.root / f).exists():
                dst_dir.mkdir(parents=True, exist_ok=True)
                dst = dst_dir / f"{pid}__{Path(f).name}"
                shutil.move(str(proj.root / f), str(dst))
                moved.append(proj.rel(dst))
    snapshot = json.loads(json.dumps({"row": row, "topics": topics, "dois": led.aliases(pid)}, default=str))
    jsonl_append(proj.logs / "removed_log.jsonl", {"id": pid, "doi": row.get("doi"), "reason": reason,
                                                   "files_moved": moved, "ts": now_iso(), **snapshot})
    for tbl in ("dois", "source_topics", "source_subjects", "extractions"):
        led.x(f"DELETE FROM {tbl} WHERE source_id=?", (pid,))
    led.x("DELETE FROM sources WHERE id=?", (pid,))
    return moved


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--non-english", action="store_true", help="every record whose title or abstract is not English")
    g.add_argument("--ids", help="file of source IDs, one per line (with --reason)")
    ap.add_argument("--reason", help="why these sources leave the index (logged with each)")
    ap.add_argument("--keep-topic", action="append", default=[], help="spare this topic's sources (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="count and show examples; change nothing")
    a = ap.parse_args()
    proj = Project(a.project)
    led = Ledger(proj)
    if a.non_english:
        picked, spared = pick_non_english(proj, led, a.keep_topic)
        kind = "non-english"
    else:
        if not a.reason:
            die("--ids needs --reason")
        ids = {int(x) for x in Path(a.ids).read_text().split() if x.strip().isdigit()}
        kept = {r[0] for t in a.keep_topic for r in led.q("SELECT source_id FROM source_topics WHERE topic=?", (t,))}
        picked, spared = {i: a.reason for i in ids - kept}, Counter(kept_topic=len(ids & kept))
        kind = re.sub(r"[^a-z0-9]+", "-", a.reason.lower()).strip("-")[:40] or "removed"
    kinds = Counter(r.split(": ", 1)[-1].split(" in ")[0] for r in picked.values())
    log(f"remove: {len(picked)} sources ({dict(kinds)}); spared {dict(spared)}")
    if a.dry_run:
        with_pdf = sum(1 for p in picked if led.q("SELECT 1 FROM sources WHERE id=? AND downloaded=1", (p,)))
        print(json.dumps({"would_remove": len(picked), "by_kind": dict(kinds), "with_pdf": with_pdf,
                          "spared": dict(spared), "examples": [(led.get(p) or {}).get("title") for p in list(picked)[:10]]},
                         ensure_ascii=False))
        return
    done, files = 0, 0
    items = list(picked.items())
    for i in range(0, len(items), 500):
        with led.tx():
            for pid, reason in items[i:i + 500]:
                moved = remove(proj, led, pid, reason, kind)
                if moved is not None:
                    done += 1
                    files += len(moved)
        log(f"remove: {min(i + 500, len(items))}/{len(items)}")
    led.export()
    print(json.dumps({"removed": done, "files_moved": files, "by_kind": dict(kinds), "spared": dict(spared),
                      "log": proj.rel(proj.logs / "removed_log.jsonl"), "vector_store": after_step(proj, led),
                      "finished_at": now_iso()}))


if __name__ == "__main__":
    main()
