#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -euo pipefail
python "$CLAUDE_PROJECT_DIR/tools/brain_agent_context.py" --hook-output
