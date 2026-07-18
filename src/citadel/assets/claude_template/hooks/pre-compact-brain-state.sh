#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -euo pipefail
mkdir -p "$CLAUDE_PROJECT_DIR/.claude/state"; cp "$CLAUDE_PROJECT_DIR/.claude/state/next-context.json" "$CLAUDE_PROJECT_DIR/.claude/state/pre-compact-next-context.json" 2>/dev/null || true; printf "{}\n"
