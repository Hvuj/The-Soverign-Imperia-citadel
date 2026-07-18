#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -euo pipefail
event="${1:-unknown}"
python "$CLAUDE_PROJECT_DIR/tools/task_ledger.py" "$event"
