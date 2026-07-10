#!/usr/bin/env bash
# DEPRECATED — this script is superseded by the packaged `citadel up` command.

echo "[warn] claude-start-smart.sh is deprecated — use: citadel up"
echo ""
exec citadel up "$@"
