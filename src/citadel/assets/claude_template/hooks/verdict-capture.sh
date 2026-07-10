#!/usr/bin/env bash
# Stop hook — ordered BEFORE audit-gate.sh.
set -uo pipefail
INPUT="$(cat 2>/dev/null || true)"
printf '%s' "$INPUT" | python "$CLAUDE_PROJECT_DIR/tools/verdict_ledger.py" 2>/dev/null || echo '{}'
exit 0
