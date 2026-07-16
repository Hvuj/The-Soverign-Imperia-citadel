"""LocalCodingExecutor: verified-before-write local coding. Deterministic fakes; a live case lives in
test_ollama_live.py."""

from citadel.services.execute import (
    Blueprint,
    LocalCodingExecutor,
    extract_code,
)
from citadel.services.execute.coding import extract_files
from citadel.services.execute.local.engine import LocalEngine

_TWO_FILES = "### FILE: a.py\n```python\nA = 1\n```\n### FILE: b.py\n```python\nB = 2\n```"


class FakeEngine(LocalEngine):
    name = "fake"

    def __init__(self, output, avail=True):
        self._output = output
        self._avail = avail

    def available(self):
        return self._avail

    def generate(self, prompt, spec):
        return self._output


def _bp(target="mod.py", instruction="write it"):
    return Blueprint(task_id="t", instruction=instruction, allowed_files=[target])


def test_extract_code_fenced_and_plain():
    assert extract_code("```python\nx = 1\n```") == "x = 1"
    assert extract_code("no fence here") == "no fence here"


def test_pass_writes_file_when_verified(tmp_path):
    engine = FakeEngine("```python\nVALUE = 42\n```")
    executor = LocalCodingExecutor(engine, tmp_path, verify=lambda sb: (True, "ok"))
    result = executor.execute(_bp("mod.py"))
    assert result.status == "pass"
    assert (tmp_path / "mod.py").read_text() == "VALUE = 42"


def test_needs_fix_does_not_write_when_verification_fails(tmp_path):
    engine = FakeEngine("```python\nBROKEN(\n```")
    executor = LocalCodingExecutor(engine, tmp_path, verify=lambda sb: (False, "syntax error"))
    result = executor.execute(_bp("mod.py"))
    assert result.status == "needs_fix"
    assert "verification_failed" in result.reason
    assert not (tmp_path / "mod.py").exists()


def test_verify_sees_new_content_in_sandbox(tmp_path):
    (tmp_path / "mod.py").write_text("OLD = 1\n")
    seen = {}

    def verify(sandbox):
        seen["content"] = (sandbox / "mod.py").read_text()
        return True, "ok"

    executor = LocalCodingExecutor(FakeEngine("```python\nNEW = 2\n```"), tmp_path, verify=verify)
    executor.execute(_bp("mod.py"))
    assert seen["content"] == "NEW = 2"
    assert (tmp_path / "mod.py").read_text() == "NEW = 2"


def test_no_target_blocks(tmp_path):
    executor = LocalCodingExecutor(FakeEngine("x"), tmp_path, verify=lambda sb: (True, ""))
    result = executor.execute(Blueprint(task_id="t", instruction="x"))
    assert result.status == "blocked"
    assert result.reason == "no_target_file"


def test_engine_unavailable_blocks(tmp_path):
    executor = LocalCodingExecutor(FakeEngine("x", avail=False), tmp_path, verify=lambda sb: (True, ""))
    result = executor.execute(_bp())
    assert result.status == "blocked"
    assert "engine_unavailable" in result.reason


def test_empty_generation_needs_fix(tmp_path):
    executor = LocalCodingExecutor(FakeEngine(""), tmp_path, verify=lambda sb: (True, ""))
    result = executor.execute(_bp())
    assert result.status == "needs_fix"


def test_extract_files_tagged_and_ignores_untargeted():
    assert extract_files(_TWO_FILES, ["a.py", "b.py"]) == {"a.py": "A = 1", "b.py": "B = 2"}
    assert extract_files("### FILE: evil.py\n```\nX\n```", ["a.py", "b.py"]) == {}


def test_multifile_writes_all_on_verify_pass(tmp_path):
    executor = LocalCodingExecutor(FakeEngine(_TWO_FILES), tmp_path, verify=lambda sb: (True, "ok"))
    result = executor.execute(Blueprint(task_id="t", instruction="x", allowed_files=["a.py", "b.py"]))
    assert result.status == "pass"
    assert (tmp_path / "a.py").read_text() == "A = 1"
    assert (tmp_path / "b.py").read_text() == "B = 2"


def test_multifile_missing_file_writes_nothing(tmp_path):
    executor = LocalCodingExecutor(FakeEngine("### FILE: a.py\n```\nA = 1\n```"), tmp_path, verify=lambda sb: (True, "ok"))
    result = executor.execute(Blueprint(task_id="t", instruction="x", allowed_files=["a.py", "b.py"]))
    assert result.status == "needs_fix"
    assert "incomplete_generation" in result.reason
    assert not (tmp_path / "a.py").exists()
    assert not (tmp_path / "b.py").exists()


def test_multifile_verify_fail_writes_nothing(tmp_path):
    executor = LocalCodingExecutor(FakeEngine(_TWO_FILES), tmp_path, verify=lambda sb: (False, "boom"))
    result = executor.execute(Blueprint(task_id="t", instruction="x", allowed_files=["a.py", "b.py"]))
    assert result.status == "needs_fix"
    assert not (tmp_path / "a.py").exists()
    assert not (tmp_path / "b.py").exists()


def test_ledger_records_pass_and_backs_up_preimage(tmp_path):
    from citadel.services.execute.verdict import PASS, VerdictLedger, artifact_hash

    (tmp_path / "mod.py").write_text("OLD = 1\n", encoding="utf-8")
    ledger = VerdictLedger(tmp_path / ".ledger")
    executor = LocalCodingExecutor(
        FakeEngine("```python\nNEW = 2\n```"), tmp_path, verify=lambda sb: (True, "ok"), ledger=ledger
    )
    result = executor.execute(_bp("mod.py"))
    assert result.status == "pass"
    assert ledger.verdict(artifact_hash("NEW = 2")) == PASS
    assert any((tmp_path / ".ledger" / "pre-images").iterdir())


def test_ledger_blocks_condemned_content(tmp_path):
    from citadel.services.execute.verdict import VerdictLedger, artifact_hash

    ledger = VerdictLedger(tmp_path / ".ledger")
    ledger.condemn(artifact_hash("BAD = 1"))
    executor = LocalCodingExecutor(
        FakeEngine("```python\nBAD = 1\n```"), tmp_path, verify=lambda sb: (True, "ok"), ledger=ledger
    )
    result = executor.execute(_bp("mod.py"))
    assert result.status == "blocked"
    assert "condemned" in result.reason
    assert not (tmp_path / "mod.py").exists()


def test_ledger_records_fail_on_verify_fail(tmp_path):
    from citadel.services.execute.verdict import FAIL, VerdictLedger, artifact_hash

    ledger = VerdictLedger(tmp_path / ".ledger")
    executor = LocalCodingExecutor(
        FakeEngine("```python\nX = 1\n```"), tmp_path, verify=lambda sb: (False, "boom"), ledger=ledger
    )
    result = executor.execute(_bp("mod.py"))
    assert result.status == "needs_fix"
    assert ledger.verdict(artifact_hash("X = 1")) == FAIL
