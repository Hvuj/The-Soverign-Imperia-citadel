"""Tests for tools/prompt_usage_miner.py — learned prompt->context reuse index."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "prompt_usage_miner.py"


def _run(ws: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(ws), env=env, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    state = tmp_path / ".claude" / "state"
    state.mkdir(parents=True)
    ledger = [
        {"intent": "debugging", "unit": "core", "labels": ["code-change", "validation"],
         "prompt_preview": "fix the failing daemon traceback error", "ts": "2026-07-02T10:00:00+00:00"},
        {"intent": "debugging", "unit": "core", "labels": ["code-change"],
         "prompt_preview": "fix the failing daemon traceback error again", "ts": "2026-07-02T11:00:00+00:00"},
        {"intent": "question", "unit": "bi", "labels": ["bi"],
         "prompt_preview": "what is the revenue metric formula", "ts": "2026-07-02T12:00:00+00:00"},
    ]
    (state / "prompt-ledger.ndjson").write_text(
        "".join(json.dumps(r) + "\n" for r in ledger), encoding="utf-8")
    runs = [
        {"event": "subagent-stop", "agent": "test-validation-runner", "task_type": "debugging",
         "session_id": "s1", "ts": "2026-07-02T10:05:00+00:00"},
        {"event": "subagent-stop", "agent": "test-validation-runner", "task_type": "debugging",
         "session_id": "s1", "ts": "2026-07-02T11:05:00+00:00"},
        {"event": "subagent-start", "agent": "ignored", "task_type": "debugging",
         "session_id": "s1", "ts": "2026-07-02T10:04:00+00:00"},
    ]
    (state / "agent-runs.ndjson").write_text(
        "".join(json.dumps(r) + "\n" for r in runs), encoding="utf-8")
    return tmp_path


def test_mine_builds_index(ws: Path):
    r = _run(ws, "--mine", "--json")
    assert r.returncode == 0, r.stderr
    summary = json.loads(r.stdout)
    assert summary["intents"] == 2
    idx = json.loads((ws / ".claude" / "state" / "prompt-usage-index.json").read_text())
    assert idx["agents_by_task_type"]["debugging"] == {"test-validation-runner": 2}
    assert "debugging" in idx["by_intent"]


def test_lookup_hit_and_miss(ws: Path):
    _run(ws, "--mine")
    hit = json.loads(_run(ws, "--lookup", "fix the failing daemon traceback error", "--json").stdout)
    assert hit is not None
    assert hit["intent"] == "debugging"
    assert hit["unit"] == "core"
    miss = json.loads(_run(ws, "--lookup", "totally unrelated zzz qqq wibble", "--json").stdout)
    assert miss is None
