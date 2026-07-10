#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
touch .claude/state/outcome-miner-daemon.stop
echo "outcome miner daemon stop signal sent"
