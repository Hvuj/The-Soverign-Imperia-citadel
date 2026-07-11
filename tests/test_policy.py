"""The Sovereign local-first policy: routing by intent/complexity/risk, learned confidence, and the
local-first -> escalate -> learn run primitive."""

from citadel.services.execute import (
    Blueprint,
    ExecutionResult,
    Executor,
    LocalConfidence,
    route,
    sovereign_run,
)


class Scripted(Executor):
    def __init__(self, name, status):
        self.name = name
        self._status = status
        self.calls = 0

    def execute(self, blueprint):
        self.calls += 1
        return ExecutionResult(blueprint.task_id, self._status, reason=self.name)


def _bp():
    return Blueprint(task_id="t", instruction="do it")


def test_cheap_intents_route_local_free():
    for intent in ("question", "search", "simple_function", "check", "docstring_only"):
        r = route(intent)
        assert r.tier == "local"
        assert r.free is True


def test_complex_and_risky_route_cloud():
    assert route("architecture").tier == "cloud"
    assert route("feature_change", complexity="high").tier == "cloud"
    assert route("question", high_risk=True).tier == "cloud"


def test_low_local_confidence_escalates():
    assert route("simple_function", local_confidence=0.2).tier == "cloud"
    assert route("simple_function", local_confidence=0.9).tier == "local"


def test_confidence_learns_from_outcomes(tmp_path):
    conf = LocalConfidence(path=tmp_path / "outcomes.jsonl", min_attempts=3)
    assert conf.confidence("simple_function") == 1.0
    for _ in range(4):
        conf.record("simple_function", "local", "needs_fix")
    assert conf.confidence("simple_function") == 0.0
    assert route("simple_function", local_confidence=conf.confidence("simple_function")).tier == "cloud"


def test_confidence_persists_across_instances(tmp_path):
    path = tmp_path / "outcomes.jsonl"
    first = LocalConfidence(path=path, min_attempts=2)
    first.record("check", "local", "pass")
    first.record("check", "local", "pass")
    reloaded = LocalConfidence(path=path, min_attempts=2)
    assert reloaded.confidence("check") == 1.0


def test_sovereign_run_local_pass_never_hits_cloud():
    local = Scripted("local", "pass")
    cloud = Scripted("cloud", "pass")
    result = sovereign_run(_bp(), "question", local=local, cloud=cloud)
    assert result.reason == "local"
    assert cloud.calls == 0


def test_sovereign_run_escalates_on_local_failure_and_learns(tmp_path):
    conf = LocalConfidence(path=tmp_path / "o.jsonl", min_attempts=2)
    local = Scripted("local", "needs_fix")
    cloud = Scripted("cloud", "pass")
    r1 = sovereign_run(_bp(), "simple_function", local=local, cloud=cloud, confidence=conf)
    r2 = sovereign_run(_bp(), "simple_function", local=local, cloud=cloud, confidence=conf)
    assert r1.reason == "cloud" and r2.reason == "cloud"
    assert local.calls == 2 and cloud.calls == 2
    r3 = sovereign_run(_bp(), "simple_function", local=local, cloud=cloud, confidence=conf)
    assert r3.reason == "cloud"
    assert local.calls == 2


def test_sovereign_run_high_risk_goes_straight_to_cloud():
    local = Scripted("local", "pass")
    cloud = Scripted("cloud", "pass")
    result = sovereign_run(_bp(), "question", local=local, cloud=cloud, high_risk=True)
    assert result.reason == "cloud"
    assert local.calls == 0
