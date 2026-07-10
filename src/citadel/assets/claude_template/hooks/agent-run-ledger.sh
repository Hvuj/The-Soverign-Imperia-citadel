#!/usr/bin/env bash
set -euo pipefail
event="${1:-unknown}"
python "$CLAUDE_PROJECT_DIR/tools/agent_run_ledger.py" "$event"
