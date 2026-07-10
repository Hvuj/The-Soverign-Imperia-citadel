#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PYTHON="${PWD}/.venv/bin/python"; [ ! -x "$PYTHON" ] && PYTHON="python3"
"$PYTHON" tools/incremental_brain_daemon.py --stop
if [ -f .claude/state/incremental-brain-daemon.pid ]; then PID="$(cat .claude/state/incremental-brain-daemon.pid || true)"; [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null && kill "$PID" || true; rm -f .claude/state/incremental-brain-daemon.pid; fi
echo "stopped incremental brain daemon"
