"""Hermetic test of legion_orchestrator._supervise — spawn/respawn/finalize/ledger.

Stubs spawn_worker (fake process + fake worker JSON output) and the governance gate,
and redirects legion_run_state paths into tmp_path, so no real `claude` process, no real
git, and no writes to the dev repo occur. Covers the riskiest new function.
"""

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import legion_orchestrator as lo  # noqa: E402
import legion_run_state as lrs  # noqa: E402


class _FakeProc:
    def __init__(self, returncode: int) -> None:
        self._returncode = returncode
        self.returncode = None

    def poll(self) -> int | None:
        self.returncode = self._returncode
        return self._returncode


class _FakeGate:
    def __init__(self, approved: bool, reason: str = "ok") -> None:
        self.approved = approved
        self.reason = reason
        self.detail: dict = {}


def _redirect(monkeypatch, tmp_path: Path) -> None:
    runs_dir = tmp_path / ".claude" / "state" / "legion-runs"
    monkeypatch.setattr(lrs, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(lrs, "CURRENT_RUN_POINTER", runs_dir / "current-run.json")
    monkeypatch.setattr(lo.legion_governance, "run_full_gate", lambda tid, files: _FakeGate(True))


def _spec(tmp_path: Path, tier: str = "cheap") -> lo.WorkerSpec:
    resolved = lo.schedule_agent(tier)
    return lo.WorkerSpec(
        worker_id="worker-A", company_id="repo-1", company_path=tmp_path,
        role="lead", task="do it", tier=tier,
        model=resolved["model"], effort=resolved["effort"], prompt="p",
    )


def _install_fake_spawn(monkeypatch, results: list[dict], returncodes: list[int]) -> dict:
    """Fake spawn_worker that yields scripted (worker-output, returncode) per attempt."""
    state = {"attempt": 0}

    def fake_spawn(spec, run_id, claude_bin, permission_mode, ws, *, read_only=False):
        i = min(state["attempt"], len(results) - 1)
        out = lrs.worker_log_path(run_id, spec.worker_id, "out")
        out.write_text(json.dumps(results[i]), encoding="utf-8")
        rc = returncodes[min(state["attempt"], len(returncodes) - 1)]
        state["attempt"] += 1
        return _FakeProc(rc)

    monkeypatch.setattr(lo, "spawn_worker", fake_spawn)
    return state


def test_clean_worker_finalizes_and_records_usage(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    run_id = lrs.new_run_id()
    lrs.init_run(run_id, "t", max_workers=1)
    _install_fake_spawn(
        monkeypatch,
        results=[{"model": "claude-haiku-4-5-20251001", "usage": {"input_tokens": 100, "output_tokens": 20},
                  "is_error": False, "total_cost_usd": 0.001}],
        returncodes=[0],
    )

    rc = lo._supervise([_spec(tmp_path)], run_id, "claude", tmp_path, permission_mode="dontAsk", dashboard=False)

    assert rc == 0
    events = [r["event"] for r in lrs.read_ledger(run_id)]
    assert "worker-usage" in events
    assert "worker-final" in events
    finals = [r for r in lrs.read_ledger(run_id) if r["event"] == "worker-final"]
    assert finals[0]["status"] == "done"


def test_failed_worker_respawns_then_finalizes(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    run_id = lrs.new_run_id()
    lrs.init_run(run_id, "t", max_workers=1)
    ok = {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 10, "output_tokens": 5}, "is_error": False}
    err = {"model": "claude-haiku-4-5-20251001", "usage": {"input_tokens": 10, "output_tokens": 5}, "is_error": True}
    _install_fake_spawn(monkeypatch, results=[err, ok], returncodes=[1, 0])

    rc = lo._supervise([_spec(tmp_path)], run_id, "claude", tmp_path, permission_mode="dontAsk", dashboard=False)

    events = [r["event"] for r in lrs.read_ledger(run_id)]
    assert "worker-respawn" in events
    assert events[-1] == "worker-final"
    assert rc == 0


def test_blocked_gate_returns_nonzero(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    monkeypatch.setattr(lo.legion_governance, "run_full_gate", lambda tid, files: _FakeGate(False, "board veto"))
    run_id = lrs.new_run_id()
    lrs.init_run(run_id, "t", max_workers=1)
    _install_fake_spawn(
        monkeypatch,
        results=[{"model": "claude-haiku-4-5-20251001", "usage": {"input_tokens": 1, "output_tokens": 1},
                  "is_error": False}],
        returncodes=[0],
    )

    rc = lo._supervise([_spec(tmp_path)], run_id, "claude", tmp_path, permission_mode="dontAsk", dashboard=False)

    assert rc == 1
    finals = [r for r in lrs.read_ledger(run_id) if r["event"] == "worker-final"]
    assert finals[0]["status"] == "blocked"


def test_build_worker_argv_never_uses_hanging_modes():
    for read_only in (True, False):
        argv = lo._build_worker_argv("claude", "claude-haiku-4-5-20251001", "dontAsk", read_only=read_only)
        assert "--permission-mode" in argv
        assert "dontAsk" in argv
        assert "acceptEdits" not in argv
        assert "--allowedTools" in argv
        assert "--disallowedTools" in argv


def test_build_worker_argv_bypass_has_no_allowlist():
    argv = lo._build_worker_argv("claude", "claude-opus-4-8", "bypassPermissions")
    assert "bypassPermissions" in argv
    assert "--allowedTools" not in argv
