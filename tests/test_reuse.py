"""Tests for the zero-token reuse decider gating logic."""

import pytest

from citadel.services._tools_bridge import import_tool
from citadel.services.reuse import ReuseDecider, ReuseDecision, decider as decider_mod


def test_can_execute_requires_high_confidence_and_template():
    assert ReuseDecision("q", "high", True, "tmpl").can_execute is True
    assert ReuseDecision("q", "high", True, None).can_execute is False
    assert ReuseDecision("q", "medium", True, "tmpl").can_execute is False
    assert ReuseDecision("q", "none", False, None).can_execute is False


def test_decide_unknown_query_has_no_fast_path():
    decision = ReuseDecider().decide("zzqqxx11 vvbbnn22 wwee33 qqzz44 xxyy55")
    assert decision.confidence == "none"
    assert decision.can_execute is False
    assert decision.template_id is None


def test_match_template_id_and_description(monkeypatch):
    fr = import_tool("feature_replicator")
    fake_registry = {
        "intent-routing-gateway": {"description": "intent routing gateway", "status": "active"},
        "rate-transformer": {"description": "compute rate rate transformer", "status": "active"},
        "old-disabled": {"description": "intent routing gateway", "status": "disabled"},
        "_meta_version": "1.0",
    }
    monkeypatch.setattr(fr, "_load_registry", lambda: fake_registry)

    patterns = [{"id": "intent-routing-gateway"}]
    assert decider_mod._match_template("anything", patterns) == "intent-routing-gateway"

    tid = decider_mod._match_template("compute rate rate", [])
    assert tid == "rate-transformer"

    monkeypatch.setattr(fr, "_load_registry", lambda: {"old-disabled": fake_registry["old-disabled"]})
    assert decider_mod._match_template("intent routing gateway", []) is None

    monkeypatch.setattr(fr, "_load_registry", lambda: fake_registry)
    assert decider_mod._match_template("xyzzy", []) is None


def test_executor_aggregates_results():
    from citadel.services.reuse import ReplicationExecutor

    ex = ReplicationExecutor.__new__(ReplicationExecutor)

    class _FakeReplicator:
        def replicate(self, template_id, targets):
            return [{"success": True}, {"success": False}, {"success": True}]

    ex._replicator = _FakeReplicator()
    result = ex.execute("tmpl", [{}, {}, {}])
    assert result.applied == 3
    assert result.succeeded == 2
    assert result.failed == 1
    assert result.ok is False


def test_executor_ok_when_all_succeed():
    from citadel.services.reuse import ReplicationExecutor

    ex = ReplicationExecutor.__new__(ReplicationExecutor)

    class _AllGood:
        def replicate(self, template_id, targets):
            return [{"success": True}, {"success": True}]

    ex._replicator = _AllGood()
    result = ex.execute("tmpl", [{}, {}])
    assert result.ok is True
    assert result.failed == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
