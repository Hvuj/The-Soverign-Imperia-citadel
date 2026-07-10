#!/usr/bin/env bash
set -euo pipefail
python "$CLAUDE_PROJECT_DIR/tools/brain_preflight.py" --bootstrap --hook-output
