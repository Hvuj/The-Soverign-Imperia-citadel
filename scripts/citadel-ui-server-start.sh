#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PYTHON="${PWD}/.venv/bin/python"; [ ! -x "$PYTHON" ] && PYTHON="python3"
PORT="${CITADEL_UI_PORT:-8765}"
PID_FILE=".claude/state/citadel-ui-server.pid"
OUT_LOG=".claude/state/citadel-ui-server.out.log"
ERR_LOG=".claude/state/citadel-ui-server.err.log"

mkdir -p .claude/state

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    echo "citadel ui server already running pid=$PID url=http://localhost:${PORT}/brain/graph.html"
    exit 0
  fi
fi

nohup "$PYTHON" tools/citadel_ui_server.py >> "$OUT_LOG" 2>> "$ERR_LOG" &
PID=$!
echo "$PID" > "$PID_FILE"
sleep 0.4

if ! kill -0 "$PID" 2>/dev/null; then
  echo "failed to start citadel ui server" >&2
  rm -f "$PID_FILE"
  exit 1
fi

echo "started citadel ui server pid=$PID url=http://localhost:${PORT}/brain/graph.html"
