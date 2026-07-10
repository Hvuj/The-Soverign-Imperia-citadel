#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PID_FILE=".claude/state/citadel-ui-server.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "citadel ui server not running (no pid file)"
  exit 0
fi

PID="$(cat "$PID_FILE" || true)"
if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "stopped citadel ui server pid=$PID"
else
  echo "citadel ui server was not running"
fi
rm -f "$PID_FILE"
