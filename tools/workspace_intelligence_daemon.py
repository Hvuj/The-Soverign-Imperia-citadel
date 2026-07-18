#!/usr/bin/env python3
"""workspace_intelligence_daemon.py — Optional file-watch daemon for workspace intelligence.

Watches included repos for changes and triggers incremental rebuilds.
Uses `watchdog` if installed, otherwise falls back to polling (safe, no busy-loop).

Usage (managed by scripts):
    python tools/workspace_intelligence_daemon.py [--config PATH] [--interval SECS] [--quiet]

PID file: .claude/state/workspace-intelligence/daemon.pid
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from citadel._process import no_window_creationflags

_NO_WINDOW = no_window_creationflags()

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from _workspace_intel_common import (  # noqa: E402
    ROOT,
    WS_STATE,
    is_excluded_dir,
    load_config,
)

PID_FILE = WS_STATE / "daemon.pid"
LOG_FILE = WS_STATE / "daemon.log"
DEFAULT_POLL_INTERVAL = 30

_venv_py = ROOT / ".venv" / "bin" / "python"
PYTHON = str(_venv_py) if _venv_py.is_file() else sys.executable

_running = True


def _log(msg: str, quiet: bool = False) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if not quiet:
        print(line, flush=True)


def _write_pid() -> None:
    WS_STATE.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def _remove_pid() -> None:
    try:
        if PID_FILE.exists():
            pid_text = PID_FILE.read_text().strip()
            if pid_text == str(os.getpid()):
                PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _trigger_rebuild(cfg: dict, quiet: bool) -> None:
    """Trigger incremental index rebuild."""
    _log("triggering incremental rebuild...", quiet)
    try:
        result = subprocess.run(
            [PYTHON, str(_TOOLS / "build_workspace_intelligence_index.py"), "--quiet"],
            cwd=str(ROOT), timeout=120, capture_output=True, text=True, creationflags=_NO_WINDOW
        )
        if result.returncode == 0:
            _log("rebuild complete", quiet)
        else:
            _log(f"rebuild failed (rc={result.returncode}): {result.stderr[:200]}", quiet)
    except subprocess.TimeoutExpired:
        _log("rebuild timed out after 120s", quiet)
    except Exception as exc:
        _log(f"rebuild error: {exc}", quiet)


def _scoped_repo_dirs(workspace_root: str, cfg: dict) -> list[Path]:
    """Return the repo directories this daemon should watch/scan.

    Honors an explicit `repo_include_paths` (populated from a `*.code-workspace`
    file's `folders[]`) over globbing `workspace_root`'s children, mirroring
    `discover_repos()` in `build_workspace_intelligence_index.py` so the daemon
    watches exactly the same repo set the index builder discovers.
    """
    import fnmatch
    explicit_paths = cfg.get("repo_include_paths")
    if explicit_paths:
        return [p for p in (Path(ep) for ep in explicit_paths) if p.is_dir()]
    include_globs = cfg.get("repo_include_globs", ["*"])
    try:
        entries = list(Path(workspace_root).iterdir())
    except OSError:
        return []
    return [e for e in entries if e.is_dir() and any(fnmatch.fnmatch(e.name, g) for g in include_globs)]


def _collect_mtimes(workspace_root: str, cfg: dict) -> dict[str, int]:
    """Collect mtime_ns for all included files (lightweight scan)."""
    include_exts = set(cfg.get("include_extensions", [".py", ".md"]))
    mtimes: dict[str, int] = {}

    for entry in _scoped_repo_dirs(workspace_root, cfg):
        _scan_dir_mtimes(entry, "", mtimes, include_exts, cfg, set())

    return mtimes


def _scan_dir_mtimes(dirpath: Path, relp: str, mtimes: dict,
                      include_exts: set, cfg: dict, visited: set) -> None:
    try:
        rp = str(dirpath.resolve())
        if rp in visited:
            return
        visited.add(rp)
    except Exception:
        return

    try:
        entries = list(os.scandir(str(dirpath)))
    except Exception:
        return

    for entry in entries:
        name = entry.name
        rel = f"{relp}/{name}".lstrip("/") if relp else name
        if entry.is_dir(follow_symlinks=False):
            if is_excluded_dir(name, cfg):
                continue
            _scan_dir_mtimes(Path(entry.path), rel, mtimes, include_exts, cfg, visited)
        elif entry.is_file(follow_symlinks=False):
            if Path(name).suffix.lower() in include_exts:
                try:
                    mtimes[entry.path] = entry.stat().st_mtime_ns
                except Exception:
                    pass


def _poll_loop(cfg: dict, interval: int, quiet: bool) -> None:
    """Polling-based watch loop. Debounces with interval seconds."""
    workspace_root = cfg.get("workspace_root", str(ROOT.parent))
    _log(f"polling watcher started (interval={interval}s, workspace={workspace_root})", quiet)
    prev_mtimes = _collect_mtimes(workspace_root, cfg)
    debounce_pending = False
    last_change_time = 0.0

    while _running:
        time.sleep(min(interval, 5))
        if not _running:
            break

        current_mtimes = _collect_mtimes(workspace_root, cfg)
        changed = False
        for path, mtime in current_mtimes.items():
            if prev_mtimes.get(path) != mtime:
                changed = True
                break
        for path in prev_mtimes:
            if path not in current_mtimes:
                changed = True
                break

        if changed:
            last_change_time = time.monotonic()
            debounce_pending = True
            prev_mtimes = current_mtimes

        if debounce_pending and (time.monotonic() - last_change_time) >= max(interval * 0.5, 3):
            _trigger_rebuild(cfg, quiet)
            debounce_pending = False


def _try_watchdog_loop(cfg: dict, interval: int, quiet: bool) -> bool:
    """Try to use watchdog. Return False if not available."""
    try:
        from watchdog.events import FileSystemEventHandler  # type: ignore[import]
        from watchdog.observers import Observer  # type: ignore[import]
    except ImportError:
        return False

    workspace_root = cfg.get("workspace_root", str(ROOT.parent))

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._last = 0.0

        def on_any_event(self, event):
            path = getattr(event, "src_path", "")
            parts = Path(path).parts
            for part in parts:
                if is_excluded_dir(part, cfg):
                    return
            ext = Path(path).suffix.lower()
            include_exts = set(cfg.get("include_extensions", [".py", ".md"]))
            if ext not in include_exts:
                return
            now = time.monotonic()
            if now - self._last > max(interval, 5):
                self._last = now
                _trigger_rebuild(cfg, quiet)

    observer = Observer()
    handler = _Handler()
    watch_paths = []
    try:
        for entry in _scoped_repo_dirs(workspace_root, cfg):
            observer.schedule(handler, str(entry), recursive=True)
            watch_paths.append(entry.name)
    except OSError:
        return False

    if not watch_paths:
        return False

    _log(f"watchdog observer started on {watch_paths}", quiet)
    observer.start()
    try:
        while _running:
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()
    return True


def _install_signals() -> None:
    def _stop(sig, _frame):
        global _running
        _running = False
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)


def main() -> int:
    parser = argparse.ArgumentParser(description="Workspace intelligence file-watch daemon")
    parser.add_argument("--config", help="Config path")
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_INTERVAL,
                        help=f"Poll interval seconds (default: {DEFAULT_POLL_INTERVAL})")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    _install_signals()
    _write_pid()

    _log(f"workspace-intelligence-daemon starting (pid={os.getpid()})", args.quiet)

    try:
        if not _try_watchdog_loop(cfg, args.interval, args.quiet):
            _log("watchdog not available — using polling fallback", args.quiet)
            _poll_loop(cfg, args.interval, args.quiet)
    except Exception as exc:
        _log(f"daemon error: {exc}", args.quiet)
        return 1
    finally:
        _remove_pid()
        _log("workspace-intelligence-daemon stopped", args.quiet)

    return 0


if __name__ == "__main__":
    sys.exit(main())
