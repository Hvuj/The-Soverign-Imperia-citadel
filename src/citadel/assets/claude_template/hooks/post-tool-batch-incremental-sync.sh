#!/usr/bin/env bash
# PostToolBatch incremental sync.
set -euo pipefail

IDX="$CLAUDE_PROJECT_DIR/.claude/state/brain-search/index.json"
NODES="$CLAUDE_PROJECT_DIR/docs/brain/nodes"

need_rebuild=0
if [ ! -f "$IDX" ]; then
  need_rebuild=1
elif [ -d "$NODES" ] && [ -n "$(find "$NODES" -type f -newer "$IDX" -print -quit 2>/dev/null)" ]; then
  need_rebuild=1
fi

if [ "$need_rebuild" = "1" ]; then
  python "$CLAUDE_PROJECT_DIR/tools/build_brain_search_index.py" --quiet >/dev/null 2>&1 || true
  python "$CLAUDE_PROJECT_DIR/tools/brain_context_builder.py" "recent tool batch" --mode prompt --out "$CLAUDE_PROJECT_DIR/.claude/state/next-context.json" >/dev/null 2>&1 || true
fi

python "$CLAUDE_PROJECT_DIR/tools/manifest_status.py" >/dev/null 2>&1 || true
printf "{}\n"
