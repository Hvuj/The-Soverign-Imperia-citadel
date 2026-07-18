#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
# post-tool-batch-session-snapshot.sh — persist a durable mid-session context snapshot.
set -uo pipefail
PYTHON="${CLAUDE_PROJECT_DIR}/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"
"$PYTHON" "${CLAUDE_PROJECT_DIR}/tools/session_snapshotter.py" 2>/dev/null || echo '{}'
