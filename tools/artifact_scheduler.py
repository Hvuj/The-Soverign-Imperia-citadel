#!/usr/bin/env python3
"""Scheduler 8: Artifact scheduler — thin CLI wrapper around build_execution_manifest.schedule_artifacts.

Shows which artifacts are required/conditional for a given task type.
Reads canonical policy from .claude/brain/artifact-policy.json.
"""
import argparse
import json
import sys

from _brain_common import ROOT, load_artifact_policy, load_json

_MANIFEST_CFG = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"


def run(prompt: str, task_type: str | None = None, as_json: bool = False) -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from build_execution_manifest import classify_task_type, schedule_artifacts

    cfg = load_json(_MANIFEST_CFG, {})

    if task_type is None:
        task_type, confidence = classify_task_type(prompt, "question", cfg)
    else:
        confidence = 1.0

    artifact_policy = load_artifact_policy()
    artifacts = schedule_artifacts(task_type, artifact_policy)

    required = [a for a in artifacts if a.get("required")]
    conditional = [a for a in artifacts if not a.get("required")]

    result = {
        "task_type": task_type,
        "artifact_policy_version": artifact_policy.get("version", "unknown"),
        "required_artifacts": required,
        "conditional_artifacts": conditional,
    }

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"task_type: {task_type}")
        print(f"required_artifacts ({len(required)}):")
        for a in required:
            print(f"  {a['id']}: {a['path']}")
        print(f"conditional_artifacts ({len(conditional)}):")
        for a in conditional:
            print(f"  {a['id']}: {a.get('condition', 'when applicable')}")

    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Show artifact schedule for a prompt.")
    ap.add_argument("prompt", nargs="*")
    ap.add_argument("--task-type", default=None)
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()
    prompt = " ".join(args.prompt).strip() or "bootstrap"
    sys.exit(run(prompt, task_type=args.task_type, as_json=args.as_json))


if __name__ == "__main__":
    main()
