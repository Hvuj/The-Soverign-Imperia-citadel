"""image_gen.py — text→image via NVIDIA's visual-GenAI endpoint (Phase 5).

Image generation is NOT on the chat catalog — it's a separate endpoint: POST
`https://ai.api.nvidia.com/v1/genai/{model}` with `{prompt, steps, cfg_scale, width, height, seed}`, and the
response carries the PNG as base64 (`artifacts[0].base64`, with fallbacks for other shapes). The prompt is
redacted; the decoded image is written to disk. `http_post` is injectable for tests (no network).
"""

import base64
from collections.abc import Callable
from pathlib import Path

from citadel.services.execute.providers.keys import ensure_tls, resolve_provider_key

_GENAI_BASE = "https://ai.api.nvidia.com/v1/genai"
_DEFAULT_MODEL = "black-forest-labs/flux.1-schnell"


def _redact() -> Callable[[str], str]:
    try:
        from citadel.services._tools_bridge import import_tool

        return import_tool("citadel_custos").redact
    except Exception:
        return lambda text: text


def _default_http_post(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    import httpx

    ensure_tls()
    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _extract_b64(body: dict) -> str | None:
    if isinstance(body.get("artifacts"), list) and body["artifacts"]:
        return body["artifacts"][0].get("base64")
    for key in ("image", "b64_json", "data"):
        val = body.get(key)
        if isinstance(val, str):
            return val
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val[0].get("b64_json") or val[0].get("base64")
    return None


def generate_image(
    prompt: str,
    out_path: str | Path,
    *,
    model: str = _DEFAULT_MODEL,
    steps: int = 4,
    cfg_scale: float = 3.5,
    width: int = 1024,
    height: int = 1024,
    seed: int = 0,
    key_env: str = "NVIDIA_API_KEY",
    http_post: Callable[[str, dict, dict, float], dict] | None = None,
    timeout: float = 120.0,
) -> Path | None:
    """Generate an image from `prompt` and write it to `out_path`. Returns the path, or None without a key."""
    key = resolve_provider_key(key_env)
    if not key:
        return None
    url = f"{_GENAI_BASE}/{model}"
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    payload = {
        "prompt": _redact()(prompt), "steps": steps, "cfg_scale": cfg_scale,
        "width": width, "height": height, "seed": seed,
    }
    post = http_post or _default_http_post
    body = post(url, headers, payload, timeout)
    b64 = _extract_b64(body)
    if not b64:
        return None
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(b64))
    return out
