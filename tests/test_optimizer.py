"""Phase Z4 — the code-optimizer Z-worker. Fake coding engine → no Ollama. Proves: system code auto-applies
only on a verified pass (with a pre-image + verdict); user code is propose-only (diff returned, file
untouched); a verify failure applies nothing (verified-before-trust)."""

from citadel.services.execute.local.engine import LocalEngine, RunSpec
from citadel.services.execute.optimizer import (
    CodeOptimizer,
    OptimizeResult,
    is_system_path,
    update_optimizer_stats,
)
from citadel.services.execute.verdict import PASS, VerdictLedger


class FakeCodingEngine(LocalEngine):
    name = "fake-coding"

    def __init__(self, new_body: str) -> None:
        self._new_body = new_body

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, spec: RunSpec) -> str:
        # emit the whole file in the ### FILE: block form the executor parses
        target = prompt.split("### FILE: ")[1].split(" ")[0].strip()
        return f"### FILE: {target}\n```python\n{self._new_body}```\n"


def test_is_system_path():
    assert is_system_path("src/citadel/x.py") is True
    assert is_system_path("tools/y.py") is True
    assert is_system_path("myapp/models.py") is False


def test_system_code_auto_applies_on_verified_pass(tmp_path):
    (tmp_path / "src" / "citadel").mkdir(parents=True)
    f = tmp_path / "src" / "citadel" / "mod.py"
    f.write_text("def add(a,b):\n    return a+b\n", encoding="utf-8")
    ledger = VerdictLedger(tmp_path / ".citadel" / "state" / "verdicts")
    opt = CodeOptimizer(FakeCodingEngine("def add(a, b):\n    return a + b\n"), tmp_path, ledger=ledger)

    result = opt.optimize("src/citadel/mod.py")  # system path → auto_apply
    assert result.status == "pass" and result.applied is True
    assert "return a + b" in f.read_text(encoding="utf-8")  # real file updated
    assert result.diff  # a diff was produced


def test_user_code_is_propose_only(tmp_path):
    (tmp_path / "app").mkdir()
    f = tmp_path / "app" / "logic.py"
    original = "def mul(a,b):\n    return a*b\n"
    f.write_text(original, encoding="utf-8")
    opt = CodeOptimizer(FakeCodingEngine("def mul(a, b):\n    return a * b\n"), tmp_path)

    result = opt.optimize("app/logic.py")  # user path → propose-only
    assert result.status == "pass" and result.applied is False and result.proposed is True
    assert result.diff and "return a * b" in result.diff
    assert f.read_text(encoding="utf-8") == original  # real file NOT changed


def test_verify_failure_applies_nothing(tmp_path):
    (tmp_path / "src" / "citadel").mkdir(parents=True)
    f = tmp_path / "src" / "citadel" / "broken.py"
    original = "x = 1\n"
    f.write_text(original, encoding="utf-8")
    # the "optimization" is a syntax error → the default ast verifier fails
    opt = CodeOptimizer(FakeCodingEngine("def oops(:\n    pass\n"), tmp_path)

    result = opt.optimize("src/citadel/broken.py")
    assert result.applied is False
    assert f.read_text(encoding="utf-8") == original  # unverified change never written


def test_verdict_recorded_on_apply(tmp_path):
    (tmp_path / "tools").mkdir()
    f = tmp_path / "tools" / "t.py"
    f.write_text("y=2\n", encoding="utf-8")
    ledger = VerdictLedger(tmp_path / ".citadel" / "state" / "verdicts")
    opt = CodeOptimizer(FakeCodingEngine("y = 2\n"), tmp_path, ledger=ledger)
    result = opt.optimize("tools/t.py")
    assert result.applied is True
    # the applied artifact (exactly what was written) is recorded PASS in the ledger
    from citadel.services.execute.verdict import artifact_hash
    assert ledger.verdict(artifact_hash(f.read_text(encoding="utf-8"))) == PASS


def test_optimizer_stats_accumulate_for_workers_view(tmp_path):
    stats_path = tmp_path / "optimizer-stats.json"
    update_optimizer_stats(stats_path, OptimizeResult("a.py", "pass", True, False, "d", ""))
    update_optimizer_stats(stats_path, OptimizeResult("b.py", "pass", False, True, "d", ""))
    final = update_optimizer_stats(stats_path, OptimizeResult("c.py", "needs_fix", False, False, "", "x"))
    assert final["worker"] == "optimizer"
    assert final["applied"] == 1 and final["proposed"] == 1 and final["rejected"] == 1
    assert final["tokens_saved"] == 1200
