#!/usr/bin/env python3
"""citadel_execution_manifest.py — Task manifest lifecycle, state machine, approval tokens, and locks.

Called ONLY from citadel_ai_orchestrator.py and citadel_ui_server.py.
Daemons, index builders, and graph builders must NOT import this module.
"""

import fcntl
import hashlib
import json
import os
import secrets
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
_MANIFESTS_DIR = ROOT / ".claude" / "state" / "execution-manifests"
_LOCKS_DIR = ROOT / ".claude" / "state" / "locks"
_CAPSULES_DIR = ROOT / ".claude" / "state" / "context-capsules"
_VALIDATION_DIR = ROOT / ".claude" / "state" / "validation-results"
_LEARNING_DIR = ROOT / ".claude" / "state" / "learning-candidates"
_AUDIT_LOG = ROOT / ".claude" / "state" / "ai-provider-audit.log"
_PROVIDER_CONFIG = ROOT / ".claude" / "brain" / "ai-provider-config.json"

FORBIDDEN_COMMANDS: list[str] = [
    "rm -rf", "git push", "git commit", "deploy", "kubectl",
    "terraform apply", "npm publish", "git push --force",
]

_VALID_STATES = {
    "draft", "planned", "awaiting_plan_approval", "plan_rejected",
    "execution_approved", "executing", "execution_failed",
    "executed", "reviewing", "review_failed", "validating",
    "validation_failed", "completed", "blocked", "cancelled",
}

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft":                   {"planned", "blocked", "cancelled"},
    "planned":                 {"awaiting_plan_approval", "blocked", "cancelled"},
    "awaiting_plan_approval":  {"execution_approved", "plan_rejected", "blocked", "cancelled"},
    "plan_rejected":           {"draft", "cancelled"},
    "execution_approved":      {"executing", "blocked", "cancelled"},
    "executing":               {"executed", "execution_failed", "blocked", "cancelled"},
    "execution_failed":        {"executing", "cancelled", "blocked"},
    "executed":                {"reviewing", "validating", "completed", "blocked", "cancelled"},
    "reviewing":               {"review_failed", "validating", "completed", "blocked", "cancelled"},
    "review_failed":           {"reviewing", "cancelled", "blocked"},
    "validating":              {"completed", "validation_failed", "blocked", "cancelled"},
    "validation_failed":       {"validating", "cancelled", "blocked"},
    "completed":               set(),
    "blocked":                 {"cancelled"},
    "cancelled":               set(),
}

_STUCK_STATES = {"executing", "reviewing", "validating"}


@dataclass
class ApprovalBlock:
    plan_approved: bool = False
    execution_approved: bool = False
    approved_by_user: bool = False
    approved_at: str | None = None
    approval_token_hash: str | None = None
    approval_token_expires_at: str | None = None
    approval_token_used: bool = False


@dataclass
class ProviderPlan:
    planner: str = "claude_code"
    executor: str = "claude_code"
    reviewer: str = "cowork"


@dataclass
class TaskManifest:
    schema_version: str = "1.0"
    task_id: str = ""
    task_title: str = ""
    task_type: str = "qna"
    mode: str = "local_only"
    created_at: str = ""
    created_by: str = "citadel"
    updated_at: str = ""
    user_request: str = ""
    classification: dict = field(default_factory=lambda: {
        "topic": "",
        "risk_level": "low",
        "requires_code_edits": False,
        "requires_tests": False,
        "requires_review": False,
    })
    allowed_repos: list[str] = field(default_factory=list)
    allowed_files: list[str] = field(default_factory=list)
    forbidden_files: list[str] = field(default_factory=list)
    allowed_commands: list[str] = field(default_factory=list)
    forbidden_commands: list[str] = field(default_factory=list)
    context_sources: list[str] = field(default_factory=list)
    context_capsule_path: str = ""
    agents_considered: list[str] = field(default_factory=list)
    agents_selected: list[str] = field(default_factory=list)
    skills_considered: list[str] = field(default_factory=list)
    skills_selected: list[str] = field(default_factory=list)
    workflows_selected: list[str] = field(default_factory=list)
    artifacts_required: list[str] = field(default_factory=list)
    validation_required: list[str] = field(default_factory=list)
    approval: ApprovalBlock = field(default_factory=ApprovalBlock)
    provider_plan: ProviderPlan = field(default_factory=ProviderPlan)
    status: str = "draft"
    state_history: list[dict] = field(default_factory=list)
    plan_output: dict = field(default_factory=dict)
    execution_output: dict = field(default_factory=dict)
    review_output: dict = field(default_factory=dict)
    validation_output: dict = field(default_factory=dict)
    attempt_id: str | None = None
    attempt_count: int = 0
    pid: int | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_provider_config() -> dict:
    try:
        return json.loads(_PROVIDER_CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _manifest_path(task_id: str) -> Path:
    _MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    return _MANIFESTS_DIR / f"{task_id}.json"


def _manifest_to_dict(m: TaskManifest) -> dict:
    d = asdict(m)
    return d


def _manifest_from_dict(d: dict) -> TaskManifest:
    approval_d = d.pop("approval", {})
    approval = ApprovalBlock(**{k: v for k, v in approval_d.items() if k in ApprovalBlock.__dataclass_fields__})
    provider_d = d.pop("provider_plan", {})
    provider = ProviderPlan(**{k: v for k, v in provider_d.items() if k in ProviderPlan.__dataclass_fields__})
    valid_fields = TaskManifest.__dataclass_fields__
    filtered = {k: v for k, v in d.items() if k in valid_fields}
    m = TaskManifest(**filtered)
    m.approval = approval
    m.provider_plan = provider
    return m


class ManifestStore:
    def save(self, m: TaskManifest) -> None:
        _MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
        m.updated_at = _now_iso()
        path = _manifest_path(m.task_id)
        path.write_text(json.dumps(_manifest_to_dict(m), indent=2))

    def load(self, task_id: str) -> TaskManifest | None:
        path = _manifest_path(task_id)
        if not path.exists():
            return None
        try:
            return _manifest_from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

    def list_all(self, status_filter: str | None = None) -> list[TaskManifest]:
        _MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
        results: list[TaskManifest] = []
        for p in sorted(_MANIFESTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                m = _manifest_from_dict(json.loads(p.read_text()))
                if status_filter is None or m.status == status_filter:
                    results.append(m)
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
        return results


_store = ManifestStore()


def create_manifest(
    task_title: str,
    task_type: str = "planning",
    mode: str = "claude_code_plan_only",
    user_request: str = "",
    allowed_files: list[str] | None = None,
    risk_level: str = "low",
) -> TaskManifest:
    task_id = uuid.uuid4().hex[:12]
    now = _now_iso()
    m = TaskManifest(
        task_id=task_id,
        task_title=task_title[:200],
        task_type=task_type,
        mode=mode,
        created_at=now,
        updated_at=now,
        user_request=user_request[:2000],
        allowed_files=allowed_files or [],
        forbidden_commands=list(FORBIDDEN_COMMANDS),
        classification={
            "topic": "",
            "risk_level": risk_level,
            "requires_code_edits": task_type in ("implementation",),
            "requires_tests": task_type in ("implementation",),
            "requires_review": task_type in ("implementation", "review"),
        },
        status="draft",
        state_history=[{"state": "draft", "at": now, "reason": "created"}],
    )
    _store.save(m)
    return m


def transition(m: TaskManifest, new_state: str, reason: str = "") -> TaskManifest:
    if new_state not in _VALID_STATES:
        raise ValueError(f"Unknown state: {new_state!r}")
    allowed = _ALLOWED_TRANSITIONS.get(m.status, set())
    if new_state not in allowed:
        raise ValueError(
            f"Invalid transition {m.status!r} → {new_state!r}. "
            f"Allowed: {sorted(allowed)}"
        )
    m.status = new_state
    m.state_history.append({"state": new_state, "at": _now_iso(), "reason": reason[:200]})
    _store.save(m)
    return m


def generate_approval_token(m: TaskManifest) -> str:
    """Generate a single-use approval token. Returns plaintext token (never stored)."""
    cfg = _load_provider_config()
    ttl = cfg.get("approval_token", {}).get("ttl_seconds", 1800)
    length = cfg.get("approval_token", {}).get("length_bytes", 32)
    token = secrets.token_hex(length)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.fromtimestamp(time.time() + ttl, tz=UTC).isoformat()
    m.approval.approval_token_hash = token_hash
    m.approval.approval_token_expires_at = expires_at
    m.approval.approval_token_used = False
    _store.save(m)
    return token


def verify_approval_token(m: TaskManifest, token: str) -> tuple[bool, str]:
    """Verify token. Returns (valid, reason). Marks token used on success."""
    if not m.approval.approval_token_hash:
        return False, "no_token_set"
    if m.approval.approval_token_used:
        return False, "token_already_used"
    exp = m.approval.approval_token_expires_at
    if exp and datetime.fromisoformat(exp) < datetime.now(UTC):
        return False, "token_expired"
    candidate_hash = hashlib.sha256(token.encode()).hexdigest()
    if not secrets.compare_digest(candidate_hash, m.approval.approval_token_hash):
        return False, "token_mismatch"
    m.approval.approval_token_used = True
    _store.save(m)
    return True, "ok"


def can_execute(m: TaskManifest) -> tuple[bool, str]:
    """Check all guards before execution. Returns (allowed, reason)."""
    if m.status != "execution_approved":
        return False, f"status is {m.status!r}, must be execution_approved"
    if not m.approval.execution_approved:
        return False, "approval.execution_approved is false"
    if not m.approval.approved_by_user:
        return False, "approval.approved_by_user is false"
    if not m.allowed_files:
        return False, "allowed_files is empty"
    if m.mode not in ("claude_code_execute_scoped", "full_controlled_workflow"):
        return False, f"mode {m.mode!r} does not allow execution"
    if m.task_type not in ("qna",) and not m.validation_required:
        return False, "validation_required is empty"
    return True, "ok"


class TaskLock:
    """File-based lock for a task_id. Prevents concurrent execution."""

    def __init__(self, task_id: str) -> None:
        _LOCKS_DIR.mkdir(parents=True, exist_ok=True)
        self._path = _LOCKS_DIR / f"{task_id}.lock"
        self._fd: int | None = None

    def acquire(self, timeout: float = 2.0) -> bool:
        """Try to acquire lock. Returns True on success."""
        _clean_stale_lock(self._path)
        try:
            self._fd = os.open(str(self._path), os.O_CREAT | os.O_RDWR)
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    os.write(self._fd, str(os.getpid()).encode())
                    return True
                except OSError:
                    if time.monotonic() >= deadline:
                        os.close(self._fd)
                        self._fd = None
                        return False
                    time.sleep(0.1)
        except OSError:
            return False

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
                self._path.unlink(missing_ok=True)
            except OSError:
                pass
            self._fd = None

    def __enter__(self) -> "TaskLock":
        if not self.acquire():
            raise RuntimeError("Could not acquire task lock — task may already be running.")
        return self

    def __exit__(self, *_: Any) -> None:
        self.release()


def _clean_stale_lock(path: Path) -> None:
    if not path.exists():
        return
    try:
        pid_bytes = path.read_bytes()
        pid = int(pid_bytes.strip()) if pid_bytes.strip() else 0
        if pid:
            os.kill(pid, 0)
    except (ProcessLookupError, ValueError, OSError):
        path.unlink(missing_ok=True)


def detect_stuck_tasks() -> list[TaskManifest]:
    """Find tasks stuck in active states with no live PID."""
    stuck = []
    for m in _store.list_all():
        if m.status not in _STUCK_STATES:
            continue
        pid = m.pid
        if pid:
            try:
                os.kill(pid, 0)
                continue
            except (ProcessLookupError, OSError):
                pass
        stuck.append(m)
    return stuck


def recover_stuck_tasks() -> list[str]:
    """Mark stuck tasks as blocked. Returns list of recovered task_ids."""
    recovered = []
    for m in detect_stuck_tasks():
        try:
            transition(m, "blocked", "recovered_from_stuck_at_startup")
            recovered.append(m.task_id)
        except ValueError:
            pass
    return recovered


def load_manifest(task_id: str) -> TaskManifest | None:
    return _store.load(task_id)


def list_tasks(status_filter: str | None = None) -> list[TaskManifest]:
    return _store.list_all(status_filter)


def write_audit_entry(task_id: str, action: str, metadata: dict) -> None:
    """Write a safe audit entry (no prompts, no secrets)."""
    entry = {
        "timestamp": _now_iso(),
        "task_id": task_id,
        "action": action,
        "metadata": {k: v for k, v in metadata.items() if k not in ("prompt", "context", "token")},
    }
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def write_learning_candidate(task_id: str, candidate: dict) -> Path:
    _LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    path = _LEARNING_DIR / f"{task_id}.json"
    path.write_text(json.dumps(candidate, indent=2))
    return path
