"""keys.py — resolve cloud-provider API keys from `.env` / env, without ever logging them.

`.env` is loaded once via python-dotenv (searched up from cwd, or `CITADEL_DOTENV`). Precedence:
explicit arg > process env > `.env`. Returns None when a key is absent so callers skip that provider
gracefully. Keys are never printed — only a masked form (`sk-…abcd`) is ever surfaced.
"""

import os

_tls_ready = False


def ensure_tls() -> None:
    """Trust the OS certificate store for outbound HTTPS (once), via truststore when available.

    Fixes `CERTIFICATE_VERIFY_FAILED` in corporate/Windows environments where the proxy's root CA lives in
    the system store, not in certifi. No-op if truststore is absent (the default certifi path still works
    on machines without a TLS-intercepting proxy)."""
    global _tls_ready
    if _tls_ready:
        return
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        pass
    _tls_ready = True


def load_env(explicit_path: str | None = None) -> None:
    """Load `.env` into the process environment once. Thin shim — the loader now lives in
    `citadel.config.ensure_dotenv_loaded()` so pydantic settings and key resolution share one code path."""
    from citadel.config import ensure_dotenv_loaded

    if explicit_path:
        os.environ.setdefault("CITADEL_DOTENV", explicit_path)
    ensure_dotenv_loaded()


def resolve_provider_key(env_var: str, *, explicit: str | None = None) -> str | None:
    """Return the API key for `env_var` (explicit > CitadelSettings/env/.env), or None if unset.

    Modeled keys (`GROK_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `ANTHROPIC_API_KEY`) resolve through the
    typed pydantic settings; any other var falls back to the (`.env`-loaded) process environment."""
    if explicit:
        return explicit
    from citadel.config import get_settings

    settings = get_settings()
    field = env_var.lower()
    if field in type(settings).model_fields:
        return getattr(settings, field) or None
    return os.environ.get(env_var) or None


def masked(key: str | None) -> str:
    """A safe, loggable fingerprint of a key — never the key itself."""
    if not key:
        return "(absent)"
    return f"{key[:3]}…{key[-4:]}" if len(key) > 8 else "set"
