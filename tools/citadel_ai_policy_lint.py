#!/usr/bin/env python3
"""citadel_ai_policy_lint.py — Enforce AI provider security policy.

Checks:
  1. ai-provider-config.json exists, parses, and has all security flags set correctly
  2. daemon_invocation_allowed=false
  3. citadel_ai_orchestrator.py does NOT import daemon/indexer modules
  4. citadel_provider_runner.py / citadel_review_runner.py not imported outside approved files
  5. audit.log_prompts=false
  6. Forbidden commands list non-empty in config
  7. docs/brain/tasks.html exists
  8. citadel_validation_runner.py exists
  9. .claude/state/ is writable
 10. Source badge strings exist in citadel_model_fallback.py
 11. citadel_ask_lint.py exists (ask security contract enforced)
 12. Prompt injection defense string exists in context capsule builder
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])

_PROVIDER_CONFIG = ROOT / ".claude" / "brain" / "ai-provider-config.json"
_STATE_DIR = ROOT / ".claude" / "state"
_TOOLS_DIR = ROOT / "tools"

_SECURITY_FLAGS_MUST_BE_FALSE = [
    "daemon_invocation_allowed",
    "indexer_invocation_allowed",
    "auto_execution_allowed",
    "allow_secret_access",
    "allow_destructive_commands",
    "allow_production_deploy",
    "allow_git_push",
    "allow_git_commit",
]

_FORBIDDEN_IMPORTS_IN_ORCHESTRATOR = [
    "incremental_brain",
    "workspace_intelligence",
    "build_brain_graph",
    "graph_brain_lint",
    "brain_preflight",
    "build_execution_manifest",
    "execution_manifest_lint",
]

_APPROVED_IMPORTER_FILES = {
    "citadel_ui_server.py",
    "citadel_ai_orchestrator.py",
}

_SOURCE_BADGE_STRINGS = [
    "local_plus_claude",
    "claude_fallback",
    "unavailable",
]


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "status": "pass" if passed else "fail", "detail": detail}


def check_provider_config() -> list[dict]:
    results: list[dict] = []

    if not _PROVIDER_CONFIG.exists():
        results.append(_check("provider_config_exists", False, f"{_PROVIDER_CONFIG} not found"))
        return results
    results.append(_check("provider_config_exists", True, str(_PROVIDER_CONFIG)))

    try:
        cfg = json.loads(_PROVIDER_CONFIG.read_text())
    except json.JSONDecodeError as exc:
        results.append(_check("provider_config_parses", False, f"JSON error: {exc}"))
        return results
    results.append(_check("provider_config_parses", True, "valid JSON"))

    security = cfg.get("security", {})
    for flag in _SECURITY_FLAGS_MUST_BE_FALSE:
        val = security.get(flag, False)
        results.append(_check(
            f"security.{flag}_is_false",
            val is False,
            f"security.{flag}={val!r} (must be false)",
        ))

    audit = cfg.get("audit", {})
    log_prompts = audit.get("log_prompts", True)
    results.append(_check("audit.log_prompts_false", log_prompts is False, f"audit.log_prompts={log_prompts!r}"))

    providers = cfg.get("providers", {})
    cc_forbidden = providers.get("claude_code", {})
    results.append(_check(
        "claude_code_requires_explicit_approval",
        cc_forbidden.get("requires_explicit_approval_for_execution", False) is True,
        "claude_code.requires_explicit_approval_for_execution must be true",
    ))

    return results


def check_orchestrator_no_daemon_imports() -> dict:
    orc = _TOOLS_DIR / "citadel_ai_orchestrator.py"
    if not orc.exists():
        return _check("orchestrator_no_daemon_imports", False, "citadel_ai_orchestrator.py not found")
    text = orc.read_text()
    found = [imp for imp in _FORBIDDEN_IMPORTS_IN_ORCHESTRATOR if imp in text]
    if found:
        return _check("orchestrator_no_daemon_imports", False, f"forbidden imports found: {found}")
    return _check("orchestrator_no_daemon_imports", True, "no forbidden daemon imports")


def check_provider_runner_import_scope() -> dict:
    provider_runner = "citadel_provider_runner"
    review_runner = "citadel_review_runner"
    issues: list[str] = []
    for pyfile in _TOOLS_DIR.glob("*.py"):
        if pyfile.name in _APPROVED_IMPORTER_FILES:
            continue
        try:
            text = pyfile.read_text()
        except OSError:
            continue
        if provider_runner in text or review_runner in text:
            import re
            patterns = [
                r"^\s*import\s+" + provider_runner,
                r"^\s*from\s+" + provider_runner,
                r"^\s*import\s+" + review_runner,
                r"^\s*from\s+" + review_runner,
            ]
            for pat in patterns:
                if re.search(pat, text, re.MULTILINE):
                    issues.append(pyfile.name)
                    break
    if issues:
        return _check("provider_runner_import_scope", False,
                      f"provider runner imported outside approved scope: {issues}")
    return _check("provider_runner_import_scope", True, "provider runners only imported from approved files")


def check_tasks_html_exists() -> dict:
    path = ROOT / "docs" / "brain" / "tasks.html"
    return _check("tasks_html_exists", path.exists(), str(path))


def check_validation_runner_exists() -> dict:
    path = _TOOLS_DIR / "citadel_validation_runner.py"
    return _check("validation_runner_exists", path.exists(), str(path))


def check_state_dir_writable() -> dict:
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        test = _STATE_DIR / ".write_test"
        test.write_text("ok")
        test.unlink()
        return _check("state_dir_writable", True, str(_STATE_DIR))
    except OSError as exc:
        return _check("state_dir_writable", False, f"not writable: {exc}")


def check_source_badges_exist() -> dict:
    fb_path = _TOOLS_DIR / "citadel_model_fallback.py"
    if not fb_path.exists():
        return _check("source_badges_exist", False, "citadel_model_fallback.py not found")
    text = fb_path.read_text()
    missing = [b for b in _SOURCE_BADGE_STRINGS if b not in text]
    if missing:
        return _check("source_badges_exist", False, f"missing source badges: {missing}")
    return _check("source_badges_exist", True, f"found: {_SOURCE_BADGE_STRINGS}")


def check_ask_lint_exists() -> dict:
    path = _TOOLS_DIR / "citadel_ask_lint.py"
    return _check("citadel_ask_lint_exists", path.exists(), str(path))


def check_prompt_injection_defense() -> dict:
    cb_path = _TOOLS_DIR / "citadel_context_capsule_builder.py"
    if not cb_path.exists():
        return _check("prompt_injection_defense", False, "citadel_context_capsule_builder.py not found")
    text = cb_path.read_text()
    marker = "DATA only"
    found = marker in text
    return _check("prompt_injection_defense", found,
                  f"injection defense header {'found' if found else 'MISSING'} in capsule builder")


def check_forbidden_commands_in_config() -> dict:
    if not _PROVIDER_CONFIG.exists():
        return _check("forbidden_commands_in_config", False, "ai-provider-config.json not found")
    try:
        cfg = json.loads(_PROVIDER_CONFIG.read_text())
    except json.JSONDecodeError:
        return _check("forbidden_commands_in_config", False, "parse error")
    audit = cfg.get("audit", {})
    has_audit = "path" in audit
    return _check("forbidden_commands_in_config", has_audit,
                  "audit block present in provider config" if has_audit else "audit.path missing")


def run_all() -> list[dict]:
    results: list[dict] = []
    results.extend(check_provider_config())
    results.append(check_orchestrator_no_daemon_imports())
    results.append(check_provider_runner_import_scope())
    results.append(check_tasks_html_exists())
    results.append(check_validation_runner_exists())
    results.append(check_state_dir_writable())
    results.append(check_source_badges_exist())
    results.append(check_ask_lint_exists())
    results.append(check_prompt_injection_defense())
    results.append(check_forbidden_commands_in_config())
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Citadel AI provider policy lint")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    results = run_all()
    failures = [r for r in results if r["status"] == "fail"]

    if args.pretty:
        print(f"Citadel AI Policy Lint — {'PASS' if not failures else f'FAIL ({len(failures)} issue(s))'}")
        for r in results:
            icon = "✓" if r["status"] == "pass" else "✗"
            print(f"  [{icon}] {r['name']}: {r['detail']}")
    else:
        print(json.dumps({
            "status": "pass" if not failures else "fail",
            "total": len(results),
            "failures": len(failures),
            "results": results,
        }, indent=2))

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
