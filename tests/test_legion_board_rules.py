"""Tests for legion_board's two newly-implemented precedence rules (convention/dryness)."""

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from legion_board import LegionBoardArbiter  # noqa: E402

_PRINCIPLES = [
    "simplicity", "frugality", "structure", "dryness",
    "decoupling", "encapsulation", "convention", "craft",
]
_HIGH = dict.fromkeys(_PRINCIPLES, 1.0)


def _scorecard(**overrides) -> dict:
    scores = {**_HIGH, **overrides}
    return {"companies": scores}


def test_convention_rule_passes_when_score_ok():
    arbiter = LegionBoardArbiter()
    passed, rule, _ = arbiter.evaluate_precedence("convention", _scorecard(convention=0.8))
    assert rule == "convention_vs_explicit"
    assert passed is True


def test_convention_rule_vetoes_when_score_low():
    arbiter = LegionBoardArbiter()
    passed, rule, _ = arbiter.evaluate_precedence("convention", _scorecard(convention=0.2))
    assert rule == "convention_vs_explicit"
    assert passed is False


def test_dryness_uses_do_it_once_rule():
    arbiter = LegionBoardArbiter()
    passed, rule, msg = arbiter.evaluate_precedence("dryness", _scorecard(dryness=0.3))
    assert rule == "do_it_once_vs_novel"
    assert passed is False
    assert "consolidate" in msg.lower()


def test_new_principles_are_no_longer_all_generic_fallback():
    arbiter = LegionBoardArbiter()
    _, conv_rule, _ = arbiter.evaluate_precedence("convention", _scorecard(convention=0.1))
    _, dry_rule, _ = arbiter.evaluate_precedence("dryness", _scorecard(dryness=0.1))
    assert conv_rule != "fallback_safety_bias"
    assert dry_rule != "fallback_safety_bias"


def test_existing_rules_still_intact():
    arbiter = LegionBoardArbiter()
    passed_s, rule_s, _ = arbiter.evaluate_precedence("structure", _scorecard(simplicity=0.5))
    assert rule_s == "simplicity_vs_structure"
    assert passed_s is True
    passed_f, rule_f, _ = arbiter.evaluate_precedence("frugality", _scorecard(dryness=0.4))
    assert rule_f == "frugality_vs_dryness"
    assert passed_f is False
