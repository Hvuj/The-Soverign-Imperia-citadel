"""Tests for tools/feature_improvement_store.py — propose, RICE rank, approve→promote."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "feature_improvement_store.py"


def _run(ws: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(ws), env=env, input=stdin, capture_output=True, text=True, timeout=30,
    )


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "state").mkdir(parents=True)
    patterns = tmp_path / "docs" / "ai-context"
    patterns.mkdir(parents=True)
    (patterns / "feature-implementation-patterns.md").write_text("# Patterns\n", encoding="utf-8")
    return tmp_path


def _propose(ws: Path, title: str, rice: dict) -> dict:
    payload = json.dumps({"title": title, "source": "zombie", "target": "tools/x.py",
                          "why": "slow", "how": ["step1"], "rice": rice})
    r = _run(ws, "--propose", "--json", stdin=payload)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_propose_writes_scored_record(ws: Path):
    rec = _propose(ws, "speed up X", {"reach": 10, "impact": 2, "confidence": 0.8, "effort": 2})
    assert rec["id"].startswith("fi_")
    assert len(rec["id"]) == 15
    assert rec["rice_score"] == 8.0
    assert rec["status"] == "proposed"
    assert len(rec["reasoning_hash"]) == 64
    files = list((ws / ".claude" / "state" / "feature-improvements").glob("*.json"))
    assert len(files) == 1


def test_list_ranked_by_rice(ws: Path):
    _propose(ws, "low value", {"reach": 1, "impact": 1, "confidence": 0.5, "effort": 5})
    _propose(ws, "high value", {"reach": 20, "impact": 3, "confidence": 0.9, "effort": 1})
    listed = json.loads(_run(ws, "--list", "--json").stdout)
    assert listed[0]["title"] == "high value"
    assert listed[0]["rice_score"] > listed[1]["rice_score"]


def test_approve_promotes_card(ws: Path):
    rec = _propose(ws, "promote me", {"reach": 5, "impact": 2, "confidence": 1, "effort": 1})
    _run(ws, "--approve", rec["id"])
    updated = json.loads(_run(ws, "--get", rec["id"], "--json").stdout)
    assert updated["status"] == "approved"
    patterns = (ws / "docs" / "ai-context" / "feature-implementation-patterns.md").read_text()
    assert "promote me" in patterns


def test_reject_records_reason(ws: Path):
    rec = _propose(ws, "reject me", {"reach": 1, "impact": 1, "confidence": 0.1, "effort": 9})
    _run(ws, "--reject", rec["id"], "--reason", "below threshold")
    updated = json.loads(_run(ws, "--get", rec["id"], "--json").stdout)
    assert updated["status"] == "rejected"
    assert updated["review_reason"] == "below threshold"
