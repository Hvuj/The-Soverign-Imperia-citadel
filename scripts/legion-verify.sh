#!/usr/bin/env bash
# legion-verify.sh — fast pre-iteration gate for the The Sovereign Imperia Citadel Z codespace.
set -uo pipefail
WS="${CITADEL_WORKSPACE:-$PWD}"
PY="$WS/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
cd "$WS" || exit 1

fail=0
run() { echo "== $1 =="; shift; "$@" || fail=1; }

echo "== ruff (advisory) =="
"$PY" -m ruff check tools src tests 2>&1 | tail -1 | sed 's/^/  /'

run "py_compile"         "$PY" -m compileall -q src tests
run "pytest"             "$PY" -m pytest -q
run "best_practices"     "$PY" tools/best_practices_lint.py
run "brand_lint"         "$PY" tools/brand_lint.py

if [ "$fail" = 0 ]; then
  echo "VERIFY: PASS"
else
  echo "VERIFY: FAIL"
  exit 1
fi
