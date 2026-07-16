"""keys.py — resolve cloud-provider API keys from `.env` / env, without ever logging them.

`.env` is loaded once via python-dotenv (searched up from cwd, or `CITADEL_DOTENV`). Precedence:
explicit arg > process env > `.env`. Returns None when a key is absent so callers skip that provider
gracefully. Keys are never printed — only a masked form (`sk-…abcd`) is ever surfaced.
"""

import os

_loaded = False
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
    """Load `.env` into the process environment once (no override of already-set vars)."""
    global _loaded
    if _loaded:
        return
    try:
        from dotenv import find_dotenv, load_dotenv

        path = explicit_path or os.environ.get("CITADEL_DOTENV") or find_dotenv(usecwd=True)
        if path:
            load_dotenv(path, override=False)
    except Exception:
        pass
    _loaded = True


def resolve_provider_key(env_var: str, *, explicit: str | None = None) -> str | None:
    """Return the API key for `env_var` (explicit > env > .env), or None if unset."""
    if explicit:
        return explicit
    load_env()
    key = os.environ.get(env_var)
    return key or None


def masked(key: str | None) -> str:
    """A safe, loggable fingerprint of a key — never the key itself."""
    if not key:
        return "(absent)"
    return f"{key[:3]}…{key[-4:]}" if len(key) > 8 else "set"
