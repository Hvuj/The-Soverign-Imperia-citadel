"""Tests for tools/legion_review.py — deterministic RICE/dup gate + plan generation."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
REVIEW = TOOLS / "legion_review.py"
STORE = TOOLS / "feature_improvement_store.py"


def _run(tool: Path, ws: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(tool), *args],
        cwd=str(ws), env=env, input=stdin, capture_output=True, text=True, timeout=30,
    )


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "state").mkdir(parents=True)
    (tmp_path / "docs" / "ai-context").mkdir(parents=True)
    (tmp_path / "docs" / "ai-context" / "feature-implementation-patterns.md").write_text(
        "# Patterns\n", encoding="utf-8")
    return tmp_path


def _propose(ws: Path, title: str, rice: dict) -> dict:
    payload = json.dumps({"title": title, "source": "zombie", "target": title, "rice": rice})
    return json.loads(_run(STORE, ws, "--propose", "--json", stdin=payload).stdout)


def test_high_rice_approved_and_plan_written(ws: Path):
    rec = _propose(ws, "big win", {"reach": 20, "impact": 3, "confidence": 0.9, "effort": 1})
    out = json.loads(_run(REVIEW, ws, "--review", rec["id"], "--json").stdout)
    assert out["status"] == "approved"
    plan = ws / ".claude" / "state" / "feature-improvements" / f"{rec['id']}-plan.md"
    assert plan.exists()
    assert "E2E validation checklist" in plan.read_text()


def test_low_rice_rejected(ws: Path):
    rec = _propose(ws, "meh", {"reach": 1, "impact": 1, "confidence": 0.2, "effort": 9})
    out = json.loads(_run(REVIEW, ws, "--review", rec["id"], "--json").stdout)
    assert out["status"] == "rejected"
    assert "RICE" in out["review_reason"]


def test_duplicate_title_rejected(ws: Path):
    r1 = _propose(ws, "dupe", {"reach": 20, "impact": 3, "confidence": 0.9, "effort": 1})
    _run(REVIEW, ws, "--review", r1["id"])
    r2 = _propose(ws, "dupe", {"reach": 20, "impact": 3, "confidence": 0.9, "effort": 1})
    out = json.loads(_run(REVIEW, ws, "--review", r2["id"], "--json").stdout)
    assert out["status"] == "rejected"
    assert "duplicate" in out["review_reason"]
