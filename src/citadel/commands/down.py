"""commands/down.py — `citadel down`

Gracefully stop all Citadel daemons and the UI server, clean up pidfiles,
and leave the machine clean for a fresh `citadel up`.

Mirrors the four scripts/*-stop.sh scripts in pure Python so it works
workspace-agnostically after `citadel install`.

Stop sequence per daemon
------------------------
1. Send SIGTERM to the whole process group (daemons use start_new_session=True,
   so each is its own group — this also reaps launcher wrappers like `uv run`
   that hold a different PID than their child listener).
2. Wait up to GRACE_SECS for the process to exit.
3. If still alive, send SIGKILL.
4. Remove the pidfile.

The outcome-miner additionally receives a sentinel-file signal, since it
watches for `.claude/state/outcome-miner-daemon.stop` (see outcome-miner-daemon-stop.sh).

After the per-workspace pidfile pass, a global process scan (`_daemons.py`)
catches any Citadel daemon still alive anywhere on the machine — including ones
whose pidfile was deleted out from under them, or that were started from a
different workspace (or a global uv-tool install). This is intentionally
machine-wide: `citadel down` stops every Citadel daemon it can find, not just
the ones tied to the current workspace.
"""

import contextlib
import os
import sys
from pathlib import Path

from citadel._process import process_command_line
from citadel.commands import _daemons
from citadel.commands._runner import _daemon_path
from citadel.paths import resolve_home

GRACE_SECS = _daemons.GRACE_SECS

_DAEMONS: list[tuple[str, str, bool, str]] = [
    ("incremental brain daemon", ".claude/state/incremental-brain-daemon.pid", False, "incremental_brain_daemon"),
    (
        "workspace intelligence daemon",
        ".claude/state/workspace-intelligence/daemon.pid",
        False,
        "workspace_intelligence_daemon",
    ),
    ("outcome miner daemon", ".claude/state/outcome-miner-daemon.pid", True, "outcome_miner_daemon"),
    ("git-history daemon", ".claude/state/git-history-daemon.pid", False, "git_history_daemon"),
    ("RAM cache daemon", ".claude/state/ram-cache-daemon.pid", False, "ram_cache_daemon"),
    ("bug-record daemon", ".claude/state/bug-record-daemon.pid", False, "bug_record_daemon"),
    ("zombie worker daemon", ".claude/state/zombie-worker-daemon.pid", False, "zombie_worker_daemon"),
    ("embedder daemon", ".claude/state/embedder-daemon.pid", False, "embedder_daemon"),
    ("Citadel UI server", ".claude/state/citadel-ui-server.pid", False, "citadel_ui_server"),
]


def run(workspace: str | None = None) -> int:
    """Stop every Citadel daemon + UI server, on this workspace and machine-wide.

    Returns 0 on success.
    """
    ws = Path(workspace).expanduser().resolve() if workspace else resolve_home()
    if not ws.exists():
        print(f"ERROR: workspace '{ws}' does not exist.", file=sys.stderr)
        return 1

    os.environ["CITADEL_WORKSPACE"] = str(ws)

    print(f"[citadel down] workspace: {ws}")
    print("[citadel down] stopping all Citadel processes …")

    entries: list[tuple[str, Path, int]] = []
    for label, pidfile_rel, use_sentinel, expected_stem in _DAEMONS:
        pidfile = _daemon_path(ws, pidfile_rel)
        if use_sentinel:
            sentinel = pidfile.parent / "outcome-miner-daemon.stop"
            with contextlib.suppress(OSError):
                sentinel.touch()

        if not pidfile.exists():
            print(f"  {label}: not running (no pidfile)")
            continue
        try:
            pid = int(pidfile.read_text().strip())
        except (ValueError, OSError):
            pidfile.unlink(missing_ok=True)
            print(f"  {label}: stale pidfile removed")
            continue
        if pid <= 0:
            pidfile.unlink(missing_ok=True)
            print(f"  {label}: invalid pidfile removed (pid={pid})")
            continue
        command_line = process_command_line(pid)
        if command_line is None:
            pidfile.unlink(missing_ok=True)
            print(f"  {label}: uninspectable pidfile removed (pid={pid})")
            continue
        if expected_stem not in command_line:
            pidfile.unlink(missing_ok=True)
            print(f"  {label}: stale pidfile removed (pid={pid} was reused)")
            continue
        entries.append((label, pidfile, pid))

    signaled = _daemons.terminate_many([pid for _, _, pid in entries], GRACE_SECS)

    stopped_pids: set[int] = set()
    for label, pidfile, pid in entries:
        pidfile.unlink(missing_ok=True)
        stopped_pids.add(pid)
        if pid in signaled:
            print(f"  {label}: stopped (pid={pid})")
        else:
            print(f"  {label}: already stopped (pid={pid})")

    print("[citadel down] scanning for stray Citadel daemons machine-wide …")
    orphans = _daemons.find_citadel_daemon_procs(exclude_pids=stopped_pids)
    if orphans:
        for msg in _daemons.kill_procs(orphans):
            print(msg)
    else:
        print("  none found")

    print("[citadel down] done — machine is clean for a fresh `citadel up`")
    return 0
