#!/bin/zsh
# Keeps the single EZproxy runner alive for days: restarts after an unexpected crash (max 20 per day), never after a
# HARD STOP (a human must review it: python3 -I <skill>/scripts/_ezlimit.py status).
# usage: nohup zsh run_paywalled.sh <project_dir> [--topic <slug>] > /dev/null 2>&1 &
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="${1:?usage: run_paywalled.sh <project_dir> [args for download_paywalled.py]}"
shift
cd "$PROJ" || exit 1
mkdir -p .scripts/logs .scripts/ezproxy
G="$(python3 -I -c "import sys; sys.path.insert(0, sys.argv[1]); import _core; from _common import GLOBAL_DIR; print(GLOBAL_DIR)" "$HERE")/ezproxy"
L=.scripts/logs/paywalled.log
echo $$ > .scripts/ezproxy/runner.pid
restarts=0; day=$(date +%F)
while true; do
  python3 -I -u "$HERE/download_paywalled.py" --project "$PROJ" "$@" >> $L 2>&1
  rc=$?
  if python3 -I -c "import json,sys; sys.exit(0 if (json.load(open(sys.argv[1])).get('hard_stop')) else 1)" "$G/limiter_state.json" 2>/dev/null; then
    echo "[$(date +%T)] runner: HARD STOP in effect — not restarting" >> $L; exit 0
  fi
  if [[ $rc -eq 3 || $rc -eq 4 ]]; then echo "[$(date +%T)] runner: exit $rc (not set up / already running) — not restarting" >> $L; exit $rc; fi
  [[ $(date +%F) != $day ]] && { day=$(date +%F); restarts=0; }
  restarts=$((restarts+1))
  if (( restarts > 20 )); then echo "[$(date +%T)] runner: >20 restarts today — giving up" >> $L; exit 1; fi
  echo "[$(date +%T)] runner: exited rc=$rc — restarting in 10 min ($restarts today)" >> $L
  sleep 600
done
