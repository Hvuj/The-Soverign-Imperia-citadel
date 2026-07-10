"""Tests for the legion_orchestrator worker-mode substrate (Part C)."""

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import legion_orchestrator as lo  # noqa: E402
from token_ledger import parse_worker_result  # noqa: E402

from citadel.services.corporate import Company  # noqa: E402


def _company(repo_id: str) -> Company:
    return Company(repo_id=repo_id, path=Path(f"/tmp/{repo_id}"), is_git=True, python_root=".")


def test_task_mode_keeps_lead_and_support():
    companies = [_company("a"), _company("b")]
    specs = lo.plan_run("refactor entire thing", companies, 2, lo.MODE_TASK)
    assert "lead" in specs[0].role
    assert "support" in specs[1].role


def test_parse_worker_result_extracts_result_json():
    raw = json.dumps({"result": '{"repo":"a","metrics":[]}', "usage": {}, "is_error": False})
    assert parse_worker_result(raw) == '{"repo":"a","metrics":[]}'
    assert parse_worker_result("not json") is None
    assert parse_worker_result(json.dumps({"usage": {}})) is None


def test_run_benchmark_local_delegates_to_tool(monkeypatch):
    import best_practices_benchmark as bpb
    captured = {}

    def fake_run(paths, ws, *, max_workers, dry_run):
        captured["paths"] = [Path(p).as_posix() for p in paths]  # OS-agnostic comparison
        captured["dry_run"] = dry_run
        return 0

    monkeypatch.setattr(bpb, "run_benchmark", fake_run)
    rc = lo._run_benchmark_local([_company("a"), _company("b")], Path("/tmp/ws"), max_workers=4, dry_run=True)
    assert rc == 0
    assert captured["paths"] == ["/tmp/a", "/tmp/b"]
    assert captured["dry_run"] is True
