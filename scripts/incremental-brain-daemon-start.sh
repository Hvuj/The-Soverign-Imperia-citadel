#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
mkdir -p .claude/state
if [ -f .claude/state/incremental-brain-daemon.pid ]; then
  PID="$(cat .claude/state/incremental-brain-daemon.pid || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then echo "incremental brain daemon already running pid=$PID"; exit 0; fi
fi
rm -f .claude/state/incremental-brain-daemon.stop
PYTHON="${PWD}/.venv/bin/python"; [ ! -x "$PYTHON" ] && PYTHON="python3"
nohup "$PYTHON" tools/incremental_brain_daemon.py --watch >> .claude/state/incremental-brain-daemon.out.log 2>> .claude/state/incremental-brain-daemon.err.log &
PID=$!; echo "$PID" > .claude/state/incremental-brain-daemon.pid; sleep 0.4
kill -0 "$PID" 2>/dev/null || { echo "failed to start mandatory incremental brain daemon" >&2; exit 1; }
echo "started incremental brain daemon pid=$PID"
