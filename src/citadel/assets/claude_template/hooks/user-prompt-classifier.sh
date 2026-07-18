#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -euo pipefail
python "${CLAUDE_PROJECT_DIR}/tools/classify_prompt.py"
