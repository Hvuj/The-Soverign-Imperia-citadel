#!/usr/bin/env python3
"""citadel_system_health.py — Write real system health to docs/brain/system-status.json.

Runs 12 checks covering the incremental brain daemon, graph data, lint tools, UI files,
and the Citadel UI server, then writes a health JSON file consumed by the Citadel UI.

Exit code is always 0 — status is conveyed in the output file, never via exit code.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
STATE = ROOT / ".claude" / "state"
SEARCH_STATE = STATE / "brain-search"

_venv_py = ROOT / ".venv" / "bin" / "python"
PYTHON = str(_venv_py) if _venv_py.is_file() else "python3"

CRITICAL = {
    "incremental_brain_daemon",
    "graph_json_valid",
    "graph_has_nodes_links",
    "mandatory_auto_lint",
    "graph_brain_lint",
    "ui_file_graph_html",
    "ui_file_graph_css",
    "ui_file_graph_js",
    "ai_provider_config_valid",
    "daemon_no_ai_invocation_policy",
}


def _check(name: str, status: str, details: str, evidence: str = "") -> dict:
    return {"name": name, "status": status, "details": details, "evidence": evidence}


def run_tool(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", f"timeout after {timeout}s"
    except Exception as exc:
        return 1, "", str(exc)


def pid_alive(pid_file: Path) -> tuple[bool, str]:
    """Return (alive, evidence_string) for a PID file."""
    if not pid_file.exists():
        return False, "pid file not found"
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return False, "pid file unreadable"
    try:
        os.kill(pid, 0)
        return True, f"pid={pid} alive"
    except ProcessLookupError:
        return False, f"pid={pid} not running"
    except PermissionError:
        return True, f"pid={pid} alive (permission check)"


def check_incremental_brain_daemon() -> dict:
    alive, evidence = pid_alive(STATE / "incremental-brain-daemon.pid")
    if alive:
        return _check("incremental_brain_daemon", "green", "daemon running", evidence)
    return _check("incremental_brain_daemon", "red", "daemon not running", evidence)


def check_graph_json_valid() -> dict:
    path = ROOT / "docs" / "brain" / "graph.json"
    if not path.exists():
        return _check("graph_json_valid", "red", "graph.json missing", str(path))
    try:
        data = json.loads(path.read_text())
        return _check("graph_json_valid", "green", "graph.json valid JSON", f"{len(str(data))} chars"), data
    except json.JSONDecodeError as exc:
        return _check("graph_json_valid", "red", f"graph.json parse error: {exc}", str(path)), None


def check_graph_has_nodes_links(graph_data: dict | None) -> dict:
    if graph_data is None:
        return _check("graph_has_nodes_links", "red", "graph data unavailable (parse failed)", "")
    nodes = graph_data.get("nodes", [])
    links = graph_data.get("links", [])
    node_count = len(nodes)
    link_count = len(links)
    if node_count == 0:
        return _check("graph_has_nodes_links", "red", "graph has no nodes",
                      f"nodes={node_count} links={link_count}")
    if link_count == 0:
        return _check("graph_has_nodes_links", "yellow", "graph has nodes but no links",
                      f"nodes={node_count} links={link_count}")
    return _check("graph_has_nodes_links", "green", f"{node_count} nodes, {link_count} links",
                  f"nodes={node_count} links={link_count}")


def check_brain_search_index() -> dict:
    path = SEARCH_STATE / "index.json"
    if not path.exists():
        return _check("brain_search_index", "yellow", "brain search index missing", str(path))
    try:
        data = json.loads(path.read_text())
        n = len(data.get("nodes", data) if isinstance(data, dict) else data)
        return _check("brain_search_index", "green", "index exists", f"{n} entries")
    except json.JSONDecodeError:
        return _check("brain_search_index", "yellow", "index exists but invalid JSON", str(path))


def check_mandatory_auto_lint() -> dict:
    tool = ROOT / "tools" / "mandatory_auto_lint.py"
    if not tool.exists():
        return _check("mandatory_auto_lint", "yellow", "tool not found", str(tool))
    rc, stdout, stderr = run_tool([PYTHON, str(tool)])
    if rc == 0:
        return _check("mandatory_auto_lint", "green", "lint pass", "rc=0")
    detail = (stdout + " " + stderr).strip()[:200]
    return _check("mandatory_auto_lint", "red", "lint failed", f"rc={rc}: {detail}")


def check_graph_brain_lint() -> dict:
    tool = ROOT / "tools" / "graph_brain_lint.py"
    if not tool.exists():
        return _check("graph_brain_lint", "yellow", "tool not found", str(tool))
    rc, stdout, stderr = run_tool([PYTHON, str(tool)])
    if rc == 0:
        return _check("graph_brain_lint", "green", "lint pass", "rc=0")
    detail = (stdout + " " + stderr).strip()[:200]
    return _check("graph_brain_lint", "red", "lint failed", f"rc={rc}: {detail}")


def check_execution_manifest() -> dict:
    path = STATE / "execution-manifest.json"
    if not path.exists():
        return _check("execution_manifest", "yellow", "execution manifest absent", str(path))
    try:
        json.loads(path.read_text())
        return _check("execution_manifest", "green", "manifest valid JSON", str(path))
    except json.JSONDecodeError:
        return _check("execution_manifest", "yellow", "manifest invalid JSON", str(path))


def check_scheduler_health() -> dict:
    tool = ROOT / "tools" / "scheduler_lint.py"
    if not tool.exists():
        return _check("scheduler_health", "yellow", "scheduler_lint.py not present", "skipped")
    rc, stdout, stderr = run_tool([PYTHON, str(tool)])
    if rc == 0:
        return _check("scheduler_health", "green", "scheduler lint pass", "rc=0")
    detail = (stdout + " " + stderr).strip()[:200]
    return _check("scheduler_health", "yellow", f"scheduler lint issue: {detail[:80]}", f"rc={rc}")


def check_ui_file(name: str, path: Path) -> dict:
    if path.exists():
        return _check(f"ui_file_{name}", "green", f"{name} present", str(path))
    return _check(f"ui_file_{name}", "red", f"{name} missing", str(path))


def check_citadel_ui_server() -> dict:
    alive, evidence = pid_alive(STATE / "citadel-ui-server.pid")
    if alive:
        return _check("citadel_ui_server", "green", "UI server running", evidence)
    return _check("citadel_ui_server", "yellow", "UI server not running", evidence)


def check_workspace_index() -> dict:
    """Check workspace intelligence index exists and is valid."""
    ws_state = STATE / "workspace-intelligence"
    build_meta = ws_state / "build-metadata.json"
    ws_index = ws_state / "workspace-index.json"

    if not build_meta.exists():
        return _check("workspace_index", "yellow", "workspace-intelligence index not built",
                      str(build_meta))
    if not ws_index.exists():
        return _check("workspace_index", "yellow", "workspace-index.json missing", str(ws_index))

    try:
        bm = json.loads(build_meta.read_text())
        wi = json.loads(ws_index.read_text())
    except json.JSONDecodeError as exc:
        return _check("workspace_index", "yellow", f"workspace index invalid JSON: {exc}",
                      str(build_meta))

    repo_count = bm.get("repo_count", 0)
    file_count = bm.get("file_count", 0)
    if repo_count == 0:
        return _check("workspace_index", "yellow", "workspace index: repo_count=0",
                      f"build_id={bm.get('build_id', '?')}")
    if file_count == 0:
        return _check("workspace_index", "yellow", "workspace index: file_count=0",
                      f"repos={repo_count}")
    return _check("workspace_index", "green",
                  f"workspace index valid: repos={repo_count}, files={file_count}",
                  f"build_id={bm.get('build_id', '?')}, dur={bm.get('build_duration_sec', '?')}s")


def check_workspace_intelligence_daemon_running() -> dict:
    """Check workspace intelligence daemon PID (advisory — yellow when down, not red)."""
    alive, evidence = pid_alive(STATE / "workspace-intelligence" / "daemon.pid")
    if alive:
        return _check("workspace_intelligence_daemon", "green",
                      "workspace intelligence daemon running", evidence)
    return _check("workspace_intelligence_daemon", "yellow",
                  "workspace intelligence daemon not running", evidence)


def check_citadel_ask_config_valid() -> dict:
    path = ROOT / ".claude" / "brain" / "citadel-ask-config.json"
    if not path.exists():
        return _check("citadel_ask_config_valid", "yellow", "citadel-ask-config.json missing", str(path))
    try:
        cfg = json.loads(path.read_text())
        amf = cfg.get("allow_model_fallback", False)
        return _check("citadel_ask_config_valid", "green", "citadel-ask-config.json valid",
                      f"allow_model_fallback={amf}")
    except json.JSONDecodeError as exc:
        return _check("citadel_ask_config_valid", "red", f"citadel-ask-config.json parse error: {exc}", str(path))


def check_citadel_ask_skill_count() -> dict:
    skills_dir = ROOT / ".claude" / "skills"
    if not skills_dir.exists():
        return _check("citadel_ask_skill_count", "yellow", "skills dir not found", str(skills_dir))
    try:
        count = sum(
            1 for e in skills_dir.iterdir()
            if not e.name.startswith(".") and e.name != "__pycache__"
            and (e.is_dir() or e.suffix == ".md")
        )
        return _check("citadel_ask_skill_count", "green", f"{count} skills in .claude/skills/", str(skills_dir))
    except OSError as exc:
        return _check("citadel_ask_skill_count", "yellow", f"skills dir unreadable: {exc}", str(skills_dir))


def check_citadel_ask_agent_count() -> dict:
    agents_dir = ROOT / ".claude" / "agents"
    if not agents_dir.exists():
        return _check("citadel_ask_agent_count", "yellow", "agents dir not found", str(agents_dir))
    try:
        count = sum(
            1 for e in agents_dir.iterdir()
            if e.suffix == ".md" and not e.name.startswith(".")
        )
        return _check("citadel_ask_agent_count", "green", f"{count} agents in .claude/agents/", str(agents_dir))
    except OSError as exc:
        return _check("citadel_ask_agent_count", "yellow", f"agents dir unreadable: {exc}", str(agents_dir))


def check_citadel_ask_workflow_count() -> dict:
    manifest = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"
    if not manifest.exists():
        return _check("citadel_ask_workflow_count", "yellow", "workflow manifest not found", str(manifest))
    try:
        data = json.loads(manifest.read_text())
        count = len(data.get("task_types", {}))
        return _check("citadel_ask_workflow_count", "green",
                      f"{count} workflow types in manifest",
                      f"version={data.get('version', '?')}")
    except json.JSONDecodeError:
        return _check("citadel_ask_workflow_count", "yellow", "workflow manifest invalid JSON", str(manifest))


def check_citadel_ask_fallback_status() -> dict:
    """Multi-provider fallback health check.

    Supports: claude_cli, anthropic_sdk, auto (priority order).
    Reports resolved_provider, availability of each, and a human-readable message.
    NOTE: must NOT import the fallback module (isolation contract enforced by citadel_ask_lint.py).
    """
    import importlib.util as _ilu
    import shutil as _shutil

    path = ROOT / ".claude" / "brain" / "citadel-ask-config.json"
    if not path.exists():
        return _check("citadel_ask_fallback_status", "yellow", "citadel-ask-config.json missing", str(path))
    try:
        cfg = json.loads(path.read_text())
    except json.JSONDecodeError:
        return _check("citadel_ask_fallback_status", "red", "citadel-ask-config.json invalid JSON", str(path))

    enabled = cfg.get("allow_model_fallback", False)
    if not enabled:
        base = _check("citadel_ask_fallback_status", "green", "model fallback disabled (intentional)", "")
        base.update({"fallback_enabled": False, "configured_provider": cfg.get("model_fallback_provider", "auto"),
                     "resolved_provider": None, "claude_cli_available": False,
                     "anthropic_sdk_available": False, "fallback_status": "green",
                     "fallback_message": "model fallback disabled (intentional)"})
        return base

    cli_ok = _shutil.which("claude") is not None
    sdk_ok = _ilu.find_spec("anthropic") is not None

    raw_provider = cfg.get("model_fallback_provider", "auto")
    if raw_provider not in ("claude_cli", "anthropic_sdk", "auto"):
        raw_provider = "auto"
    priority: list = cfg.get("model_fallback_provider_priority", ["claude_cli", "anthropic_sdk"])
    _avail = {"claude_cli": cli_ok, "anthropic_sdk": sdk_ok}

    if raw_provider == "claude_cli":
        resolved = "claude_cli" if cli_ok else None
    elif raw_provider == "anthropic_sdk":
        resolved = "anthropic_sdk" if sdk_ok else None
    else:
        resolved = next((p for p in priority if _avail.get(p, False)), None)

    if resolved is not None:
        if resolved == "claude_cli" and raw_provider == "auto" and not sdk_ok:
            msg = "anthropic SDK unavailable; using claude_cli"
        else:
            msg = f"model fallback enabled; resolved provider: {resolved}"
        status = "green"
        evidence = ""
    else:
        status = "yellow"
        if raw_provider == "anthropic_sdk":
            msg = "model fallback enabled but anthropic SDK missing"
            evidence = "run: uv add anthropic"
        elif raw_provider == "claude_cli":
            msg = "model fallback enabled but Claude CLI missing"
            evidence = "ensure the `claude` binary is on PATH"
        else:
            msg = "model fallback enabled but no provider available"
            evidence = "install anthropic SDK (uv add anthropic) or ensure claude CLI is on PATH"

    base = _check("citadel_ask_fallback_status", status, msg, evidence if resolved is None else "")
    base.update({
        "fallback_enabled": True,
        "configured_provider": raw_provider,
        "resolved_provider": resolved,
        "claude_cli_available": cli_ok,
        "anthropic_sdk_available": sdk_ok,
        "fallback_status": status,
        "fallback_message": msg,
    })
    return base


def check_workspace_index_smoke() -> dict:
    """Smoke-test the workspace intelligence query tool."""
    tool = ROOT / "tools" / "workspace_intelligence_query.py"
    if not tool.exists():
        return _check("workspace_index_smoke", "yellow", "workspace_intelligence_query.py not found",
                      str(tool))
    rc, stdout, stderr = run_tool([PYTHON, str(tool), "summary"], timeout=20)
    if rc == 0:
        try:
            data = json.loads(stdout)
            if "results" in data:
                return _check("workspace_index_smoke", "green",
                              "workspace query smoke: summary ok", "rc=0")
        except json.JSONDecodeError:
            pass
        return _check("workspace_index_smoke", "yellow",
                      "workspace query smoke: unexpected output", f"rc={rc}")
    detail = (stdout + " " + stderr).strip()[:200]
    return _check("workspace_index_smoke", "yellow",
                  f"workspace query smoke failed: {detail[:80]}", f"rc={rc}")


_AI_PROVIDER_CONFIG = ROOT / ".claude" / "brain" / "ai-provider-config.json"
_AI_PROVIDER_STATUS = STATE / "ai-provider-status.json"
_TOOLS_DIR = ROOT / "tools"


def check_ai_provider_config_valid() -> dict:
    if not _AI_PROVIDER_CONFIG.exists():
        return _check("ai_provider_config_valid", "red", "ai-provider-config.json not found",
                      str(_AI_PROVIDER_CONFIG))
    try:
        cfg = json.loads(_AI_PROVIDER_CONFIG.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return _check("ai_provider_config_valid", "red", f"parse error: {exc}", str(_AI_PROVIDER_CONFIG))
    security = cfg.get("security", {})
    if security.get("daemon_invocation_allowed", True):
        return _check("ai_provider_config_valid", "red",
                      "security.daemon_invocation_allowed must be false", "policy violation")
    return _check("ai_provider_config_valid", "green", "ai-provider-config.json valid and secure",
                  str(_AI_PROVIDER_CONFIG))


def check_daemon_no_ai_invocation_policy() -> dict:
    if not _AI_PROVIDER_CONFIG.exists():
        return _check("daemon_no_ai_invocation_policy", "yellow",
                      "ai-provider-config.json not found — cannot verify", "")
    try:
        cfg = json.loads(_AI_PROVIDER_CONFIG.read_text())
        daemon_ok = not cfg.get("security", {}).get("daemon_invocation_allowed", True)
        indexer_ok = not cfg.get("security", {}).get("indexer_invocation_allowed", True)
        auto_ok = not cfg.get("security", {}).get("auto_execution_allowed", True)
        if daemon_ok and indexer_ok and auto_ok:
            return _check("daemon_no_ai_invocation_policy", "green",
                          "daemon/indexer AI invocation prohibited by config", "")
        return _check("daemon_no_ai_invocation_policy", "red",
                      "one or more AI invocation flags are enabled — security risk",
                      f"daemon={not daemon_ok} indexer={not indexer_ok} auto={not auto_ok}")
    except (json.JSONDecodeError, OSError) as exc:
        return _check("daemon_no_ai_invocation_policy", "yellow", f"config read error: {exc}", "")


def check_claude_code_available() -> dict:
    import shutil
    cfg = {}
    if _AI_PROVIDER_CONFIG.exists():
        try:
            cfg = json.loads(_AI_PROVIDER_CONFIG.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    provider_cfg = cfg.get("providers", {}).get("claude_code", {})
    if not provider_cfg.get("enabled", True):
        return _check("claude_code_available", "green", "claude_code disabled in config (intentional)", "")
    cmd = provider_cfg.get("command", "claude") or "claude"
    found = shutil.which(cmd)
    if found:
        return _check("claude_code_available", "green", f"{cmd!r} found on PATH", found)
    return _check("claude_code_available", "yellow", f"{cmd!r} not found on PATH — provider unavailable", "")


def check_cowork_available() -> dict:
    import shutil
    cfg = {}
    if _AI_PROVIDER_CONFIG.exists():
        try:
            cfg = json.loads(_AI_PROVIDER_CONFIG.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    provider_cfg = cfg.get("providers", {}).get("cowork", {})
    if not provider_cfg.get("enabled", True):
        return _check("cowork_available", "green", "cowork disabled in config (intentional)", "")
    cmd = (provider_cfg.get("command", "") or "").strip()
    if not cmd:
        return _check("cowork_available", "yellow",
                      "cowork command not configured — set providers.cowork.command", "")
    found = shutil.which(cmd)
    if found:
        return _check("cowork_available", "green", f"{cmd!r} found on PATH", found)
    return _check("cowork_available", "yellow", f"{cmd!r} not found on PATH", "")


def check_ask_fallback_provider_resolved() -> dict:
    if not _AI_PROVIDER_STATUS.exists():
        return _check("ask_fallback_provider_resolved", "yellow",
                      "ai-provider-status.json not found — run ai_provider_detection.py", "")
    try:
        data = json.loads(_AI_PROVIDER_STATUS.read_text())
        resolved = data.get("resolved", {}).get("ask_fallback")
        if resolved:
            return _check("ask_fallback_provider_resolved", "green",
                          f"ask_fallback resolved to: {resolved}", "")
        return _check("ask_fallback_provider_resolved", "yellow",
                      "ask_fallback provider not resolved — no provider available", "")
    except (json.JSONDecodeError, OSError) as exc:
        return _check("ask_fallback_provider_resolved", "yellow", f"status file read error: {exc}", "")


def check_orchestrator_ready() -> dict:
    files = [
        "citadel_ai_orchestrator.py", "citadel_execution_manifest.py",
        "citadel_context_capsule_builder.py", "citadel_provider_runner.py",
        "citadel_review_runner.py", "citadel_validation_runner.py",
    ]
    missing = [f for f in files if not (_TOOLS_DIR / f).exists()]
    if missing:
        return _check("orchestrator_ready", "yellow",
                      f"missing orchestrator files: {missing}", "")
    return _check("orchestrator_ready", "green", f"all {len(files)} orchestrator files present", "")


def check_task_cockpit_ui_available() -> dict:
    path = ROOT / "docs" / "brain" / "tasks.html"
    if path.exists():
        return _check("task_cockpit_ui_available", "green", "tasks.html found", str(path))
    return _check("task_cockpit_ui_available", "yellow", "tasks.html not found", str(path))


def check_validation_runner_available() -> dict:
    path = _TOOLS_DIR / "citadel_validation_runner.py"
    if path.exists():
        return _check("validation_runner_available", "green", "citadel_validation_runner.py found", str(path))
    return _check("validation_runner_available", "yellow",
                  "citadel_validation_runner.py not found", str(path))


def check_ai_provider_audit_log_writable() -> dict:
    audit_dir = STATE
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        test_path = audit_dir / ".audit_write_test"
        test_path.write_text("ok")
        test_path.unlink()
        return _check("ai_provider_audit_log_writable", "green",
                      f"{audit_dir} is writable", str(audit_dir))
    except OSError as exc:
        return _check("ai_provider_audit_log_writable", "red",
                      f"state dir not writable: {exc}", str(audit_dir))


def check_grounding_layer() -> dict:
    """Check that grounding infrastructure (policy + quote extractor + claim verifier) exists."""
    missing = []
    grounding_rule = ROOT / ".claude" / "rules" / "grounding.md"
    grounding_policy = ROOT / "docs" / "ai-context" / "system" / "grounding-policy.md"
    quote_extractor = ROOT / "tools" / "grounding_quote_extractor.py"
    claim_verifier = ROOT / "tools" / "grounding_claim_verifier.py"

    if not grounding_rule.exists():
        missing.append(".claude/rules/grounding.md")
    if not grounding_policy.exists():
        missing.append("docs/ai-context/system/grounding-policy.md")
    if not quote_extractor.exists():
        missing.append("tools/grounding_quote_extractor.py")
    if not claim_verifier.exists():
        missing.append("tools/grounding_claim_verifier.py")

    if missing:
        return _check("grounding_layer", "yellow",
                      f"grounding infrastructure incomplete: missing {missing}",
                      "run tools/grounding_lint.py --pretty for details")
    return _check("grounding_layer", "green",
                  "grounding layer present (policy, quote extractor, claim verifier)", "")


def check_output_schema_layer() -> dict:
    """Check that .claude/schemas/ exists with all 16 required schemas."""
    schemas_dir = ROOT / ".claude" / "schemas"
    required = [
        "ask-response.schema.json", "execution-manifest.schema.json",
        "system-health.schema.json", "claim-verification.schema.json",
        "quote-extraction.schema.json", "provider-status.schema.json",
        "validation-result.schema.json", "learning-candidate.schema.json",
    ]
    if not schemas_dir.exists():
        return _check("output_schema_layer", "yellow",
                      ".claude/schemas/ directory does not exist",
                      "run tools/output_schema_lint.py --pretty for details")
    missing = [s for s in required if not (schemas_dir / s).exists()]
    if missing:
        return _check("output_schema_layer", "yellow",
                      f"{len(missing)} required schemas missing: {missing[:3]}",
                      "run tools/output_schema_lint.py --pretty for details")
    all_schemas = list(schemas_dir.glob("*.schema.json"))
    return _check("output_schema_layer", "green",
                  f"output schema layer present ({len(all_schemas)} schemas in .claude/schemas/)", "")


def check_prompt_leak_layer() -> dict:
    """Check that prompt-leak defense (policy + output filter) exists."""
    missing = []
    leak_rule = ROOT / ".claude" / "rules" / "prompt-leak-policy.md"
    leak_policy = ROOT / "docs" / "ai-context" / "system" / "prompt-leak-policy.md"
    output_filter = ROOT / "tools" / "prompt_leak_output_filter.py"

    if not leak_rule.exists():
        missing.append(".claude/rules/prompt-leak-policy.md")
    if not leak_policy.exists():
        missing.append("docs/ai-context/system/prompt-leak-policy.md")
    if not output_filter.exists():
        missing.append("tools/prompt_leak_output_filter.py")

    if missing:
        return _check("prompt_leak_layer", "yellow",
                      f"prompt-leak defense incomplete: missing {missing}",
                      "run tools/prompt_leak_lint.py --pretty for details")
    return _check("prompt_leak_layer", "green",
                  "prompt-leak layer present (policy, output filter)", "")


def check_schema_lint() -> dict:
    """Run output_schema_lint.py and report result."""
    tool = ROOT / "tools" / "output_schema_lint.py"
    if not tool.exists():
        return _check("schema_lint", "yellow", "output_schema_lint.py not found", str(tool))
    rc, stdout, stderr = run_tool([PYTHON, str(tool)], timeout=15)
    if rc == 0:
        return _check("schema_lint", "green", "output_schema_lint pass", "rc=0")
    detail = (stdout + " " + stderr).strip()[:200]
    return _check("schema_lint", "yellow", f"output_schema_lint issues: {detail[:80]}", f"rc={rc}")


def check_scaffold_integrity() -> dict:
    """Run scaffold_integrity_lint.py — verifies the workspace is 100% scaffolded
    (tools/scripts links, .mcp.json, seeded docs, graph UI files, executable hooks).

    Advisory (yellow, not red): the individual critical pieces (UI files, lint) have
    their own red checks; this one surfaces the *root cause* (a broken scaffold) in
    one place so 'nothing is broken' can be re-validated on every `citadel up`.
    """
    tool = ROOT / "tools" / "scaffold_integrity_lint.py"
    if not tool.exists():
        return _check("scaffold_integrity", "yellow", "scaffold_integrity_lint.py not found", str(tool))
    rc, stdout, stderr = run_tool([PYTHON, str(tool), "--workspace", str(ROOT), "--json"], timeout=15)
    if rc == 0:
        return _check("scaffold_integrity", "green", "workspace scaffold complete", "rc=0")
    try:
        data = json.loads(stdout)
        failed = [c["name"] for c in data.get("checks", []) if c.get("status") == "fail"]
        detail = f"scaffold incomplete: {failed}" if failed else "scaffold incomplete"
    except (json.JSONDecodeError, ValueError):
        detail = (stdout + " " + stderr).strip()[:120] or "scaffold incomplete"
    return _check("scaffold_integrity", "yellow", detail, f"rc={rc}")


def check_stuck_tasks() -> dict:
    manifests_dir = STATE / "execution-manifests"
    if not manifests_dir.exists():
        return _check("stuck_tasks", "green", "no execution-manifests dir (no tasks yet)", "")
    stuck_states = {"executing", "reviewing", "validating"}
    stuck_count = 0
    total = 0
    for p in manifests_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            total += 1
            if data.get("status") in stuck_states:
                stuck_count += 1
        except (json.JSONDecodeError, OSError):
            continue
    if stuck_count:
        return _check("stuck_tasks", "yellow",
                      f"{stuck_count}/{total} task(s) stuck in active state — restart server to recover",
                      str(manifests_dir))
    return _check("stuck_tasks", "green", f"no stuck tasks (checked {total})", "")


def run_checks() -> list[dict]:
    """Run all 35 checks and return the list."""
    checks: list[dict] = []

    checks.append(check_incremental_brain_daemon())

    result = check_graph_json_valid()
    if isinstance(result, tuple):
        graph_check, graph_data = result
    else:
        graph_check, graph_data = result, None
    checks.append(graph_check)
    checks.append(check_graph_has_nodes_links(graph_data))

    checks.append(check_brain_search_index())

    checks.append(check_mandatory_auto_lint())

    checks.append(check_graph_brain_lint())

    checks.append(check_execution_manifest())

    checks.append(check_scheduler_health())

    brain_dir = ROOT / "docs" / "brain"
    checks.append(check_ui_file("graph_html", brain_dir / "graph.html"))
    checks.append(check_ui_file("graph_css",  brain_dir / "graph.css"))
    checks.append(check_ui_file("graph_js",   brain_dir / "graph.js"))

    checks.append(check_citadel_ui_server())

    checks.append(check_workspace_index())

    checks.append(check_workspace_index_smoke())

    checks.append(check_workspace_intelligence_daemon_running())

    checks.append(check_citadel_ask_config_valid())
    checks.append(check_citadel_ask_skill_count())
    checks.append(check_citadel_ask_agent_count())
    checks.append(check_citadel_ask_workflow_count())
    checks.append(check_citadel_ask_fallback_status())

    checks.append(check_ai_provider_config_valid())
    checks.append(check_daemon_no_ai_invocation_policy())
    checks.append(check_claude_code_available())
    checks.append(check_cowork_available())
    checks.append(check_ask_fallback_provider_resolved())
    checks.append(check_orchestrator_ready())
    checks.append(check_task_cockpit_ui_available())
    checks.append(check_validation_runner_available())
    checks.append(check_ai_provider_audit_log_writable())
    checks.append(check_stuck_tasks())
    checks.append(check_scaffold_integrity())

    checks.append(check_grounding_layer())
    checks.append(check_output_schema_layer())
    checks.append(check_prompt_leak_layer())
    checks.append(check_schema_lint())

    return checks


def compute_overall(checks: list[dict]) -> tuple[str, dict]:
    """Compute overall_status and summary counts."""
    summary = {"green": 0, "yellow": 0, "red": 0}
    for c in checks:
        s = c.get("status", "yellow")
        summary[s] = summary.get(s, 0) + 1

    for c in checks:
        if c["name"] in CRITICAL and c["status"] == "red":
            return "red", summary

    if summary["yellow"] > 0:
        return "yellow", summary

    return "green", summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Write Citadel system health to JSON")
    parser.add_argument("--out", default=str(ROOT / "docs" / "brain" / "system-status.json"),
                        help="Output file path (default: docs/brain/system-status.json)")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")
    args = parser.parse_args()

    checks = run_checks()
    overall_status, summary = compute_overall(checks)

    now_utc = datetime.now(UTC)
    payload = {
        "created_at": now_utc.isoformat(),
        "epoch_ms": int(now_utc.timestamp() * 1000),
        "overall_status": overall_status,
        "checks": checks,
        "summary": summary,
        "ui": {
            "server_expected": True,
            "url": "http://localhost:8765/brain/graph.html"
        }
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))

    if not args.quiet:
        g = summary["green"]; y = summary["yellow"]; r = summary["red"]
        print(f"Citadel health: {overall_status} ({g} green, {y} yellow, {r} red) → {out_path}")

    sys.exit(0)


if __name__ == "__main__":
    main()
