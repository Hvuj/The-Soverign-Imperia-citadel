"""Tests for tools/worker_memory.py — per-worker/per-task memory `.md` cards + INDEX.md pointer."""

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import legion_run_state as lrs  # noqa: E402
import worker_memory  # noqa: E402


def _redirect(monkeypatch, tmp_path: Path) -> None:
    runs_dir = tmp_path / ".claude" / "state" / "legion-runs"
    monkeypatch.setattr(lrs, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(lrs, "CURRENT_RUN_POINTER", runs_dir / "current-run.json")


def test_write_task_card_creates_file_with_frontmatter(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    run_id = "run_mem_0001"
    lrs.init_run(run_id, "task", max_workers=1)

    path = worker_memory.write_task_card(
        run_id, worker_id="worker-A", company_id="repo-1", model="claude-opus-4-8",
        effort="high", tier="strong-planning", task="implement X", status="working",
    )

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "worker: worker-A" in text
    assert "company: repo-1" in text
    assert "model: claude-opus-4-8" in text
    assert "status: working" in text
    assert "implement X" in text


def test_write_task_card_indexes_exactly_once_across_updates(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    run_id = "run_mem_0002"
    lrs.init_run(run_id, "task", max_workers=1)

    worker_memory.write_task_card(
        run_id, worker_id="worker-A", company_id="repo-1", model="m", effort="e",
        tier="cheap", task="same task", status="working",
    )
    worker_memory.write_task_card(
        run_id, worker_id="worker-A", company_id="repo-1", model="m", effort="e",
        tier="cheap", task="same task", status="done",
    )

    index_text = lrs.index_path(run_id).read_text(encoding="utf-8")
    tid = worker_memory.task_id_for("worker-A", "same task")
    assert index_text.count(f"/{tid}.md") == 1


def test_different_tasks_get_different_cards(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    run_id = "run_mem_0003"
    lrs.init_run(run_id, "task", max_workers=1)

    p1 = worker_memory.write_task_card(
        run_id, worker_id="worker-A", company_id="repo-1", model="m", effort="e",
        tier="cheap", task="task one", status="working",
    )
    p2 = worker_memory.write_task_card(
        run_id, worker_id="worker-A", company_id="repo-1", model="m", effort="e",
        tier="cheap", task="task two", status="working",
    )
    assert p1 != p2


def test_read_task_card_returns_none_when_missing(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    run_id = "run_mem_0004"
    lrs.init_run(run_id, "task", max_workers=1)
    assert worker_memory.read_task_card(run_id, "worker-Z", "nope") is None
