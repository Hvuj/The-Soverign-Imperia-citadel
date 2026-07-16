"""Phase-2 local execution tier: HRA GPU auto-discovery + VRAM budget, engine swap, Ollama HTTP,
predictive sequencer, self-heal ladder, and the model_backend Path bugfix."""

import sys
from pathlib import Path

import pytest

from citadel.services.execute import (
    Blueprint,
    ExecutionResult,
    Executor,
    LocalExecutor,
    NullArbitrator,
    OllamaEngine,
    RunSpec,
    orchestrate,
    resilient_orchestrate,
    sequence,
)
from citadel.services.execute.local.engine import LocalEngine
from citadel.services.execute.local.hra import HardwareResourceArbitrator

_TOOLS = str(Path(__file__).resolve().parents[1] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import model_backend  # noqa: E402


def _profile(device, vram=0.0, cpu=8, ram=32.0):
    return model_backend.HardwareProfile(
        device=device,
        cpu_count=cpu,
        total_ram_gb=ram,
        available_ram_gb=ram,
        vram_gb=vram,
        cuda_available=device in (model_backend.BackendDevice.CUDA_FULL, model_backend.BackendDevice.CUDA_SPLIT),
    )


class FakeEngine(LocalEngine):
    name = "fake"

    def __init__(self, output="done", ok=True, avail=True):
        self.output = output
        self._ok = ok
        self._avail = avail
        self.calls: list = []

    def available(self):
        return self._avail

    def generate(self, prompt, spec):
        self.calls.append(spec)
        if not self._ok:
            raise RuntimeError("boom")
        return self.output


class ScriptedExecutor(Executor):
    def __init__(self, name, status):
        self.name = name
        self._status = status

    def execute(self, blueprint):
        return ExecutionResult(blueprint.task_id, self._status, reason=self.name)


def _bp(task_id="t", **kw):
    return Blueprint(task_id=task_id, instruction=kw.pop("instruction", "do it"), **kw)


def test_hra_uses_gpu_when_present():
    hra = HardwareResourceArbitrator(profile=_profile(model_backend.BackendDevice.CUDA_FULL, vram=24.0))
    decision = hra.arbitrate(_bp())
    assert decision.admit
    assert decision.run_spec.n_gpu_layers != 0


def test_hra_cpu_when_no_gpu():
    hra = HardwareResourceArbitrator(profile=_profile(model_backend.BackendDevice.CPU_ADEQUATE, vram=0.0))
    decision = hra.arbitrate(_bp())
    assert decision.admit
    assert decision.run_spec.n_gpu_layers == 0


def test_hra_rejects_model_too_large_for_vram():
    hra = HardwareResourceArbitrator(profile=_profile(model_backend.BackendDevice.CUDA_SPLIT, vram=1.0))
    decision = hra.arbitrate(_bp(context_token_budget=100000))
    assert not decision.admit
    assert "vram" in decision.reason.lower()


def test_hra_shrinks_context_to_fit_vram():
    hra = HardwareResourceArbitrator(profile=_profile(model_backend.BackendDevice.CUDA_SPLIT, vram=6.0))
    decision = hra.arbitrate(_bp(context_token_budget=100000))
    assert decision.admit
    assert decision.run_spec.n_ctx < 4096


def test_local_executor_via_orchestrate_swap():
    hra = HardwareResourceArbitrator(profile=_profile(model_backend.BackendDevice.CPU_ADEQUATE, vram=0.0))
    engine = FakeEngine(output="  patched  ")
    local = LocalExecutor(engine=engine, hra=hra)
    results = orchestrate(local, [_bp("a"), _bp("b")], arbitrator=NullArbitrator())
    assert [r.status for r in results] == ["pass", "pass"]
    assert results[0].output == "patched"
    assert len(engine.calls) == 2


def test_local_executor_blocks_when_hra_rejects():
    hra = HardwareResourceArbitrator(profile=_profile(model_backend.BackendDevice.CUDA_SPLIT, vram=1.0))
    local = LocalExecutor(engine=FakeEngine(), hra=hra)
    result = local.execute(_bp(context_token_budget=100000))
    assert result.status == "blocked"
    assert "vram" in result.reason.lower()


def test_local_executor_blocks_when_engine_unavailable():
    hra = HardwareResourceArbitrator(profile=_profile(model_backend.BackendDevice.CPU_ADEQUATE, vram=0.0))
    local = LocalExecutor(engine=FakeEngine(avail=False), hra=hra)
    result = local.execute(_bp())
    assert result.status == "blocked"
    assert "engine_unavailable" in result.reason


def test_ollama_engine_forwards_gpu_and_parses_response():
    calls: list = []

    def http_post(url, payload, timeout):
        calls.append((url, payload))
        return {"response": "hello from ollama\n"}

    engine = OllamaEngine(http_post=http_post, http_get=lambda url, timeout: {"models": []})
    assert engine.available() is True
    output = engine.generate("hi", RunSpec(model="llama3", n_gpu_layers=-1, n_ctx=2048, threads=4))
    assert output == "hello from ollama"
    gen = next(c for c in calls if c[0].endswith("/api/generate"))
    assert gen[1]["model"] == "llama3"
    assert gen[1]["options"]["num_gpu"] == -1


def test_generate_omits_num_gpu_when_zero_so_ollama_uses_the_gpu():
    """RunSpec default n_gpu_layers=0 must NOT force num_gpu=0 (CPU) — omit it so Ollama uses the GPU fully."""
    calls: list = []

    def http_post(url, payload, timeout):
        calls.append(payload)
        return {"response": "ok"}

    engine = OllamaEngine(http_post=http_post, http_get=lambda url, timeout: {"models": []})
    engine.generate("hi", RunSpec(model="llama3", n_ctx=2048, threads=4))  # n_gpu_layers defaults to 0
    options = calls[0]["options"]
    assert "num_gpu" not in options  # omitted → Ollama's scheduler uses the GPU (and spreads across GPUs)


def test_ollama_available_false_when_get_raises():
    def boom(url, timeout):
        raise OSError("connection refused")

    engine = OllamaEngine(http_get=boom)
    assert engine.available() is False


def test_local_executor_model_override_replaces_model():
    seen: list = []

    class RecordingEngine(LocalEngine):
        name = "rec"

        def available(self):
            return True

        def generate(self, prompt, spec):
            seen.append(spec.model)
            return "ok"

    hra = HardwareResourceArbitrator(profile=_profile(model_backend.BackendDevice.CPU_ADEQUATE, vram=0.0))
    local = LocalExecutor(engine=RecordingEngine(), hra=hra, model_override="qwen2.5:0.5b")
    result = local.execute(_bp())
    assert result.status == "pass"
    assert seen == ["qwen2.5:0.5b"]


def test_local_executor_engine_error_is_reported():
    hra = HardwareResourceArbitrator(profile=_profile(model_backend.BackendDevice.CPU_ADEQUATE, vram=0.0))
    local = LocalExecutor(engine=FakeEngine(ok=False), hra=hra)
    result = local.execute(_bp())
    assert result.status == "error"
    assert "boom" in result.reason


def test_get_local_engine_factory_and_unknown():
    from citadel.services.execute import get_local_engine
    from citadel.services.execute.local.engine import LlamaCppEngine, OllamaEngine as OE

    assert isinstance(get_local_engine("llama_cpp"), LlamaCppEngine)
    assert isinstance(get_local_engine("ollama"), OE)
    with pytest.raises(ValueError):
        get_local_engine("gpt5-local")


def test_llama_cpp_engine_unavailable_without_ml_libs():
    from citadel.services.execute.local.engine import LlamaCppEngine

    engine = LlamaCppEngine()
    assert engine.available() is False


def test_sequencer_groups_by_model():
    blueprints = [
        _bp("a", assigned_tier="cheap"),
        _bp("b", assigned_tier="strong"),
        _bp("c", assigned_tier="cheap"),
    ]
    batches = sequence(blueprints)
    assert [[b.task_id for b in group] for group in batches] == [["a", "c"], ["b"]]


def test_selfheal_escalates_to_architect():
    primary = ScriptedExecutor("local", "error")
    architect = ScriptedExecutor("cloud", "pass")
    results = resilient_orchestrate(primary, [_bp("t")], architect=architect)
    assert results[0].status == "pass"
    assert results[0].reason == "cloud"


def test_selfheal_alt_before_architect():
    primary = ScriptedExecutor("local", "needs_fix")
    alt = ScriptedExecutor("alt", "pass")
    architect = ScriptedExecutor("cloud", "pass")
    results = resilient_orchestrate(primary, [_bp("t")], alt=alt, architect=architect)
    assert results[0].reason == "alt"


def test_selfheal_circuit_breaker():
    primary = ScriptedExecutor("local", "error")
    results = resilient_orchestrate(primary, [_bp("t")])
    assert results[0].status == "blocked"
    assert results[0].reason == "architecturally_blocked"


def test_model_backend_resolve_gguf_raises_filenotfound():
    backend = model_backend.get_backend()
    with pytest.raises(FileNotFoundError):
        backend._resolve_gguf_path("definitely-not-a-real-model.gguf")
