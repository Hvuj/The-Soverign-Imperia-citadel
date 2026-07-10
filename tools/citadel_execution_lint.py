#!/usr/bin/env python3
"""citadel_execution_lint.py — Lint execution manifests for policy compliance.

Checks that manifests conform to the AI provider security policy:
  - required fields present
  - forbidden commands list non-empty
  - allowed_files set before execution
  - status is valid
  - approval block is valid

Called from citadel_ai_policy_lint.py and can be run standalone.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
_MANIFESTS_DIR = ROOT / ".claude" / "state" / "execution-manifests"

_REQUIRED_TOP_FIELDS = {
    "schema_version", "task_id", "task_title", "task_type", "mode",
    "created_at", "status", "approval", "forbidden_commands",
}

_VALID_STATUSES = {
    "draft", "planned", "awaiting_plan_approval", "plan_rejected",
    "execution_approved", "executing", "execution_failed",
    "executed", "reviewing", "review_failed", "validating",
    "validation_failed", "completed", "blocked", "cancelled",
}

_REQUIRED_APPROVAL_FIELDS = {
    "plan_approved", "execution_approved", "approved_by_user",
}


def lint_manifest(data: dict, path: str = "") -> list[str]:
    issues: list[str] = []
    label = f"[{path}]" if path else ""

    missing = _REQUIRED_TOP_FIELDS - set(data.keys())
    if missing:
        issues.append(f"{label} missing required fields: {sorted(missing)}")

    status = data.get("status", "")
    if status not in _VALID_STATUSES:
        issues.append(f"{label} invalid status: {status!r}")

    forbidden = data.get("forbidden_commands", [])
    if not isinstance(forbidden, list) or len(forbidden) == 0:
        issues.append(f"{label} forbidden_commands must be a non-empty list")

    approval = data.get("approval", {})
    if not isinstance(approval, dict):
        issues.append(f"{label} approval must be a dict")
    else:
        missing_approval = _REQUIRED_APPROVAL_FIELDS - set(approval.keys())
        if missing_approval:
            issues.append(f"{label} approval missing fields: {sorted(missing_approval)}")

    if status == "execution_approved":
        allowed = data.get("allowed_files", [])
        if not allowed:
            issues.append(f"{label} status=execution_approved but allowed_files is empty")
        if not approval.get("execution_approved"):
            issues.append(f"{label} status=execution_approved but approval.execution_approved is false")
        if not approval.get("approved_by_user"):
            issues.append(f"{label} status=execution_approved but approval.approved_by_user is false")

    return issues


def lint_all() -> tuple[list[str], int]:
    if not _MANIFESTS_DIR.exists():
        return [], 0

    all_issues: list[str] = []
    count = 0
    for path in sorted(_MANIFESTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            all_issues.append(f"[{path.name}] parse error: {exc}")
            continue
        issues = lint_manifest(data, path.name)
        all_issues.extend(issues)
        count += 1

    return all_issues, count


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint Citadel execution manifests")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("manifest", nargs="?", help="Single manifest file to lint")
    args = parser.parse_args()

    if args.manifest:
        path = Path(args.manifest)
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        issues = lint_manifest(data, path.name)
        if args.pretty:
            if issues:
                print(f"FAIL ({len(issues)} issue(s)):")
                for i in issues:
                    print(f"  - {i}")
            else:
                print("PASS")
        else:
            print(json.dumps({"status": "fail" if issues else "pass", "issues": issues}))
        sys.exit(1 if issues else 0)

    all_issues, count = lint_all()
    if args.pretty:
        print(f"Checked {count} manifest(s): {'PASS' if not all_issues else f'FAIL ({len(all_issues)} issue(s))'}")
        for i in all_issues:
            print(f"  - {i}")
    else:
        print(json.dumps({"status": "fail" if all_issues else "pass", "count": count, "issues": all_issues}))
    sys.exit(1 if all_issues else 0)


if __name__ == "__main__":
    main()
