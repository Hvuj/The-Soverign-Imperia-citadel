"""Tests for tools/legion_governance.py — wires the dormant companies/board/L5/L6/plan
gates into a live pipeline. Runs as a subprocess (same convention as
test_legion_review.py) so CITADEL_WORKSPACE is resolved fresh per test instead of
racing the module-level ROOT caching every tools/*.py script relies on.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
GOVERNANCE = TOOLS / "legion_governance.py"


def _run(ws: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(GOVERNANCE), *args],
        cwd=str(ws), env=env, capture_output=True, text=True, timeout=60,
    )


def _last_json(result: subprocess.CompletedProcess) -> dict:
    """`main()` always prints one `GATE_RESULT:{...}` line, but the gate classes
    it wires in (l5_structural_decay, l6_shadow_compiler) print their own
    human-readable status lines to stdout first — pull out the marked line.
    """
    for line in result.stdout.splitlines():
        if line.startswith("GATE_RESULT:"):
            return json.loads(line[len("GATE_RESULT:"):])
    return {}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "state").mkdir(parents=True)
    (tmp_path / ".claude" / "legion").mkdir(parents=True)
    (tmp_path / "docs" / "ai-context").mkdir(parents=True)
    (tmp_path / "docs" / "ai-context" / "feature-implementation-patterns.md").write_text(
        "# Patterns\n", encoding="utf-8")
    (tmp_path / ".claude" / "legion" / "board-config.json").write_text(json.dumps({
        "directors": ["correctness", "velocity", "maintainability"],
        "tie_breaker_policy": "Correctness always breaks deadlocks.",
        "precedence_rules": {},
    }), encoding="utf-8")
    return tmp_path


def test_plan_gate_approves_reasonable_plan(ws: Path):
    result = _run(
        ws, "--stage", "plan", "--task", "implement something useful", "--num-workers", "2", "--task-id", "t1",
    )
    assert result.returncode == 0, result.stderr
    out = _last_json(result)
    assert out["approved"] is True


def test_plan_gate_rejects_when_score_below_explicit_threshold(ws: Path):
    result = _run(
        ws, "--stage", "plan", "--task", "y", "--num-workers", "1", "--task-id", "t1b",
        "--threshold", "1000",
    )
    assert result.returncode == 1
    out = _last_json(result)
    assert out["approved"] is False


def test_plan_gate_rice_scales_with_worker_count(ws: Path):
    small = _last_json(_run(ws, "--stage", "plan", "--task", "a", "--num-workers", "1", "--task-id", "t1c"))
    assert small["approved"] is True


def test_full_gate_passes_with_no_changed_files(ws: Path):
    result = _run(ws, "--stage", "full", "--task-id", "t2")
    assert result.returncode == 0, result.stderr
    out = _last_json(result)
    assert out["approved"] is True

    scorecard = json.loads((ws / ".claude" / "state" / "principle-scorecard.json").read_text())
    assert scorecard["conflicts"] == []

    decision = json.loads((ws / ".claude" / "state" / "tier-decision.json").read_text())
    assert decision["tier"] == 1


def test_full_gate_vetoes_on_low_simplicity_score(ws: Path):
    bad_file = ws / "bad_complexity.py"
    body = "".join(f"    if x == {i}:\n        x += 1\n" for i in range(8))
    bad_file.write_text(f"def f(x):\n{body}    return x\n", encoding="utf-8")

    result = _run(ws, "--stage", "full", "--task-id", "t3", "--files", str(bad_file))
    assert result.returncode == 1
    out = _last_json(result)
    assert out["approved"] is False
    assert "board veto" in out["reason"]

    decision = json.loads((ws / ".claude" / "state" / "tier-decision.json").read_text())
    assert decision["tier"] == 0


def test_board_decision_file_lands_where_audit_gate_looks(ws: Path):
    """Regression test for the _ROOT path-resolution bug: tier-decision.json must
    land under CITADEL_WORKSPACE/.claude/state, the same path audit-gate.sh reads
    via $CLAUDE_PROJECT_DIR — not under the installed package's own directory.
    """
    _run(ws, "--stage", "full", "--task-id", "t4")
    assert (ws / ".claude" / "state" / "tier-decision.json").exists()
