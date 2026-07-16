"""Local-first pre-pass for the parallel legion: safe-by-default (drops nothing without a verifier),
records every local attempt, and drops only verifier-confirmed slices."""

import sys
from pathlib import Path
from types import SimpleNamespace

_TOOLS = str(Path(__file__).resolve().parents[1] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import legion_orchestrator as lo  # noqa: E402

from citadel.services.execute import ExecutionResult, LocalConfidence  # noqa: E402


class FakeLocal:
    def __init__(self, statuses):
        self._statuses = dict(statuses)

    def execute(self, blueprint):
        return ExecutionResult(blueprint.task_id, self._statuses.get(blueprint.task_id, "needs_fix"))


def _spec(worker_id, company="repo"):
    return SimpleNamespace(worker_id=worker_id, company_id=company, prompt=f"do {worker_id}")


def test_prepass_drops_nothing_without_verifier(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(lo, "append_ledger", lambda run_id, rec: events.append(rec))
    specs = [_spec("worker-A"), _spec("worker-B")]
    local = FakeLocal({"worker-A": "pass", "worker-B": "pass"})
    conf = LocalConfidence(path=tmp_path / "c.jsonl")
    remaining = lo.local_first_prepass(specs, "run1", tmp_path, local=local, confidence=conf)
    assert [s.worker_id for s in remaining] == ["worker-A", "worker-B"]
    assert all(e["event"] == "worker-local-attempt" for e in events)
    assert all(e["resolved"] is False for e in events)


def test_prepass_drops_only_verified_slices(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(lo, "append_ledger", lambda run_id, rec: events.append(rec))
    specs = [_spec("worker-A"), _spec("worker-B"), _spec("worker-C")]
    local = FakeLocal({"worker-A": "pass", "worker-B": "needs_fix", "worker-C": "pass"})
    conf = LocalConfidence(path=tmp_path / "c.jsonl")
    remaining = lo.local_first_prepass(
        specs, "run1", tmp_path,
        verify=lambda spec, result: spec.worker_id == "worker-A",
        local=local, confidence=conf,
    )
    assert [s.worker_id for s in remaining] == ["worker-B", "worker-C"]
    passed = [e for e in events if e["event"] == "worker-local-pass"]
    assert [e["worker"] for e in passed] == ["worker-A"]


def test_prepass_records_confidence(tmp_path, monkeypatch):
    monkeypatch.setattr(lo, "append_ledger", lambda run_id, rec: None)
    specs = [_spec("worker-A"), _spec("worker-B")]
    local = FakeLocal({"worker-A": "pass", "worker-B": "needs_fix"})
    conf = LocalConfidence(path=tmp_path / "c.jsonl", min_attempts=1)
    lo.local_first_prepass(specs, "run1", tmp_path, local=local, confidence=conf)
    assert conf.confidence("legion_slice") == 0.5
