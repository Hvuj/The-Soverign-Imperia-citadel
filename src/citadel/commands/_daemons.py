"""commands/_daemons.py — Global Citadel daemon discovery and termination.

Daemons are launched with ``start_new_session=True`` (see ``_runner.start_daemon``)
and tracked per-workspace via a pidfile under ``<ws>/.claude/state/*.pid``. That
tracking breaks down whenever a pidfile is deleted out from under a still-live
process, a daemon was started from a different workspace (or a global uv-tool
install), or a tool isn't in the fixed per-workspace daemon list — the process
keeps running and is invisible to the normal pidfile stop path.

This module scans *all* OS processes by command line so ``citadel down``,
``citadel up`` (pre-start cleanup), and the session-end shutdown hook can find
and stop every Citadel daemon on the machine regardless of which workspace
launched it or whether its pidfile survives. Detection is a cmdline substring
match, so it is inherently identity-checked — it can never signal an unrelated
process that merely reused a stale PID.
"""

import contextlib
import os
import signal
import subprocess
import time

GRACE_SECS = 3.0

Citadel_DAEMON_STEMS: tuple[str, ...] = (
    "incremental_brain_daemon",
    "workspace_intelligence_daemon",
    "outcome_miner_daemon",
    "git_history_daemon",
    "ram_cache_daemon",
    "bug_record_daemon",
    "zombie_worker_daemon",
    "obsidian_intent_daemon",
    "citadel_ui_server",
)


def find_citadel_daemon_procs(exclude_pids: set[int] | None = None) -> list[tuple[int, str]]:
    """Scan all OS processes for Citadel daemons by command-line match.

    Returns ``(pid, label)`` pairs for every process whose command line
    contains a known daemon stem *and* looks like a citadel-managed process
    (path contains "citadel" or "/tools/"). Complements the per-workspace
    pidfile lookups in ``down.py`` — it catches daemons whose pidfile was
    deleted, that were started from a different workspace, or from a global
    tool install.
    """
    exclude = set(exclude_pids or ())
    exclude.add(os.getpid())
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,args="],
            capture_output=True,
            timeout=5,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    found: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pid_str, args = line.split(maxsplit=1)
            pid = int(pid_str)
        except ValueError:
            continue
        if pid in exclude:
            continue
        for stem in Citadel_DAEMON_STEMS:
            if stem in args and ("citadel" in args.lower() or "/tools/" in args):
                found.append((pid, stem))
                break
    return found


def terminate_pid(pid: int, grace: float = GRACE_SECS) -> bool:
    """SIGTERM the process group (or process), wait `grace` seconds, then SIGKILL.

    Returns True if a signal was successfully delivered (the process existed).
    Shared by ``down.py``'s per-pidfile stop path and the global scan here.
    """
    killed = False
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        killed = True
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
            killed = True
        except (ProcessLookupError, PermissionError):
            pass
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
            killed = True
        except ProcessLookupError:
            pass

    if not killed:
        return False

    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except (ProcessLookupError, PermissionError):
            return True
    else:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
    return True


def terminate_many(pids: list[int], grace: float = GRACE_SECS) -> set[int]:
    """SIGTERM every pid in *pids* immediately, then wait once on a shared
    deadline (up to *grace* seconds total) before SIGKILL-ing any still alive.

    Returns the subset of *pids* a signal was actually delivered to (existed).

    Signaling sequentially and waiting up to `grace` per-pid (as `terminate_pid`
    does) makes total shutdown time scale with the number of processes. Firing
    all signals up front and waiting on one shared deadline caps total time at
    `grace` regardless of how many processes are being stopped.
    """
    signaled: set[int] = set()
    for pid in pids:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
            signaled.add(pid)
        except (ProcessLookupError, PermissionError):
            continue
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
                signaled.add(pid)
            except ProcessLookupError:
                pass

    deadline = time.monotonic() + grace
    remaining = set(signaled)
    while remaining and time.monotonic() < deadline:
        for pid in list(remaining):
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                remaining.discard(pid)
        if remaining:
            time.sleep(0.1)

    for pid in remaining:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)

    return signaled


def kill_procs(procs: list[tuple[int, str]], grace: float = GRACE_SECS) -> list[str]:
    """Terminate each ``(pid, label)`` pair in parallel (one shared grace window).

    Returns status lines for printing.
    """
    signaled = terminate_many([pid for pid, _ in procs], grace)
    messages = []
    for pid, label in procs:
        if pid in signaled:
            messages.append(f"  {label} (pid={pid}): stopped [orphan]")
        else:
            messages.append(f"  {label} (pid={pid}): already stopped")
    return messages
