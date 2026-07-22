#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -euo pipefail

if [ -z "${CLAUDE_PROJECT_DIR:-}" ]; then
  cat >/dev/null || true
  echo "{}"
  exit 0
fi

python "$CLAUDE_PROJECT_DIR/tools/dir_brain_hook.py"
