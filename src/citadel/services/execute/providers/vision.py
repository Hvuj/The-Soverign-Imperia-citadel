"""vision.py — image understanding via NVIDIA VLMs (Phase 5).

Sends an image + a text prompt to a vision-language model over the standard OpenAI chat endpoint (the image
rides as a base64 data-URI content part). The text prompt is secret-redacted; the image bytes are sent as-is
(the user opted into cloud vision). Returns the model's description, or None when the key/model is absent.
"""

import base64
import mimetypes
from collections.abc import Callable
from pathlib import Path

from citadel.services.execute.providers.keys import ensure_tls, resolve_provider_key
from citadel.services.execute.providers.registry import provider_spec


def _redact() -> Callable[[str], str]:
    try:
        from citadel.services._tools_bridge import import_tool

        return import_tool("citadel_custos").redact
    except Exception:
        return lambda text: text


def describe_image(
    image_path: str | Path,
    prompt: str = "Describe this image in detail.",
    *,
    provider: str = "nvidia",
    model: str | None = None,
    max_tokens: int = 512,
    client=None,
) -> str | None:
    """Return a VLM's description of the image, or None if the provider key/model is unavailable."""
    spec = provider_spec(provider)
    if spec is None:
        raise ValueError(f"unknown provider {provider!r}")
    key = resolve_provider_key(spec.key_env)
    model = model or spec.default_model("vision")
    if not key or not model:
        return None
    data = Path(image_path).read_bytes()
    mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
    b64 = base64.b64encode(data).decode("ascii")
    content = [
        {"type": "text", "text": _redact()(prompt)},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]
    if client is None:
        from openai import OpenAI

        ensure_tls()
        client = OpenAI(base_url=spec.base_url, api_key=key)
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": content}], max_tokens=max_tokens
    )
    return (resp.choices[0].message.content or "").strip()
