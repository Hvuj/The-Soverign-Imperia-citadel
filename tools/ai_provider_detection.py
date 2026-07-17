#!/usr/bin/env python3
"""ai_provider_detection.py — Detect Claude Code, co-work, and Anthropic SDK availability.

Writes .claude/state/ai-provider-status.json with detection results and resolved provider map.
Never crashes if a provider is missing — marks it unavailable cleanly.

Called ONLY from Citadel endpoints or manual invocation.
Daemons, index builders, and graph builders must NOT import this module.
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
_PROVIDER_CONFIG_PATH = ROOT / ".claude" / "brain" / "ai-provider-config.json"
_STATUS_PATH = ROOT / ".claude" / "state" / "ai-provider-status.json"

_FORBIDDEN_COMMANDS = [
    "rm -rf", "git push", "git commit", "deploy", "kubectl",
    "terraform apply", "npm publish",
]


def _load_provider_config() -> dict:
    try:
        return json.loads(_PROVIDER_CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _safe_version(cmd: str, version_flag: str = "--version", timeout: int = 5) -> str | None:
    """Run `cmd version_flag` and return stdout, or None on any failure."""
    if not cmd:
        return None
    try:
        result = subprocess.run(
            [cmd, version_flag],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip().split("\n")[0][:120] if result.returncode == 0 else None
    except Exception:
        return None


def detect_claude_code(config: dict) -> dict:
    """Detect Claude Code / Claude CLI availability."""
    provider_cfg = config.get("providers", {}).get("claude_code", {})
    if not provider_cfg.get("enabled", True):
        return {
            "configured": False, "available": False,
            "mode": "disabled", "command": "", "version": None, "status": "disabled",
        }

    cmd = provider_cfg.get("command", "claude") or "claude"
    configured_bin = os.environ.get("CLAUDE_BIN")
    found = configured_bin if configured_bin and Path(configured_bin).is_file() else shutil.which(cmd)

    if not found:
        return {
            "configured": True, "available": False,
            "mode": "cli", "command": cmd, "version": None,
            "status": "yellow",
            "hint": f"'{cmd}' not found on PATH. Install Claude Code or add it to PATH.",
        }

    version = _safe_version(found, "--version")
    return {
        "configured": True, "available": True,
        "mode": "cli", "command": found, "version": version or "unknown",
        "status": "green",
    }


def detect_cowork(config: dict) -> dict:
    """Detect co-work provider. Config-driven — binary name must be set in ai-provider-config.json."""
    provider_cfg = config.get("providers", {}).get("cowork", {})
    if not provider_cfg.get("enabled", True):
        return {
            "configured": False, "available": False,
            "mode": "disabled", "command": "", "version": None, "status": "disabled",
        }

    cmd = provider_cfg.get("command", "").strip()
    if not cmd:
        return {
            "configured": False, "available": False,
            "mode": "detect", "command": "", "version": None,
            "status": "yellow",
            "hint": (
                "co-work command not configured. "
                "Set providers.cowork.command in .claude/brain/ai-provider-config.json."
            ),
        }

    found = shutil.which(cmd)
    if not found:
        return {
            "configured": True, "available": False,
            "mode": "cli", "command": cmd, "version": None,
            "status": "yellow",
            "hint": f"co-work command '{cmd}' not found on PATH.",
        }

    version = _safe_version(cmd, "--version")
    return {
        "configured": True, "available": True,
        "mode": "cli", "command": cmd, "version": version or "unknown",
        "status": "green",
    }


def detect_anthropic_sdk(config: dict) -> dict:
    """Detect Anthropic SDK — only if explicitly enabled in config."""
    provider_cfg = config.get("providers", {}).get("anthropic_sdk", {})
    if not provider_cfg.get("enabled", False):
        return {
            "configured": False, "available": False,
            "status": "disabled",
        }

    available = importlib.util.find_spec("anthropic") is not None
    return {
        "configured": True, "available": available,
        "status": "green" if available else "yellow",
        "hint": None if available else "Install anthropic SDK: uv add anthropic",
    }


def resolve_providers(config: dict, detection: dict) -> dict:
    """Map each mode to the best available provider."""
    def _best_for(mode_key: str, allowed_attr: str) -> str | None:
        providers_cfg = config.get("providers", {})
        for p_name in ["claude_code", "cowork", "anthropic_sdk"]:
            p_cfg = providers_cfg.get(p_name, {})
            if not p_cfg.get("enabled", False):
                continue
            if not p_cfg.get(allowed_attr, False):
                continue
            det = detection.get(p_name, {})
            if det.get("available", False):
                return p_name
        return None

    ask_fallback = _best_for("ask_fallback", "allow_qna")
    planning = _best_for("planning", "allow_planning")
    execution = _best_for("execution", "allow_execution")
    review = _best_for("review", "allow_review")

    return {
        "ask_fallback": ask_fallback,
        "planning": planning,
        "execution": execution,
        "review": review,
    }


def detect_all(config: dict | None = None) -> dict:
    """Run all provider detections and return full status dict."""
    if config is None:
        config = _load_provider_config()

    claude_code = detect_claude_code(config)
    cowork = detect_cowork(config)
    anthropic_sdk = detect_anthropic_sdk(config)

    detection = {
        "claude_code": claude_code,
        "cowork": cowork,
        "anthropic_sdk": anthropic_sdk,
    }

    resolved = resolve_providers(config, detection)

    providers_cfg = config.get("providers", {})

    def _capabilities(p_name: str, det: dict) -> dict:
        p_cfg = providers_cfg.get(p_name, {})
        available = det.get("available", False)
        return {
            "supports_qna": available and p_cfg.get("allow_qna", False),
            "supports_plan": available and p_cfg.get("allow_planning", False),
            "supports_execute": available and p_cfg.get("allow_execution", False),
            "supports_review": available and p_cfg.get("allow_review", False),
            "supports_noninteractive": available and p_name in ("claude_code", "anthropic_sdk"),
            "supports_readonly_mode": available,
        }

    now = datetime.now(UTC).isoformat()
    status = {
        "schema_version": "1.0",
        "detected_at": now,
        "claude_code": {**claude_code, "capabilities": _capabilities("claude_code", claude_code)},
        "cowork": {**cowork, "capabilities": _capabilities("cowork", cowork)},
        "anthropic_sdk": {**anthropic_sdk},
        "resolved": resolved,
        "overall": _overall_status(claude_code, cowork, config),
    }
    return status


def _overall_status(claude_code: dict, cowork: dict, config: dict) -> str:
    security = config.get("security", {})
    if security.get("daemon_invocation_allowed", False):
        return "red"

    cc_enabled = config.get("providers", {}).get("claude_code", {}).get("enabled", True)
    cw_enabled = config.get("providers", {}).get("cowork", {}).get("enabled", True)

    if cc_enabled and not claude_code.get("available", False):
        return "yellow"
    if cw_enabled and not cowork.get("available", False):
        return "yellow"
    return "green"


def write_status(status: dict) -> None:
    _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATUS_PATH.write_text(json.dumps(status, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect AI provider availability")
    parser.add_argument("--pretty", action="store_true", help="Print human-readable output")
    parser.add_argument("--no-write", action="store_true", help="Skip writing status file")
    args = parser.parse_args()

    config = _load_provider_config()
    status = detect_all(config)

    if not args.no_write:
        write_status(status)

    if args.pretty:
        print("AI Provider Detection")
        print("=" * 40)
        for p_name in ("claude_code", "cowork", "anthropic_sdk"):
            det = status[p_name]
            s = det.get("status", "unknown")
            cmd = det.get("command", "")
            ver = det.get("version", "")
            icon = {"green": "✓", "yellow": "~", "red": "✗", "disabled": "-"}.get(s, "?")
            print(f"  [{icon}] {p_name}: {s}  cmd={cmd!r}  ver={ver!r}")
            hint = det.get("hint")
            if hint:
                print(f"       hint: {hint}")

        print()
        print("Resolved providers:")
        for mode, provider in status["resolved"].items():
            print(f"  {mode}: {provider or 'none'}")
        print(f"\nOverall: {status['overall']}")
        if not args.no_write:
            print(f"Written: {_STATUS_PATH}")
    else:
        print(json.dumps(status, indent=2))

    sys.exit(0)


if __name__ == "__main__":
    main()
