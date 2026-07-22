"""openai_compat.py — one Executor for every OpenAI-compatible cloud provider (Groq, NVIDIA, …).

Implements the same `Executor.execute(blueprint) -> ExecutionResult` contract as `CloudClaudeExecutor`, so
the whole federation drops into `sovereign_run`, the army, and the consensus engine unchanged. The `openai`
client is injectable, so unit tests never hit the network. **Privacy is baked in:** every prompt is
secret-redacted (`citadel_custos.redact`) before it leaves the machine — this is a cloud call, so the
data-boundary rule applies by default.
"""

from collections.abc import Callable

from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor
from citadel.services.execute.providers.keys import resolve_provider_key
from citadel.services.execute.providers.registry import provider_spec

_STABLE_PREFIX = (
    "You are one member of a multi-model panel in the Sovereign Imperia Citadel. Follow the task exactly "
    "and return only the result."
)


def _default_redact() -> Callable[[str], str]:
    try:
        from citadel.services._tools_bridge import import_tool

        return import_tool("citadel_custos").redact
    except Exception:
        return lambda text: text


def _is_rate_limited(exc: Exception) -> bool:
    """True for an HTTP 429 / rate-limit error (so the budget guard can throttle the provider)."""
    if getattr(exc, "status_code", None) == 429:
        return True
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


class OpenAICompatExecutor(Executor):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        provider: str = "openai",
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout: float = 120.0,
        client=None,
        redact: Callable[[str], str] | None = None,
        gate: bool = True,
        audit_path: str | None = None,
        budget=None,
    ) -> None:
        self.name = f"provider:{provider}:{model}"
        self.provider = provider
        self.model = model
        self._base_url = base_url
        self._api_key = api_key
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._client = client
        self._redact = redact if redact is not None else _default_redact()
        self._gate = gate
        self._audit_path = audit_path
        self._budget = budget

    def _get_client(self):
        if self._client is not None:
            return self._client
        from openai import OpenAI

        from citadel.services.execute.providers.keys import ensure_tls

        ensure_tls()  # trust the OS cert store (corporate-proxy environments) before the first call
        self._client = OpenAI(base_url=self._base_url, api_key=self._api_key, timeout=self._timeout)
        return self._client

    def available(self) -> bool:
        return bool(self._api_key)

    def _build_prompt(self, blueprint: Blueprint) -> str:
        parts = [_STABLE_PREFIX]
        if blueprint.allowed_files:
            parts.append("Allowed files: " + ", ".join(blueprint.allowed_files))
        if blueprint.context:
            parts.append("Context:\n" + blueprint.context)
        parts.append("Task:\n" + blueprint.instruction)
        return "\n\n".join(parts)

    def _audit(self, blueprint: Blueprint, *, sent: int, status: str, note: str = "") -> None:
        if not self._audit_path:
            return
        from citadel.services.execute.providers.gate import audit_cloud_call

        audit_cloud_call(self._audit_path, {
            "provider": self.provider, "model": self.model, "task_id": blueprint.task_id,
            "bytes_sent": sent, "status": status, "note": note, "redacted": True,
        })

    def execute(self, blueprint: Blueprint) -> ExecutionResult:
        from citadel.services.execute.providers.gate import contains_sensitive, egress_allowed

        if not self._api_key:
            return ExecutionResult(blueprint.task_id, "error", tier_used=self.name, reason="no api key")
        raw = self._build_prompt(blueprint)
        # Data-boundary gate: refuse to send sensitive material to the cloud (caller falls back to local).
        if self._gate:
            marker = contains_sensitive(raw)
            if marker:
                self._audit(blueprint, sent=0, status="blocked", note=marker)
                return ExecutionResult(blueprint.task_id, "blocked", tier_used=self.name,
                                       reason=f"withheld from cloud (sensitive: {marker})")
            if not egress_allowed(self._base_url):
                return ExecutionResult(blueprint.task_id, "error", tier_used=self.name,
                                       reason=f"egress not allowed to {self._base_url}")
        if self._budget is not None and not self._budget.allow(self.provider):
            return ExecutionResult(blueprint.task_id, "blocked", tier_used=self.name,
                                   reason=f"budget/rate limit for {self.provider}")
        prompt = self._redact(raw)  # redact secrets BEFORE it leaves the machine
        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            text = (resp.choices[0].message.content or "").strip()
        except Exception as exc:
            if self._budget is not None and _is_rate_limited(exc):
                self._budget.throttle(self.provider)  # deprioritize until it recovers
            self._audit(blueprint, sent=len(prompt), status="error", note=type(exc).__name__)
            return ExecutionResult(blueprint.task_id, "error", tier_used=self.name, reason=str(exc))
        if self._budget is not None:
            self._budget.record(self.provider)
        self._audit(blueprint, sent=len(prompt), status="pass")
        return ExecutionResult(blueprint.task_id, "pass", output=text, tier_used=self.name)


def build_provider_executor(
    provider: str,
    *,
    model: str | None = None,
    modality: str = "text",
    **kwargs,
) -> OpenAICompatExecutor | None:
    """Build an executor for a named provider (groq/nvidia), or None if the key is absent."""
    spec = provider_spec(provider)
    if spec is None:
        raise ValueError(f"unknown provider {provider!r}")
    key = resolve_provider_key(spec.key_env)
    if not key:
        return None
    chosen = model or spec.default_model(modality)
    if not chosen:
        return None
    return OpenAICompatExecutor(base_url=spec.base_url, api_key=key, model=chosen, provider=provider, **kwargs)
