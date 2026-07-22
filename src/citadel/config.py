"""config.py — one typed, `.env`-backed settings object for all env-driven configuration.

Centralizes the provider keys, service URLs, and model names that used to be read ad-hoc via
`os.environ.get` across the codebase. Backed by pydantic-settings: `.env` is loaded once into the process
environment (searched up from cwd, `override=False` so a real shell/CI value always wins), then every
`get_settings()` reads the *current* environment fresh — so `monkeypatch.setenv`/`delenv` and runtime changes
are always reflected. Secrets are never logged; surface them only via `masked()` in `providers/keys.py`.

Deliberately out of scope: workspace/path resolution (`CITADEL_WORKSPACE`, `CITADEL_STATE_DIR`) stays in
`paths.py` — that is path logic, not settings.
"""

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_env_loaded = False


def ensure_dotenv_loaded() -> None:
    """Load `.env` into `os.environ` once (searched up from cwd, or `CITADEL_DOTENV`). Never overrides an
    already-set variable, and never raises — a missing/absent `.env` is fine."""
    global _env_loaded
    if _env_loaded:
        return
    try:
        from dotenv import find_dotenv, load_dotenv

        path = os.environ.get("CITADEL_DOTENV") or find_dotenv(usecwd=True)
        if path:
            load_dotenv(path, override=False)
    except Exception:
        pass
    _env_loaded = True


class CitadelSettings(BaseSettings):
    """Typed view over the env-driven configuration. Field name → env var is case-insensitive; the
    `CITADEL_*` service/model fields use explicit aliases."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, populate_by_name=True)

    # Provider API keys (None when absent → the provider is skipped gracefully).
    grok_api_key: str | None = None       # xAI Grok — api.x.ai
    groq_api_key: str | None = None       # Groq — api.groq.com
    nvidia_api_key: str | None = None
    anthropic_api_key: str | None = None

    # Services. redis_url defaults to None so `.citadel/config.toml` can still win over the hard default
    # (precedence lives in paths.resolve_redis_url); ollama_host has a concrete default.
    redis_url: str | None = Field(default=None, alias="CITADEL_REDIS_URL")
    ollama_host: str = Field(default="http://localhost:11434", alias="CITADEL_OLLAMA_HOST")

    # Local model names.
    ollama_model: str = Field(default="qwen2.5-coder:7b", alias="CITADEL_OLLAMA_MODEL")
    chat_fast_model: str = Field(default="qwen2.5:0.5b", alias="CITADEL_CHAT_FAST_MODEL")
    embed_model: str = Field(default="nomic-embed-text", alias="CITADEL_EMBED_MODEL")


def get_settings() -> CitadelSettings:
    """Return a settings view over the current environment (`.env` loaded once, then read fresh each call)."""
    ensure_dotenv_loaded()
    return CitadelSettings()
