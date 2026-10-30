#!/bin/sh
# Installs (or with --uninstall removes) the two launchd agents of a SCALE service on a Mac: the service, always on,
# and the inbox runner, started whenever the inbox's queue holds something (service/README.md, "The inbox").
#   service/launchd/install.sh [settings file]       default ~/scale-web/scale-web.env
#   service/launchd/install.sh --uninstall
# The checkout, the settings file and the inbox must lie outside Desktop, Documents and Downloads, which macOS keeps
# from agents started by launchd.
set -eu
AGENTS="$HOME/Library/LaunchAgents"
if [ "${1:-}" = "--uninstall" ]; then
  for label in scale-catal.web scale-catal.inbox; do
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    rm -f "$AGENTS/$label.plist"
  done
  echo "removed the SCALE launchd agents"
  exit 0
fi
ENV_FILE="$(cd "$(dirname "${1:-$HOME/scale-web/scale-web.env}")" && pwd)/$(basename "${1:-scale-web.env}")"
CHECKOUT="$(cd "$(dirname "$0")/../.." && pwd)"
[ -f "$ENV_FILE" ] || { echo "no settings file at $ENV_FILE (service/README.md lists the settings)" >&2; exit 1; }
INBOX="$(set -a; . "$ENV_FILE"; printf %s "${SCALE_WEB_INBOX:-}")"
[ -n "$INBOX" ] || { echo "SCALE_WEB_INBOX is not set in $ENV_FILE" >&2; exit 1; }
case "$CHECKOUT$ENV_FILE$INBOX" in
  *"$HOME/Desktop"*|*"$HOME/Documents"*|*"$HOME/Downloads"*)
    echo "move the checkout, the settings and the inbox out of Desktop, Documents and Downloads first" >&2; exit 1 ;;
esac
LOGS="$(dirname "$ENV_FILE")"
mkdir -p "$INBOX/queue" "$AGENTS"
chmod 600 "$ENV_FILE"
for name in scale-web scale-inbox; do
  label=$([ "$name" = scale-web ] && echo scale-catal.web || echo scale-catal.inbox)
  sed -e "s#@CHECKOUT@#$CHECKOUT#g" -e "s#@ENV@#$ENV_FILE#g" -e "s#@INBOX@#$INBOX#g" -e "s#@LOGS@#$LOGS#g" \
    "$CHECKOUT/service/launchd/$name.plist" > "$AGENTS/$label.plist"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$label.plist"
  echo "loaded $label ($AGENTS/$label.plist)"
done
echo "logs: $LOGS/service.log and $LOGS/runner.log; the queue: $INBOX/queue"
