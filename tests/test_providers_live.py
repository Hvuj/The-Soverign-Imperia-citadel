"""Live provider smoke — real Groq/NVIDIA calls when a key is present. Skips without the key, and skips on
no-network (so it passes locally with keys, skips cleanly in sandboxed CI)."""

import pytest

from citadel.services.execute.blueprint import Blueprint
from citadel.services.execute.providers import available_providers, build_provider_executor

_AVAILABLE = available_providers()


def _run(provider: str):
    ex = build_provider_executor(provider)
    assert ex is not None
    result = ex.execute(Blueprint(task_id="live", instruction="Reply with exactly the word: ok"))
    if result.status != "pass" and ("Connection" in result.reason or "certificate" in result.reason.lower()):
        pytest.skip(f"no network to {provider}")
    assert result.status == "pass", result.reason
    assert isinstance(result.output, str) and result.output


@pytest.mark.skipif("groq" not in _AVAILABLE, reason="GROK_API_KEY not set")
def test_groq_live():
    _run("groq")


@pytest.mark.skipif("nvidia" not in _AVAILABLE, reason="NVIDIA_API_KEY not set")
def test_nvidia_live():
    _run("nvidia")
