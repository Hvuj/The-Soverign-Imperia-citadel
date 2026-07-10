#!/usr/bin/env python3
"""prompt_leak_output_filter.py — Scan model output for prompt-leak markers.

Local-only, no AI calls.

Modes:
  check  — Return JSON {leaked, markers_found, safe_message} (default).
  redact — Return text with markers replaced by [REDACTED].

Usage:
  echo "output text" | python tools/prompt_leak_output_filter.py [--mode check|redact]
  python tools/prompt_leak_output_filter.py --input output.txt [--mode check]
"""

import argparse
import json
import re
import sys
from pathlib import Path

_MARKERS: list[tuple[str, re.Pattern, bool]] = []

_MARKER_DEFS: list[tuple[str, str, bool]] = [
    ("private_key_begin", r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY", False),
    ("api_key_assignment", r"(API_KEY|ANTHROPIC_API_KEY|OPENAI_API_KEY|SECRET_KEY)\s*=\s*\S", False),
    ("token_assignment", r"(ACCESS_TOKEN|AUTH_TOKEN|SERVICE_TOKEN)\s*=\s*\S", False),
    ("password_assignment", r"PASSWORD\s*=\s*\S", False),
    ("reveal_system_prompt", r"(here is|this is|showing|displaying)\s+(my|the|your)\s+system\s+prompt", True),
    ("system_prompt_verbatim", r"system\s+prompt\s*[:=\|>]", True),
    ("developer_message", r"developer\s+message\s*[:=\|>]", True),
    ("hidden_instructions_verbatim", r"hidden\s+instructions\s*[:=\|>]", True),
    ("internal_prompt_verbatim", r"internal\s+prompt\s*[:=\|>]", True),
    ("verbatim_instructions", r"verbatim\s+instructions\s*[:=\|>]", True),
    ("raw_prompt_template", r"raw\s+prompt\s+template", True),
    ("template_hash_leak", r"template_(id|hash)\s*[:=]\s*[a-f0-9]{6,}", False),
]

for name, pattern, case_sensitive in _MARKER_DEFS:
    flags = 0 if case_sensitive else re.IGNORECASE
    _MARKERS.append((name, re.compile(pattern, flags), case_sensitive))


def scan_text(text: str) -> list[str]:
    """Return list of marker names found in text."""
    found = []
    for name, pattern, _ in _MARKERS:
        if pattern.search(text):
            found.append(name)
    return found


def check_mode(text: str) -> dict:
    """Scan text and return {leaked, markers_found, safe_message}."""
    markers = scan_text(text)
    leaked = len(markers) > 0
    safe_message = (
        "Citadel cannot reveal internal instructions, prompt templates, or secrets. "
        "Response blocked by prompt-leak filter."
        if leaked else ""
    )
    return {
        "leaked": leaked,
        "markers_found": markers,
        "safe_message": safe_message,
    }


def redact_mode(text: str) -> str:
    """Replace all leak markers with [REDACTED] and return modified text."""
    result = text
    for name, pattern, _ in _MARKERS:
        result = pattern.sub("[REDACTED]", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan model output for prompt-leak markers."
    )
    parser.add_argument("--input", default=None, help="Input file path. Reads stdin if not provided.")
    parser.add_argument("--mode", choices=["check", "redact"], default="check",
                        help="check: return JSON status. redact: return filtered text.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON in check mode.")
    args = parser.parse_args()

    if args.input:
        try:
            text = Path(args.input).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            sys.stderr.write(f"Error reading input: {exc}\n")
            sys.exit(1)
    else:
        text = sys.stdin.read()

    if args.mode == "check":
        result = check_mode(text)
        print(json.dumps(result, indent=2 if args.pretty else None))
    else:
        print(redact_mode(text), end="")


if __name__ == "__main__":
    main()
