#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -euo pipefail
input="$(cat || true)"
printf '%s\n' "$input" | grep -A 8 -B 3 -E '(FAILED|ERROR|AssertionError|Traceback|E   |FAILURES|short test summary)' | head -300 || true
