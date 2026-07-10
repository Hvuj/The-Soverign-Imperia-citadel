#!/usr/bin/env bash
set -euo pipefail

if [ -z "${CLAUDE_PROJECT_DIR:-}" ]; then
  cat >/dev/null || true
  echo "{}"
  exit 0
fi

python "$CLAUDE_PROJECT_DIR/tools/dir_brain_hook.py"
