#!/usr/bin/env python3
"""citadel_ai_orchestrator.py — Manifest-driven AI execution orchestrator for Citadel.

Security contract:
  - Called ONLY from citadel_ui_server.py endpoints.
  - Daemons, index builders, and graph builders must NOT import this module.
  - No provider call without a manifest.
  - No execution without explicit user approval.
  - All forbidden requests return a structured refusal without calling any provider.

Supported modes:
  local_only                 — no provider call; local index answer only
  local_plus_claude_code     — local first; Claude Code Q&A fallback if insufficient
  claude_code_plan_only      — create manifest + plan; no edits
  claude_code_execute_scoped — scoped execution with approval + validation
  cowork_review_only         — co-work read-only review
  full_controlled_workflow   — full manifest-driven flow with gates
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
_PROVIDER_CONFIG = ROOT / ".claude" / "brain" / "ai-provider-config.json"

_FORBIDDEN_REQUEST_PATTERNS = [
    "run arbitrary shell", "run shell", "expose secrets", "bypass approval",
    "bypass validation", "edit without approval", "push to", "deploy to",
    "delete files", "bypass manifest",
]

_REFUSAL = (
    "Citadel cannot do that. "
    "AI execution is manifest-driven, scoped, approval-gated, and validation-gated."
)


def _load_config() -> dict:
    try:
        return json.loads(_PROVIDER_CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _is_forbidden_request(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in _FORBIDDEN_REQUEST_PATTERNS)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _manifest_module():
    import citadel_execution_manifest as m
    return m


def _capsule_module():
    import citadel_context_capsule_builder as c
    return c


def _provider_module():
    import citadel_provider_runner as p
    return p


def _review_module():
    import citadel_review_runner as r
    return r


def _validation_module():
    import citadel_validation_runner as v
    return v


def run_local_only(task_request: dict) -> dict:
    return {
        "status": "answered",
        "mode": "local_only",
        "source": "local",
        "message": "Local mode — no provider called.",
        "task": task_request.get("task", ""),
    }


def run_local_plus_claude_code(task_request: dict) -> dict:
    """Q&A mode: local first; Claude Code fallback if insufficient.

    For Q&A this delegates to citadel_model_fallback, which already implements
    the provider detection, bounded context, and security audit.
    """
    question = task_request.get("task") or task_request.get("question", "")
    if _is_forbidden_request(question):
        return {"status": "blocked", "reason": "forbidden_request", "message": _REFUSAL}

    try:
        import citadel_model_fallback as mf
        config = mf.load_citadel_ask_config()
        if not mf.is_model_fallback_enabled(config):
            return {
                "status": "answered",
                "source": "local",
                "mode": "local_only",
                "message": "Model fallback not enabled. Local answer only.",
            }
        category = task_request.get("category", "unknown")
        local_evidence = task_request.get("local_evidence", [])
        bounded = mf.build_bounded_context(question, category, local_evidence, config=config)
        prompt = mf.build_claude_fallback_prompt(question, category, bounded)
        result = mf.ask_claude_fallback(prompt, config)
        result["mode"] = "local_plus_claude_code"
        return result
    except ImportError:
        return {"status": "blocked", "reason": "citadel_model_fallback_unavailable"}


def run_plan_only(task_request: dict) -> dict:
    """Create manifest + context capsule + call Claude Code for plan. No file edits."""
    task = task_request.get("task", "")
    if not task:
        return {"status": "blocked", "reason": "task is required"}
    if _is_forbidden_request(task):
        return {"status": "blocked", "reason": "forbidden_request", "message": _REFUSAL}

    em = _manifest_module()
    cb = _capsule_module()
    pr = _provider_module()

    risk_level = task_request.get("risk_level", "low")
    selected_files = task_request.get("selected_files", [])

    manifest = em.create_manifest(
        task_title=task[:200],
        task_type="planning",
        mode="claude_code_plan_only",
        user_request=task,
        allowed_files=selected_files,
        risk_level=risk_level,
    )

    try:
        em.transition(manifest, "planned", "orchestrator_started_plan")
    except ValueError as exc:
        return {"status": "blocked", "reason": str(exc)}

    extra = {"risks": task_request.get("risks", []), "open_questions": task_request.get("open_questions", [])}
    capsule_text = cb.build_capsule(manifest, extra)

    plan_result = pr.run_plan(manifest, capsule_text)

    if plan_result.get("status") == "blocked":
        try:
            em.transition(manifest, "blocked", plan_result.get("reason", "plan_failed"))
        except ValueError:
            pass
        manifest.plan_output = plan_result
        em._store.save(manifest)
        return {"status": "blocked", "task_id": manifest.task_id, **plan_result}

    manifest.plan_output = plan_result
    manifest.validation_required = plan_result.get("validation_required", [])
    if not manifest.allowed_files and plan_result.get("allowed_files_proposed"):
        manifest.allowed_files = plan_result["allowed_files_proposed"]

    em._store.save(manifest)
    try:
        em.transition(manifest, "awaiting_plan_approval", "plan_ready_for_review")
    except ValueError:
        pass

    return {
        "status": "planned",
        "task_id": manifest.task_id,
        "mode": "claude_code_plan_only",
        **plan_result,
    }


def run_execute_scoped(task_request: dict) -> dict:
    """Load approved manifest, verify token, lock, execute, validate."""
    task_id = task_request.get("task_id", "")
    token = task_request.get("approval_token", "")

    if not task_id:
        return {"status": "blocked", "reason": "task_id required"}

    em = _manifest_module()
    cb = _capsule_module()
    pr = _provider_module()
    vr = _validation_module()

    manifest = em.load_manifest(task_id)
    if manifest is None:
        return {"status": "blocked", "reason": "manifest_not_found", "task_id": task_id}

    ok, reason = em.can_execute(manifest)
    if not ok:
        return {"status": "blocked", "reason": reason, "task_id": task_id}

    token_ok, token_reason = em.verify_approval_token(manifest, token)
    if not token_ok:
        return {"status": "blocked", "reason": f"approval_token_invalid: {token_reason}", "task_id": task_id}

    lock = em.TaskLock(task_id)
    if not lock.acquire(timeout=3.0):
        return {"status": "blocked", "reason": "task_already_running", "task_id": task_id}

    try:
        em.transition(manifest, "executing", "execution_started")
        manifest.pid = os.getpid()
        em._store.save(manifest)

        capsule_path = cb.capsule_path_for(task_id)
        if capsule_path.exists():
            capsule_text = capsule_path.read_text()
        else:
            capsule_text = cb.build_capsule(manifest)

        exec_result = pr.run_execute(manifest, capsule_text)

        if exec_result.get("status") == "blocked":
            manifest.execution_output = exec_result
            em._store.save(manifest)
            em.transition(manifest, "execution_failed", exec_result.get("reason", "execution_blocked"))
            return {"task_id": task_id, **exec_result}

        manifest.execution_output = exec_result
        em._store.save(manifest)
        em.transition(manifest, "executed", "execution_completed")

        val_result = vr.run_validation(manifest)
        manifest.validation_output = val_result
        em._store.save(manifest)

        next_state = "validating" if val_result["status"] in ("passed", "partial") else "validation_failed"
        try:
            em.transition(manifest, next_state, f"validation_{val_result['status']}")
        except ValueError:
            pass

        if val_result["status"] == "passed":
            try:
                em.transition(manifest, "completed" if not manifest.classification.get("requires_review") else "reviewing", "validation_passed")
            except ValueError:
                pass

        return {
            "status": exec_result.get("status", "executed"),
            "task_id": task_id,
            "changed_files": exec_result.get("changed_files", []),
            "diff_summary": exec_result.get("diff_summary", ""),
            "validation": val_result,
            "requires_review": exec_result.get("requires_review", True),
            "warnings": exec_result.get("warnings", []),
        }
    finally:
        lock.release()


def run_cowork_review(task_request: dict) -> dict:
    """Run co-work read-only review."""
    task_id = task_request.get("task_id", "")
    review_type = task_request.get("review_type", "final")

    if not task_id:
        return {"status": "blocked", "reason": "task_id required"}

    em = _manifest_module()
    cb = _capsule_module()
    rr = _review_module()

    manifest = em.load_manifest(task_id)
    if manifest is None:
        return {"status": "blocked", "reason": "manifest_not_found", "task_id": task_id}

    try:
        em.transition(manifest, "reviewing", "review_started")
    except ValueError as exc:
        return {"status": "blocked", "reason": str(exc), "task_id": task_id}

    capsule_path = cb.capsule_path_for(task_id)
    if capsule_path.exists():
        capsule_text = capsule_path.read_text()
    else:
        capsule_text = cb.build_capsule(manifest)

    review_result = rr.run_review(manifest, capsule_text, review_type)
    manifest.review_output = review_result
    em._store.save(manifest)

    if review_result.get("status") == "blocked":
        try:
            em.transition(manifest, "review_failed", review_result.get("reason", "review_error"))
        except ValueError:
            pass
    else:
        try:
            em.transition(manifest, "validating" if manifest.validation_output else "reviewing",
                          f"review_{review_result.get('status', 'unknown')}")
        except ValueError:
            pass

    return {"task_id": task_id, **review_result}


def run_full_workflow(task_request: dict) -> dict:
    """Full controlled workflow: plan → approval gate → execute → review → validate."""
    plan_result = run_plan_only(task_request)
    if plan_result.get("status") in ("blocked", "failed"):
        return plan_result
    plan_result["next_step"] = "approve_plan"
    plan_result["message"] = (
        "Plan created. Review the plan and call POST /api/execute/approve to approve, "
        "then POST /api/execute/run to execute."
    )
    return plan_result


_MODE_HANDLERS = {
    "local_only": run_local_only,
    "local_plus_claude_code": run_local_plus_claude_code,
    "claude_code_plan_only": run_plan_only,
    "claude_code_execute_scoped": run_execute_scoped,
    "cowork_review_only": run_cowork_review,
    "full_controlled_workflow": run_full_workflow,
}


def run(mode: str, task_request: dict) -> dict:
    """Main orchestrator entry point. Dispatches to mode handler."""
    cfg = _load_config()
    if not cfg.get("enabled", True):
        return {"status": "blocked", "reason": "ai_provider_config_disabled"}

    security = cfg.get("security", {})
    if security.get("auto_execution_allowed", False) is True:
        return {"status": "blocked", "reason": "config_violation: auto_execution_allowed must be false"}

    task = task_request.get("task") or task_request.get("question", "")
    if task and _is_forbidden_request(task):
        return {"status": "blocked", "reason": "forbidden_request", "message": _REFUSAL}

    handler = _MODE_HANDLERS.get(mode)
    if handler is None:
        return {"status": "blocked", "reason": f"unknown_mode: {mode!r}"}

    try:
        return handler(task_request)
    except Exception as exc:
        return {"status": "blocked", "reason": f"orchestrator_error: {str(exc)[:200]}"}
