#!/usr/bin/env python3
"""worker_status.py — Reduce daemon pidfiles + the agent-run ledger into live worker state.

Two categories of "worker":
  - daemons: long-running background processes tracked by pidfile (mirrors the
    pidfile_rel list `up.py`'s `_start_*_daemon` functions use).
  - subagents: Claude Code Task-tool invocations, tracked via SubagentStart/Stop hook
    events appended to `.claude/state/agent-runs.ndjson` by `agent_run_ledger.py`.
    "Active" = a subagent-start with no matching subagent-stop for the same
    (session_id, task_id) pair.

`agent-runs.ndjson` is append-only and never rotated, so it can grow to many
thousands of lines over a long-lived workspace. A currently-active subagent, by
definition, started recently — so this only scans the last `_TAIL_BYTES` of the
file (a bounded seek-from-end read, not a full-file parse), keeping the cost of
every call O(1) regardless of total ledger size. This matters because both the
statusline (re-rendered on every prompt) and `--watch` (polled every second or
two) call this on a tight cadence.

Usage:
    python tools/worker_status.py            # human-readable one-shot
    python tools/worker_status.py --json
    python tools/worker_status.py --watch    # live-refreshing terminal view
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import legion_run_state as _lrs  # noqa: E402

from citadel.paths import claude_dir, workspace_root  # noqa: E402

DAEMON_PIDFILES: dict[str, str] = {
    "incremental_brain_daemon": ".claude/state/incremental-brain-daemon.pid",
    "workspace_intelligence_daemon": ".claude/state/workspace-intelligence/daemon.pid",
    "outcome_miner_daemon": ".claude/state/outcome-miner-daemon.pid",
    "git_history_daemon": ".claude/state/git-history-daemon.pid",
    "ram_cache_daemon": ".claude/state/ram-cache-daemon.pid",
    "bug_record_daemon": ".claude/state/bug-record-daemon.pid",
    "zombie_worker_daemon": ".claude/state/zombie-worker-daemon.pid",
    "citadel_ui_server": ".claude/state/citadel-ui-server.pid",
}

MINING_DAEMONS = frozenset({"git_history_daemon", "outcome_miner_daemon", "zombie_worker_daemon"})
_TAIL_BYTES = 512_000
_WATCH_INTERVAL_SECS = 1.5


def _pid_alive(pidfile: Path) -> int | None:
    try:
        pid = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return None
    return pid


def daemon_status(ws: Path) -> list[dict]:
    out = []
    for name, rel in DAEMON_PIDFILES.items():
        pid = _pid_alive(ws / rel)
        out.append({"name": name, "pid": pid, "alive": pid is not None, "mining": name in MINING_DAEMONS})
    return out


def _tail_lines(path: Path, max_bytes: int) -> list[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()
            chunk = fh.read()
    except OSError:
        return []
    return chunk.decode("utf-8", errors="ignore").splitlines()


def active_subagents(ws: Path) -> list[dict]:
    """Reduce the ledger's tail to subagents with a start but no matching stop."""
    ledger = claude_dir(ws) / "state" / "agent-runs.ndjson"
    if not ledger.exists():
        return []
    open_agents: dict[tuple, dict] = {}
    for line in _tail_lines(ledger, _TAIL_BYTES):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (rec.get("session_id"), rec.get("task_id"))
        if key == (None, None):
            continue
        if rec.get("event") == "subagent-start":
            open_agents[key] = rec
        elif rec.get("event") == "subagent-stop":
            open_agents.pop(key, None)
    return list(open_agents.values())


def build_status(ws: Path | None = None) -> dict:
    ws = ws or workspace_root()
    daemons = daemon_status(ws)
    agents = active_subagents(ws)
    return {
        "daemons": daemons,
        "daemons_alive": sum(1 for d in daemons if d["alive"]),
        "daemons_mining": sum(1 for d in daemons if d["alive"] and d["mining"]),
        "active_subagents": len(agents),
        "subagents": agents,
    }


def render_text(status: dict) -> str:
    lines = []
    for d in status["daemons"]:
        dot = "●" if d["alive"] else "○"
        tag = " (mining)" if d["alive"] and d["mining"] else ""
        lines.append(f"  {dot} {d['name']}{tag}")
    lines.append("")
    lines.append(f"daemons:   {status['daemons_alive']}/{len(status['daemons'])} alive, "
                 f"{status['daemons_mining']} mining")
    lines.append(f"subagents: {status['active_subagents']} active")
    for a in status["subagents"][:10]:
        lines.append(f"  ▸ {a.get('agent', 'unknown')} (tier={a.get('tier') or '-'})")
    return "\n".join(lines)


_LEGION_EVENT_ORDER = ("worker-start", "worker-respawn", "worker-usage", "worker-final")


def legion_status(run_id: str | None = None) -> dict:
    """Reduce a `citadel run`'s ledger into live per-worker state.

    Replays `worker-start` / `worker-respawn` / `worker-usage` / `worker-final`
    events in order, so each worker's row always reflects its CURRENT
    model/effort/tier/status — the concrete "N workers, each its own model +
    effort, visible in the terminal" view.
    """
    run_id = run_id or _lrs.current_run_id()
    if not run_id:
        return {"run_id": None, "workers": []}

    workers: dict[str, dict] = {}
    for rec in _lrs.read_ledger(run_id):
        wid = rec.get("worker")
        if not wid:
            continue
        w = workers.setdefault(wid, {
            "worker_id": wid, "company": None, "model": None, "effort": None,
            "tier": None, "status": "pending", "tokens": 0, "cost_usd": 0.0, "gate": None,
        })
        event = rec.get("event")
        if event == "worker-start":
            w.update(company=rec.get("company"), model=rec.get("model"),
                      effort=rec.get("effort"), tier=rec.get("tier"), status="working")
        elif event == "worker-respawn":
            w.update(model=rec.get("model"), effort=rec.get("effort"),
                      tier=rec.get("tier"), status="respawning")
        elif event == "worker-usage":
            w["tokens"] += rec.get("total_tokens", 0) or 0
            w["cost_usd"] = round(w["cost_usd"] + (rec.get("cost_usd", 0.0) or 0.0), 6)
        elif event == "worker-final":
            w["status"] = rec.get("status", w["status"])
            w["gate"] = rec.get("gate")

    return {"run_id": run_id, "workers": list(workers.values())}


_STATUS_GLYPH = {"working": "▶", "respawning": "↻", "done": "✓", "blocked": "✗", "pending": "⏸"}


def render_legion_text(status: dict) -> str:
    if not status.get("run_id"):
        return "no active run (.claude/state/legion-runs/current-run.json not found)"

    lines = [f"run: {status['run_id']}", ""]
    lines.append(f"{'WORKER':<12}{'COMPANY':<26}{'MODEL':<28}{'EFFORT':<8}{'STATUS':<14}{'TOKENS':>10}")
    for w in status["workers"]:
        glyph = _STATUS_GLYPH.get(w["status"], "?")
        status_col = f"{glyph} {w['status']}"
        lines.append(
            f"{w['worker_id']:<12}{(w['company'] or '-'):<26}{(w['model'] or '-'):<28}"
            f"{(w['effort'] or '-'):<8}{status_col:<14}{w['tokens']:>10}"
        )
    total_tokens = sum(w["tokens"] for w in status["workers"])
    total_cost = sum(w["cost_usd"] for w in status["workers"])
    lines.append("")
    lines.append(f"total tokens: {total_tokens}   total cost: ${total_cost:.4f}")
    return "\n".join(lines)


def watch(
    ws: Path | None = None, interval: float = _WATCH_INTERVAL_SECS, *, legion: bool = False, run_id: str | None = None,
) -> None:
    """Clear-and-redraw loop for a live terminal view. Ctrl-C to exit."""
    try:
        while True:
            status = build_status(ws)
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write("The Sovereign Imperia Citadel Z — live worker status (Ctrl-C to exit)\n")
            sys.stdout.write("=" * 55 + "\n")
            if legion:
                sys.stdout.write(render_legion_text(legion_status(run_id)) + "\n")
                sys.stdout.write("-" * 55 + "\n")
            sys.stdout.write(render_text(status) + "\n")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live Citadel worker (daemon + subagent) status.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--watch", action="store_true", help="Live-refreshing terminal view")
    parser.add_argument("--interval", type=float, default=_WATCH_INTERVAL_SECS)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--legion", action="store_true", help="Show the `citadel run` per-worker table")
    parser.add_argument("--run-id", default=None, help="Legion run id (default: the current run)")
    args = parser.parse_args(argv)

    ws = Path(args.workspace).expanduser().resolve() if args.workspace else None

    if args.watch:
        watch(ws, args.interval, legion=args.legion, run_id=args.run_id)
        return 0

    if args.legion:
        status = legion_status(args.run_id)
        print(json.dumps(status, indent=2) if args.json else render_legion_text(status))
        return 0

    status = build_status(ws)
    print(json.dumps(status, indent=2) if args.json else render_text(status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
