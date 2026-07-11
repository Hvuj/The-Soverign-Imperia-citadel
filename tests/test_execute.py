"""Tests for the Tier-2 execution seam: executor swap, arbitration budget + rate limit."""

import pytest

from citadel.services.execute import (
    Blueprint,
    CloudClaudeExecutor,
    ExecutionResult,
    Executor,
    ResourceArbitrator,
    orchestrate,
)


class FakeExecutor(Executor):
    name = "fake"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def execute(self, blueprint: Blueprint) -> ExecutionResult:
        self.seen.append(blueprint.task_id)
        return ExecutionResult(blueprint.task_id, "pass", output="ok", tier_used=blueprint.assigned_tier)


def _bp(task_id: str, **kw) -> Blueprint:
    return Blueprint(task_id=task_id, instruction=kw.pop("instruction", "do the thing"), **kw)


def test_blueprint_rejects_bad_tier():
    with pytest.raises(ValueError):
        Blueprint(task_id="t", instruction="x", assigned_tier="gpu")


def test_fake_and_cloud_share_the_orchestration_path():
    blueprints = [_bp("t1"), _bp("t2", assigned_tier="cheap")]

    fake = FakeExecutor()
    fake_results = orchestrate(fake, [_bp("t1"), _bp("t2", assigned_tier="cheap")])
    assert [r.status for r in fake_results] == ["pass", "pass"]
    assert fake.seen == ["t1", "t2"]

    def fake_invoke(cmd, stdin):
        assert cmd[0] == "claude" and "--model" in cmd
        return 0, "  edited files  "

    cloud = CloudClaudeExecutor(invoke=fake_invoke)
    cloud_results = orchestrate(cloud, blueprints)
    assert [r.status for r in cloud_results] == ["pass", "pass"]
    assert cloud_results[0].output == "edited files"


def test_cloud_prefix_is_stable_and_first():
    seen_prompts: list[str] = []

    def capture(cmd, stdin):
        seen_prompts.append(stdin)
        return 0, "done"

    cloud = CloudClaudeExecutor(invoke=capture)
    orchestrate(cloud, [_bp("a", context="ctxA"), _bp("b", context="ctxB")])
    prefix_a = seen_prompts[0].split("\n\n", 1)[0]
    prefix_b = seen_prompts[1].split("\n\n", 1)[0]
    assert prefix_a == prefix_b


def test_cloud_nonzero_exit_is_error():
    cloud = CloudClaudeExecutor(invoke=lambda cmd, stdin: (2, "boom"))
    result = cloud.execute(_bp("t"))
    assert result.status == "error"
    assert result.reason == "exit_2"


def test_arbitrator_blocks_over_budget_context():
    arb = ResourceArbitrator()
    big = _bp("big", context="x" * 40000, context_token_budget=1000)
    fake = FakeExecutor()
    results = orchestrate(fake, [big], arbitrator=arb)
    assert results[0].status == "blocked"
    assert "context_over_budget" in results[0].reason
    assert fake.seen == []


def test_arbitrator_enforces_rate_limit():
    arb = ResourceArbitrator(max_calls_per_hour=2)
    fake = FakeExecutor()
    results = orchestrate(fake, [_bp("t1"), _bp("t2"), _bp("t3")], arbitrator=arb)
    assert [r.status for r in results] == ["pass", "pass", "blocked"]
    assert results[2].reason == "rate_limited"
