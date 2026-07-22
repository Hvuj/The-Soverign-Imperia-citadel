#!/usr/bin/env python3
"""
SOVEREIGN-IMPERIA-CITADEL Anthropic Model Dispatcher — Phase 13: The Corporate Spine & Prompt Caching.

Reads the compiled corporate spine (.claude/state/corporate-spine.md) and the dynamic
context capsule (.claude/state/context-capsule.json), then dispatches to the Anthropic
API with a structured system payload that places the stable spine under a prompt-cache
marker (cache_control: {"type": "ephemeral"}) and appends the volatile capsule after it.

Prompt-cache design:
  - Stable prefix (spine)   → cache_control: ephemeral — saved on first call, read on
                               subsequent calls; avoids re-processing large governance text.
  - Volatile suffix (capsule) → no cache marker — per-task content that changes each call.

Anthropic prefix-cache requirement: the cached prefix must be byte-identical across
calls.  The spine compiler's SHA-256 gate ensures the spine file is only rewritten
when content changes, keeping the prefix stable.

Credentials: resolved exclusively from the environment via ANTHROPIC_API_KEY.
No API key is ever hardcoded, logged, written to disk, or printed.

Inputs:  .claude/state/corporate-spine.md        (compiled by corporate_spine_compiler.py)
         .claude/state/context-capsule.json       (written by obsidian_task_bridge.py)
Output:  string response from claude-opus-4-8 (or model override)
"""


import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

_ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or os.path.abspath(Path(__file__).parent.parent))
SPINE_PATH = _ROOT / ".claude" / "state" / "corporate-spine.md"
CAPSULE_PATH = _ROOT / ".claude" / "state" / "context-capsule.json"

_DEFAULT_MODEL = "claude-opus-4-8"
_CLI_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _read_spine() -> str:
    """Return the compiled corporate spine, stripping the hash-comment header.

    The first line of corporate-spine.md is ``<!-- spine-sha256: <hash> -->``
    (written by CorporateSpineCompiler).  It is stripped here so the cached
    text starts cleanly with ``# SOVEREIGN-IMPERIA-CITADEL Corporate Spine``.
    """
    if not SPINE_PATH.exists():
        return ""
    try:
        text = SPINE_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = text.split("\n", 1)
    if len(lines) == 2 and lines[0].startswith("<!-- spine-sha256:"):
        return lines[1]
    return text


def _read_capsule() -> str:
    """Return the context capsule as a formatted JSON string, or '' if absent."""
    if not CAPSULE_PATH.exists():
        return ""
    try:
        data = json.loads(CAPSULE_PATH.read_text(encoding="utf-8"))
        return json.dumps(data, indent=2)
    except (OSError, json.JSONDecodeError):
        return ""


def _build_system_payload(spine_text: str, capsule_text: str) -> list[dict]:
    """Build a structured Anthropic system payload with prompt-cache markers.

    Block order (required by Anthropic prefix-cache semantics):
      1. Stable spine  — cache_control: ephemeral (large, slow-changing prefix)
      2. Volatile capsule — no cache marker (per-task, changes each call)

    Args:
        spine_text:   Content of corporate-spine.md (hash-comment already stripped).
        capsule_text: JSON-formatted context capsule, or ''.

    Returns:
        List of Anthropic TextBlockParam dicts.
    """
    payload: list[dict] = []
    if spine_text:
        payload.append(
            {
                "type": "text",
                "text": spine_text,
                "cache_control": {"type": "ephemeral"},
            }
        )
    if capsule_text:
        payload.append(
            {
                "type": "text",
                "text": f"DYNAMIC TASK CONTEXT:\n{capsule_text}",
            }
        )
    return payload


def _build_cli_prompt(spine_text: str, capsule_text: str, user_message: str) -> str:  # noqa: ARG001
    """Build a single-string prompt for CLI dispatch.

    The CLI has no separate system channel, so context is prepended inline.
    The full spine is omitted for CLI calls — it is large and optimised for SDK
    prompt-cache prefixes.  The compact dynamic capsule is included when present.

    Args:
        spine_text:   Ignored for CLI dispatch (too large; SDK-only optimisation).
        capsule_text: JSON-formatted context capsule, or ''.
        user_message: The user question / task.

    Returns:
        A single string ready to be passed as stdin to the claude CLI.
    """
    if capsule_text:
        return f"CONTEXT:\n{capsule_text.strip()}\n\n{user_message}"
    return user_message


def _dispatch_via_cli(prompt_with_context: str, model: str = _CLI_DEFAULT_MODEL) -> str:
    """Dispatch to Claude via the authenticated ``claude`` CLI subprocess.

    Credentials are resolved by the already-authenticated CLI.  No API key is
    handled, stored, or printed here.

    Args:
        prompt_with_context: The full prompt string to send as stdin.
        model:               Claude model ID to request (default: haiku).

    Returns:
        The CLI stdout as a string.

    Raises:
        RuntimeError: If the CLI is not on PATH, times out, or exits non-zero.
                      The error message is safe to log (no credentials exposed).
    """
    claude_path = shutil.which("claude")
    if not claude_path:
        raise RuntimeError("claude CLI not on PATH — install it or ensure ~/.local/bin is in PATH")
    # A neutral scratch cwd (never the workspace). `tempfile.gettempdir()` is cross-platform —
    # a literal "/tmp" does not exist on native Windows and would raise here.
    cli_cwd = tempfile.gettempdir()
    try:
        result = subprocess.run(
            [claude_path, "--print", "--model", model],
            input=prompt_with_context,
            text=True,
            capture_output=True,
            timeout=60,
            shell=False,
            cwd=cli_cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("claude CLI timed out after 60 s") from exc
    if result.returncode != 0:
        snippet = (result.stderr or "")[:200]
        raise RuntimeError(f"claude CLI exited {result.returncode}: {snippet}")
    return result.stdout or ""


def _yield_cli_chunks(prompt_with_context: str, model: str = _CLI_DEFAULT_MODEL) -> Iterator[str]:
    """Run _dispatch_via_cli and yield the result as word-chunks (simulates streaming)."""
    full_text = _dispatch_via_cli(prompt_with_context, model=model)
    words = full_text.split(" ")
    for i in range(0, len(words), 4):
        yield " ".join(words[i : i + 4]) + " "


def dispatch(user_message: str, model: str = _DEFAULT_MODEL) -> str:
    """Dispatch a message to Anthropic, falling back to the claude CLI when the SDK is absent.

    Primary path: Anthropic SDK + ANTHROPIC_API_KEY (prompt-cache, structured system payload).
    Fallback path: authenticated ``claude`` CLI subprocess (no API key required).

    Credentials are never hardcoded, logged, or written to any file.

    Args:
        user_message: The task/question to send to the model.
        model:        Anthropic model ID for the SDK path (default: claude-opus-4-8).
                      CLI fallback always uses _CLI_DEFAULT_MODEL (haiku).

    Returns:
        Text content of the first text block in the response.

    Raises:
        RuntimeError: Only when both the SDK path and the CLI path are unavailable.
    """
    spine_text = _read_spine()
    capsule_text = _read_capsule()

    try:
        import anthropic  # noqa: PLC0415 — deferred so missing SDK falls through to CLI
    except ImportError:
        return _dispatch_via_cli(_build_cli_prompt(spine_text, capsule_text, user_message))

    system_payload = _build_system_payload(spine_text, capsule_text)

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=system_payload if system_payload else anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.AuthenticationError:
        return _dispatch_via_cli(_build_cli_prompt(spine_text, capsule_text, user_message))
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError("Anthropic API connection error — check network connectivity") from exc

    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def dispatch_stream(user_message: str, model: str = _DEFAULT_MODEL) -> Iterator[str]:
    """Stream a message to Anthropic; yield incremental text delta strings.

    Primary path: Anthropic SDK token streaming (true per-token deltas).
    Fallback path: authenticated ``claude`` CLI subprocess, output yielded as word-chunks.

    Args:
        user_message: The task/question to stream to the model.
        model:        Anthropic model ID for the SDK path (default: claude-opus-4-8).
                      CLI fallback always uses _CLI_DEFAULT_MODEL (haiku).

    Yields:
        Incremental text delta strings from the model response.

    Raises:
        RuntimeError: Only when both the SDK path and the CLI path are unavailable.
    """
    spine_text = _read_spine()
    capsule_text = _read_capsule()
    full_prompt = _build_cli_prompt(spine_text, capsule_text, user_message)

    try:
        import anthropic  # noqa: PLC0415 — deferred so missing SDK falls through to CLI
    except ImportError:
        yield from _yield_cli_chunks(full_prompt)
        return

    system_payload = _build_system_payload(spine_text, capsule_text)
    _use_cli_fallback = False

    try:
        client = anthropic.Anthropic()
        with client.messages.stream(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=system_payload if system_payload else anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            yield from stream.text_stream
    except anthropic.AuthenticationError:
        _use_cli_fallback = True
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError("Anthropic API connection error — check network connectivity") from exc

    if _use_cli_fallback:
        yield from _yield_cli_chunks(full_prompt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SOVEREIGN-IMPERIA-CITADEL Anthropic Model Dispatcher with prompt-cache injection")
    parser.add_argument(
        "--message",
        metavar="TEXT",
        help="Dispatch a message to the model and print the response",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help=(
            "Offline payload-shape test — asserts cache_control is well-formed "
            "on the spine block and absent on the capsule block. "
            "No network call; no API key required."
        ),
    )
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"Model ID to use (default: {_DEFAULT_MODEL})",
    )
    args = parser.parse_args()

    if args.test:
        spine_text = _read_spine()
        capsule_text = _read_capsule()
        payload = _build_system_payload(spine_text, capsule_text)

        assert isinstance(payload, list), f"Expected list payload, got {type(payload)}"

        for block in payload:
            assert isinstance(block, dict), f"Expected dict block, got {type(block)}"
            assert block.get("type") == "text", f"Expected text block, got type={block.get('type')}"

        if spine_text and payload:
            spine_block = payload[0]
            assert spine_block.get("cache_control") == {"type": "ephemeral"}, (
                f"Spine block cache_control mismatch: {spine_block.get('cache_control')}"
            )

        if capsule_text and len(payload) > 1:
            capsule_block = payload[-1]
            assert "cache_control" not in capsule_block, "Capsule block must NOT carry cache_control (volatile content)"

        print(
            f"Dispatcher payload test passed. "
            f"blocks={len(payload)}, "
            f"spine_present={bool(spine_text)}, "
            f"capsule_present={bool(capsule_text)}"
        )
        sys.exit(0)

    if args.message:
        try:
            result = dispatch(args.message, model=args.model)
            print(result)
            sys.exit(0)
        except RuntimeError as exc:
            print(f"Dispatch error: {exc}", file=sys.stderr)
            sys.exit(1)

    parser.print_help()
    sys.exit(1)
