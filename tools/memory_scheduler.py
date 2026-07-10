#!/usr/bin/env python3
"""Scheduler 10: Memory scheduler — thin CLI wrapper around build_execution_manifest.schedule_memory.

Shows the memory gate decision for a given task type.
Also surfaces domain_join_rules when the task type is relevant.
"""
import argparse
import json
import sys

from _brain_common import ROOT, load_json, load_memory_policy

_MANIFEST_CFG = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"


def run(prompt: str, task_type: str | None = None, as_json: bool = False) -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from build_execution_manifest import classify_task_type, schedule_memory

    cfg = load_json(_MANIFEST_CFG, {})
    memory_policy_data = load_memory_policy()

    if task_type is None:
        task_type, confidence = classify_task_type(prompt, "question", cfg)
    else:
        confidence = 1.0

    task_to_wf = cfg.get("task_type_to_workflow", {})
    workflow_id = task_to_wf.get(task_type, "question_workflow")
    wf = cfg.get("workflows", {}).get(workflow_id, {})

    memory_policy = schedule_memory(task_type, wf, memory_policy_data)

    relevant_rules = []
    for rule_name, rule_data in memory_policy_data.get("domain_join_rules", {}).items():
        relevant_types = rule_data.get("task_types_where_relevant", [])
        if task_type in relevant_types:
            relevant_rules.append({
                "rule_name": rule_name,
                "rule": rule_data.get("rule", ""),
                "applies_to": rule_data.get("applies_to", []),
            })

    result = {
        "task_type": task_type,
        "workflow": workflow_id,
        "memory_policy": memory_policy,
        "durable_triggers": memory_policy_data.get("memory_policy_rules", {}).get("durable_triggers", []),
        "not_durable": memory_policy_data.get("memory_policy_rules", {}).get("not_durable", []),
        "relevant_domain_rules": relevant_rules,
    }

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"task_type:     {task_type}  workflow: {workflow_id}")
        print(f"memory_policy: {memory_policy}")
        if relevant_rules:
            print(f"relevant_domain_rules ({len(relevant_rules)}):")
            for r in relevant_rules:
                print(f"  [{r['rule_name']}] {r['rule']}")
        else:
            print("no domain-specific join rules for this task type")

    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Show memory gate decision for a prompt.")
    ap.add_argument("prompt", nargs="*")
    ap.add_argument("--task-type", default=None)
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()
    prompt = " ".join(args.prompt).strip() or "bootstrap"
    sys.exit(run(prompt, task_type=args.task_type, as_json=args.as_json))


if __name__ == "__main__":
    main()
