#!/usr/bin/env python3
"""Check manifest satisfaction: which required artifacts exist, which validations ran.

Used by:
  - PostToolBatch hook (refresh after tool use)
  - audit-gate.sh (Stop hook — surface unmet requirements)

Output (--json): {"trivial": bool, "unmet_requirements": [...], "verdict_hint": str}
"""
import argparse
import json
from pathlib import Path

from _brain_common import STATE, load_json

MANIFEST_PATH = STATE / "execution-manifest.json"
ARTIFACTS_DIR = STATE / "artifacts" / "current"
MODEL_EFFORT_PATH = STATE / "model-effort-schedule.json"

_TIER_KEYS = [
    "planning_tier", "execution_tier", "review_tier",
    "planning_effort_tier", "execution_effort_tier", "review_effort_tier",
    "cheap_execution_allowed", "plan_frozen",
]

_TRIVIAL_GATES = frozenset(["Trivial turn; no audit needed"])

_TRIVIAL_TASK_TYPES = frozenset({"terminal_help", "question", "docstring_only"})


def _stop_gate_is_trivial(stop_gate: list[str]) -> bool:
    return bool(set(stop_gate) & _TRIVIAL_GATES)


def _artifact_exists(art: dict) -> bool:
    path_str = art.get("path", "")
    if not path_str:
        return False
    p = Path(path_str)
    if not p.is_absolute():
        from _brain_common import ROOT
        p = ROOT / p
    return p.exists() and p.stat().st_size > 0


def check(manifest_path: Path = MANIFEST_PATH) -> dict:
    m = load_json(manifest_path, {})
    if not m:
        return {"trivial": True, "unmet_requirements": [], "verdict_hint": "no manifest found"}

    task_type = m.get("task_type", "question")
    stop_gate = m.get("stop_gate_requirements", [])

    if task_type in _TRIVIAL_TASK_TYPES or _stop_gate_is_trivial(stop_gate):
        return {"trivial": True, "unmet_requirements": [], "verdict_hint": "trivial task"}

    unmet: list[str] = []

    for art in m.get("required_artifacts", []):
        if not art.get("required", False):
            continue
        if not _artifact_exists(art):
            unmet.append(f"artifact missing: {art.get('id')} ({art.get('path')})")

    mem_policy = m.get("memory_policy", "")
    if mem_policy not in ("skip", ""):
        mem_arts = [
            a for a in m.get("required_artifacts", [])
            if a.get("id") == "memory_candidate" and a.get("required", False)
        ]
        if mem_arts and not _artifact_exists(mem_arts[0]):
            pass

    agent_runs_path = STATE / "agent-runs.ndjson"
    ran_agents: set[str] = set()
    if agent_runs_path.exists():
        for line in agent_runs_path.read_text().splitlines():
            try:
                entry = json.loads(line)
                if entry.get("event") in ("subagent-start", "subagent-stop"):
                    ran_agents.add(entry.get("agent", ""))
            except (json.JSONDecodeError, KeyError):
                pass

    for agent in m.get("required_agents", []):
        if agent and agent not in ran_agents:
            unmet.append(f"required agent not run: {agent}")

    advisory: list[str] = []
    me_sched = load_json(MODEL_EFFORT_PATH, {})
    if me_sched:
        for key in _TIER_KEYS:
            manifest_val = m.get(key)
            sched_val = me_sched.get(key)
            if manifest_val is not None and sched_val is not None and manifest_val != sched_val:
                advisory.append(
                    f"tier mismatch for {key!r}: manifest={manifest_val!r}, "
                    f"model-effort-schedule={sched_val!r}"
                )
    else:
        advisory.append("model-effort-schedule.json not found — run build_execution_manifest.py")

    if not unmet:
        verdict_hint = "Pass"
    elif len(unmet) <= 2:
        verdict_hint = "Needs Fix"
    else:
        verdict_hint = "Blocked"

    return {
        "trivial": False,
        "task_type": task_type,
        "workflow": m.get("selected_workflow"),
        "unmet_requirements": unmet,
        "advisory": advisory,
        "verdict_hint": verdict_hint,
        "required_agents": m.get("required_agents", []),
        "ran_agents": sorted(ran_agents),
        "stop_gate_requirements": stop_gate,
        "plan_frozen": m.get("plan_frozen", False),
        "planning_tier": m.get("planning_tier", ""),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Check execution manifest satisfaction.")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--manifest", default=None)
    args = ap.parse_args()

    path = Path(args.manifest) if args.manifest else MANIFEST_PATH
    result = check(path)

    if args.as_json:
        print(json.dumps(result, indent=2))
        return

    if result.get("trivial"):
        print("Status: Trivial; no audit needed")
        return

    unmet = result.get("unmet_requirements", [])
    print(f"Status: {result.get('verdict_hint', 'Unknown')}")
    print(f"task_type: {result.get('task_type')}  workflow: {result.get('workflow')}")
    if unmet:
        print(f"Unmet ({len(unmet)}):")
        for u in unmet:
            print(f"  - {u}")
    else:
        print("All manifest requirements satisfied.")


if __name__ == "__main__":
    main()
