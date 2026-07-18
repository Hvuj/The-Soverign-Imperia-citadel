#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -euo pipefail
event="${1:-unknown}"
python "$CLAUDE_PROJECT_DIR/tools/agent_run_ledger.py" "$event"
