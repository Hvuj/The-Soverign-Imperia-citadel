#!/usr/bin/env bash
set -euo pipefail
input="$(cat || true)"
lines="$(printf '%s\n' "$input" | wc -l | tr -d ' ')"
if [ "$lines" -le 200 ]; then
  printf '%s\n' "$input"
  exit 0
fi
echo "=== OUTPUT TRUNCATED/SUMMARIZED: ${lines} lines ==="
echo "--- error lines ---"
printf '%s\n' "$input" | grep -Ei 'error|failed|exception|traceback|assert|warning|fatal|panic' | head -120 || true
echo "--- head ---"
printf '%s\n' "$input" | head -40
echo "--- tail ---"
printf '%s\n' "$input" | tail -80
