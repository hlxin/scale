#!/bin/sh
# Starts the SCALE web service (serve) or its inbox runner (runner) with the settings in $SCALE_WEB_ENV, from this
# checkout (service/README.md, "The inbox"). launchd starts both (scale-web.plist, scale-inbox.plist); by hand:
#   service/launchd/scale-web.sh serve      the service, on 127.0.0.1:$SCALE_WEB_PORT (8080)
#   service/launchd/scale-web.sh runner     curate what the inbox's queue holds, then exit
set -eu
: "${SCALE_WEB_ENV:=$HOME/scale-web/scale-web.env}"
set -a
. "$SCALE_WEB_ENV"
set +a
cd "$(dirname "$0")/../.."                          # the checkout: the schema, the skills and the tools
PY="${SCALE_WEB_PYTHON:-python3}"
PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"        # where `claude` is usually installed
PYTHONPATH="$PWD/service${PYTHONPATH:+:$PYTHONPATH}"
if ! PYTHONPATH="$PYTHONPATH" "$PY" -c "import scale" 2>/dev/null; then
  # scale-catal is not installed in this Python: run this checkout's tools/ as the package
  shim="$(dirname "$SCALE_WEB_ENV")/pyshim"
  mkdir -p "$shim" && ln -sfn "$PWD/tools" "$shim/scale"
  PYTHONPATH="$shim:$PYTHONPATH"
fi
export PATH PYTHONPATH SCALE_NO_UPDATE_CHECK=1
case "${1:-}" in
  serve)  exec "$PY" -m scaleweb --host 127.0.0.1 --port "${SCALE_WEB_PORT:-8080}" ;;
  runner) exec "$PY" -m scaleweb.runner ;;
  *)      echo "usage: $0 serve|runner" >&2; exit 2 ;;
esac
