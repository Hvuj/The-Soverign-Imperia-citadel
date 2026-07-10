#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PID_FILE=".claude/state/workspace-intelligence/daemon.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "workspace-intelligence-daemon: not running (no pid file)"
  exit 0
fi

PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
if [ -z "$PID" ]; then
  echo "workspace-intelligence-daemon: not running (empty pid file)"
  exit 0
fi

if kill -0 "$PID" 2>/dev/null; then
  echo "workspace-intelligence-daemon: running (pid=$PID)"
else
  echo "workspace-intelligence-daemon: not running (pid=$PID stale)"
fi
