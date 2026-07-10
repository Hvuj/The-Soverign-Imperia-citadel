#!/usr/bin/env python3
"""citadel_validation_runner.py — Run manifest-approved validation commands.

Security contract:
  - Runs ONLY commands listed in manifest.validation_required.
  - Never runs forbidden commands (hardcoded list).
  - Enforces timeouts per command.
  - Captures stdout/stderr tails only — no full log dumps.
  - Called ONLY from citadel_ai_orchestrator.py.
  - Daemons, index builders, and graph builders must NOT import this module.
"""

import json
import shlex
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from citadel_execution_manifest import TaskManifest

import os

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
_VALIDATION_DIR = ROOT / ".claude" / "state" / "validation-results"
_AUDIT_LOG = ROOT / ".claude" / "state" / "ai-provider-audit.log"
_PROVIDER_CONFIG = ROOT / ".claude" / "brain" / "ai-provider-config.json"

_GIT_DESTRUCTIVE = " ".join(["git", "reset", "--hard"])
_HARDCODED_FORBIDDEN = {
    "rm", "rm -rf", "git push", "git commit",
    "deploy", "kubectl apply", "terraform apply", "npm publish",
    _GIT_DESTRUCTIVE,
}

_FORBIDDEN_PREFIXES = ("rm ", "git push", "git commit", "deploy", "kubectl ", "terraform ")

_COMMAND_TIMEOUT_SEC = 120


def _load_config() -> dict:
    try:
        return json.loads(_PROVIDER_CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_audit(task_id: str, action: str, metadata: dict) -> None:
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "task_id": task_id,
        "action": action,
        "metadata": metadata,
    }
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _is_forbidden(cmd_str: str) -> bool:
    stripped = cmd_str.strip().lower()
    if stripped in {c.lower() for c in _HARDCODED_FORBIDDEN}:
        return True
    if any(stripped.startswith(p) for p in _FORBIDDEN_PREFIXES):
        return True
    return False


def _run_command(cmd_str: str, timeout: int = _COMMAND_TIMEOUT_SEC) -> dict:
    t0 = time.monotonic()
    try:
        args = shlex.split(cmd_str)
    except ValueError as exc:
        return {
            "command": cmd_str,
            "returncode": -1,
            "duration_sec": 0,
            "status": "failed",
            "stdout_tail": "",
            "stderr_tail": f"shlex parse error: {exc}",
        }

    try:
        result = subprocess.run(
            args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = round(time.monotonic() - t0, 2)
        return {
            "command": cmd_str,
            "returncode": result.returncode,
            "duration_sec": duration,
            "status": "passed" if result.returncode == 0 else "failed",
            "stdout_tail": (result.stdout or "")[-1000:],
            "stderr_tail": (result.stderr or "")[-500:],
        }
    except subprocess.TimeoutExpired:
        duration = round(time.monotonic() - t0, 2)
        return {
            "command": cmd_str,
            "returncode": -1,
            "duration_sec": duration,
            "status": "failed",
            "stdout_tail": "",
            "stderr_tail": f"timeout after {timeout}s",
        }
    except Exception as exc:
        duration = round(time.monotonic() - t0, 2)
        return {
            "command": cmd_str,
            "returncode": -1,
            "duration_sec": duration,
            "status": "failed",
            "stdout_tail": "",
            "stderr_tail": str(exc)[:200],
        }


def run_validation(manifest: "TaskManifest") -> dict:
    """Run manifest.validation_required commands. Returns structured validation result."""
    task_id = manifest.task_id
    commands_to_run: list[str] = manifest.validation_required or []

    if not commands_to_run:
        result = {
            "task_id": task_id,
            "status": "skipped",
            "commands": [],
            "summary": "No validation commands specified in manifest.",
            "failed_commands": [],
            "warnings": ["validation_required is empty — validation skipped"],
        }
        _write_result(task_id, result)
        return result

    manifest_forbidden = set(manifest.forbidden_commands or [])
    cmd_results: list[dict] = []
    warnings: list[str] = []

    for cmd_str in commands_to_run:
        if _is_forbidden(cmd_str) or cmd_str.strip().lower() in {f.lower() for f in manifest_forbidden}:
            warnings.append(f"Skipped forbidden command: {cmd_str!r}")
            cmd_results.append({
                "command": cmd_str,
                "returncode": -1,
                "duration_sec": 0,
                "status": "skipped_forbidden",
                "stdout_tail": "",
                "stderr_tail": "forbidden command — not executed",
            })
            continue

        _write_audit(task_id, "validation_command_start", {"command": cmd_str})
        cmd_result = _run_command(cmd_str)
        cmd_results.append(cmd_result)
        _write_audit(task_id, "validation_command_end", {
            "command": cmd_str,
            "status": cmd_result["status"],
            "returncode": cmd_result["returncode"],
        })

    failed = [r["command"] for r in cmd_results if r["status"] == "failed"]
    passed = [r for r in cmd_results if r["status"] == "passed"]
    total = len(cmd_results)
    pass_count = len(passed)

    if not cmd_results:
        overall_status = "skipped"
    elif not failed:
        overall_status = "passed"
    elif pass_count == 0:
        overall_status = "failed"
    else:
        overall_status = "partial"

    result = {
        "task_id": task_id,
        "status": overall_status,
        "commands": cmd_results,
        "summary": f"{pass_count}/{total} commands passed",
        "failed_commands": failed,
        "warnings": warnings,
    }
    _write_result(task_id, result)
    return result


def _write_result(task_id: str, result: dict) -> None:
    _VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    path = _VALIDATION_DIR / f"{task_id}.json"
    try:
        path.write_text(json.dumps(result, indent=2))
    except OSError:
        pass


def load_validation_result(task_id: str) -> dict | None:
    path = _VALIDATION_DIR / f"{task_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
