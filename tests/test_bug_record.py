"""Tests for tools/bug_record.py — the bug-record company: detect, dedup, closed-loop triage."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
BUG_RECORD = TOOLS / "bug_record.py"
SELF_HEAL = TOOLS / "legion_self_heal.py"


def _run(tool: Path, ws: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(tool), *args],
        cwd=str(ws), env=env, capture_output=True, text=True, timeout=120,
    )


def _json(tool: Path, ws: Path, *args: str) -> dict:
    r = _run(tool, ws, "--json", *args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    state = tmp_path / ".claude" / "state"
    state.mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _rollup(ws: Path) -> dict:
    return json.loads((ws / ".claude" / "state" / "bug-ledger.json").read_text(encoding="utf-8"))


def test_scan_records_self_heal_finding(ws: Path):
    rec = {"ts": "t", "mode": "check", "is_git_repo": False, "finding_count": 1, "high": 0,
           "findings": [{"kind": "malformed_json", "severity": "high",
                         "path": ".claude/brain/x.json", "detail": "bad", "action": "reported"}]}
    (ws / ".claude" / "state" / "self-heal.ndjson").write_text(
        json.dumps(rec) + "\n", encoding="utf-8")

    result = _json(BUG_RECORD, ws, "--scan")
    assert result["new"] == 1
    assert result["open"] == 1
    kinds = {r["kind"] for r in _rollup(ws).values()}
    assert "malformed_json" in kinds


def test_err_log_traceback_detected(ws: Path):
    log = ws / ".claude" / "state" / "some-daemon.err.log"
    log.write_text("ok\nTraceback (most recent call last)\n  boom\n", encoding="utf-8")
    result = _json(BUG_RECORD, ws, "--scan")
    assert result["new"] >= 1
    assert any(r["kind"] == "log_error" for r in _rollup(ws).values())


def test_critical_err_log_writes_restart_request(ws: Path):
    log = ws / ".claude" / "state" / "citadel-ui-server.err.log"
    log.write_text(
        "Traceback (most recent call last)\n"
        "OSError: [Errno 48] Address already in use\n",
        encoding="utf-8",
    )
    result = _json(BUG_RECORD, ws, "--scan")
    assert result["new"] >= 1
    critical_recs = [r for r in _rollup(ws).values() if r.get("severity") == "critical"]
    assert critical_recs
    marker = ws / ".claude" / "state" / "restart-request.json"
    assert marker.exists()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["fingerprint"] == critical_recs[0]["fingerprint"]
    assert payload["severity"] == "critical"


def test_stale_err_log_not_reported_after_clean_restart(ws: Path):
    log = ws / ".claude" / "state" / "some-daemon.err.log"
    pidfile = ws / ".claude" / "state" / "some-daemon.pid"
    log.write_text("Traceback (most recent call last)\n  boom\n", encoding="utf-8")
    pidfile.write_text("123", encoding="utf-8")
    os.utime(pidfile, (log.stat().st_mtime + 10, log.stat().st_mtime + 10))

    result = _json(BUG_RECORD, ws, "--scan")
    assert result["new"] == 0
    assert not any(r["kind"] == "log_error" for r in _rollup(ws).values())


def test_err_log_bug_auto_closes_once_daemon_restarts_cleanly(ws: Path):
    log = ws / ".claude" / "state" / "flaky-daemon.err.log"
    log.write_text("Traceback (most recent call last)\n  boom\n", encoding="utf-8")

    first = _json(BUG_RECORD, ws, "--scan")
    assert first["new"] == 1
    assert first["open"] == 1

    pidfile = ws / ".claude" / "state" / "flaky-daemon.pid"
    pidfile.write_text("456", encoding="utf-8")
    os.utime(pidfile, (log.stat().st_mtime + 10, log.stat().st_mtime + 10))

    second = _json(BUG_RECORD, ws, "--scan")
    assert second["auto_closed"] == 1
    rec = next(r for r in _rollup(ws).values() if r["kind"] == "log_error")
    assert rec["status"] == "resolved"


def test_expanded_remediable_kinds_dispatch_self_heal(ws: Path):
    hooks = ws / ".claude" / "hooks"
    hooks.mkdir()
    (hooks / "bad.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\ngit diff\n", encoding="utf-8")

    assert _run(SELF_HEAL, ws, "--check", "--quiet").returncode == 0
    scan = _json(BUG_RECORD, ws, "--scan")
    assert scan["open"] >= 1
    assert any(r["kind"] == "unguarded_git_in_hook" for r in _rollup(ws).values())

    triage = _json(BUG_RECORD, ws, "--triage")
    assert triage["self_heal_dispatched"] is True
    assert "|| true" in (hooks / "bad.sh").read_text(encoding="utf-8")
    git_recs = [r for r in _rollup(ws).values() if r["kind"] == "unguarded_git_in_hook"]
    assert git_recs
    assert all(r["status"] == "resolved" for r in git_recs)


def test_closed_loop_triage_self_heals_duplicate(ws: Path):
    hooks = ws / ".claude" / "hooks"
    hooks.mkdir()
    (hooks / "dup.sh").write_text("echo canonical\n", encoding="utf-8")
    (ws / ".claude" / "dup.sh").write_text("echo stale\n", encoding="utf-8")

    assert _run(SELF_HEAL, ws, "--check", "--quiet").returncode == 0
    scan = _json(BUG_RECORD, ws, "--scan")
    assert scan["open"] >= 1
    assert any(r["kind"] == "duplicate_divergent_hook" and r["status"] == "open"
               for r in _rollup(ws).values())
    triage = _json(BUG_RECORD, ws, "--triage")
    assert triage["self_heal_dispatched"] is True
    assert not (ws / ".claude" / "dup.sh").exists()
    dup_recs = [r for r in _rollup(ws).values() if r["kind"] == "duplicate_divergent_hook"]
    assert dup_recs
    assert all(r["status"] == "resolved" for r in dup_recs)
