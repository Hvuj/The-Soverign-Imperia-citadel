"""Tests for tools/efficiency_gate.py — the enforced (not just advisory) budget backstop."""

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from efficiency_gate import check_token_budget, check_worker_count  # noqa: E402


def test_worker_count_within_cap_approved():
    verdict = check_worker_count(4, worker_cap=8)
    assert verdict.approved is True


def test_worker_count_exceeding_cap_rejected():
    verdict = check_worker_count(20, worker_cap=8)
    assert verdict.approved is False
    assert "exceeds cap" in verdict.reason


def test_worker_count_exactly_at_cap_approved():
    verdict = check_worker_count(8, worker_cap=8)
    assert verdict.approved is True


def test_token_budget_under_limit_approved():
    verdict = check_token_budget(100, token_budget=1000)
    assert verdict.approved is True


def test_token_budget_at_or_over_limit_rejected():
    verdict = check_token_budget(1000, token_budget=1000)
    assert verdict.approved is False
    assert "no further worker spawns" in verdict.reason
