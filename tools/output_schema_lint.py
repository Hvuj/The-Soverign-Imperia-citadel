#!/usr/bin/env python3
"""output_schema_lint.py — Verify Citadel output schema infrastructure exists and is valid.

Checks:
1. .claude/schemas/ directory exists
2. All required schemas exist
3. All schemas are valid JSON
4. Each schema has $schema, type: object, required array, properties
5. tools/output_normalizer.py exists and compiles
6. .claude/brain/prompt-template-registry.json exists and is valid JSON
7. Each template in registry references a valid output_schema

Exit 0 = pass, exit 1 = fail.
"""

import argparse
import json
import os
import py_compile
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
SCHEMAS_DIR = ROOT / ".claude" / "schemas"

REQUIRED_SCHEMAS = [
    "ask-response.schema.json",
    "execution-manifest.schema.json",
    "provider-plan.schema.json",
    "provider-review.schema.json",
    "validation-result.schema.json",
    "learning-candidate.schema.json",
    "system-health.schema.json",
    "workspace-summary.schema.json",
    "workspace-repo.schema.json",
    "workspace-dir.schema.json",
    "workspace-module.schema.json",
    "workspace-file.schema.json",
    "workspace-source-range.schema.json",
    "claim-verification.schema.json",
    "quote-extraction.schema.json",
    "provider-status.schema.json",
    "legion-run-ledger.schema.json",
    "legion-current-run.schema.json",
    "bi-understanding.schema.json",
    "benchmark-report.schema.json",
]


def _check(name: str, status: str, message: str) -> dict:
    return {"name": name, "status": status, "message": message}


def check_schemas_dir() -> dict:
    if SCHEMAS_DIR.exists() and SCHEMAS_DIR.is_dir():
        return _check("schemas_dir", "pass", ".claude/schemas/ directory exists")
    return _check("schemas_dir", "fail", ".claude/schemas/ directory does not exist")


def check_required_schemas() -> list[dict]:
    checks = []
    for schema_name in REQUIRED_SCHEMAS:
        path = SCHEMAS_DIR / schema_name
        if not path.exists():
            checks.append(_check(f"schema_{schema_name}", "fail",
                                 f"{schema_name} does not exist"))
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            checks.append(_check(f"schema_{schema_name}", "fail",
                                 f"{schema_name} invalid JSON: {exc}"))
            continue

        issues = []
        if "$schema" not in data:
            issues.append("missing $schema")
        if data.get("type") != "object":
            issues.append(f"type is {data.get('type')!r}, expected 'object'")
        if "properties" not in data:
            issues.append("missing properties")
        if "required" not in data:
            issues.append("missing required array")
        elif not isinstance(data["required"], list):
            issues.append("required is not an array")
        elif len(data["required"]) == 0:
            issues.append("required array is empty")

        if issues:
            checks.append(_check(f"schema_{schema_name}", "fail",
                                 f"{schema_name} structure issues: {issues}"))
        else:
            required_count = len(data.get("required", []))
            checks.append(_check(f"schema_{schema_name}", "pass",
                                 f"{schema_name} valid ({required_count} required fields)"))
    return checks


def check_output_normalizer() -> dict:
    path = ROOT / "tools" / "output_normalizer.py"
    if not path.exists():
        return _check("output_normalizer", "fail", "tools/output_normalizer.py does not exist")
    try:
        py_compile.compile(str(path), doraise=True)
        return _check("output_normalizer", "pass", "tools/output_normalizer.py compiles OK")
    except py_compile.PyCompileError as exc:
        return _check("output_normalizer", "fail", f"tools/output_normalizer.py compile error: {exc}")


def check_template_registry() -> list[dict]:
    path = ROOT / ".claude" / "brain" / "prompt-template-registry.json"
    if not path.exists():
        return [_check("template_registry", "fail",
                       ".claude/brain/prompt-template-registry.json does not exist")]

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [_check("template_registry", "fail",
                       f"prompt-template-registry.json invalid JSON: {exc}")]

    checks = [_check("template_registry", "pass",
                     "prompt-template-registry.json is valid JSON")]

    templates = data.get("templates", {})
    if not templates:
        checks.append(_check("template_registry_content", "fail",
                             "prompt-template-registry.json has no templates"))
        return checks

    known_schemas = {s.replace(".schema.json", "") for s in REQUIRED_SCHEMAS}
    bad_refs = []
    for tid, tdef in templates.items():
        schema_ref = tdef.get("output_schema", "")
        schema_base = schema_ref.replace(".schema.json", "")
        if schema_base and schema_base not in known_schemas:
            bad_refs.append(f"{tid}: {schema_ref!r}")

    if bad_refs:
        checks.append(_check("template_schema_refs", "fail",
                             f"Templates reference unknown schemas: {bad_refs}"))
    else:
        checks.append(_check("template_schema_refs", "pass",
                             f"All {len(templates)} template schema references valid"))
    return checks


def run_checks() -> list[dict]:
    checks = []
    checks.append(check_schemas_dir())
    checks.extend(check_required_schemas())
    checks.append(check_output_normalizer())
    checks.extend(check_template_registry())
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint Citadel output schema infrastructure.")
    parser.add_argument("--pretty", action="store_true", help="Print human-readable output.")
    parser.add_argument("--json", action="store_true", help="Output JSON.")
    args = parser.parse_args()

    checks = run_checks()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    warned = sum(1 for c in checks if c["status"] == "warn")
    overall = "pass" if failed == 0 else "fail"

    result = {
        "status": overall,
        "checks": checks,
        "summary": {"pass": passed, "fail": failed, "warn": warned},
    }

    if args.pretty or not args.json:
        print(f"output_schema_lint: {overall.upper()} ({passed} pass, {failed} fail, {warned} warn)")
        for c in checks:
            icon = {"pass": "✓", "fail": "✗", "warn": "!"}.get(c["status"], "?")
            print(f"  [{icon}] {c['name']}: {c['message']}")
    else:
        print(json.dumps(result, indent=2))

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
