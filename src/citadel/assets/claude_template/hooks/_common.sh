#!/usr/bin/env bash
# _common.sh — sourced preamble for every Citadel hook (never run directly).
#
# Hooks are best-effort brain telemetry: they must never fail the session or write to the
# terminal. This guarantees $CLAUDE_PROJECT_DIR is set, routes all stderr into a write-ahead
# log (.claude/state/hooks.wal) instead of the session, and normalizes the exit code so a
# crash can never surface. Blocking decisions travel on stdout (JSON) and are left untouched;
# an explicit `exit 2` block is still honored.

if [ -z "${CLAUDE_PROJECT_DIR:-}" ]; then
  CLAUDE_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd)"
  export CLAUDE_PROJECT_DIR
fi

CITADEL_HOOKS_WAL="${CLAUDE_PROJECT_DIR}/.claude/state/hooks.wal"
mkdir -p "${CLAUDE_PROJECT_DIR}/.claude/state" 2>/dev/null || true
exec 2>>"$CITADEL_HOOKS_WAL" || true

# Windows defaults child Python stdout to cp1252, which dies on the ◆/⬢ status glyphs and any
# non-ASCII a hook prints. Force UTF-8 for every Python a hook spawns (same as the daemons).
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

_citadel_hook_exit() { local c=$?; [ "$c" = 2 ] && exit 2; exit 0; }
trap _citadel_hook_exit EXIT

# Optional explicit logger — `wal_log "message"` records a tagged line to the WAL.
wal_log() {
  printf '%s %s: %s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo '')" \
    "$(basename "${0:-hook}")" "${1:-}" >&2
}
