"""P1 — the provider federation foundation: key resolution, the registry, and the OpenAI-compatible
executor with redaction-before-send. Uses an injected fake client — no network, no keys required."""

from types import SimpleNamespace

import pytest

from citadel.services.execute.blueprint import Blueprint
from citadel.services.execute.providers import (
    OpenAICompatExecutor,
    available_providers,
    build_provider_executor,
    provider_spec,
    resolve_provider_key,
)
from citadel.services.execute.providers.keys import masked


class _Completions:
    def __init__(self, reply: str) -> None:
        self.captured_messages = None
        self._reply = reply

    def create(self, model, messages, temperature=0.2, max_tokens=2048):
        self.captured_messages = messages
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._reply))])


class FakeOpenAI:
    def __init__(self, reply: str = "def solution():\n    return 42\n") -> None:
        self.chat = SimpleNamespace(completions=_Completions(reply))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GROK_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    # prevent .env on disk from leaking a real key into these tests
    import citadel.services.execute.providers.keys as keys
    monkeypatch.setattr(keys, "_loaded", True, raising=False)


def test_key_resolution_precedence(monkeypatch):
    assert resolve_provider_key("GROK_API_KEY") is None
    monkeypatch.setenv("GROK_API_KEY", "env-key")
    assert resolve_provider_key("GROK_API_KEY") == "env-key"
    assert resolve_provider_key("GROK_API_KEY", explicit="override") == "override"


def test_masked_never_leaks_the_key():
    assert masked("nvapi-abcdefghijklmnop") == "nva…mnop"
    assert masked(None) == "(absent)"


def test_registry_specs_and_defaults():
    groq = provider_spec("groq")
    assert groq.base_url == "https://api.groq.com/openai/v1" and groq.key_env == "GROK_API_KEY"
    nvidia = provider_spec("nvidia")
    assert nvidia.default_model("text") and nvidia.default_model("vision") and nvidia.default_model("image")
    assert nvidia.egress_domain == "integrate.api.nvidia.com"


def test_available_providers_reflects_keys(monkeypatch):
    assert available_providers() == []
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    assert available_providers() == ["nvidia"]


_GROQ_URL = "https://api.groq.com/openai/v1"


def test_executor_returns_pass_and_output():
    fake = FakeOpenAI("RESULT-OK")
    ex = OpenAICompatExecutor(base_url=_GROQ_URL, api_key="k", model="m", provider="groq", client=fake)
    result = ex.execute(Blueprint(task_id="t", instruction="write a function"))
    assert result.status == "pass" and result.output == "RESULT-OK"
    assert ex.name == "provider:groq:m"


def test_executor_redacts_secrets_before_send():
    fake = FakeOpenAI()
    ex = OpenAICompatExecutor(base_url=_GROQ_URL, api_key="k", model="m", provider="groq", client=fake)
    ex.execute(Blueprint(task_id="t", instruction="fix this: API_KEY=sk-abcdefghijklmnop1234 in the code"))
    sent = fake.chat.completions.captured_messages[0]["content"]
    assert "sk-abcdefghijklmnop1234" not in sent  # secret redacted before it left the machine
    assert "[REDACTED]" in sent


def test_executor_without_key_errors_not_crashes():
    ex = OpenAICompatExecutor(base_url="x", api_key="", model="m", provider="groq", client=FakeOpenAI())
    result = ex.execute(Blueprint(task_id="t", instruction="x"))
    assert result.status == "error" and "no api key" in result.reason


def test_build_provider_executor_none_without_key_and_built_with_key(monkeypatch):
    assert build_provider_executor("groq") is None  # no key → None (graceful skip)
    monkeypatch.setenv("GROK_API_KEY", "k")
    ex = build_provider_executor("groq")
    assert ex is not None and ex.provider == "groq" and ex.model == "openai/gpt-oss-120b"
    with pytest.raises(ValueError):
        build_provider_executor("does-not-exist")
