#!/usr/bin/env bash
# mandatory-auto-lint.sh — Run all mandatory Citadel lint checks.
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PYTHON="${PWD}/.venv/bin/python"; [ ! -x "$PYTHON" ] && PYTHON="python3"

FAILED=0

run_lint() {
    local name="$1"
    shift
    if "$@" > /dev/null 2>&1; then
        echo "  [✓] $name"
    else
        echo "  [✗] $name FAILED"
        FAILED=1
    fi
}

echo "mandatory-auto-lint: running all checks"
run_lint "mandatory_auto_lint"     "$PYTHON" tools/mandatory_auto_lint.py
run_lint "grounding_lint"          "$PYTHON" tools/grounding_lint.py
run_lint "output_schema_lint"      "$PYTHON" tools/output_schema_lint.py
run_lint "prompt_leak_lint"        "$PYTHON" tools/prompt_leak_lint.py
run_lint "best_practices_lint"     "$PYTHON" tools/best_practices_lint.py

if [ "$FAILED" -eq 0 ]; then
    echo "mandatory-auto-lint: PASS"
    exit 0
else
    echo "mandatory-auto-lint: FAIL (one or more lints failed — run each tool with --pretty for details)"
    exit 1
fi
