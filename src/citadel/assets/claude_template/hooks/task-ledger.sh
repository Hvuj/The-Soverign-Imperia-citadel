#!/usr/bin/env bash
set -euo pipefail
event="${1:-unknown}"
python "$CLAUDE_PROJECT_DIR/tools/task_ledger.py" "$event"
