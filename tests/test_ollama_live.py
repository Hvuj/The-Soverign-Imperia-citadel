"""Live Ollama integration — actually generates against a running Ollama server (GPU-accelerated when
a GPU is present). Auto-skips when no server / model is reachable, so CI and other hosts stay green."""

import json
import sys
import urllib.request

import pytest

from citadel.services.execute import (
    Blueprint,
    Executor,
    LocalCodingExecutor,
    LocalExecutor,
    OllamaEngine,
    RunSpec,
    verify_by_command,
)

_HOST = "http://localhost:11434"
_MODEL = "qwen2.5:0.5b"


def _server_up() -> bool:
    return OllamaEngine(host=_HOST).available()


def _has_model() -> bool:
    try:
        with urllib.request.urlopen(f"{_HOST}/api/tags", timeout=3) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    return any(_MODEL in (m.get("name") or "") for m in tags.get("models", []))


pytestmark = pytest.mark.skipif(
    not (_server_up() and _has_model()),
    reason=f"Ollama server or model {_MODEL} not available",
)


def test_ollama_engine_real_generation():
    engine = OllamaEngine(host=_HOST)
    assert engine.available() is True
    output = engine.generate(
        "Reply with exactly one word: ping",
        RunSpec(model=_MODEL, n_gpu_layers=-1, n_ctx=2048, threads=4, max_tokens=16),
    )
    assert isinstance(output, str) and len(output) > 0


def test_local_executor_real_generation_auto_uses_hardware():
    executor = LocalExecutor(engine=OllamaEngine(host=_HOST), model_override=_MODEL)
    result = executor.execute(
        Blueprint(task_id="live", instruction="Reply with exactly one word: ok", assigned_tier="cheap")
    )
    assert result.status == "pass"
    assert isinstance(result.output, str) and len(result.output) > 0


def test_sovereign_runner_answers_question_free_on_local():
    from citadel.services.execute import SovereignRunner

    class NoCloud(Executor):
        name = "cloud"

        def execute(self, blueprint):
            raise AssertionError("cloud must not be called for a free local question")

    runner = SovereignRunner(
        local=LocalExecutor(engine=OllamaEngine(host=_HOST), model_override=_MODEL),
        cloud=NoCloud(),
        search=lambda _p: "",
    )
    result = runner.run("Reply with exactly one word: ok")
    assert result.status == "pass"
    assert isinstance(result.output, str) and len(result.output) > 0


def test_local_coding_executor_generates_and_verifies_live(tmp_path):
    (tmp_path / "answer.py").write_text("VALUE = 0\n")
    verify = verify_by_command(
        [sys.executable, "-c", "import ast; ast.parse(open('answer.py').read())"]
    )
    executor = LocalCodingExecutor(
        OllamaEngine(host=_HOST), tmp_path, verify=verify,
        run_spec=RunSpec(model=_MODEL, n_ctx=2048, max_tokens=256),
    )
    result = executor.execute(
        Blueprint(task_id="live", instruction="Set VALUE to 42.", allowed_files=["answer.py"])
    )
    assert result.status in ("pass", "needs_fix")
    if result.status == "pass":
        import ast
        ast.parse((tmp_path / "answer.py").read_text())


def test_local_coding_executor_multifile_live(tmp_path):
    (tmp_path / "a.py").write_text("A = 0\n")
    (tmp_path / "b.py").write_text("B = 0\n")
    verify = verify_by_command(
        [sys.executable, "-c", "import ast; ast.parse(open('a.py').read()); ast.parse(open('b.py').read())"]
    )
    executor = LocalCodingExecutor(
        OllamaEngine(host=_HOST), tmp_path, verify=verify,
        run_spec=RunSpec(model=_MODEL, n_ctx=2048, max_tokens=512),
    )
    result = executor.execute(
        Blueprint(task_id="live", instruction="Set A to 1 in a.py and B to 2 in b.py.",
                  allowed_files=["a.py", "b.py"])
    )
    assert result.status in ("pass", "needs_fix")
