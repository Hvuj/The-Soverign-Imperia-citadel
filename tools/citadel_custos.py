#!/usr/bin/env python3
"""citadel_custos.py — Custodiae, the context-window guard (masterplan §6.V, §8.1 ContextMinimization).

Three laws, mechanical so violating them is impossible rather than merely discouraged:
- **Count-first** — every large output is preceded by its size (count-before-content). `guard_output`
  always emits a preamble, so no stream reaches the context window uncounted (gate G4).
- **Output splicing** — serve only a bounded byte slice with a total, never the whole file.
- **Secret redaction** — mask credentials before any stream reaches the context window.

Degree-1 graph capping lives in `citadel_oracle.degree_one`.
"""

import re

_DEFAULT_MAX_LINES = 200
_DEFAULT_MAX_BYTES = 16 * 1024

_MASK_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\b(?:ghp|gho|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*"),
]
_ENV_PATTERN = re.compile(
    r"(?im)^(\s*[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY)[A-Z0-9_]*)\s*=\s*(\S+)"
)


def redact(text: str) -> str:
    """Mask credentials/secrets in a stream. Keeps `.env` key names, masks their values."""
    out = text or ""
    for pattern in _MASK_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return _ENV_PATTERN.sub(lambda m: f"{m.group(1)}=[REDACTED]", out)


def counts(text: str) -> dict:
    """The count-first preamble data: total lines + bytes (count-before-content law)."""
    data = text or ""
    return {"lines": len(data.splitlines()), "bytes": len(data.encode("utf-8"))}


def splice(text: str, max_bytes: int = _DEFAULT_MAX_BYTES) -> tuple[str, int, int]:
    """Serve only the first `max_bytes` of a stream (kernel-splice equivalent). Returns (body, served, total)."""
    raw = (text or "").encode("utf-8")
    total = len(raw)
    if total <= max_bytes:
        return text or "", total, total
    body = raw[:max_bytes].decode("utf-8", errors="ignore")
    return body, len(body.encode("utf-8")), total


def guard_output(
    text: str,
    *,
    max_lines: int = _DEFAULT_MAX_LINES,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    redact_secrets: bool = True,
) -> dict:
    """Count-first + splice + optional redaction. The returned dict ALWAYS carries a `preamble`, so nothing
    enters context uncounted (gate G4). Over-budget output is truncated by lines then byte-spliced, and the
    preamble states the true totals plus what was shown."""
    body_full = redact(text) if redact_secrets else (text or "")
    size = counts(body_full)
    if size["lines"] <= max_lines and size["bytes"] <= max_bytes:
        return {
            "preamble": f"[{size['lines']} lines, {size['bytes']} bytes]",
            "body": body_full, "truncated": False,
            "total_lines": size["lines"], "total_bytes": size["bytes"],
        }
    shown_lines = body_full.splitlines()[:max_lines]
    body, served, _ = splice("\n".join(shown_lines), max_bytes)
    return {
        "preamble": (
            f"[{size['lines']} lines, {size['bytes']} bytes — showing {len(shown_lines)} lines / "
            f"{served} bytes; paginate or refine to see more]"
        ),
        "body": body, "truncated": True,
        "total_lines": size["lines"], "total_bytes": size["bytes"],
    }
