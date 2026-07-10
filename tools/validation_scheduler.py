#!/usr/bin/env python3
"""Scheduler 9: Validation scheduler — thin CLI wrapper around build_execution_manifest.schedule_validations.

Shows the cheapest valid checks for a given task type.
Design principle: no broad validation when focused checks are enough.
"""
import argparse
import json
import sys

from _brain_common import ROOT, load_json

_MANIFEST_CFG = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"

_CHEAPNESS_NOTES = {
    "docstring_only":   "ruff focused file only — no tests needed",
    "terminal_help":    "no validation needed",
    "question":         "no validation needed",
    "test_creation":    "focused bdd/pytest on new tests only",
    "graph_brain_tooling": "graph/index/manifest/scheduler lints only",
    "feature_change":   "focused tests + ruff for touched files",
    "validation_only":  "run requested commands only",
}


def run(prompt: str, task_type: str | None = None, as_json: bool = False) -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from build_execution_manifest import classify_task_type, schedule_validations

    cfg = load_json(_MANIFEST_CFG, {})

    if task_type is None:
        task_type, confidence = classify_task_type(prompt, "question", cfg)
    else:
        confidence = 1.0

    task_to_wf = cfg.get("task_type_to_workflow", {})
    workflow_id = task_to_wf.get(task_type, "question_workflow")
    wf = cfg.get("workflows", {}).get(workflow_id, {})

    validations, tools = schedule_validations(wf)
    cheapness_note = _CHEAPNESS_NOTES.get(task_type, "use focused tests/lints for changed files only")

    result = {
        "task_type": task_type,
        "workflow": workflow_id,
        "required_validations": validations,
        "required_tools": tools,
        "cheapness_note": cheapness_note,
    }

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"task_type: {task_type}  workflow: {workflow_id}")
        print(f"cheapness: {cheapness_note}")
        print(f"required_validations ({len(validations)}):")
        for v in validations:
            print(f"  {v}")
        if tools:
            print(f"required_tools ({len(tools)}):")
            for t in tools:
                print(f"  {t}")

    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Show validation schedule for a prompt.")
    ap.add_argument("prompt", nargs="*")
    ap.add_argument("--task-type", default=None)
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()
    prompt = " ".join(args.prompt).strip() or "bootstrap"
    sys.exit(run(prompt, task_type=args.task_type, as_json=args.as_json))


if __name__ == "__main__":
    main()
