#!/usr/bin/env bash
set -euo pipefail

input="$(cat || true)"
cmd="$(printf '%s' "$input" | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get("tool_input",{}).get("command",""))
except Exception:
    print("")')"

if printf '%s' "$cmd" | grep -Eq '(^|[ ;|])(cat |pytest -vv|find \.|grep -R|rg .*)'; then
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "message": "Token warning: command may produce large output. Prefer targeted paths or tools/summarize_* helpers."
  }
}
JSON
else
  echo "{}"
fi
