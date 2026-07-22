#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -euo pipefail
INPUT="$(cat)"; PROMPT="$(python -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("prompt") or d.get("user_prompt") or d.get("message") or "")' <<< "$INPUT")"; [ -z "$PROMPT" ] && PROMPT="bootstrap"; python "$CLAUDE_PROJECT_DIR/tools/brain_context_builder.py" "$PROMPT" --mode prompt --hook-output --hook-event UserPromptSubmit
