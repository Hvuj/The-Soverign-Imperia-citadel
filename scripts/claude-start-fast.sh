#!/usr/bin/env bash
# DEPRECATED — this script is superseded by the packaged `citadel up` command.
set -euo pipefail
echo "[warn] claude-start-fast.sh is deprecated — use: CLAUDE_MODEL=sonnet citadel up" >&2
echo "" >&2
export CLAUDE_MODEL="${CLAUDE_MODEL:-sonnet}"
exec citadel up "$@"
