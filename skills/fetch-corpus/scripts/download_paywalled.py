"""Step 7b — download queued sources (and their SI) through the institution's EZproxy, slowly and safely.

Works the queue of every topic: sources marked "Queued for EZproxy" by download_open.py, most relevant and most cited
first, round-robin over publishers. Every visit is granted by the global limiter (_ezlimit.py): >= 90 s (+ jitter)
between two visits to the same publisher, <= 120 visits per publisher per day, global caps (15 s gap, 20 / 15 min,
60 / hour, 600 / day, MB caps), and only ONE EZproxy process at a time. A login page pauses everything (never logs
in), a usage-limit page or blocks from 2 publishers in a day stop everything until a human clears it.

Runs for days. Start it in the background with the keep-alive wrapper:
  nohup zsh .../scripts/run_paywalled.sh <project> > /dev/null 2>&1 &
or directly (foreground, e.g. to test a few sources):
  python3 -I download_paywalled.py [--topic <slug>] [--max-sources 3] [--exit-when-empty] [--no-si]
                                   [--access OA,OA+ND] [--skip-publishers iop] [--dry-run]
--access keeps only sources of those access types (and their SI): OA,OA+ND = open licences only (CC BY, CC BY-NC,
CC BY-ND, CC BY-NC-ND ...), the rest stays queued. --dry-run prints the queue per publisher and contacts nothing.
Requires ~/.scale/sources/ezproxy/config.json written by check_paywalled_access.py (enabled + verified).
"""
import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _core  # noqa: F401,E402  (index-sources' scripts: the shared core)
import _ezlimit as EZL
import _ezproxy as EZ
from _common import (ACCESS_TYPES, Project, add_project_arg, json_read, jsonl_append, jsonl_iter, log, now_iso,
                     user_agent, set_contact)
from _download import clone_or_copy, ez_publisher
from _corpus import add_corpus_arg, scope
from _ledger import Ledger
from _vectors import after_step

FINAL_FAIL = {"wrong_paper", "invalid_pdf", "no_pdf", "not_subscribed", "too_large", "no_pdf_link"}
NOTE = {"not_subscribed": "EZproxy: not covered by the institution's subscription",
        "no_pdf": "EZproxy: no PDF on the publisher page", "wrong_paper": "EZproxy: publisher returned a different PDF",
        "invalid_pdf": "EZproxy: broken PDF", "too_large": "EZproxy: file larger than the size cap",
        "no_pdf_link": "EZproxy: no PDF link on the publisher page"}


def queues(proj, led, topic, with_si, tries, skip=frozenset(), ids=None, access=frozenset()):
    """{publisher: [(priority, kind, source)]} — PDFs first, then SI. Publishers in `skip` are never contacted; with
    `access`, only sources of those access types (and their SI) are queued."""
    where = "WHERE p.downloaded = 0 AND p.dl_status = 'queued_paywalled'"
    args = ()
    if topic:
        where += " AND p.id IN (SELECT source_id FROM source_topics WHERE topic = ?)"
        args = (topic,)
    only = f" AND p.access_type IN ({','.join('?' * len(access))})" if access else ""
    q = defaultdict(list)
    for r in led.q(f"SELECT p.* FROM sources p {where}{only}", args + tuple(sorted(access))):
        p = led.row(r)
        pub = ez_publisher(p.get("doi"))
        if ids is not None and p["id"] not in ids:
            continue
        if not pub or pub in skip or tries.get(p["id"], 0) >= 3:
            continue
        ts = led.topics_of(p["id"])
        rel = max([t["relevance"] for t in ts if t.get("relevance") is not None] or [3])
        q[pub].append(((-rel, -(p.get("cited_by") or 0)), "pdf", p))
    if with_si:
        for r in led.q(f"SELECT p.* FROM sources p WHERE p.downloaded = 1 AND p.si_status = 'queued_paywalled'{only}",
                       tuple(sorted(access))):
            p = led.row(r)
            pub = ez_publisher(p.get("doi"))
            if ids is not None and p["id"] not in ids:
                continue
            if pub and pub not in skip and tries.get(("si", p["id"]), 0) < 2:
                q[pub].append(((9, 0), "si", p))
    for pub in q:
        q[pub].sort(key=lambda t: t[0])
    return q


NET_ERRORS = ("network_error", "ez_server_error")
OUTAGE_RUN = 3          # this many network or proxy errors in a row: an outage, not the sources' fault


def retry_counts(proj):
    """Failed tries so far per source (and per source's SI), from the outcomes log. Network or proxy errors in a run
    of OUTAGE_RUN or more in a row were an outage (the computer offline, DNS down, the proxy down): they do not
    count."""
    rows = list(jsonl_iter(proj.ez / "outcomes.jsonl"))
    outage, i = set(), 0
    while i < len(rows):
        j = i
        while j < len(rows) and rows[j].get("outcome") in NET_ERRORS:
            j += 1
        if j - i >= OUTAGE_RUN:
            outage.update(range(i, j))
        i = max(j, i + 1)
    tries = Counter()
    for k, r in enumerate(rows):
        if r.get("outcome") in EZ.RETRYABLE and k not in outage:
            tries[(r.get("kind") == "si" and ("si", r["id"])) or r["id"]] += 1
    return tries


class Outage:
    """The run of network or proxy errors in progress. OUTAGE_RUN in a row are an outage: their tries are given back
    and the next visit waits 15 min, then 30, then an hour each time while it lasts; any other outcome ends it."""

    def __init__(self):
        self.keys, self.pauses = [], 0

    def note(self, outcome, key, tries):
        """After a visit (its try already counted in `tries`): the seconds to wait before the next one, 0 for none."""
        if outcome not in NET_ERRORS:
            self.keys, self.pauses = [], 0
            return 0
        self.keys.append(key)
        if len(self.keys) < OUTAGE_RUN:
            return 0
        for k in self.keys:
            tries[k] -= 1
        pause = min(3600, 900 * 2 ** self.pauses)
        self.keys, self.pauses = [], self.pauses + 1
        return pause


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    add_corpus_arg(ap)                    # neither: the queue of every topic
    ap.add_argument("--max-sources", "--max-papers", dest="max_sources", type=int, default=None, help="stop after N sources (testing)")
    ap.add_argument("--exit-when-empty", action="store_true")
    ap.add_argument("--no-si", action="store_true")
    ap.add_argument("--skip-publishers", default="",
                    help="comma list of publisher keys never contacted, PDFs and SI (e.g. sage,annualreviews: they ask for "
                         "a login through the proxy; iop after a block page)")
    ap.add_argument("--access", default="",
                    help="comma list of access types to fetch, e.g. OA,OA+ND (open licences only); default: every queued source")
    ap.add_argument("--dry-run", action="store_true", help="print the queue per publisher and stop, contacting nothing")
    a = ap.parse_args()
    access = frozenset(x.strip() for x in a.access.split(",") if x.strip())
    if access - set(ACCESS_TYPES):
        print(json.dumps({"error": f"unknown access type(s) {sorted(access - set(ACCESS_TYPES))}; known: {ACCESS_TYPES}"}))
        return 2
    skip = frozenset(x.strip().lower() for x in a.skip_publishers.split(",") if x.strip())
    proj = Project(a.project)
    a.topic, ids = scope(a)
    if a.dry_run:
        q = queues(proj, Ledger(proj), a.topic, not a.no_si, retry_counts(proj), skip, ids, access)
        n = Counter(kind for v in q.values() for _, kind, _ in v)
        print(json.dumps({"queue": {p: len(v) for p, v in sorted(q.items()) if v}, "pdfs": n["pdf"], "si": n["si"],
                          "access": sorted(access) or "all", "skipped_publishers": sorted(skip)}))
        return 0
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
    from _download import extract_si_links
    from fetch_si import ext_of
    led = Ledger(proj)
    sess = requests.Session()
    sess.headers.update({"User-Agent": user_agent()})
    done_log = proj.ez / "outcomes.jsonl"
    tries = retry_counts(proj)
    q = queues(proj, led, a.topic, not a.no_si, tries, skip, ids, access)
    reloaded = time.time()
    log(f"EZproxy via {host}: queue " + ", ".join(f"{p}={len(v)}" for p, v in sorted(q.items())) + f" | limits={EZL.LIMITS}"
        + (f" | skipped publishers: {','.join(sorted(skip))}" if skip else "")
        + (f" | access: {','.join(sorted(access))}" if access else ""))
    unsupported, rr_order, handled, since_export = set(), [], 0, 0
    outage = Outage()                     # an outage costs no source a try, and visits wait for it to end
    try:
        while True:
            if time.time() - reloaded > 1800:
                q = queues(proj, led, a.topic, not a.no_si, tries, skip, ids, access)
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
                outcome = EZ.fetch_source(proj, led, sess, lim, host, p, chosen)
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
            elif outcome in NET_ERRORS:
                tries[p["id"] if kind == "pdf" else ("si", p["id"])] += 1
                q[chosen].append((prio, kind, p))
            pause = outage.note(outcome, p["id"] if kind == "pdf" else ("si", p["id"]), tries)
            if pause:
                log(f"{OUTAGE_RUN} network or proxy errors in a row: the network or the proxy is down — pausing "
                    f"{pause // 60} min (no source loses a try)")
                time.sleep(pause)
            handled += 1
            since_export += 1
            if since_export >= 10:
                led.export_progress()
                since_export = 0
            if a.max_sources and handled >= a.max_sources:
                break
    except EZL.HardStop as e:
        log(f"EZproxy stopped: {e}")
    led.export()
    print(json.dumps({"handled": handled, "hard_stop": lim.hard_stopped(), "vector_store": after_step(proj, led),
                      "finished_at": now_iso()}))


if __name__ == "__main__":
    sys.exit(main() or 0)
