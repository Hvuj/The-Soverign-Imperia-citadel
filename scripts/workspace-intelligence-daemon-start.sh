#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PYTHON="${PWD}/.venv/bin/python"; [ ! -x "$PYTHON" ] && PYTHON="python3"
PID_FILE=".claude/state/workspace-intelligence/daemon.pid"
LOG_FILE=".claude/state/workspace-intelligence/daemon.log"
OUT_LOG=".claude/state/workspace-intelligence/daemon.out.log"
ERR_LOG=".claude/state/workspace-intelligence/daemon.err.log"

mkdir -p "$(dirname "$PID_FILE")"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo "workspace-intelligence-daemon: already running (pid=$PID)"
    exit 0
  fi
fi

"$PYTHON" tools/workspace_intelligence_daemon.py --quiet \
  >"$OUT_LOG" 2>"$ERR_LOG" &
DAEMON_PID=$!
echo "$DAEMON_PID" > "$PID_FILE"
echo "workspace-intelligence-daemon: started (pid=$DAEMON_PID)"
