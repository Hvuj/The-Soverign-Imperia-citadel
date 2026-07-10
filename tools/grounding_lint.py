#!/usr/bin/env python3
"""grounding_lint.py — Verify Citadel grounding infrastructure exists and is correct.

Checks:
1. .claude/rules/grounding.md exists with content
2. docs/ai-context/system/grounding-policy.md exists
3. docs/brain/nodes/knowledge/knowledge-grounding-policy.md exists
4. tools/grounding_quote_extractor.py exists and compiles
5. tools/grounding_claim_verifier.py exists and compiles
6. Required phrases present in grounding policy
7. docs/ai-context/system/prompt-template-registry.md exists

Exit 0 = pass, exit 1 = fail.
"""

import argparse
import json
import os
import py_compile
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])


def _check(name: str, status: str, message: str) -> dict:
    return {"name": name, "status": status, "message": message}


def check_grounding_rules() -> dict:
    path = ROOT / ".claude" / "rules" / "grounding.md"
    if not path.exists():
        return _check("grounding_rules", "fail", ".claude/rules/grounding.md does not exist")
    content = path.read_text(errors="replace").strip()
    if len(content) < 100:
        return _check("grounding_rules", "fail", ".claude/rules/grounding.md exists but appears empty/stub")
    return _check("grounding_rules", "pass", f".claude/rules/grounding.md exists ({len(content)} chars)")


def check_grounding_policy_doc() -> dict:
    path = ROOT / "docs" / "ai-context" / "system" / "grounding-policy.md"
    if not path.exists():
        return _check("grounding_policy_doc", "fail",
                      "docs/ai-context/system/grounding-policy.md does not exist")
    content = path.read_text(errors="replace").strip()
    if len(content) < 200:
        return _check("grounding_policy_doc", "fail",
                      "docs/ai-context/system/grounding-policy.md appears empty/stub")
    return _check("grounding_policy_doc", "pass",
                  f"docs/ai-context/system/grounding-policy.md exists ({len(content)} chars)")


def check_grounding_brain_node() -> dict:
    path = ROOT / "docs" / "brain" / "nodes" / "knowledge" / "knowledge-grounding-policy.md"
    if not path.exists():
        return _check("grounding_brain_node", "fail",
                      "docs/brain/nodes/knowledge/knowledge-grounding-policy.md does not exist")
    return _check("grounding_brain_node", "pass",
                  "docs/brain/nodes/knowledge/knowledge-grounding-policy.md exists")


def check_tool_compiles(tool_name: str) -> dict:
    path = ROOT / "tools" / tool_name
    if not path.exists():
        return _check(f"tool_{tool_name}", "fail", f"tools/{tool_name} does not exist")
    try:
        py_compile.compile(str(path), doraise=True)
        return _check(f"tool_{tool_name}", "pass", f"tools/{tool_name} compiles OK")
    except py_compile.PyCompileError as exc:
        return _check(f"tool_{tool_name}", "fail", f"tools/{tool_name} compile error: {exc}")


def check_required_phrases() -> dict:
    paths = [
        ROOT / ".claude" / "rules" / "grounding.md",
        ROOT / "docs" / "ai-context" / "system" / "grounding-policy.md",
    ]
    required = [
        "I do not have enough information",
        "No relevant quotes found",
        "assumption, not a verified fact",
    ]
    missing_phrases = []
    for phrase in required:
        found_in_any = False
        for p in paths:
            if p.exists() and phrase.lower() in p.read_text(errors="replace").lower():
                found_in_any = True
                break
        if not found_in_any:
            missing_phrases.append(phrase)
    if missing_phrases:
        return _check("required_phrases", "fail",
                      f"Required phrases missing from grounding docs: {missing_phrases}")
    return _check("required_phrases", "pass", "All required grounding phrases present")


def check_template_registry_doc() -> dict:
    path = ROOT / "docs" / "ai-context" / "system" / "prompt-template-registry.md"
    if not path.exists():
        return _check("template_registry_doc", "fail",
                      "docs/ai-context/system/prompt-template-registry.md does not exist")
    return _check("template_registry_doc", "pass",
                  "docs/ai-context/system/prompt-template-registry.md exists")


def run_checks() -> list[dict]:
    checks = [
        check_grounding_rules(),
        check_grounding_policy_doc(),
        check_grounding_brain_node(),
        check_tool_compiles("grounding_quote_extractor.py"),
        check_tool_compiles("grounding_claim_verifier.py"),
        check_required_phrases(),
        check_template_registry_doc(),
    ]
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint Citadel grounding infrastructure.")
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
        print(f"grounding_lint: {overall.upper()} ({passed} pass, {failed} fail, {warned} warn)")
        for c in checks:
            icon = {"pass": "✓", "fail": "✗", "warn": "!"}.get(c["status"], "?")
            print(f"  [{icon}] {c['name']}: {c['message']}")
    else:
        print(json.dumps(result, indent=2))

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
