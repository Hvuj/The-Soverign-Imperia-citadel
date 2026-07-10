"""Tests for tools/worker_status.py's legion multi-worker view (legion_status/render_legion_text) —
the live terminal view showing N concurrent workers, each its own model/effort/status.
"""

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import worker_status  # noqa: E402


def test_legion_status_no_active_run(monkeypatch):
    monkeypatch.setattr(worker_status._lrs, "current_run_id", lambda: None)
    assert worker_status.legion_status() == {"run_id": None, "workers": []}


def test_legion_status_replays_lifecycle_events(monkeypatch):
    records = [
        {"event": "worker-start", "worker": "worker-A", "company": "repo-1",
         "model": "claude-opus-4-8", "effort": "high", "tier": "strong-planning"},
        {"event": "worker-usage", "worker": "worker-A", "total_tokens": 500, "cost_usd": 0.01},
        {"event": "worker-final", "worker": "worker-A", "status": "done", "gate": "L5+L6 passed"},
    ]
    monkeypatch.setattr(worker_status._lrs, "read_ledger", lambda run_id: records)

    status = worker_status.legion_status("run_x")
    assert status["run_id"] == "run_x"
    [worker] = status["workers"]
    assert worker["model"] == "claude-opus-4-8"
    assert worker["effort"] == "high"
    assert worker["status"] == "done"
    assert worker["tokens"] == 500
    assert worker["gate"] == "L5+L6 passed"


def test_legion_status_distinguishes_multiple_concurrent_workers(monkeypatch):
    records = [
        {"event": "worker-start", "worker": "worker-A", "company": "repo-1",
         "model": "claude-opus-4-8", "effort": "high", "tier": "strong-planning"},
        {"event": "worker-start", "worker": "worker-B", "company": "repo-2",
         "model": "claude-haiku-4-5-20251001", "effort": "low", "tier": "cheap"},
    ]
    monkeypatch.setattr(worker_status._lrs, "read_ledger", lambda run_id: records)

    status = worker_status.legion_status("run_x")
    models = {w["worker_id"]: w["model"] for w in status["workers"]}
    efforts = {w["worker_id"]: w["effort"] for w in status["workers"]}
    assert models == {"worker-A": "claude-opus-4-8", "worker-B": "claude-haiku-4-5-20251001"}
    assert efforts == {"worker-A": "high", "worker-B": "low"}


def test_legion_status_respawn_updates_model_and_status(monkeypatch):
    records = [
        {"event": "worker-start", "worker": "worker-A", "company": "repo-1",
         "model": "claude-haiku-4-5-20251001", "effort": "low", "tier": "cheap"},
        {"event": "worker-respawn", "worker": "worker-A",
         "model": "claude-sonnet-4-6", "effort": "medium", "tier": "standard", "reason": "exit code 1"},
    ]
    monkeypatch.setattr(worker_status._lrs, "read_ledger", lambda run_id: records)

    [worker] = worker_status.legion_status("run_x")["workers"]
    assert worker["model"] == "claude-sonnet-4-6"
    assert worker["status"] == "respawning"


def test_render_legion_text_shows_each_worker_row():
    status = {
        "run_id": "run_x",
        "workers": [
            {"worker_id": "worker-A", "company": "repo-1", "model": "claude-opus-4-8",
             "effort": "high", "status": "working", "tokens": 100, "cost_usd": 0.001},
        ],
    }
    text = worker_status.render_legion_text(status)
    assert "worker-A" in text
    assert "claude-opus-4-8" in text
    assert "high" in text


def test_render_legion_text_no_run():
    assert "no active run" in worker_status.render_legion_text({"run_id": None, "workers": []})
