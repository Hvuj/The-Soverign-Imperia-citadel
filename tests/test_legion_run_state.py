"""Tests for tools/legion_run_state.py — run-scoped state root for `citadel run`.

Redirects the module's path globals into tmp_path via monkeypatch rather than
setting CITADEL_WORKSPACE, since ROOT/STATE/RUNS_DIR are resolved once at import
time (same pattern as `_brain_common.py`) — by the time a test runs, the module
is already imported against whatever workspace the pytest process started in.
"""

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import legion_run_state as lrs  # noqa: E402


def _redirect(monkeypatch, tmp_path: Path) -> None:
    runs_dir = tmp_path / ".claude" / "state" / "legion-runs"
    monkeypatch.setattr(lrs, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(lrs, "CURRENT_RUN_POINTER", runs_dir / "current-run.json")


def test_new_run_id_is_unique():
    assert lrs.new_run_id() != lrs.new_run_id()


def test_init_run_creates_layout_and_current_pointer(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    run_id = "run_test_0001"

    lrs.init_run(run_id, "do the thing", max_workers=2)

    assert lrs.workers_dir(run_id).is_dir()
    assert lrs.gates_dir(run_id).is_dir()
    assert lrs.index_path(run_id).exists()
    assert "do the thing" in lrs.index_path(run_id).read_text(encoding="utf-8")
    assert lrs.current_run_id() == run_id


def test_append_and_read_ledger_round_trips(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    run_id = "run_test_0002"
    lrs.init_run(run_id, "task", max_workers=1)

    lrs.append_ledger(run_id, {"event": "worker-start", "worker": "worker-A"})
    lrs.append_ledger(run_id, {"event": "worker-final", "worker": "worker-A", "status": "done"})

    records = lrs.read_ledger(run_id)
    assert [r["event"] for r in records] == ["worker-start", "worker-final"]
    assert all("ts" in r for r in records)


def test_read_ledger_missing_run_returns_empty(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    assert lrs.read_ledger("run_does_not_exist") == []


def test_current_run_id_none_when_no_pointer(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    assert lrs.current_run_id() is None


def test_append_index_line_creates_index_if_missing(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    run_id = "run_test_0003"
    lrs.append_index_line(run_id, "- pointer line")
    assert "- pointer line" in lrs.index_path(run_id).read_text(encoding="utf-8")
