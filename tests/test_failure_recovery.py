"""Tests for tools/failure_recovery.py — deterministic legion worker respawn/escalation policy."""

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from failure_recovery import MAX_ESCALATIONS, decide  # noqa: E402


def test_clean_exit_never_respawns():
    decision = decide(tier="cheap", exit_code=0, blocked_verdict=False, escalations_used=0)
    assert decision.should_respawn is False
    assert decision.tier == "cheap"


def test_retryable_exit_escalates_one_tier():
    decision = decide(tier="cheap", exit_code=1, blocked_verdict=False, escalations_used=0)
    assert decision.should_respawn is True
    assert decision.tier == "standard"
    assert decision.model != ""
    assert decision.effort != ""


def test_blocked_verdict_escalates_even_on_zero_exit():
    decision = decide(tier="standard", exit_code=0, blocked_verdict=True, escalations_used=0)
    assert decision.should_respawn is True
    assert decision.tier == "strong-planning"


def test_escalation_ladder_reaches_ultracode():
    decision = decide(tier="strong-planning", exit_code=1, blocked_verdict=False, escalations_used=0)
    assert decision.tier == "ultracode"


def test_escalation_budget_is_bounded():
    decision = decide(tier="cheap", exit_code=1, blocked_verdict=True, escalations_used=MAX_ESCALATIONS)
    assert decision.should_respawn is False
    assert "exhausted" in decision.reason


def test_non_retryable_exit_code_does_not_respawn():
    decision = decide(tier="cheap", exit_code=2, blocked_verdict=False, escalations_used=0)
    assert decision.should_respawn is False
