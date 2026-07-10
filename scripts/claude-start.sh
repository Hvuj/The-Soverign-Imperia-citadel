#!/usr/bin/env bash
# DEPRECATED — this script is superseded by the packaged `citadel up` command.
set -euo pipefail
echo "[warn] claude-start.sh is deprecated — use: citadel up" >&2
echo "" >&2
exec citadel up "$@"
