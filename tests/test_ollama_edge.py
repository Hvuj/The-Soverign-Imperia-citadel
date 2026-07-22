"""Ollama engine edge behavior — hermetic (injected HTTP), including the GPU-offload wiring seam. No server."""
import pytest

from citadel.services.execute.local.engine import OllamaEngine, RunSpec


def _engine(post=None, get=None, host="http://localhost:11434"):
    return OllamaEngine(host=host, http_post=post, http_get=get)


def test_available_true_when_tags_ok():
    assert _engine(get=lambda _url, _t: {"models": []}).available() is True


def test_available_false_when_tags_raise():
    def boom(_url, _t):
        raise OSError("connection refused")

    assert _engine(get=boom).available() is False


def test_generate_returns_stripped_response():
    eng = _engine(post=lambda _u, _p, _t: {"response": "  hello  "})
    assert eng.generate("hi", RunSpec(model="m", n_ctx=2048, max_tokens=16)) == "hello"


def test_generate_empty_or_malformed_response_is_empty_string():
    assert _engine(post=lambda _u, _p, _t: {}).generate("hi", RunSpec(model="m")) == ""
    assert _engine(post=lambda _u, _p, _t: {"response": None}).generate("hi", RunSpec(model="m")) == ""


def test_generate_propagates_http_error_for_caller_to_handle():
    # The engine does not swallow errors; callers (chat gate, UI gate) catch and degrade.
    def boom(_u, _p, _t):
        raise TimeoutError("timed out")

    with pytest.raises(TimeoutError):
        _engine(post=boom).generate("hi", RunSpec(model="m"))


def test_gpu_offload_sets_num_gpu_only_when_nonzero():
    captured: dict = {}

    def post(_url, payload, _t):
        captured.clear()
        captured.update(payload)
        return {"response": "x"}

    # n_gpu_layers=-1 → offload all layers to the discovered GPU(s) → num_gpu pinned.
    _engine(post=post).generate("hi", RunSpec(model="m", n_gpu_layers=-1))
    assert captured["options"]["num_gpu"] == -1

    # n_gpu_layers=0 → CPU → num_gpu omitted so Ollama's own scheduler decides (never forced to CPU).
    _engine(post=post).generate("hi", RunSpec(model="m", n_gpu_layers=0))
    assert "num_gpu" not in captured["options"]


def test_generate_targets_the_configured_host_and_endpoint():
    seen: dict = {}

    def post(url, _p, _t):
        seen["url"] = url
        return {"response": "ok"}

    _engine(post=post, host="http://gpu-box:11500/").generate("hi", RunSpec(model="m"))
    assert seen["url"] == "http://gpu-box:11500/api/generate"  # trailing slash stripped


def test_explicit_host_wins_over_settings():
    assert OllamaEngine(host="http://custom:9999")._host == "http://custom:9999"


def test_embed_batches_then_falls_back_to_per_text():
    def only_batch(url, _p, _t):
        return {"embeddings": [[0.1, 0.2], [0.3, 0.4]]} if url.endswith("/api/embed") else {}

    assert _engine(post=only_batch).embed(["a", "b"], "nomic-embed-text") == [[0.1, 0.2], [0.3, 0.4]]

    # /api/embed returns a mismatched shape → fall back to per-text /api/embeddings.
    def fallback(url, _p, _t):
        if url.endswith("/api/embed"):
            return {"embeddings": []}
        return {"embedding": [9.0]}

    assert _engine(post=fallback).embed(["a"], "nomic-embed-text") == [[9.0]]


def test_embed_empty_input_returns_empty():
    assert _engine(post=lambda *_a: {}).embed([], "m") == []
