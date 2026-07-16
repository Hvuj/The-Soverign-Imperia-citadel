"""http_client.py — a pooled, keep-alive HTTP client for the local Ollama round-trips.

The embed-heavy path makes many small POSTs to Ollama; `urllib.urlopen` opens a fresh TCP connection every
call (a full-repo sweep = hundreds of handshakes). This module keeps ONE shared `httpx.Client` with a
keep-alive connection pool, so the socket is reused across calls — the real wire win. It degrades to the
stdlib `urllib` helpers when httpx is absent (the zero-dep core stays intact). HTTP/2 is opt-in
(`CITADEL_OLLAMA_HTTP2=1`, needs the `h2` extra) but off by default: Ollama's server does not offer cleartext
HTTP/2 on localhost, so keep-alive — not the protocol version — is what matters.
"""

import json
import os
import threading
import urllib.request

_client = None
_lock = threading.Lock()


def _urllib_post(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _urllib_get(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_client():
    """Return the shared httpx.Client (built once), or None when httpx is unavailable."""
    global _client
    if _client is not None:
        return _client or None  # False sentinel → httpx absent
    with _lock:
        if _client is not None:
            return _client or None
        try:
            import httpx

            http2 = os.environ.get("CITADEL_OLLAMA_HTTP2") == "1"
            limits = httpx.Limits(max_keepalive_connections=8, max_connections=16, keepalive_expiry=30.0)
            _client = httpx.Client(http2=http2, limits=limits, trust_env=False)
        except Exception:
            _client = False  # remember the miss so we don't retry the import every call
    return _client or None


def pooled_post(url: str, payload: dict, timeout: float) -> dict:
    """POST JSON and return the parsed JSON body — over a reused keep-alive connection when possible."""
    client = _get_client()
    if client is None:
        return _urllib_post(url, payload, timeout)
    resp = client.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def pooled_get(url: str, timeout: float) -> dict:
    client = _get_client()
    if client is None:
        return _urllib_get(url, timeout)
    resp = client.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
