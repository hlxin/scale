"""Stop hook: keep Claude working while a data-curation run is genuinely mid-pipeline.

Wired in <project>/.claude/settings.json (Stop event). Reads the hook payload from stdin, looks at the run states
.scripts/<topic>/kg/<name>/state.json, and — when a run was active in the last 30 minutes and is not finished — prints
{"decision": "block", "reason": "..."} so Claude dispatches the next batch instead of stopping. A stop is always
allowed when: the payload says stop_hook_active (already continuing), the per-session cap of forced continuations is
reached, the run is waiting for the user (state.awaiting_user is set), or it is a scratch/smoke-test run.

Cheap by design: one glob over .scripts/*/kg/*/state.json, no recursive walk of the project. Exit code 0 always.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[4])
NUDGE_DIR = ROOT / ".claude" / ".nudge_state"
MAX_NUDGES = 20
RECENT_SEC = 30 * 60
FINISHED = {"done", "released", "stopped"}


def payload():
    try:
        data = sys.stdin.read()
        return json.loads(data) if data.strip() else {}
    except Exception:
        return {}


def active_runs():
    now = time.time()
    for sp in sorted((ROOT / ".scripts").glob("*/kg/*/state.json")):
        try:
            if now - sp.stat().st_mtime > RECENT_SEC:
                continue
            st = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if st.get("scratch") or st.get("smoke_test") or st.get("awaiting_user"):
            continue
        if (st.get("phase") or "") in FINISHED:
            continue
        yield sp, st


def main():
    p = payload()
    if p.get("stop_hook_active"):
        return 0
    runs = list(active_runs())
    if not runs:
        return 0
    sid = str(p.get("session_id") or "no-session")
    nf = NUDGE_DIR / f"{sid}.count"
    try:
        n = int(nf.read_text().strip() or 0) if nf.exists() else 0
    except Exception:
        n = 0
    if n >= MAX_NUDGES:
        print(f"[check_resume] forced-continuation cap ({MAX_NUDGES}) reached; stopping is allowed.", file=sys.stderr)
        return 0
    try:
        NUDGE_DIR.mkdir(parents=True, exist_ok=True)
        nf.write_text(str(n + 1))
        for f in NUDGE_DIR.glob("*.count"):
            if time.time() - f.stat().st_mtime > 86400:
                f.unlink()
    except Exception:
        pass
    lines = []
    for sp, st in runs:
        c = st.get("counts") or {}
        lines.append(f"{st.get('topic')}/{st.get('name')}: phase={st.get('phase')}, extracted {c.get('extracted', 0)} of "
                     f"{c.get('with_pdf', '?')} papers" + (f" — next: {st['next']}" if st.get("next") else ""))
    reason = ("A data-curation run is mid-pipeline:\n  " + "\n  ".join(lines) +
              "\nContinue it now (next_batch.py / review_status.py / the next phase) unless a genuine decision needs the "
              "user — then set state.awaiting_user via review_status.py --await-user and ask with AskUserQuestion. "
              f"Forced continuation {n + 1}/{MAX_NUDGES}.")
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
