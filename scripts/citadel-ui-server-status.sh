#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PORT="${CITADEL_UI_PORT:-8765}"
PID_FILE=".claude/state/citadel-ui-server.pid"

RUNNING="no"
PID_VAL="–"

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    RUNNING="yes"
    PID_VAL="$PID"
  fi
fi

echo "running:        $RUNNING"
echo "pid:            $PID_VAL"
echo "url:            http://localhost:${PORT}/brain/graph.html"
echo "port:           $PORT"
echo "root directory: docs"
