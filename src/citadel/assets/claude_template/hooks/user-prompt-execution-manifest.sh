#!/usr/bin/env bash
set -euo pipefail
INPUT="$(cat)"
PROMPT="$(python -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("prompt") or d.get("user_prompt") or d.get("message") or "")' <<< "$INPUT")"
[ -z "$PROMPT" ] && PROMPT="bootstrap"
python "$CLAUDE_PROJECT_DIR/tools/build_execution_manifest.py" "$PROMPT" --hook-output --hook-event UserPromptSubmit
