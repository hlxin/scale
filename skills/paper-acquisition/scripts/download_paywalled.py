"""Step 7b — download queued papers (and their SI) through the institution's EZproxy, slowly and safely.

Works the queue of every topic: papers marked "Queued for EZproxy" by download_open.py, most relevant and most cited
first, round-robin over publishers. Every visit is granted by the global limiter (_ezlimit.py): >= 90 s (+ jitter)
between two visits to the same publisher, <= 120 visits per publisher per day, global caps (15 s gap, 20 / 15 min,
60 / hour, 600 / day, MB caps), and only ONE EZproxy process at a time. A login page pauses everything (never logs
in), a usage-limit page or blocks from 2 publishers in a day stop everything until a human clears it.

Runs for days. Start it in the background with the keep-alive wrapper:
  nohup zsh .../scripts/run_paywalled.sh <project> > /dev/null 2>&1 &
or directly (foreground, e.g. to test a few papers):
  python3 -I download_paywalled.py [--topic <slug>] [--max-papers 3] [--exit-when-empty] [--no-si]
Requires ~/.paper-acquisition/ezproxy/config.json written by check_paywalled_access.py (enabled + verified).
"""
import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ezlimit as EZL
import _ezproxy as EZ
from _common import Project, add_project_arg, json_read, jsonl_append, jsonl_iter, log, now_iso, user_agent, set_contact
from _download import clone_or_copy, ez_publisher
from _ledger import Ledger

FINAL_FAIL = {"wrong_paper", "invalid_pdf", "no_pdf", "not_subscribed", "too_large", "no_pdf_link"}
NOTE = {"not_subscribed": "EZproxy: not covered by the institution's subscription",
        "no_pdf": "EZproxy: no PDF on the publisher page", "wrong_paper": "EZproxy: publisher returned a different PDF",
        "invalid_pdf": "EZproxy: broken PDF", "too_large": "EZproxy: file larger than the size cap",
        "no_pdf_link": "EZproxy: no PDF link on the publisher page"}


def queues(proj, led, topic, with_si, tries):
    """{publisher: [(priority, kind, paper)]} — PDFs first, then SI."""
    where = "WHERE p.downloaded = 0 AND p.dl_status = 'queued_paywalled'"
    args = ()
    if topic:
        where += " AND p.id IN (SELECT paper_id FROM paper_topics WHERE topic = ?)"
        args = (topic,)
    q = defaultdict(list)
    for r in led.q(f"SELECT p.* FROM papers p {where}", args):
        p = led.row(r)
        pub = ez_publisher(p.get("doi"))
        if not pub or tries.get(p["id"], 0) >= 3:
            continue
        ts = led.topics_of(p["id"])
        rel = max([t["relevance"] for t in ts if t.get("relevance") is not None] or [3])
        q[pub].append(((-rel, -(p.get("cited_by") or 0)), "pdf", p))
    if with_si:
        for r in led.q("SELECT p.* FROM papers p WHERE p.downloaded = 1 AND p.si_status = 'queued_paywalled'"):
            p = led.row(r)
            pub = ez_publisher(p.get("doi"))
            if pub and tries.get(("si", p["id"]), 0) < 2:
                q[pub].append(((9, 0), "si", p))
    for pub in q:
        q[pub].sort(key=lambda t: t[0])
    return q


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", default=None, help="only this topic's queue (default: every topic)")
    ap.add_argument("--max-papers", type=int, default=None, help="stop after N papers (testing)")
    ap.add_argument("--exit-when-empty", action="store_true")
    ap.add_argument("--no-si", action="store_true")
    a = ap.parse_args()
    proj = Project(a.project)
    proj.ezg.mkdir(parents=True, exist_ok=True)
    ez = json_read(proj.ezg / "config.json", {}) or {}
    if not (ez.get("enabled") and ez.get("host") and ez.get("verified_at")):
        print(json.dumps({"error": "paywalled access not set up — run check_paywalled_access.py first"}))
        return 3
    set_contact(ez.get("polite_email"))
    host = ez["host"]
    proj.ez.mkdir(parents=True, exist_ok=True)
    try:
        lim = EZL.Limiter(proj.ezg / "limiter_state.json", log=log)
    except EZL.Busy as e:
        print(json.dumps({"error": str(e)}))
        return 4
    if lim.hard_stopped():
        print(json.dumps({"error": "HARD STOP in effect", "detail": lim.hard_stopped(),
                          "next": "review .scripts/logs/ezproxy_evidence/, then: python3 -I _ezlimit.py clear-hard-stop"}))
        return 5
    from fetch_si import extract_si_links, ext_of
    led = Ledger(proj)
    sess = requests.Session()
    sess.headers.update({"User-Agent": user_agent()})
    done_log = proj.ez / "outcomes.jsonl"
    tries = Counter()
    for r in jsonl_iter(done_log):
        if r.get("outcome") in EZ.RETRYABLE:
            tries[(r.get("kind") == "si" and ("si", r["id"])) or r["id"]] += 1
    q = queues(proj, led, a.topic, not a.no_si, tries)
    reloaded = time.time()
    log(f"EZproxy via {host}: queue " + ", ".join(f"{p}={len(v)}" for p, v in sorted(q.items())) + f" | limits={EZL.LIMITS}")
    unsupported, rr_order, handled, since_export = set(), [], 0, 0
    try:
        while True:
            if time.time() - reloaded > 1800:
                q = queues(proj, led, a.topic, not a.no_si, tries)
                for p in unsupported:
                    q.pop(p, None)
                reloaded = time.time()
                log("queue reloaded: " + ", ".join(f"{p}={len(v)}" for p, v in sorted(q.items())))
            pubs = [p for p in q if q[p]]
            if not pubs:
                led.export(db=False)
                if a.exit_when_empty:
                    break
                time.sleep(1800)
                reloaded = 0
                continue
            rr_order = [p for p in rr_order if p in pubs] + [p for p in sorted(pubs) if p not in rr_order]
            chosen, soonest = None, None
            for p in rr_order:
                ok, wait, why = lim.check(p)
                if ok:
                    chosen = p
                    break
                if wait is not None:
                    soonest = wait if soonest is None else min(soonest, wait)
            if chosen is None:
                if soonest is None and a.exit_when_empty:
                    log("every publisher reached today's cap")
                    break
                time.sleep(min(max(soonest if soonest is not None else 900, 2), 900))
                continue
            rr_order.remove(chosen)
            rr_order.append(chosen)
            ok, _, _ = lim.acquire(chosen)
            if not ok:
                continue
            prio, kind, p = q[chosen].pop(0)
            if kind == "pdf":
                outcome = EZ.fetch_paper(proj, led, sess, lim, host, p, chosen)
                nfiles = None
            else:
                outcome, nfiles = EZ.fetch_si(proj, led, sess, lim, host, p, chosen, extract_si_links, ext_of, clone_or_copy)
            jsonl_append(done_log, {"kind": kind, "id": p["id"], "doi": p.get("doi"), "publisher": chosen,
                                    "outcome": outcome, "files": nfiles, "ts": now_iso()})
            if outcome in ("valid_pdf", "si_downloaded", "duplicate", "wrong_paper", "no_pdf", "not_subscribed",
                           "si_not_found", "invalid_pdf"):
                lim.login_ok()
            if kind == "pdf" and outcome in FINAL_FAIL:
                led.set(p["id"], dl_status="failed", dl_note=NOTE.get(outcome, f"EZproxy: {outcome}"))
            if kind == "si" and outcome == "si_not_found":
                led.set(p["id"], si_status="not_found")
            if outcome == "blocked":
                tries[p["id"] if kind == "pdf" else ("si", p["id"])] += 1
                q[chosen].append((prio, kind, p))
                lim.block(chosen, f"{kind} {p.get('doi')}")
            elif outcome == "login_prompt":
                q[chosen].insert(0, (prio, kind, p))
                lim.login_prompt(p.get("doi"))
            elif outcome == "usage_limit":
                lim.hard_stop(f"EZproxy usage-limit / suspension page seen while fetching {p.get('doi')}")
            elif outcome == "not_configured":
                unsupported.add(chosen)
                q.pop(chosen, None)
                lim.event("publisher_not_configured_in_ezproxy", publisher=chosen)
                lim.save()
                log(f"{chosen} is not configured in this EZproxy — skipping that publisher")
            elif outcome in ("network_error", "ez_server_error"):
                tries[p["id"] if kind == "pdf" else ("si", p["id"])] += 1
                q[chosen].append((prio, kind, p))
            handled += 1
            since_export += 1
            if since_export >= 10:
                led.export_progress()
                since_export = 0
            if a.max_papers and handled >= a.max_papers:
                break
    except EZL.HardStop as e:
        log(f"EZproxy stopped: {e}")
    led.export()
    print(json.dumps({"handled": handled, "hard_stop": lim.hard_stopped(), "finished_at": now_iso()}))


if __name__ == "__main__":
    sys.exit(main() or 0)
