#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PYTHON="${PWD}/.venv/bin/python"; [ ! -x "$PYTHON" ] && PYTHON="python3"
PID_FILE=".claude/state/outcome-miner-daemon.pid"
STOP_FILE=".claude/state/outcome-miner-daemon.stop"
rm -f "$STOP_FILE"
if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE")"
    if kill -0 "$PID" 2>/dev/null; then
        echo "outcome miner daemon already running (pid=$PID)"; exit 0
    fi
    rm -f "$PID_FILE"
fi
nohup "$PYTHON" tools/outcome_miner_daemon.py --watch \
    > .claude/state/outcome-miner-daemon-stdout.log 2>&1 &
echo "outcome miner daemon started (pid=$!)"
