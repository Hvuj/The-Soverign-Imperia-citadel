#!/usr/bin/env python3
"""citadel_model_fallback.py — Bounded Claude fallback for Ask Citadel /api/ask.

Security contract (enforced here and checked by citadel_ask_lint.py):
  - Q&A only. One model call max. No tools. No shell. No file edits.
  - No arbitrary file reads. No secrets. No external browsing.
  - Input context capped by config. Output length capped by config.
  - Audit log written on every fallback attempt when enabled.
  - Called ONLY from tools/citadel_ui_server.py /api/ask handler.
  - Daemons, index builders, and graph builders must NOT import this module.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
_DEFAULT_CONFIG_PATH = ROOT / ".claude" / "brain" / "citadel-ask-config.json"

_FALLBACK_TEMPLATE: dict = {
    "answer": "",
    "source": "claude_fallback",
    "confidence": "low",
    "category": "",
    "evidence": [],
    "warnings": [],
    "suggested_questions": [],
    "model_fallback_used": True,
    "local_context_used": False,
}

_FORBIDDEN_CONTEXT = [".env", "credentials", "private_key", "secret", "token", "password"]
_FORBIDDEN_QUESTION_PATTERNS = [
    "run command", "execute shell", "delete", "remove files",
    "secret", "token", "password", "private key", "env var",
    "environment variable", "upload", "send email",
]

_CATEGORY_FILE_HINTS: dict[str, list[str]] = {
    "skills":    [".claude/brain/workflow-manifest-config.json"],
    "agents":    [".claude/brain/workflow-manifest-config.json"],
    "workflows": [".claude/brain/workflow-manifest-config.json"],
    "graph":     ["docs/brain/graph.json"],
    "routing":   ["docs/brain/graph.json", ".claude/brain/workflow-manifest-config.json"],
    "health":    ["docs/brain/system-status.json"],
    "node":      ["docs/brain/graph.json"],
}


def load_citadel_ask_config(config_path: Path | None = None) -> dict:
    path = config_path or _DEFAULT_CONFIG_PATH
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def is_model_fallback_enabled(config: dict) -> bool:
    return bool(config.get("allow_model_fallback", False))


def detect_claude_cli() -> bool:
    """Return True if the `claude` binary is on PATH. Presence-only check — no subprocess."""
    return shutil.which("claude") is not None


def detect_anthropic_sdk() -> bool:
    """Return True if the `anthropic` package is importable. Never crashes if missing."""
    return importlib.util.find_spec("anthropic") is not None


def resolve_provider(config: dict) -> str | None:
    """Resolve the active fallback provider from config.

    Returns "claude_cli", "anthropic_sdk", or None if nothing is available.
    Legacy value "claude" is normalised to "auto".
    """
    raw = config.get("model_fallback_provider", "auto")
    if raw not in ("claude_cli", "anthropic_sdk", "auto"):
        raw = "auto"

    priority: list[str] = config.get(
        "model_fallback_provider_priority", ["claude_cli", "anthropic_sdk"]
    )
    _available = {
        "claude_cli": detect_claude_cli(),
        "anthropic_sdk": detect_anthropic_sdk(),
    }

    if raw == "claude_cli":
        return "claude_cli" if _available["claude_cli"] else None
    if raw == "anthropic_sdk":
        return "anthropic_sdk" if _available["anthropic_sdk"] else None
    for p in priority:
        if _available.get(p, False):
            return p
    return None


def _ask_via_anthropic_sdk(
    prompt: str,
    cfg: dict,
    _audit,
    timeout_sec: int,
) -> dict:
    """Call Anthropic Python SDK. Returns normalized response dict."""
    max_output = cfg.get("max_answer_chars", 2500)
    try:
        import anthropic as _anthropic  # type: ignore[import]
    except ImportError:
        _audit("unavailable", "sdk_missing", "unavailable", ["anthropic SDK not installed"])
        return {
            **_FALLBACK_TEMPLATE,
            "source": "unavailable",
            "answer": "Claude fallback is enabled but the anthropic SDK is unavailable.",
            "warnings": ["anthropic SDK not installed. Run: uv add anthropic"],
        }
    try:
        client = _anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=min(max_output // 2, 1024),
            messages=[{"role": "user", "content": prompt}],
            timeout=float(timeout_sec),
        )
        raw_text: str = msg.content[0].text if msg.content else ""
    except _anthropic.AuthenticationError:
        _audit("unavailable", "auth_error", "error", ["ANTHROPIC_API_KEY not set or invalid"])
        return {
            **_FALLBACK_TEMPLATE,
            "source": "unavailable",
            "answer": "Claude fallback is enabled but ANTHROPIC_API_KEY is not set or invalid.",
            "warnings": ["ANTHROPIC_API_KEY not set or invalid."],
        }
    except Exception as exc:
        reason = str(exc)[:120]
        _audit("unavailable", reason, "error", [f"Provider error: {reason}"])
        return {
            **_FALLBACK_TEMPLATE,
            "source": "unavailable",
            "answer": "Claude fallback provider returned an error.",
            "warnings": [f"Provider error: {reason}"],
        }
    result = normalize_model_answer(raw_text)
    _audit(result.get("source", "claude_fallback"), "local_insufficient", "ok", result.get("warnings", []))
    return result


def _ask_via_claude_cli(
    prompt: str,
    cfg: dict,
    _audit,
    timeout_sec: int,
) -> dict:
    """Call the `claude` CLI in non-interactive print mode.

    Uses --print so no interactive UI is spawned. --no-tools and --dangerously-skip-permissions
    are deliberately NOT passed — they are not valid flags. Instead the prompt itself is the
    full Q&A boundary; the model is constrained by the prompt schema, not CLI flags.
    Shell access is NOT granted to the answering model; this subprocess is just the transport.
    """
    claude_path = shutil.which("claude")
    if not claude_path:
        _audit("unavailable", "cli_missing", "unavailable", ["claude CLI not found on PATH"])
        return {
            **_FALLBACK_TEMPLATE,
            "source": "unavailable",
            "answer": "Claude fallback is enabled but the Claude CLI is unavailable.",
            "warnings": ["claude CLI not found on PATH"],
        }
    try:
        result = subprocess.run(
            [claude_path, "--print", "--model", "claude-haiku-4-5-20251001"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=float(timeout_sec),
            shell=False,
        )
    except subprocess.TimeoutExpired:
        _audit("unavailable", "cli_timeout", "error", ["Claude CLI call timed out"])
        return {
            **_FALLBACK_TEMPLATE,
            "source": "unavailable",
            "answer": "Claude fallback provider timed out.",
            "warnings": ["Claude CLI call timed out."],
        }
    except FileNotFoundError:
        _audit("unavailable", "cli_not_found", "error", ["claude binary not found"])
        return {
            **_FALLBACK_TEMPLATE,
            "source": "unavailable",
            "answer": "Claude fallback is enabled but the Claude CLI binary is not found.",
            "warnings": ["claude binary not found at expected path."],
        }
    except Exception as exc:
        reason = str(exc)[:120]
        _audit("unavailable", reason, "error", [f"CLI error: {reason}"])
        return {
            **_FALLBACK_TEMPLATE,
            "source": "unavailable",
            "answer": "Claude fallback provider returned an error.",
            "warnings": [f"CLI error: {reason}"],
        }
    if result.returncode != 0:
        stderr_snippet = (result.stderr or "")[:200]
        _audit("unavailable", "cli_nonzero_exit", "error", [f"Claude CLI exited {result.returncode}: {stderr_snippet}"])
        return {
            **_FALLBACK_TEMPLATE,
            "source": "unavailable",
            "answer": "Claude fallback provider returned an error.",
            "warnings": [f"Claude CLI exited {result.returncode}: {stderr_snippet}"],
        }
    raw_text = result.stdout or ""
    norm = normalize_model_answer(raw_text)
    _audit(norm.get("source", "claude_fallback"), "local_insufficient", "ok", norm.get("warnings", []))
    return norm


def build_bounded_context(
    question: str,
    category: str,
    local_evidence: list[dict],
    selected_node_id: str | None = None,
    config: dict | None = None,
) -> dict:
    """Gather bounded, curated context from allowlisted files only.

    Returns:
        context_text: compact string passed to Claude
        has_context: bool (False if no context found)
        evidence: evidence dicts used
        warnings: list of warnings
    """
    cfg = config or load_citadel_ask_config()
    max_ctx = cfg.get("max_context_chars", 20000)
    max_items = cfg.get("max_evidence_items", 12)
    allowed_files: list[str] = cfg.get("allowed_context_files", [])

    context_parts: list[str] = []
    evidence: list[dict] = []
    warnings: list[str] = []

    for ev in (local_evidence or [])[:max_items]:
        src = str(ev.get("source", ""))
        det = str(ev.get("detail", ""))
        if any(p in src.lower() for p in _FORBIDDEN_CONTEXT):
            warnings.append(f"Skipped forbidden evidence source: {src}")
            continue
        context_parts.append(f"[{src}] {det}")
        evidence.append(ev)
        if sum(len(p) for p in context_parts) >= max_ctx // 2:
            break

    if selected_node_id and len(context_parts) < max_items:
        graph_path = ROOT / "docs" / "brain" / "graph.json"
        if graph_path.exists():
            try:
                gdata = json.loads(graph_path.read_text())
                nodes = {n["id"]: n for n in gdata.get("nodes", [])}
                node = nodes.get(selected_node_id)
                if node:
                    node_str = json.dumps(node, ensure_ascii=False)[:2000]
                    context_parts.append(f"[selected-node: {selected_node_id}] {node_str}")
                    evidence.append({
                        "source": "docs/brain/graph.json",
                        "detail": f"node → {selected_node_id}",
                    })
            except (json.JSONDecodeError, OSError):
                warnings.append("Could not read graph.json for node context.")

    for rel_path in _CATEGORY_FILE_HINTS.get(category, [])[:2]:
        if rel_path not in allowed_files:
            continue
        if any(p in rel_path.lower() for p in _FORBIDDEN_CONTEXT):
            continue
        full_path = ROOT / rel_path
        if not full_path.exists():
            continue
        try:
            snippet = full_path.read_text()[:3000]
            context_parts.append(f"[{rel_path}] (excerpt)\n{snippet}")
            evidence.append({"source": rel_path, "detail": f"loaded for {category} context"})
        except OSError:
            warnings.append(f"Could not read {rel_path}")

    full_ctx = "\n".join(context_parts)
    if len(full_ctx) > max_ctx:
        full_ctx = full_ctx[:max_ctx] + "\n... [context truncated]"
        warnings.append("Context truncated to max_context_chars.")

    return {
        "context_text": full_ctx,
        "has_context": bool(context_parts),
        "evidence": evidence[:max_items],
        "warnings": warnings,
    }


def build_claude_fallback_prompt(question: str, category: str, bounded_context: dict) -> str:
    """Build bounded-context Claude prompt. Never includes secrets or unallowlisted paths."""
    ctx = bounded_context.get("context_text", "")
    return f"""You are answering a Citadel local system question.
Category: {category}
Use ONLY the provided context below. Do not claim access to files or tools you do not have.
Do not invent counts. If counts are not present in the context, say the evidence is insufficient.
If sources disagree, report the mismatch. Be concise (max ~400 words).
Return valid JSON only — no markdown, no code fences, no commentary outside the JSON.

Required response schema:
{{
  "answer": "...",
  "source": "claude_fallback",
  "confidence": "high|medium|low",
  "category": "{category}",
  "evidence": [{{"source": "...", "detail": "..."}}],
  "warnings": [],
  "suggested_questions": []
}}

--- CONTEXT ---
{ctx}
--- END CONTEXT ---

Question: {question}"""


def _write_audit(
    audit_path: Path,
    prompt_prefix: str,
    source: str,
    reason: str,
    provider_status: str,
    warnings: list[str],
    t0: float,
) -> None:
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "question_hash": hashlib.sha256(prompt_prefix.encode()).hexdigest()[:16],
        "source": source,
        "provider_status": provider_status,
        "fallback_reason": reason,
        "duration_ms": int((time.monotonic() - t0) * 1000),
        "warnings": warnings,
    }
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def ask_claude_fallback(
    prompt: str, config: dict | None = None, timeout_sec: int = 30
) -> dict:
    """Call the resolved fallback provider with a bounded Q&A prompt.

    Supports providers: claude_cli, anthropic_sdk.
    Provider is resolved from config (supports auto, claude_cli, anthropic_sdk).
    Enforces: Q&A only, one call, no tools, bounded input/output.
    """
    cfg = config or load_citadel_ask_config()
    audit_enabled = cfg.get("audit_log_enabled", False)
    audit_path = ROOT / cfg.get("audit_log_path", ".claude/state/citadel-ask-audit.log")
    t_sec = cfg.get("timeout_sec", cfg.get("model_fallback_timeout_sec", timeout_sec))
    t0 = time.monotonic()
    prompt_prefix = prompt[:200]

    def _audit(source: str, reason: str, status: str, w: list[str]) -> None:
        if audit_enabled:
            _write_audit(audit_path, prompt_prefix, source, reason, status, w, t0)

    prompt_lower = prompt.lower()
    if any(p in prompt_lower for p in _FORBIDDEN_QUESTION_PATTERNS):
        _audit("unavailable", "forbidden_request", "rejected", ["Forbidden request rejected"])
        return {
            **_FALLBACK_TEMPLATE,
            "source": "unavailable",
            "answer": (
                "I cannot do that from Ask Citadel. "
                "Ask Citadel is read-only Q&A and cannot run commands, edit files, or access secrets."
            ),
            "warnings": ["Forbidden request rejected before model call."],
        }

    provider = resolve_provider(cfg)
    if provider is None:
        _audit("unavailable", "no_provider", "unavailable", ["No fallback provider available"])
        return {
            **_FALLBACK_TEMPLATE,
            "source": "unavailable",
            "answer": "Claude fallback is enabled but no fallback provider is available.",
            "warnings": ["No fallback provider available. Install the anthropic SDK or ensure the claude CLI is on PATH."],
        }

    if provider == "claude_cli":
        return _ask_via_claude_cli(prompt, cfg, _audit, int(t_sec))
    return _ask_via_anthropic_sdk(prompt, cfg, _audit, int(t_sec))


def normalize_model_answer(raw_text: str) -> dict:
    """Parse Claude's JSON response. Wraps non-JSON in a low-confidence result."""
    if not raw_text:
        return {
            **_FALLBACK_TEMPLATE,
            "source": "unavailable",
            "answer": "Model returned empty response.",
            "confidence": "low",
        }

    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        data.setdefault("source", "claude_fallback")
        data.setdefault("confidence", "medium")
        data.setdefault("category", "")
        data.setdefault("evidence", [])
        data.setdefault("warnings", [])
        data.setdefault("suggested_questions", [])
        data["model_fallback_used"] = True
        if data["source"] not in {"claude_fallback", "local_plus_claude", "unavailable"}:
            data["source"] = "claude_fallback"
        return data
    except (json.JSONDecodeError, ValueError):
        return {
            **_FALLBACK_TEMPLATE,
            "answer": raw_text[:2000],
            "source": "claude_fallback",
            "confidence": "low",
            "warnings": ["Model returned non-JSON; wrapped as low-confidence answer."],
        }
