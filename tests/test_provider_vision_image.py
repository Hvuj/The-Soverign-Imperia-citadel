"""P5 — vision (image → description) + image generation (prompt → PNG). Mocked clients — no network."""

import base64
from types import SimpleNamespace

from citadel.services.execute.providers.image_gen import _extract_b64, generate_image
from citadel.services.execute.providers.vision import describe_image

# a 1x1 PNG
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class _VisionClient:
    def __init__(self):
        self.captured = None
        self.chat = SimpleNamespace(completions=self)

    def create(self, model, messages, max_tokens=512):
        self.captured = messages
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="a tiny black square"))])


def test_describe_image_builds_multimodal_message(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    img = tmp_path / "pic.png"
    img.write_bytes(_PNG)
    client = _VisionClient()
    out = describe_image(img, "What is this?", provider="nvidia", client=client)
    assert out == "a tiny black square"
    content = client.captured[0]["content"]
    assert content[0]["type"] == "text" and content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_describe_image_none_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    import citadel.config as cfg
    monkeypatch.setattr(cfg, "_env_loaded", True, raising=False)  # don't load a real .env
    img = tmp_path / "pic.png"
    img.write_bytes(_PNG)
    assert describe_image(img, client=_VisionClient()) is None


def test_extract_b64_shapes():
    b = base64.b64encode(b"x").decode()
    assert _extract_b64({"artifacts": [{"base64": b}]}) == b
    assert _extract_b64({"image": b}) == b
    assert _extract_b64({"data": [{"b64_json": b}]}) == b
    assert _extract_b64({"nothing": 1}) is None


def test_generate_image_writes_png(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    captured = {}

    def fake_post(url, headers, payload, timeout):
        captured["url"] = url
        captured["prompt"] = payload["prompt"]
        return {"artifacts": [{"base64": base64.b64encode(_PNG).decode()}]}

    out = tmp_path / "gen.png"
    path = generate_image("a red cube", out, http_post=fake_post)
    assert path == out and out.read_bytes() == _PNG
    assert captured["url"].endswith("black-forest-labs/flux.1-schnell")
    assert captured["prompt"] == "a red cube"


def test_generate_image_redacts_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    captured = {}

    def fake_post(url, headers, payload, timeout):
        captured["prompt"] = payload["prompt"]
        return {"artifacts": [{"base64": base64.b64encode(_PNG).decode()}]}

    generate_image("draw this key: sk-abcdefghijklmnop1234", tmp_path / "g.png", http_post=fake_post)
    assert "sk-abcdefghijklmnop1234" not in captured["prompt"]


def test_generate_image_none_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    import citadel.config as cfg
    monkeypatch.setattr(cfg, "_env_loaded", True, raising=False)
    assert generate_image("x", tmp_path / "g.png", http_post=lambda *a: {}) is None
