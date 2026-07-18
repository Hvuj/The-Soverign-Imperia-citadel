#!/usr/bin/env bash
# The status line runs every few seconds; it must never abort or print errors to the
# terminal. Self-locate statusline.py from this script's own directory (so an empty
# $CLAUDE_PROJECT_DIR can't turn the path into a bogus "/.claude/..."), send any stderr to
# the write-ahead log, and always exit 0. stdout is the rendered status bar.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
: "${CLAUDE_PROJECT_DIR:=$(cd "$DIR/.." 2>/dev/null && pwd)}"
WAL="$CLAUDE_PROJECT_DIR/.claude/state/hooks.wal"
mkdir -p "$CLAUDE_PROJECT_DIR/.claude/state" 2>/dev/null || true
# Force UTF-8 stdout: Windows cp1252 can't encode the ◆/⬢ status glyphs and would crash the bar.
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python "$DIR/statusline.py" 2>>"$WAL" || true
exit 0
