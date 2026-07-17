"""foreign.py — Foreign Policy (System 5): the egress gate for outbound traffic to external models.

Intercepts every outbound "envoy" (a prompt bound for a cloud provider) and evaluates it before it leaves:

1. **Threat level** — refuse outright if the text references sensitive material (`.env`, private keys,
   `[PRIVATE]`, …) — the deny-list; the caller falls back to a local model.
2. **Handshake** — egress is authorized only to **allowlisted hosts** (the provider's own domain).
3. **Redaction** — otherwise, secrets are masked *before* the packet leaves the machine.

This is the composition of the existing provider `gate` (deny-list + egress allowlist) with the single
redaction implementation — one seam so the whole federation shares one boundary policy.
"""

from collections.abc import Callable

from citadel.services.execute.providers.gate import contains_sensitive, egress_allowed


def _default_redact() -> Callable[[str], str]:
    try:
        from citadel.services._tools_bridge import import_tool

        return import_tool("citadel_custos").redact
    except Exception:
        return lambda text: text


class ForeignPolicy:
    def __init__(self, *, redact: Callable[[str], str] | None = None, extra_hosts: set[str] | None = None) -> None:
        self._redact = redact or _default_redact()
        self._extra = extra_hosts or set()

    def vet(self, text: str, base_url: str) -> tuple[bool, str, str]:
        """Return (allowed, reason, payload). `payload` is the redacted, safe-to-send text when allowed, else ""."""
        marker = contains_sensitive(text)
        if marker:
            return False, f"blocked: references sensitive material ({marker})", ""
        if not egress_allowed(base_url, self._extra):
            return False, f"blocked: egress to '{base_url}' is not on the allowlist", ""
        return True, "authorized", self._redact(text)

    def allows_host(self, base_url: str) -> bool:
        return egress_allowed(base_url, self._extra)
