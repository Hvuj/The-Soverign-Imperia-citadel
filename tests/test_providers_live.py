"""Live provider smoke — real xAI-Grok / NVIDIA / Groq calls when a key is present (keys resolve from .env
via CitadelSettings). Skips without the key, and skips on any environment-specific failure (no network,
bad/expired key, model access, quota) so a code regression still fails but a key/quota issue does not."""

import pytest

from citadel.services.execute.blueprint import Blueprint
from citadel.services.execute.providers import available_providers, build_provider_executor

_AVAILABLE = available_providers()

# Reasons that are about the *environment* (key/network/quota/model access), not a citadel code defect.
_ENV_SKIP_MARKERS = (
    "connection", "certificate", "timed out", "timeout", "getaddrinfo",
    "incorrect api key", "invalid api key", "unauthorized", "forbidden", "401", "403",
    "model not found", "does not exist", "no access", "quota", "insufficient", "rate limit", "429",
)


def _run(provider: str):
    ex = build_provider_executor(provider)
    assert ex is not None
    result = ex.execute(Blueprint(task_id="live", instruction="Reply with exactly the word: ok"))
    if result.status != "pass":
        low = (result.reason or "").lower()
        if any(m in low for m in _ENV_SKIP_MARKERS):
            pytest.skip(f"{provider} unavailable (environment): {result.reason[:90]}")
    assert result.status == "pass", result.reason
    assert isinstance(result.output, str)
    assert result.output


@pytest.mark.skipif("grok" not in _AVAILABLE, reason="GROK_API_KEY not set")
def test_grok_live():
    _run("grok")


@pytest.mark.skipif("nvidia" not in _AVAILABLE, reason="NVIDIA_API_KEY not set")
def test_nvidia_live():
    _run("nvidia")


@pytest.mark.skipif("groq" not in _AVAILABLE, reason="GROQ_API_KEY not set")
def test_groq_live():
    _run("groq")


def test_available_providers_reflects_dotenv_keys():
    # Whatever keys are in .env, available_providers() must reflect them and build real executors.
    for name in _AVAILABLE:
        ex = build_provider_executor(name)
        assert ex is not None
        assert ex.available()
