"""tests/test_chat_gate.py — `citadel chat`: local-first gate, intent model-pick, explicit escalation."""
import argparse
import builtins

from citadel import cli


class _FakeEngine:
    last: "_FakeEngine | None" = None

    def __init__(self, *_a, **_k):
        self.calls: list[tuple[str, str]] = []
        _FakeEngine.last = self

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, spec) -> str:
        self.calls.append((prompt, spec.model))
        return f"[answer to: {prompt}]"


def _run_chat(monkeypatch, inputs, engine_cls=_FakeEngine):
    monkeypatch.setattr("citadel.services.execute.local.engine.OllamaEngine", engine_cls)
    it = iter(inputs)
    monkeypatch.setattr(builtins, "input", lambda _p="": next(it))
    args = argparse.Namespace(workspace=None, model="deep-model", fast_model="fast-model")
    return cli._cmd_chat(args)


def test_chat_picks_fast_for_trivial_and_deep_for_technical(monkeypatch, capsys):
    rc = _run_chat(monkeypatch, ["hi there", "how do I refactor this function", "/exit"])
    assert rc == 0
    assert [m for _, m in _FakeEngine.last.calls] == ["fast-model", "deep-model"]
    assert "$0" in capsys.readouterr().out


def test_chat_long_prompt_uses_deep_model(monkeypatch):
    _run_chat(monkeypatch, ["please tell me a short story about a cat and a dog and a bird", "/exit"])
    assert _FakeEngine.last.calls[0][1] == "deep-model"  # >8 words → deep


def test_chat_exit_returns_zero_without_calling_engine(monkeypatch):
    rc = _run_chat(monkeypatch, ["/exit"])
    assert rc == 0
    assert _FakeEngine.last.calls == []


def test_chat_exits_when_ollama_unavailable(monkeypatch, capsys):
    class _Down(_FakeEngine):
        def available(self) -> bool:
            return False

    rc = _run_chat(monkeypatch, ["/exit"], engine_cls=_Down)
    assert rc == 1
    assert "not reachable" in capsys.readouterr().err


def test_chat_task_escalates_to_opus_tier(monkeypatch, capsys):
    captured: dict = {}

    class _FakeCloud:
        def execute(self, blueprint):
            from citadel.services.execute.blueprint import ExecutionResult
            captured["tier"] = blueprint.assigned_tier
            captured["instr"] = blueprint.instruction
            return ExecutionResult(blueprint.task_id, "pass", output="CLOUD DID IT")

    monkeypatch.setattr("citadel.services.execute.CloudClaudeExecutor", _FakeCloud)
    rc = _run_chat(monkeypatch, ["/task build a widget", "/exit"])
    assert rc == 0
    assert captured["tier"] == "ultra"  # explicit /task → Opus tier
    assert "build a widget" in captured["instr"]
    out = capsys.readouterr().out
    assert "CLOUD DID IT" in out
    # a plain /task must NOT hit the local engine
    assert _FakeEngine.last.calls == []
