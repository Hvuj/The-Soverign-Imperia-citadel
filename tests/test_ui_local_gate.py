"""The UI's /api/ask answers general questions via the free local Ollama gate ($0), not Claude."""
import sys
from pathlib import Path
from typing import ClassVar

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _import_server(monkeypatch, workspace: Path):
    monkeypatch.setenv("CITADEL_WORKSPACE", str(workspace))
    monkeypatch.syspath_prepend(str(TOOLS))
    sys.modules.pop("citadel_ui_server", None)
    import citadel_ui_server as srv
    return srv


class _FakeEngine:
    calls: ClassVar[list[str]] = []

    def __init__(self, *_a, **_k):
        pass

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, spec) -> str:
        _FakeEngine.calls.append(spec.model)
        return f"[local answer: {prompt}]"


@pytest.fixture
def srv(monkeypatch, tmp_path):
    module = _import_server(monkeypatch, tmp_path)
    _FakeEngine.calls = []
    monkeypatch.setattr(module, "_OllamaEngine", _FakeEngine)
    monkeypatch.setattr(module, "_LOCAL_GATE_AVAILABLE", True)
    return module


def test_unknown_question_answered_by_local_gate_free(srv):
    cfg = dict(srv._DEFAULT_CONFIG)
    res = srv.handle_api_ask("write me a short haiku about the sea", cfg)
    assert res["source"] == "local_gate"
    assert "local answer" in res["answer"]
    assert res["category"] == "ai"
    assert _FakeEngine.calls  # the local engine actually answered


def test_gate_auto_picks_deep_model_for_technical_questions(srv):
    cfg = dict(srv._DEFAULT_CONFIG)
    srv.handle_api_ask("how do I refactor this function to be async", cfg)
    assert _FakeEngine.calls[-1] == "qwen2.5-coder:7b"  # substantive → deep


def test_gate_auto_picks_fast_model_for_trivial(srv):
    cfg = dict(srv._DEFAULT_CONFIG)
    srv.handle_api_ask("say hi", cfg)
    assert _FakeEngine.calls[-1] == "qwen2.5:0.5b"  # short, non-technical → fast


def test_gate_disabled_falls_back_to_canned_unknown(srv):
    cfg = {**srv._DEFAULT_CONFIG, "allow_local_gate": False}
    res = srv.handle_api_ask("write me a short haiku about the sea", cfg)
    assert res["source"] == "unavailable"  # gate off → no AI answer
    assert _FakeEngine.calls == []


def test_gate_unreachable_falls_back_to_canned_unknown(monkeypatch, tmp_path):
    module = _import_server(monkeypatch, tmp_path)

    class _Down(_FakeEngine):
        def available(self) -> bool:
            return False

    monkeypatch.setattr(module, "_OllamaEngine", _Down)
    monkeypatch.setattr(module, "_LOCAL_GATE_AVAILABLE", True)
    res = module.handle_api_ask("write me a short haiku about the sea", dict(module._DEFAULT_CONFIG))
    assert res["source"] == "unavailable"  # engine down → canned unknown, never crashes


def test_answerable_question_stays_deterministic_not_gated(srv, tmp_path):
    # When the deterministic resolver CAN answer (data present), the model gate must be skipped.
    import json
    status = tmp_path / "docs" / "brain" / "system-status.json"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(json.dumps({
        "overall_status": "green",
        "summary": {"green": 2, "yellow": 0, "red": 0},
        "checks": [{"name": "daemons", "status": "green"}],
        "epoch_ms": 1_700_000_000_000,
    }), encoding="utf-8")

    res = srv.handle_api_ask("are all systems green?", dict(srv._DEFAULT_CONFIG))
    assert res["source"] == "local"  # answered deterministically
    assert _FakeEngine.calls == []   # gate never consulted
