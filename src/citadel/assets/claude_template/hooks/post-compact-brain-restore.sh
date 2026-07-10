#!/usr/bin/env bash
set -euo pipefail
if [ -f "$CLAUDE_PROJECT_DIR/.claude/state/pre-compact-next-context.json" ]; then python "$CLAUDE_PROJECT_DIR/tools/brain_context_builder.py" "post compact restore" --mode bootstrap --hook-output --hook-event PostCompact; else printf "{}\n"; fi
