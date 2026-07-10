#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PYTHON="${PWD}/.venv/bin/python"; [ ! -x "$PYTHON" ] && PYTHON="python3"
exec "$PYTHON" tools/workspace_intelligence_lint.py "$@"
