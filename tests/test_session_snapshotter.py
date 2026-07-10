"""Tests for tools/session_snapshotter.py — mid-session durable context save."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "session_snapshotter.py"


def _run(ws: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(ws), env=env, input=stdin, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "state").mkdir(parents=True)
    return tmp_path


def _sess_dir(ws: Path, sid: str) -> Path:
    return ws / ".claude" / "state" / "session-context" / sid


def test_snapshot_persists_transcript_and_manifest(ws: Path):
    transcript = ws / "transcript.jsonl"
    transcript.write_text("x" * 10000, encoding="utf-8")
    payload = {"session_id": "sessA", "transcript_path": str(transcript)}

    _run(ws, stdin=json.dumps(payload))
    sdir = _sess_dir(ws, "sessA")
    manifest = json.loads((sdir / "manifest.json").read_text())
    assert manifest["session_id"] == "sessA"
    assert len(manifest["snapshots"]) == 1
    assert (sdir / "turn-index.ndjson").exists()


def test_snapshot_dedups_by_size_then_copies_on_growth(ws: Path):
    transcript = ws / "t.jsonl"
    transcript.write_text("y" * 10000, encoding="utf-8")
    payload = json.dumps({"session_id": "sessB", "transcript_path": str(transcript)})

    _run(ws, stdin=payload)
    _run(ws, stdin=payload)
    snaps = _sess_dir(ws, "sessB") / "snapshots"
    assert len(list(snaps.glob("*.jsonl"))) == 1

    transcript.write_text("y" * 20000, encoding="utf-8")
    _run(ws, stdin=payload)
    assert len(list(snaps.glob("*.jsonl"))) == 2


def test_restore_returns_latest_snapshot(ws: Path):
    transcript = ws / "t.jsonl"
    transcript.write_text("z" * 10000, encoding="utf-8")
    _run(ws, stdin=json.dumps({"session_id": "sessC", "transcript_path": str(transcript)}))
    r = _run(ws, "--restore", "--session", "sessC", "--json")
    result = json.loads(r.stdout)
    assert result["latest_snapshot"] is not None
    assert result["manifest"]["session_id"] == "sessC"


def test_no_session_id_is_skipped(ws: Path):
    r = _run(ws, "--json", stdin=json.dumps({"transcript_path": "/nope"}))
    assert json.loads(r.stdout) == {"skipped": "no session_id"}
