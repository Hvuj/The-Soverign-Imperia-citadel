#!/usr/bin/env python3
"""git_history_daemon.py — continuous git-history miner across all companies.

Polls every git company (workspace repo) for new commits on the configured branches
(dev/main/master) and incrementally mines them into commit brain nodes with line-level
function linkage, then refreshes the commit index. Read-only w.r.t. the repos; never
calls Claude; only writes into the legion's own docs/brain and .citadel state.

Lifecycle:
    --watch    run forever (default), SIGTERM/SIGINT → graceful shutdown
    --once     run a single mine cycle and exit
    --status   print whether the daemon is running
    --stop     signal a running daemon to stop

PID file: <workspace>/.claude/state/git-history-daemon.pid
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from citadel import paths as vp
from citadel.commands._runner import _tools_dir
from citadel.mine_engine import mine_all, touched_repos

DEFAULT_POLL_INTERVAL = 300
SWEEP_INTERVAL = 86_400

_running = True


def _sweep_stamp(ws: Path) -> Path:
    return vp.claude_dir(ws) / "state" / "git-history-sweep.stamp"


def _sweep_due(ws: Path) -> bool:
    stamp = _sweep_stamp(ws)
    try:
        return (time.time() - stamp.stat().st_mtime) >= SWEEP_INTERVAL
    except OSError:
        return True


def _mark_swept(ws: Path) -> None:
    stamp = _sweep_stamp(ws)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(str(time.time()))


def _pid_file(ws: Path) -> Path:
    return vp.claude_dir(ws) / "state" / "git-history-daemon.pid"


def _log(msg: str, quiet: bool) -> None:
    if not quiet:
        print(f"[git-history-daemon] {msg}", flush=True)


def _write_pid(ws: Path) -> None:
    pid_file = _pid_file(ws)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))


def _remove_pid(ws: Path) -> None:
    pid_file = _pid_file(ws)
    try:
        if pid_file.exists() and pid_file.read_text().strip() == str(os.getpid()):
            pid_file.unlink(missing_ok=True)
    except OSError:
        pass


def _install_signals() -> None:
    def _stop(_sig, _frame):
        global _running
        _running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)


def _rebuild_commit_index(quiet: bool) -> None:
    """Refresh commit-index.json (sha/file/function maps) after mining."""
    tool = _tools_dir() / "build_commit_index.py"
    if not tool.exists():
        _log("commit-index tool missing; skipped", quiet)
        return
    args = [sys.executable, str(tool)] + (["--quiet"] if quiet else [])
    try:
        subprocess.run(args, check=False)
    except OSError as exc:
        _log(f"commit-index rebuild failed: {exc}", quiet)


def _rebuild_sharded_graph(quiet: bool) -> None:
    """Refresh the per-repo shards + pointer graph so new commits show up in the UI.

    Runs after `_rebuild_commit_index` so the freshly-mined commit nodes it just wrote
    are already on disk for `build_sharded_brain_graph.py` to group by repo.
    """
    tool = _tools_dir() / "build_sharded_brain_graph.py"
    if not tool.exists():
        _log("sharded-graph tool missing; skipped", quiet)
        return
    args = [sys.executable, str(tool), "--build"]
    try:
        subprocess.run(args, check=False, capture_output=quiet)
    except OSError as exc:
        _log(f"sharded-graph rebuild failed: {exc}", quiet)


def run_cycle(ws: Path, quiet: bool, *, sweep: bool = False) -> int:
    """One mining pass. Lazy by default: mine only repos touched this session.

    `sweep=True` mines every git company (the daily safety net). Rebuilds the commit
    index only if something was actually mined.
    """
    if sweep:
        summary = mine_all(ws, quiet=quiet)
    else:
        touched = touched_repos(ws)
        if not touched:
            return 0
        summary = mine_all(ws, only_repos=touched, quiet=quiet)
    if summary.commits:
        _log(
            f"mined {summary.commits} commits across {summary.branches_mined} "
            f"(repo,branch){' [sweep]' if sweep else ' [on-touch]'}; rebuilding commit index",
            quiet,
        )
        _rebuild_commit_index(quiet)
        _rebuild_sharded_graph(quiet)
    return summary.commits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Continuous git-history miner")
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--watch", action="store_true", help="Run forever (default)")
    parser.add_argument("--once", action="store_true", help="Run one on-touch cycle and exit")
    parser.add_argument("--sweep", action="store_true", help="Mine ALL repos once and exit")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    ws = vp.workspace_root()
    pid_file = _pid_file(ws)

    if args.status:
        if pid_file.exists():
            print(f"running (pid={pid_file.read_text().strip()})")
        else:
            print("not running")
        return 0

    if args.stop:
        if not pid_file.exists():
            print("not running")
            return 0
        try:
            os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
            print("stop signal sent")
        except (ValueError, ProcessLookupError):
            pid_file.unlink(missing_ok=True)
        return 0

    _install_signals()

    if args.sweep:
        run_cycle(ws, args.quiet, sweep=True)
        _mark_swept(ws)
        return 0

    if args.once:
        run_cycle(ws, args.quiet)
        return 0

    _write_pid(ws)
    _log(f"starting (pid={os.getpid()}, interval={args.interval}s)", args.quiet)
    try:
        while _running:
            do_sweep = _sweep_due(ws)
            run_cycle(ws, args.quiet, sweep=do_sweep)
            if do_sweep:
                _mark_swept(ws)
            slept = 0
            while _running and slept < args.interval:
                time.sleep(min(5, args.interval - slept))
                slept += 5
    finally:
        _remove_pid(ws)
        _log("stopped", args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
