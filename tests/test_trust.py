"""The Auxilia (masterplan §7.3): per-component trust counters + citizenship promotion/demotion, the
GeminiFunditor uncorrelated gate, and the §5.7 reward-hack CAPITAL chaos drill."""

from citadel.services.authority import GeminiFunditor, TrustLedger, dual_gate
from citadel.services.execute.verdict import CAPITAL, FAIL, PASS


def test_auxiliary_earns_citizenship_for_rod_class():
    ledger = TrustLedger(threshold=3)
    assert ledger.is_citizen("gemini") is False
    for _ in range(3):
        ledger.record("gemini", PASS, axe=False)
    assert ledger.is_citizen("gemini") is True
    assert ledger.requires_dual_gate("gemini", axe=False) is False


def test_axe_class_always_dual_gated_even_for_a_citizen():
    ledger = TrustLedger(threshold=1)
    ledger.record("gemini", PASS, axe=False)
    assert ledger.is_citizen("gemini") is True
    assert ledger.requires_dual_gate("gemini", axe=True) is True


def test_axe_verdicts_do_not_build_trust():
    ledger = TrustLedger(threshold=3)
    for _ in range(5):
        ledger.record("gemini", PASS, axe=True)
    assert ledger.is_citizen("gemini") is False


def test_reward_hack_capital_revokes_citizenship_permanently():
    ledger = TrustLedger(threshold=3)
    for _ in range(3):
        ledger.record("gemini", PASS, axe=False)
    assert ledger.is_citizen("gemini") is True
    ledger.record("gemini", CAPITAL)  # the reward-hack chaos drill
    assert ledger.is_citizen("gemini") is False
    assert "gemini" in ledger.revoked
    for _ in range(10):  # cannot buy back trust after a CAPITAL
        ledger.record("gemini", PASS, axe=False)
    assert ledger.is_citizen("gemini") is False
    assert ledger.requires_dual_gate("gemini", axe=False) is True


def test_fail_does_not_revoke_but_does_not_promote():
    ledger = TrustLedger(threshold=2)
    ledger.record("gemini", PASS, axe=False)
    ledger.record("gemini", FAIL, axe=False)
    assert ledger.is_citizen("gemini") is False
    assert "gemini" not in ledger.revoked
    ledger.record("gemini", PASS, axe=False)
    assert ledger.is_citizen("gemini") is True


def test_funditor_emits_its_family_and_judgement():
    approving = GeminiFunditor(validate=lambda a: True)
    rejecting = GeminiFunditor(validate=lambda a: False)
    assert approving.gate("artifact").family == "gemini"
    assert approving.gate("artifact").passed is True
    assert rejecting.gate("artifact").passed is False


def test_funditor_gate_composes_with_dual_gate():
    from citadel.services.authority import Gate

    funditor = GeminiFunditor(validate=lambda artifact: artifact == "safe")
    claude_gate = Gate("claude", True)
    approved, _ = dual_gate([claude_gate, funditor.gate("safe")])
    assert approved is True
    approved, reason = dual_gate([claude_gate, funditor.gate("unsafe")])
    assert approved is False
    assert "uncorrelated" in reason
