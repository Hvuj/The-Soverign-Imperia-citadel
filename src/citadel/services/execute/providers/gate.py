"""gate.py — the cloud data-boundary gate (Phase 2): redact + deny-list + egress allowlist + audit.

The user's data policy is "redacted, non-sensitive only." Redaction (secret masking) is baked into the
executor; this gate adds the rest: (1) a **deny-list** that refuses to send prompts referencing sensitive
material (`.env`, private keys, `**/private/**`, `[PRIVATE]` markers) — the call is BLOCKED and the caller
falls back to local; (2) an **egress allowlist** so a cloud client may only talk to its provider's host;
(3) an **audit** trail of metadata only (provider, model, bytes, blocked?) — never the content.
"""

import json
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

# Markers that must never leave the machine, even redacted (defense in depth beyond secret masking).
_SENSITIVE = re.compile(
    r"(?i)(?:-----BEGIN [A-Z ]*PRIVATE KEY|\bid_rsa\b|\bid_ed25519\b|/\.ssh/|\[PRIVATE\]|\bCONFIDENTIAL\b"
    r"|(?:^|[\s/\\])\.env(?:\.[\w.]+)?\b|(?:^|[\s/\\])secrets?\.(?:json|ya?ml|toml|env)|(?:^|[\s/\\])private/)"
)

_ALLOWED_HOSTS = {"api.groq.com", "integrate.api.nvidia.com", "ai.api.nvidia.com"}


def contains_sensitive(text: str) -> str | None:
    """Return the offending marker if the text references sensitive material, else None."""
    match = _SENSITIVE.search(text or "")
    return match.group(0).strip() if match else None


def egress_allowed(base_url: str, extra_hosts: set[str] | None = None) -> bool:
    """True only if the base_url host is on the cloud-egress allowlist (the provider's own host)."""
    host = urlparse(base_url).hostname or ""
    return host in (_ALLOWED_HOSTS | (extra_hosts or set()))


def audit_cloud_call(audit_path: str | Path, entry: dict) -> None:
    """Append one metadata-only record to the provider audit log (never the prompt/response content)."""
    path = Path(audit_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": round(time.time(), 3), **entry}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        with open(tmp, encoding="utf-8") as src, path.open("a", encoding="utf-8") as dst:
            dst.write(src.read())
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
