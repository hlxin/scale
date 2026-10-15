"""Phase 2 bookkeeping — where every paper of a run stands, and settle finished papers.

  python3 -I review_status.py --topic co2rr --name co2rr-catalysts            # table only (changes nothing)
  python3 -I review_status.py --topic co2rr --name co2rr-catalysts --apply    # settle papers (see below)
  python3 -I review_status.py ... --await-user "why"    /  --resume           # pause / unpause the Stop hook
  python3 -I review_status.py ... --phase merge|alias|validate|release|done   # record the phase

The orchestrator validates every new fragment here in its own process (independent of the validator stdout the
subagent pasted). --apply then decides, from the files on disk:
  reviewer on:  approved / approved_with_issues -> extracted (no_data when nothing matched the schema)
                rejected -> fragment moves to fragments/rejected/, status rejected
                needs_fix -> one corrective pass (next_batch.py --role fix); still needs_fix after it -> failed
  reviewer off: a valid fragment -> extracted (no_data when empty)
  invalid fragment -> moved to fragments/superseded/ and re-extracted once; invalid twice -> failed
Each settled paper gets one line in extraction_status.jsonl (paper-acquisition shows it in the index's Extracted
column, and an abstract the extractor copied fills a paper that had none); accepted.txt lists the papers the merge
uses.
"""
import argparse
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _kgcommon import Run, add_root_arg, append_jsonl, now_iso, read_json, read_jsonl, today

BUILTIN = {"Figure", "Publication"}


def frag_counts(frag):
    nodes = [n for n in frag.get("nodes") or [] if n.get("label") not in BUILTIN]
    return len(nodes), len(frag.get("edges") or [])


def main():
    ap = add_root_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--await-user", default=None)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--phase", default=None)
    a = ap.parse_args()
    run = Run(a.project, a.topic, a.name).ensure()
    if a.await_user is not None:
        run.update_state(awaiting_user=a.await_user or True)
        print(json.dumps({"awaiting_user": a.await_user}))
        return 0
    if a.resume:
        run.update_state(awaiting_user=None)
    if a.phase:
        run.update_state(phase=a.phase)
        print(json.dumps({"phase": a.phase}))
        return 0
    schema = read_json(run.schema)
    if not schema:
        print(json.dumps({"error": "no schema — run prepare_run.py first"}))
        return 2
    from validate_kg import validate_target_file
    st = run.state()
    reviewer = (st.get("options") or {}).get("reviewer", True)
    papers, final = run.papers(), run.statuses()
    pstate = st.get("papers") or {}
    seen_v = {(r.get("paper_id"), r.get("mtime")) for r in read_jsonl(run.vreport)}
    table, settle, moved = Counter(), [], []
    lists = {"to_review": [], "needs_fix": [], "invalid": [], "to_extract": []}
    for pid, p in papers.items():
        if not p.get("pdf"):
            table["no_pdf"] += 1
            continue
        if pid in final:
            table[final[pid]["status"]] += 1
            continue
        fp, rp = run.fragment(pid), run.review(pid)
        if not fp.exists():
            table["to_extract"] += 1
            lists["to_extract"].append(pid)
            continue
        ok, errs, warns = validate_target_file(fp, schema, run.schema.parent, False)
        key = (pid, int(fp.stat().st_mtime))
        if key not in seen_v:
            append_jsonl(run.vreport, {"paper_id": pid, "mtime": key[1], "ok": ok, "errors": errs[:20],
                                       "warnings": warns[:20], "at": now_iso()})
        if not ok:
            table["invalid"] += 1
            lists["invalid"].append(pid)
            if a.apply:
                ps = pstate.setdefault(str(pid), {})
                ps["invalid"] = ps.get("invalid", 0) + 1
                shutil.move(str(fp), str(run.frag / "superseded" / f"paper_{pid}.invalid.{int(time.time())}.json"))
                if ps["invalid"] >= 2:
                    settle.append((pid, "failed", None, f"fragment failed validation twice: {errs[0][:160]}"))
            continue
        frag = read_json(fp, {}) or {}
        n_nodes, n_edges = frag_counts(frag)
        if not reviewer:
            table["valid"] += 1
            if a.apply:
                settle.append((pid, "no_data" if n_nodes == 0 else "extracted", frag, "validated (no reviewer)"))
            continue
        if not rp.exists():
            table["to_review"] += 1
            lists["to_review"].append(pid)
            continue
        rv = read_json(rp, {}) or {}
        status = rv.get("status")
        if status in ("approved", "approved_with_issues"):
            table[status] += 1
            if a.apply:
                note = rv.get("summary") or status
                settle.append((pid, "no_data" if n_nodes == 0 else "extracted", frag, f"{status}: {note}"[:300]))
        elif status == "rejected":
            table["rejected_by_reviewer"] += 1
            if a.apply:
                shutil.move(str(fp), str(run.frag / "rejected" / fp.name))
                settle.append((pid, "rejected", None, (rv.get("summary") or "rejected by the reviewer")[:300]))
        elif status == "needs_fix":
            if (pstate.get(str(pid)) or {}).get("fix_attempts", 0) >= 1:
                table["failed_after_fix"] += 1
                if a.apply:
                    shutil.move(str(fp), str(run.frag / "rejected" / fp.name))
                    settle.append((pid, "failed", None, ("still needs fixes after one corrective pass: " +
                                                         str(rv.get("summary") or ""))[:300]))
            else:
                table["needs_fix"] += 1
                lists["needs_fix"].append(pid)
        else:
            table["review_unreadable"] += 1
            if a.apply:
                shutil.move(str(rp), str(run.reviews / f"paper_{pid}.unreadable.{int(time.time())}.json"))
    if a.apply and settle:
        version = st.get("schema_version")
        recs = []
        for pid, status, frag, note in settle:
            p = papers[pid]
            n_nodes, n_edges = frag_counts(frag) if frag else (None, None)
            r = {"paper_id": pid, "topic": run.topic, "kg": run.name, "status": status, "schema_version": version,
                 "nodes": n_nodes, "edges": n_edges, "date": today(), "note": note}
            ab = ((frag or {}).get("paper") or {}).get("abstract")
            if ab and not p.get("has_abstract"):
                r["abstract"] = ab
            recs.append(r)
        append_jsonl(run.status_log, recs)
    final = run.statuses()
    accepted = sorted(pid for pid, r in final.items() if r.get("status") == "extracted")
    run.accepted.write_text("".join(f"{x}\n" for x in accepted))
    counts = {k: sum(1 for r in final.values() if r.get("status") == k) for k in ("extracted", "rejected", "failed", "no_data")}
    counts.update({"selected": len(papers), "with_pdf": sum(1 for p in papers.values() if p.get("pdf")),
                   "fragments": len(list(run.frag.glob("paper_*.json"))),
                   "reviews": len(list(run.reviews.glob("paper_*.json"))),
                   "remaining": sum(1 for pid, p in papers.items() if p.get("pdf") and pid not in final)})
    def papers_n(n):
        return f"{n} paper" + ("" if n == 1 else "s")
    if lists["needs_fix"]:
        nxt = f"next_batch.py --role fix ({papers_n(len(lists['needs_fix']))})"
    elif lists["to_review"]:
        nxt = f"next_batch.py --role review ({papers_n(len(lists['to_review']))}; papers handed out in the last 2 h are skipped)"
    elif lists["to_extract"] or lists["invalid"]:
        nxt = f"next_batch.py --role extract ({papers_n(len(lists['to_extract']) + len(lists['invalid']))})"
    else:
        nxt = "all papers settled: merge_graph.py"
    upd = {"counts": counts, "next": nxt}
    if a.apply:
        upd["papers"] = pstate
    if st.get("phase") in (None, "prepared", "extraction") and counts["remaining"] == 0 and counts["with_pdf"]:
        upd["phase"] = "merge"
    run.update_state(**upd)
    print(json.dumps({"applied": a.apply, "settled_now": len(settle), "table": dict(table), "counts": counts,
                      "next": nxt, **{k: v[:20] for k, v in lists.items() if v}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
