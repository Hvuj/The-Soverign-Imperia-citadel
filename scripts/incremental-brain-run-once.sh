#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
echo "debug only: normal workflow uses mandatory incremental daemon automatically" >&2
PYTHON="${PWD}/.venv/bin/python"; [ ! -x "$PYTHON" ] && PYTHON="python3"
"$PYTHON" tools/incremental_brain_daemon.py --once
