#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -euo pipefail
INPUT="$(cat)"
if printf '%s' "$INPUT" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then exit 0; fi

if printf '%s' "$INPUT" | grep -q '"permission_mode"[[:space:]]*:[[:space:]]*"plan"'; then exit 0; fi

SESSION_ID="$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try: print(json.loads(sys.stdin.read() or "{}").get("session_id") or "")
except Exception: print("")' 2>/dev/null || echo "")"
if [ -n "$SESSION_ID" ]; then
  PENDING="$(CLAUDE_SID="$SESSION_ID" python3 - <<'PY' 2>/dev/null || echo 0
import json, os
from pathlib import Path
sid = os.environ.get("CLAUDE_SID", "")
p = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".claude/state/agent-runs.ndjson"
start = stop = 0
try:
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("session_id") != sid:
            continue
        ev = e.get("event", "")
        if ev == "subagent-start":
            start += 1
        elif ev == "subagent-stop":
            stop += 1
except FileNotFoundError:
    pass
print(max(0, start - stop))
PY
)"
  if [ "${PENDING:-0}" -gt 0 ] 2>/dev/null; then exit 0; fi
fi

TIER_DECISION="$CLAUDE_PROJECT_DIR/.claude/state/tier-decision.json"
if [ -f "$TIER_DECISION" ]; then
  TIER_VAL="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("tier",1))' "$TIER_DECISION" 2>/dev/null || echo "1")"
  if [ "$TIER_VAL" = "0" ]; then
    FACTOR="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("deciding_factor","Board veto"))' "$TIER_DECISION" 2>/dev/null || echo "Board veto")"
    RULE="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("precedence_rule_applied","unknown"))' "$TIER_DECISION" 2>/dev/null || echo "unknown")"
    REASON="LEGION Board veto (rule: $RULE): $FACTOR Run mandatory graph-aware workflow. Verdict must be Pass, Pass (dry run), Needs Fix, or Blocked."
    python3 -c "import json,sys; print(json.dumps({'decision':'block','reason':sys.argv[1]}))" "$REASON"
    exit 0
  fi
fi

MANIFEST_STATUS="{}"
MANIFEST_STATUS="$(python "$CLAUDE_PROJECT_DIR/tools/manifest_status.py" --json 2>/dev/null || echo '{}')"

IS_TRIVIAL="$(python -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print("yes" if d.get("trivial") else "no")' <<< "$MANIFEST_STATUS")"
UNMET="$(python -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); u=d.get("unmet_requirements",[]); print("; ".join(u[:5]) if u else "")' <<< "$MANIFEST_STATUS")"

if [ "$IS_TRIVIAL" = "yes" ]; then
  cat <<'JSON'
{"decision":"block","reason":"Automated completion gate. If trivial, reply exactly: Trivial turn; no audit needed. Otherwise run mandatory graph-aware workflow, required specialist agents, validation, efficiency-auditor, and memory update if recommended. Verdict must be Pass, Pass (dry run), Needs Fix, or Blocked."}
JSON
elif [ -z "$UNMET" ]; then
  exit 0
else
  REASON="Automated completion gate. Run mandatory graph-aware workflow. Verdict must be Pass, Pass (dry run), Needs Fix, or Blocked. Unmet manifest requirements: $UNMET"
  python -c "import json,sys; print(json.dumps({'decision':'block','reason':sys.argv[1]}))" "$REASON"
fi
