#!/usr/bin/env python3
"""brain_agent_context.py — SubagentStart context injection, keyed per worker/session.

Previously this always wrote `.claude/state/agent-context/generic.json`: the
`--agent` flag defaults to "generic" and the wired hook
(`subagent-context-injector.sh`) never actually passes `--agent`, so every
subagent spawn overwrote the SAME file — nothing per-worker survived. Worse,
once `citadel run` (legion_orchestrator.py) spawns N concurrent
`claude --print` worker processes, each running its OWN Claude Code session
with its own SubagentStart hooks, those processes would all race on that one
shared file. This now reads the hook's stdin JSON (same shape
`agent_run_ledger.py` already reads) for `session_id` + the agent name, and
keys the written context per (session_id, agent) — one file per worker's own
subagent spawn, with no cross-process/cross-agent clobbering.

The injected capsule is also capped smaller than before (CAPSULE_CHAR_CAP) as
part of the token-burn reduction: every subagent spawn was re-paying an up to
8000-char graph capsule regardless of whether that agent actually needed it.
"""

import argparse
import json
import sys

from _brain_common import STATE, load_json, write_json
from brain_context_builder import build

CAPSULE_CHAR_CAP = 2500


def _stdin_json() -> dict:
    if sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _resolve_identity(cli_agent: str | None, hook_input: dict) -> tuple[str, str]:
    agent = cli_agent or hook_input.get("agent_name") or hook_input.get("subagent_type") or "generic"
    session_id = hook_input.get("session_id") or "no-session"
    return agent, session_id


def build_capsule(agent: str, session_id: str, query: str = "") -> dict:
    cap = build(query or agent, mode="agent")
    cap["agent"] = agent
    cap["session_id"] = session_id

    manifest = load_json(STATE / "execution-manifest.json", {})
    if manifest:
        agent_required = agent in manifest.get("required_agents", [])
        agent_skills = [
            s for s in manifest.get("required_skills", [])
            if agent in s.get("artifact_expectations", []) or agent_required
        ]
        agent_artifacts = [a for a in manifest.get("required_artifacts", []) if a.get("required", False)]
        cap["manifest_slice"] = {
            "task_type": manifest.get("task_type"),
            "selected_workflow": manifest.get("selected_workflow"),
            "agent_is_required": agent_required,
            "agent_skills": [s.get("skill") for s in agent_skills],
            "required_artifacts": [a.get("id") for a in agent_artifacts],
            "memory_policy": manifest.get("memory_policy"),
            "stop_gate_requirements": manifest.get("stop_gate_requirements", []),
        }
    return cap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default=None)
    ap.add_argument("--query", default="")
    ap.add_argument("--hook-output", action="store_true")
    args = ap.parse_args()

    hook_input = _stdin_json() if args.hook_output else {}
    agent, session_id = _resolve_identity(args.agent, hook_input)
    cap = build_capsule(agent, session_id, args.query)

    write_json(STATE / "agent-context" / session_id / f"{agent}.json", cap)

    if args.hook_output:
        context_text = f"Agent-specific graph context for {agent}:\n" + json.dumps(cap, indent=2)[:CAPSULE_CHAR_CAP]
        print(json.dumps({
            "hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": context_text},
        }))
    else:
        print(json.dumps(cap, indent=2))


if __name__ == "__main__":
    main()
