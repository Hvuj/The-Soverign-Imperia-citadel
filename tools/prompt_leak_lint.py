#!/usr/bin/env python3
"""prompt_leak_lint.py — Verify Citadel prompt-leak defense infrastructure exists and is correct.

Checks:
1. .claude/rules/prompt-leak-policy.md exists with content
2. docs/ai-context/system/prompt-leak-policy.md exists
3. tools/prompt_leak_output_filter.py exists and compiles
4. No leaked markers in docs/ai-context/system/ content
5. ai-provider-config.json has prompt_logging not enabled
6. prompt-template-registry.json has prompt_leak_policy field on templates

Exit 0 = pass, exit 1 = fail.
"""

import argparse
import json
import os
import py_compile
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])

_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY", re.IGNORECASE),
    re.compile(r"(API_KEY|SECRET_KEY|ACCESS_TOKEN|AUTH_TOKEN)\s*=\s*[A-Za-z0-9_\-]{8,}", re.IGNORECASE),
]


def _check(name: str, status: str, message: str) -> dict:
    return {"name": name, "status": status, "message": message}


def check_prompt_leak_rules() -> dict:
    path = ROOT / ".claude" / "rules" / "prompt-leak-policy.md"
    if not path.exists():
        return _check("prompt_leak_rules", "fail",
                      ".claude/rules/prompt-leak-policy.md does not exist")
    content = path.read_text(errors="replace").strip()
    if len(content) < 100:
        return _check("prompt_leak_rules", "fail",
                      ".claude/rules/prompt-leak-policy.md appears empty/stub")
    return _check("prompt_leak_rules", "pass",
                  f".claude/rules/prompt-leak-policy.md exists ({len(content)} chars)")


def check_prompt_leak_policy_doc() -> dict:
    path = ROOT / "docs" / "ai-context" / "system" / "prompt-leak-policy.md"
    if not path.exists():
        return _check("prompt_leak_policy_doc", "fail",
                      "docs/ai-context/system/prompt-leak-policy.md does not exist")
    content = path.read_text(errors="replace").strip()
    if len(content) < 100:
        return _check("prompt_leak_policy_doc", "fail",
                      "docs/ai-context/system/prompt-leak-policy.md appears empty/stub")
    return _check("prompt_leak_policy_doc", "pass",
                  f"docs/ai-context/system/prompt-leak-policy.md exists ({len(content)} chars)")


def check_output_filter_compiles() -> dict:
    path = ROOT / "tools" / "prompt_leak_output_filter.py"
    if not path.exists():
        return _check("output_filter", "fail",
                      "tools/prompt_leak_output_filter.py does not exist")
    try:
        py_compile.compile(str(path), doraise=True)
        return _check("output_filter", "pass",
                      "tools/prompt_leak_output_filter.py compiles OK")
    except py_compile.PyCompileError as exc:
        return _check("output_filter", "fail",
                      f"tools/prompt_leak_output_filter.py compile error: {exc}")


def check_no_secrets_in_docs() -> dict:
    """Scan docs/ai-context/system/ for actual secret patterns (not example text)."""
    scan_dir = ROOT / "docs" / "ai-context" / "system"
    if not scan_dir.exists():
        return _check("no_secrets_in_docs", "warn",
                      "docs/ai-context/system/ does not exist — cannot scan")
    leaked = []
    for p in scan_dir.rglob("*.md"):
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for pattern in _SECRET_PATTERNS:
            matches = pattern.findall(text)
            if matches:
                leaked.append(f"{p.name}: pattern '{pattern.pattern[:30]}' found")
    if leaked:
        return _check("no_secrets_in_docs", "fail",
                      f"Secret-like patterns found in docs: {leaked}")
    return _check("no_secrets_in_docs", "pass",
                  "No secret patterns found in docs/ai-context/system/")


def check_ai_provider_prompt_logging() -> dict:
    path = ROOT / ".claude" / "brain" / "ai-provider-config.json"
    if not path.exists():
        return _check("ai_provider_prompt_logging", "warn",
                      "ai-provider-config.json not found — cannot verify prompt logging config")
    try:
        cfg = json.loads(path.read_text())
    except json.JSONDecodeError:
        return _check("ai_provider_prompt_logging", "fail",
                      "ai-provider-config.json invalid JSON")

    audit = cfg.get("audit", {})
    prompt_logging = audit.get("log_full_prompts", False) or audit.get("prompt_logging_enabled", False)
    if prompt_logging:
        return _check("ai_provider_prompt_logging", "fail",
                      "ai-provider-config.json has prompt logging ENABLED — security risk")
    return _check("ai_provider_prompt_logging", "pass",
                  "ai-provider-config.json does not enable full prompt logging")


def check_template_registry_leak_policy() -> dict:
    path = ROOT / ".claude" / "brain" / "prompt-template-registry.json"
    if not path.exists():
        return _check("template_registry_leak_policy", "warn",
                      "prompt-template-registry.json not found — cannot verify leak policy on templates")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return _check("template_registry_leak_policy", "fail",
                      "prompt-template-registry.json invalid JSON")

    templates = data.get("templates", {})
    missing_policy = [tid for tid, tdef in templates.items()
                      if "prompt_leak_policy" not in tdef]
    if missing_policy:
        return _check("template_registry_leak_policy", "fail",
                      f"Templates missing prompt_leak_policy: {missing_policy}")
    return _check("template_registry_leak_policy", "pass",
                  f"All {len(templates)} templates have prompt_leak_policy field")


def run_checks() -> list[dict]:
    return [
        check_prompt_leak_rules(),
        check_prompt_leak_policy_doc(),
        check_output_filter_compiles(),
        check_no_secrets_in_docs(),
        check_ai_provider_prompt_logging(),
        check_template_registry_leak_policy(),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint Citadel prompt-leak defense infrastructure.")
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
        print(f"prompt_leak_lint: {overall.upper()} ({passed} pass, {failed} fail, {warned} warn)")
        for c in checks:
            icon = {"pass": "✓", "fail": "✗", "warn": "!"}.get(c["status"], "?")
            print(f"  [{icon}] {c['name']}: {c['message']}")
    else:
        print(json.dumps(result, indent=2))

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
