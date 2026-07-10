#!/usr/bin/env python3
"""citadel_ask_lint.py — Security and config lint for Ask Citadel.

Checks:
  - citadel-ask-config.json exists and is valid JSON
  - Security flags (fallback_allow_*) all set to false
  - max_model_calls_per_question <= 1
  - allow_model_fallback is boolean
  - Daemon/index-builder files do not import citadel_model_fallback
  - /api/ask response schema includes source, evidence, model_fallback_used
  - Audit log path set if audit_log_enabled
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
TOOLS = ROOT / "tools"


def _fail(msg: str, issues: list[str]) -> None:
    issues.append(msg)


def lint_config(issues: list[str]) -> dict | None:
    path = ROOT / ".claude" / "brain" / "citadel-ask-config.json"
    if not path.exists():
        _fail(f"MISSING: citadel-ask-config.json not found at {path}", issues)
        return None
    try:
        cfg = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        _fail(f"INVALID JSON: citadel-ask-config.json: {exc}", issues)
        return None

    for flag in (
        "fallback_allow_shell",
        "fallback_allow_edits",
        "fallback_allow_external_network",
        "fallback_allow_arbitrary_file_reads",
        "fallback_allow_secret_access",
    ):
        val = cfg.get(flag)
        if val is not False:
            _fail(f"SECURITY: {flag}={val!r} must be false", issues)

    max_calls = cfg.get("max_model_calls_per_question", 1)
    if not isinstance(max_calls, int) or max_calls > 1:
        _fail(f"SECURITY: max_model_calls_per_question={max_calls!r} must be integer <= 1", issues)

    amf = cfg.get("allow_model_fallback")
    if not isinstance(amf, bool):
        _fail(f"CONFIG: allow_model_fallback={amf!r} must be boolean true or false", issues)

    return cfg


def lint_import_isolation(issues: list[str]) -> None:
    """Only citadel_ui_server.py may import citadel_model_fallback."""
    fallback_module = "citadel_model_fallback"
    forbidden_importers = [
        "build_workspace_intelligence_index.py",
        "workspace_intelligence_query.py",
        "workspace_intelligence_lint.py",
        "build_brain_graph.py",
        "incremental_brain_daemon.py",
        "mandatory_auto_lint.py",
        "graph_brain_lint.py",
        "citadel_system_health.py",
        "scheduler_lint.py",
    ]
    for fname in forbidden_importers:
        fpath = TOOLS / fname
        if not fpath.exists():
            continue
        src = fpath.read_text(errors="replace")
        if fallback_module in src:
            _fail(f"ISOLATION: {fname} must not import {fallback_module}", issues)


def lint_response_schema(issues: list[str]) -> None:
    """Check /api/ask handler includes required response fields."""
    server = TOOLS / "citadel_ui_server.py"
    if not server.exists():
        _fail("MISSING: citadel_ui_server.py not found", issues)
        return
    src = server.read_text(errors="replace")
    if '"source"' not in src and "source=" not in src:
        _fail('SCHEMA: citadel_ui_server.py may be missing "source" field in /api/ask responses', issues)
    if '"evidence"' not in src and "evidence=" not in src:
        _fail('SCHEMA: citadel_ui_server.py may be missing "evidence" field in /api/ask responses', issues)
    if "model_fallback_used" not in src:
        _fail('SCHEMA: citadel_ui_server.py does not set model_fallback_used (required for fallback responses)', issues)


def lint_audit_log_config(cfg: dict | None, issues: list[str]) -> None:
    if cfg is None:
        return
    if cfg.get("audit_log_enabled") and not cfg.get("audit_log_path"):
        _fail("CONFIG: audit_log_enabled=true but audit_log_path not set", issues)


def lint_source_badge_values(issues: list[str]) -> None:
    """Check UI handles all valid source values."""
    graph_js = ROOT / "docs" / "brain" / "graph.js"
    if not graph_js.exists():
        return
    src = graph_js.read_text(errors="replace")
    for badge in ("local_plus_claude", "claude_fallback"):
        if badge not in src:
            _fail(f"UI: graph.js does not handle source badge value: {badge!r}", issues)


def main(pretty: bool = False) -> int:
    issues: list[str] = []

    cfg = lint_config(issues)
    lint_import_isolation(issues)
    lint_response_schema(issues)
    lint_audit_log_config(cfg, issues)
    lint_source_badge_values(issues)

    if pretty:
        if issues:
            print(f"citadel_ask_lint: {len(issues)} issue(s) found:")
            for i in issues:
                print(f"  • {i}")
        else:
            print("citadel_ask_lint: OK — all checks passed")
        return 1 if issues else 0

    result = {
        "status": "ok" if not issues else "fail",
        "issues": issues,
        "issue_count": len(issues),
    }
    print(json.dumps(result, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Lint Ask Citadel security config and schema")
    p.add_argument("--pretty", action="store_true", help="Human-readable output")
    args = p.parse_args()
    sys.exit(main(pretty=args.pretty))
