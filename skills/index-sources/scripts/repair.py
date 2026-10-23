"""Re-apply the current cleaning rules to sources already in the ledger (run once after a skill upgrade).

  1 abstracts   every stored abstract goes through normalize_abstract: a leading "Abstract" / "Summary" heading
                (also glued: "AbstractMXenes ..."), ACS "High Resolution Image Download MS PowerPoint Slide" debris,
                the trailing copyright line and placeholders such as "[No abstract available]"
  2 notices  notices the title rules now recognize ("Retraction of ...", "Notice of retraction", "Withdrawn: ...")
                are flagged; a row that only one database typed as an erratum, with nothing else marking it as a notice,
                becomes an article
  3 topics      vocabulary Topic A/B/C of the sources whose abstract changed are recomputed (Claude, API and manual
                topics are kept)
  4 retractions from the Crossref answers already cached (no request is made): a retraction notice is a notice
                that names the source it retracts, not a retracted source itself; that source is marked retracted and
                names its notice (index columns Retracted and Notes; index.db is_retracted and identifiers
                retraction_of / retraction_notice). Older versions marked the notice as the retracted source.
Then the index CSVs and index.db are refreshed (--no-export to skip). Works in chunks of 20,000 sources, so a
ledger of millions of rows is fine. Never deletes a row; --dry-run only counts.
SI deposits merged into sources by older versions and patent families are fixed by dedup.py --apply; SI links from
raw hits indexed by older versions by build_list.py --si-links-only.

  python3 -I repair.py [--dry-run] [--no-export] [--retractions-only]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cache import Cache
from _common import (Project, add_project_arg, is_erratum, jsonl_append, log, norm_doi, normalize_abstract, now_iso,
                     retraction_of)
from _ledger import Ledger
from _topics import Vocab, apply_vocab

CHUNK = 20000


def repair_retractions(proj, led, dry=False):
    """Step 4: every cached Crossref answer that records a retraction, applied as classify_access.py now does."""
    n = {"notices": 0, "notices_were_marked_retracted": 0, "sources_newly_retracted": 0, "marked_itself": 0}
    for rec in Cache(proj, "crossref").iter_all(like='%"update_to": [{%'):
        doi = norm_doi(rec.get("doi"))
        itself, retracts = retraction_of(rec.get("update_to"), doi)
        pid = (itself or retracts) and led.find_id(doi=doi)
        if not pid:
            continue
        row = led.get(pid)
        if retracts:
            n["notices"] += 1
            n["notices_were_marked_retracted"] += bool(row.get("retracted"))
            if dry:
                tids = {led.find_id(doi=t) for t in retracts} - {None, pid}
                n["sources_newly_retracted"] += sum(1 for t in tids if not led.get(t).get("retracted"))
            else:
                with led.tx():
                    n["sources_newly_retracted"] += led.record_retraction(pid, retracts)
        elif not row.get("retracted"):
            n["marked_itself"] += 1
            if not dry:
                led.set(pid, retracted=1)
    log(f"repair: retractions {n}")
    return n


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--dry-run", action="store_true", help="count what would change; write nothing")
    ap.add_argument("--no-export", action="store_true", help="do not refresh the index CSVs and index.db")
    ap.add_argument("--retractions-only", action="store_true", help="only step 4 (retraction notices and their sources)")
    a = ap.parse_args()
    proj = Project(a.project)
    led = Ledger(proj)
    if a.retractions_only:
        res = {"retractions": repair_retractions(proj, led, a.dry_run), "dry_run": a.dry_run, "finished_at": now_iso()}
        if not a.dry_run:
            jsonl_append(proj.logs / "repair_log.jsonl", res)
            if not a.no_export:
                led.export()
                res["database"] = led.last_publish
        print(json.dumps(res))
        return
    last, n_rows, n_ab, n_emptied, n_flag, n_retype = 0, 0, 0, 0, 0, 0
    changed = []
    while True:
        rows = led.q("SELECT id, title, doi, doc_type, is_erratum, abstract FROM sources WHERE id > ? ORDER BY id LIMIT ?",
                     (last, CHUNK))
        if not rows:
            break
        last = rows[-1][0]
        n_rows += len(rows)
        updates = []
        for pid, title, doi, dt, ie, ab in rows:
            upd = {}
            if ab:
                new = normalize_abstract(ab)
                if new != ab:
                    upd["abstract"] = new or None
                    n_ab += 1
                    if not new:
                        upd["abstract_source"] = None
                        n_emptied += 1
                    changed.append(pid)
            if not ie and is_erratum(title, None, doi):
                upd["is_erratum"] = 1
                n_flag += 1
            elif not ie and dt == "erratum":
                upd["doc_type"] = "article"
                n_retype += 1
            if upd:
                updates.append((pid, upd))
        if updates and not a.dry_run:
            with led.tx():
                for pid, upd in updates:
                    led.set(pid, **upd)
        log(f"repair: {n_rows} sources checked; abstracts cleaned {n_ab}, notices flagged {n_flag}, retyped {n_retype}")
    n_topics = 0
    if changed and not a.dry_run:
        vocab = Vocab(proj)
        for i in range(0, len(changed), 900):
            part = changed[i:i + 900]
            rows = [led.row(r) for r in led.q(f"SELECT * FROM sources WHERE id IN ({','.join('?' * len(part))})", tuple(part))]
            n_topics += apply_vocab(led, vocab, rows)
    res = {"sources_checked": n_rows, "abstracts_cleaned": n_ab, "abstracts_emptied": n_emptied,
           "notices_flagged": n_flag, "erratum_rows_retyped_article": n_retype, "topics_recomputed": n_topics,
           "retractions": repair_retractions(proj, led, a.dry_run), "dry_run": a.dry_run, "finished_at": now_iso()}
    if not a.dry_run:
        jsonl_append(proj.logs / "repair_log.jsonl", res)
        if not a.no_export:
            led.export()
            res["database"] = led.last_publish
    print(json.dumps(res))


if __name__ == "__main__":
    main()
