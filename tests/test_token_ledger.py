"""Tests for tools/token_ledger.py — live per-worker token/cost accounting."""

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import legion_run_state as lrs  # noqa: E402
import token_ledger  # noqa: E402


def _redirect(monkeypatch, tmp_path: Path) -> None:
    runs_dir = tmp_path / ".claude" / "state" / "legion-runs"
    monkeypatch.setattr(lrs, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(lrs, "CURRENT_RUN_POINTER", runs_dir / "current-run.json")


def test_parse_worker_output_extracts_usage():
    raw = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "usage": {"input_tokens": 1000, "output_tokens": 200},
        "is_error": False,
    })
    record = token_ledger.parse_worker_output(raw)
    assert record["model"] == "claude-haiku-4-5-20251001"
    assert record["total_tokens"] == 1200
    assert record["cost_usd"] > 0
    assert record["is_error"] is False


def test_parse_worker_output_empty_returns_empty_dict():
    assert token_ledger.parse_worker_output("") == {}
    assert token_ledger.parse_worker_output("not json") == {}


def test_record_and_totals_aggregate_per_worker(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    run_id = "run_tok_0001"
    lrs.init_run(run_id, "task", max_workers=2)

    token_ledger.record_worker_usage(run_id, "worker-A", {"total_tokens": 100, "cost_usd": 0.01})
    token_ledger.record_worker_usage(run_id, "worker-A", {"total_tokens": 50, "cost_usd": 0.005})
    token_ledger.record_worker_usage(run_id, "worker-B", {"total_tokens": 200, "cost_usd": 0.02})

    totals = token_ledger.run_totals(run_id)
    assert totals["total_tokens"] == 350
    assert totals["per_worker"]["worker-A"]["total_tokens"] == 150
    assert totals["per_worker"]["worker-B"]["total_tokens"] == 200


def test_record_worker_usage_skips_empty_record(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    run_id = "run_tok_0002"
    lrs.init_run(run_id, "task", max_workers=1)

    token_ledger.record_worker_usage(run_id, "worker-A", {})
    assert lrs.read_ledger(run_id) == []
