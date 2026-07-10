#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PID_FILE=".claude/state/workspace-intelligence/daemon.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "workspace-intelligence-daemon: not running"
  exit 0
fi

PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
if [ -z "$PID" ]; then
  echo "workspace-intelligence-daemon: pid file empty"
  rm -f "$PID_FILE"
  exit 0
fi

if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "workspace-intelligence-daemon: sent SIGTERM to pid=$PID"
  for i in 1 2 3 4 5; do
    sleep 1
    if ! kill -0 "$PID" 2>/dev/null; then
      echo "workspace-intelligence-daemon: stopped"
      break
    fi
  done
  if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" 2>/dev/null || true
    echo "workspace-intelligence-daemon: force-killed"
  fi
else
  echo "workspace-intelligence-daemon: not running (stale pid=$PID)"
fi
rm -f "$PID_FILE"
