#!/usr/bin/env python3
"""Scheduler 6: Agent budget — thin CLI wrapper around build_execution_manifest.schedule_agents.

Shows which agents are required vs. skipped and verifies the cap is respected.
Useful for debug/lint without running the full manifest builder.
"""
import argparse
import json
import sys

from _brain_common import ROOT, load_json

_MANIFEST_CFG = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"
_BRAIN_CFG = ROOT / ".claude" / "brain" / "graph-aware-config.json"

_DOCS_GRAPH_TYPES = frozenset({"docs_ingestion", "question", "terminal_help"})
_DOCS_GRAPH_CAP = 5
_DEFAULT_CAP = 8


def run(prompt: str, task_type: str | None = None, as_json: bool = False) -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from build_execution_manifest import (
        classify_task_type,
        schedule_agents,
    )

    cfg = load_json(_MANIFEST_CFG, {})
    brain_cfg = load_json(_BRAIN_CFG, {})

    if task_type is None:
        intent_val = "question"
        task_type, confidence = classify_task_type(prompt, intent_val, cfg)
    else:
        confidence = 1.0
        intent_val = "question"

    task_to_wf = cfg.get("task_type_to_workflow", {})
    workflow_id = task_to_wf.get(task_type, "question_workflow")
    wf = cfg.get("workflows", {}).get(workflow_id, {})

    required, skipped = schedule_agents(prompt, wf, brain_cfg, intent_val)

    cap = _DOCS_GRAPH_CAP if task_type in _DOCS_GRAPH_TYPES else _DEFAULT_CAP
    over_cap = len(required) > cap

    result = {
        "task_type": task_type,
        "workflow": workflow_id,
        "cap": cap,
        "over_cap": over_cap,
        "required_agents": required,
        "required_count": len(required),
        "skipped_count": len(skipped),
        "skipped_agents": skipped,
    }

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"task_type: {task_type}  workflow: {workflow_id}  cap: {cap}")
        print(f"required_agents ({len(required)}): {required}")
        if over_cap:
            print(f"WARN: {len(required)} agents exceeds cap {cap}")
        print(f"skipped ({len(skipped)} agents):")
        for s in skipped[:10]:
            print(f"  {s['agent']}: {s['reason']}")
        if len(skipped) > 10:
            print(f"  ... and {len(skipped) - 10} more")

    return 1 if over_cap else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Show agent budget schedule for a prompt.")
    ap.add_argument("prompt", nargs="*")
    ap.add_argument("--task-type", default=None)
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()
    prompt = " ".join(args.prompt).strip() or "bootstrap"
    sys.exit(run(prompt, task_type=args.task_type, as_json=args.as_json))


if __name__ == "__main__":
    main()
