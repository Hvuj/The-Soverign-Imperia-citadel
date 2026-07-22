#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -euo pipefail
python "$CLAUDE_PROJECT_DIR/tools/build_brain_search_index.py" --quiet >/dev/null 2>&1 || true; printf "{}\n"
