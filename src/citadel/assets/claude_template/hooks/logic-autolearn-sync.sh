#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
# logic-autolearn-sync — re-learn + regenerate + re-wire this workspace's domain logic (Pandidakterion).
# Fires on PostToolBatch / a git-change branch. Best-effort and zero-token: it only runs the deterministic
# Cartographer pipeline and never blocks the session (|| true), so a hiccup is never fatal.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Resolve the bundled tools dir from the installed package (falls back to a workspace tools/ symlink).
TOOLS="$(python -c 'from citadel.commands._runner import _tools_dir; print(_tools_dir())' 2>/dev/null || echo "$ROOT/tools")"

PYTHONUTF8=1 python "$TOOLS/bi_wire.py" "$ROOT" >/dev/null 2>&1 || true
exit 0
