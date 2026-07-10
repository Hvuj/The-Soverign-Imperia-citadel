#!/usr/bin/env bash
# auto-pattern-capture.sh — Stop hook: auto-capture feature patterns after successful code-change tasks that passed the audit gate.
set -euo pipefail

INPUT="$(cat)"

if printf '%s' "$INPUT" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then exit 0; fi

PYTHON="${CLAUDE_PROJECT_DIR}/.venv/bin/python"
[ ! -x "$PYTHON" ] && PYTHON="python3"

TASK_JSON="${CLAUDE_PROJECT_DIR}/.claude/state/current-task.json"
if [ ! -f "$TASK_JSON" ]; then exit 0; fi

FAST_PATH="$(python3 -c "
import json, sys
try:
    d = json.load(open('$TASK_JSON'))
    labels = d.get('labels', [])
    print('yes' if 'code-change' in labels or 'data-heavy' in labels else 'no')
except Exception:
    print('no')
" 2>/dev/null || echo "no")"

if [ "$FAST_PATH" != "yes" ]; then exit 0; fi

if ! git -C "$CLAUDE_PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then exit 0; fi

CHANGED="$(git -C "$CLAUDE_PROJECT_DIR" diff --name-only 2>/dev/null | head -1 || true)"
if [ -z "$CHANGED" ]; then exit 0; fi

TASK_TYPE="$(python3 -c "
import json
try:
    d = json.load(open('$TASK_JSON'))
    print(d.get('intent', 'change'))
except Exception:
    print('change')
" 2>/dev/null || echo "change")"

FIRST_FILE="$(git -C "$CLAUDE_PROJECT_DIR" diff --name-only 2>/dev/null | head -1 | sed 's/\//-/g' | sed 's/\.py//' | sed 's/\//-/g' || true)"
TITLE="${TASK_TYPE}-${FIRST_FILE}"
DATE="$(date +%Y-%m-%d)"

cd "$CLAUDE_PROJECT_DIR"
"$PYTHON" tools/learn_feature_pattern.py \
    --title "${TITLE}-${DATE}" \
    --domain "auto-captured" \
    --task-type "$TASK_TYPE" \
    --notes "Auto-captured by Stop hook from ${FIRST_FILE}" \
    2>/dev/null || true

"$PYTHON" tools/feature_replicator.py capture \
    --id "${TITLE}-${DATE}" \
    --desc "Auto-captured template: ${TASK_TYPE} touching ${FIRST_FILE}" \
    --placeholders "" \
    --validate "true" \
    2>/dev/null || true

exit 0
