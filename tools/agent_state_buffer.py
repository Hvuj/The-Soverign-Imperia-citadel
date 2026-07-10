#!/usr/bin/env python3
"""agent_state_buffer.py — Lossless agent state checkpoint + restore for model/effort handoff.

When an agent needs to switch model or effort tier mid-task, it:
  1. Calls checkpoint() to flush its working state to a .md + JSON buffer.
  2. The next-tier agent is spawned with preload() to restore that state.
  3. The main-loop prompt cache is never touched (switching is spawn-layer only).

Buffer path: .claude/state/agent-buffers/<unit>/<agent>/<task_id>.{md,json}

Zero-token: never calls any LLM. Pure Python write/read.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
BUFFER_ROOT = ROOT / ".claude" / "state" / "agent-buffers"
_MAX_BUFFER_CHARS = 8000


def _now() -> str:
    return datetime.now(UTC).isoformat()


def checkpoint(
    unit: str,
    agent: str,
    task_id: str,
    state: dict,
) -> Path:
    """Write agent working state to buffer. Returns the .md path.

    state keys (all optional, include what the agent knows so far):
      - progress: str (what was done)
      - findings: list[str]
      - files_read: list[str]
      - files_changed: list[str]
      - next_action: str (what to do next)
      - context: str (any key context worth preserving)
      - model: str (the model that wrote this checkpoint)
      - effort: str (the effort level that wrote this checkpoint)
    """
    buf_dir = BUFFER_ROOT / unit / agent
    buf_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "unit": unit,
        "agent": agent,
        "task_id": task_id,
        "created_at": _now(),
        **state,
    }
    json_path = buf_dir / f"{task_id}.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    progress = state.get("progress", "")
    findings = state.get("findings", [])
    files_read = state.get("files_read", [])
    files_changed = state.get("files_changed", [])
    next_action = state.get("next_action", "")
    context = state.get("context", "")
    from_model = state.get("model", "unknown")
    from_effort = state.get("effort", "unknown")

    md_lines = [
        f"# Agent State Buffer",
        f"",
        f"unit: {unit}",
        f"agent: {agent}",
        f"task_id: {task_id}",
        f"created_at: {_now()}",
        f"from_model: {from_model}",
        f"from_effort: {from_effort}",
        f"",
        f"## Progress so far",
        progress or "(none recorded)",
        f"",
    ]
    if findings:
        md_lines += ["## Findings", *[f"- {f}" for f in findings[:20]], ""]
    if files_read:
        md_lines += ["## Files read", *[f"- {f}" for f in files_read[:20]], ""]
    if files_changed:
        md_lines += ["## Files changed", *[f"- {f}" for f in files_changed[:20]], ""]
    if context:
        md_lines += ["## Context", context[:_MAX_BUFFER_CHARS], ""]
    if next_action:
        md_lines += ["## Next action", next_action, ""]

    md_text = "\n".join(md_lines)
    md_path = buf_dir / f"{task_id}.md"
    md_path.write_text(md_text, encoding="utf-8")

    return md_path


def preload(
    unit: str,
    agent: str,
    task_id: str,
) -> "dict | None":
    """Load the buffer for a task. Returns the state dict, or None if not found."""
    json_path = BUFFER_ROOT / unit / agent / f"{task_id}.json"
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def preload_md(
    unit: str,
    agent: str,
    task_id: str,
) -> "str | None":
    """Return the markdown handoff text for a task, or None if not found."""
    md_path = BUFFER_ROOT / unit / agent / f"{task_id}.md"
    if not md_path.exists():
        return None
    try:
        return md_path.read_text(encoding="utf-8")
    except OSError:
        return None


def clear(unit: str, agent: str, task_id: str) -> None:
    """Remove buffer files after successful handoff."""
    buf_dir = BUFFER_ROOT / unit / agent
    for suffix in (".json", ".md"):
        p = buf_dir / f"{task_id}{suffix}"
        p.unlink(missing_ok=True)


def list_buffers(unit: str | None = None) -> list[dict]:
    """List all active buffers, optionally filtered by unit."""
    results: list[dict] = []
    if not BUFFER_ROOT.exists():
        return results
    search_root = BUFFER_ROOT / unit if unit else BUFFER_ROOT
    if not search_root.exists():
        return results
    for json_path in sorted(search_root.rglob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            results.append({
                "unit": data.get("unit", "?"),
                "agent": data.get("agent", "?"),
                "task_id": data.get("task_id", "?"),
                "created_at": data.get("created_at", "?"),
                "path": str(json_path.relative_to(ROOT)),
            })
        except Exception:
            pass
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="Agent state buffer.")
    sub = ap.add_subparsers(dest="cmd")

    cp = sub.add_parser("checkpoint", help="Write a checkpoint")
    cp.add_argument("--unit", required=True)
    cp.add_argument("--agent", required=True)
    cp.add_argument("--task-id", required=True)
    cp.add_argument("--state", default="{}", help="JSON state dict")

    pl = sub.add_parser("preload", help="Load a checkpoint")
    pl.add_argument("--unit", required=True)
    pl.add_argument("--agent", required=True)
    pl.add_argument("--task-id", required=True)
    pl.add_argument("--md", action="store_true", help="Return markdown instead of JSON")

    cl = sub.add_parser("clear", help="Remove a checkpoint after successful handoff")
    cl.add_argument("--unit", required=True)
    cl.add_argument("--agent", required=True)
    cl.add_argument("--task-id", required=True)

    ls = sub.add_parser("list", help="List active buffers")
    ls.add_argument("--unit", default=None)

    args = ap.parse_args()

    if args.cmd == "checkpoint":
        state = json.loads(args.state)
        path = checkpoint(args.unit, args.agent, args.task_id, state)
        print(str(path.relative_to(ROOT)))
    elif args.cmd == "preload":
        if args.md:
            result = preload_md(args.unit, args.agent, args.task_id)
            print(result or "(no buffer found)")
        else:
            result = preload(args.unit, args.agent, args.task_id)
            print(json.dumps(result, indent=2) if result else "null")
    elif args.cmd == "clear":
        clear(args.unit, args.agent, args.task_id)
    elif args.cmd == "list":
        buffers = list_buffers(args.unit)
        for b in buffers:
            print(f"{b['unit']}/{b['agent']}/{b['task_id']} @ {b['created_at']}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
