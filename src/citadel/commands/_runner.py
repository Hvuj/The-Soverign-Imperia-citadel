"""_runner.py — Shared helpers for running bundled tools and daemons.

All paths are resolved relative to the installed sovereign-imperia-citadel package root, so
these helpers work from ANY workspace after `citadel init`.
"""

import contextlib
import functools
import os
import subprocess
import sys
from pathlib import Path

from citadel._process import pid_is_alive, process_command_line


def _package_root() -> Path:
    """This file's absolute path WITHOUT `os.path.realpath`.

    `Path(__file__).resolve()` walks and resolves every path component (reparse points / OneDrive cloud
    placeholders), which can BLOCK indefinitely when the tree lives under a OneDrive-redirected folder. We
    only need the package directory to locate bundled `tools/`/`scripts/`, not symlink resolution — so use
    the pure-string `os.path.abspath` (never touches the filesystem)."""
    return Path(os.path.abspath(__file__))


def _child_env(ws: Path) -> dict:
    """Environment for spawned tools/daemons: the workspace pointer + forced UTF-8.

    Child processes do NOT inherit the parent's `sys.stdout.reconfigure(utf-8)` from `cli.main()`, and on
    Windows a subprocess defaults to the legacy cp1252 codepage — so a tool that prints a ✓/✗/● icon dies
    with UnicodeEncodeError. `PYTHONUTF8=1` (+ `PYTHONIOENCODING`) makes every child emit UTF-8, whether its
    stdout is a console, a pipe, or a log file."""
    return {
        **os.environ,
        "CITADEL_WORKSPACE": str(ws),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }


@functools.cache
def _tools_dir() -> Path:
    """Return the directory containing bundled sovereign-imperia-citadel tools.

    Works for both wheel installs (tools at citadel/tools/) and editable/src
    installs (tools at <repo>/tools/). Callers use warn-and-continue semantics for
    missing individual tools, so returning a non-existent path is acceptable. Cached: the answer is constant
    for the process, so the filesystem is probed once, not on every daemon/tool spawn.

    Layout mapping:
      Wheel:    <site-packages>/citadel/commands/_runner.py
                parents[1] = <site-packages>/citadel/   ← has tools/ here
      Editable: <repo>/src/citadel/commands/_runner.py
                parents[3] = <repo>/                          ← has tools/ here
    """
    here = _package_root()
    for cand in (here.parents[1], here.parents[3]):
        td = cand / "tools"
        if td.is_dir():
            return td
    return here.parents[1] / "tools"


@functools.cache
def _scripts_dir() -> Path:
    """Return the directory containing bundled sovereign-imperia-citadel scripts.

    Same wheel/editable resolution as `_tools_dir()`, for `scripts/`. Cached (constant per process).
    """
    here = _package_root()
    for cand in (here.parents[1], here.parents[3]):
        sd = cand / "scripts"
        if sd.is_dir():
            return sd
    return here.parents[1] / "scripts"


def run_tool(
    name: str,
    ws: Path,
    extra_args: list[str] | None = None,
    *,
    quiet: bool = True,
    timeout: int = 300,
) -> bool:
    """Run ``tools/<name>`` from the bundled package against workspace ``ws``.

    Returns True on success, False on error/timeout (warn-and-continue semantics).
    """
    tool = _tools_dir() / name
    if not tool.exists():
        print(f"  [warn] bundled tool not found: tools/{name}", file=sys.stderr)
        return False

    env = _child_env(ws)
    cmd = [sys.executable, str(tool)] + (extra_args or [])
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ws),
            env=env,
            capture_output=quiet,
            timeout=timeout,
        )
        if result.returncode != 0:
            print(f"  [warn] tools/{name} exited {result.returncode}", file=sys.stderr)
            if quiet and result.stderr:
                print(result.stderr[:500].decode(errors="replace"), file=sys.stderr)
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"  [warn] tools/{name} timed out after {timeout}s", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"  [warn] tools/{name} error: {exc}", file=sys.stderr)
        return False


def _pid_is_our_daemon(pid: int, tool_name: str) -> bool:
    """Return True if ``pid`` looks like it's running ``tool_name``.

    Uses /proc/<pid>/cmdline on Linux or `ps -p` on macOS/BSD.
    Returns True (allow reuse) on any platform that can't be checked,
    so this never blocks a false negative — it only catches obvious PID reuse.
    """
    stem = tool_name.removesuffix(".py")
    cmdline = process_command_line(pid)
    if cmdline is None:
        return sys.platform != "win32"
    return stem in cmdline


def _low_priority_spawn_kwargs() -> dict:
    """Popen kwargs that detach Windows daemons at below-normal priority."""
    if sys.platform == "win32":
        flags = (
            getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
        if flags:
            return {"creationflags": flags, "stdin": subprocess.DEVNULL}
    return {}


def _lower_priority(pid: int) -> None:
    """Nice a spawned daemon down on POSIX so background work never starves the foreground."""
    if sys.platform != "win32" and hasattr(os, "setpriority"):
        with contextlib.suppress(OSError, PermissionError):
            os.setpriority(os.PRIO_PROCESS, pid, 10)


def _daemon_path(ws: Path, relative: str) -> Path:
    """Return a daemon pid/log path without traversing the root ``.claude`` link.

    New installations keep the real Claude directory at
    ``.citadel/.claude`` and expose root ``.claude`` as a symlink (POSIX) or
    junction (Windows).  Writing daemon state through the Windows junction can
    block under OneDrive and has caused ``citadel up`` to hang while starting
    the UI server.  Initialized workspaces always have the managed directory,
    so map it lexically without an ``exists()``/``is_dir()`` probe on the hot
    startup path.

    This is intentionally a lexical mapping: resolving either path would walk
    the junction and reintroduce the problem this helper avoids.
    """
    rel = Path(relative)
    parts = rel.parts
    if not rel.is_absolute() and parts[:1] == (".claude",):
        return (ws / ".citadel" / ".claude").joinpath(*parts[1:])
    return ws / rel


def start_daemon(
    tool_name: str,
    ws: Path,
    daemon_args: list[str],
    pidfile_rel: str,
    out_rel: str,
    err_rel: str,
    *,
    check_tool: bool = True,
) -> int | None:
    """Start a daemon tool in a detached subprocess if not already running.

    Returns the PID of the (new or existing) daemon, or None on failure.
    - Idempotent: if the pidfile exists and the process is alive, returns its PID.
    - State files are written to the initialized workspace's managed
      ``.citadel/.claude`` directory, bypassing the root symlink/junction.
    - ``check_tool=False`` skips a redundant pre-spawn stat for callers that
      must avoid OneDrive placeholder stalls; ``Popen`` still reports a missing
      script through the daemon log/process exit.
    - Missing optional deps (watchdog, anthropic) → warning, not an error.
    """
    tool = _tools_dir() / tool_name
    if check_tool and not tool.exists():
        print(f"  [warn] daemon tool not found: tools/{tool_name}", file=sys.stderr)
        return None

    try:
        pidfile = _daemon_path(ws, pidfile_rel)
        pidfile.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"  [warn] {tool_name} state path unavailable: {exc}", file=sys.stderr)
        return None

    if pidfile.exists():
        try:
            existing_pid = int(pidfile.read_text().strip())
            if pid_is_alive(existing_pid) and _pid_is_our_daemon(existing_pid, tool_name):
                return existing_pid
        except (ValueError, OSError):
            pass

    try:
        out_path = _daemon_path(ws, out_rel)
        err_path = _daemon_path(ws, err_rel)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        err_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"  [warn] {tool_name} log path unavailable: {exc}", file=sys.stderr)
        return None

    env = _child_env(ws)
    cmd = [sys.executable, str(tool), *daemon_args]

    try:
        with open(out_path, "a") as fout, open(err_path, "a") as ferr:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ws),
                env=env,
                stdout=fout,
                stderr=ferr,
                start_new_session=True,
                **_low_priority_spawn_kwargs(),
            )
        pidfile.write_text(str(proc.pid))
        _lower_priority(proc.pid)
        return proc.pid
    except FileNotFoundError:
        print(f"  [warn] could not start {tool_name}: python interpreter not found", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"  [warn] {tool_name} failed to start: {exc}", file=sys.stderr)
        return None


def daemon_alive(pidfile_rel: str, ws: Path) -> bool:
    """Return True if the daemon described by ``pidfile_rel`` is running."""
    pidfile = _daemon_path(ws, pidfile_rel)
    if not pidfile.exists():
        return False
    try:
        pid = int(pidfile.read_text().strip())
    except (ValueError, OSError):
        return False
    return pid_is_alive(pid)
