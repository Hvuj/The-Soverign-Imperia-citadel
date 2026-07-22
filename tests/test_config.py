"""CitadelSettings — typed env/.env config: defaults, aliases, dynamic reads, and key-field mapping."""
import pytest

import citadel.config as cfg
from citadel.config import CitadelSettings, get_settings


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    # Never let a real .env leak into these tests; start from a clean, modeled env.
    monkeypatch.setattr(cfg, "_env_loaded", True, raising=False)
    for var in ("GROK_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY", "ANTHROPIC_API_KEY",
                "CITADEL_REDIS_URL", "CITADEL_OLLAMA_HOST", "CITADEL_OLLAMA_MODEL",
                "CITADEL_CHAT_FAST_MODEL", "CITADEL_EMBED_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_defaults_when_env_empty():
    s = get_settings()
    assert s.grok_api_key is None
    assert s.nvidia_api_key is None
    assert s.redis_url is None  # None so config.toml can still win in resolve_redis_url
    assert s.ollama_host == "http://localhost:11434"
    assert s.ollama_model == "qwen2.5-coder:7b"
    assert s.chat_fast_model == "qwen2.5:0.5b"
    assert s.embed_model == "nomic-embed-text"


def test_reads_are_fresh_not_cached(monkeypatch):
    assert get_settings().grok_api_key is None
    monkeypatch.setenv("GROK_API_KEY", "xai-abc")
    assert get_settings().grok_api_key == "xai-abc"  # a new setenv is reflected immediately


def test_citadel_prefixed_aliases(monkeypatch):
    monkeypatch.setenv("CITADEL_REDIS_URL", "redis://box:6390")
    monkeypatch.setenv("CITADEL_OLLAMA_MODEL", "my-model")
    monkeypatch.setenv("CITADEL_EMBED_MODEL", "my-embed")
    s = get_settings()
    assert s.redis_url == "redis://box:6390"
    assert s.ollama_model == "my-model"
    assert s.embed_model == "my-embed"


def test_case_insensitive_env(monkeypatch):
    monkeypatch.setenv("nvidia_api_key", "nvapi-lower")
    assert get_settings().nvidia_api_key == "nvapi-lower"


def test_extra_env_vars_ignored(monkeypatch):
    monkeypatch.setenv("SOME_UNRELATED_VAR", "x")
    # must not raise despite extra="ignore"
    assert isinstance(get_settings(), CitadelSettings)


def test_key_field_names_match_lowercased_env_vars():
    # resolve_provider_key relies on env_var.lower() being a field name.
    for env_var in ("GROK_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY", "ANTHROPIC_API_KEY"):
        assert env_var.lower() in CitadelSettings.model_fields
