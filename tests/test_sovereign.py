"""The Sovereign runner: intent classification, local-first routing, escalation to the Sonnet tier, and
the direct-to-cloud path for complex work."""

from citadel.services.execute import (
    ExecutionResult,
    Executor,
    SovereignRunner,
    classify_intent,
)


class Recorder(Executor):
    def __init__(self, name, status):
        self.name = name
        self._status = status
        self.calls = 0
        self.tiers: list = []
        self.contexts: list = []

    def execute(self, blueprint):
        self.calls += 1
        self.tiers.append(blueprint.assigned_tier)
        self.contexts.append(blueprint.context)
        return ExecutionResult(blueprint.task_id, self._status, reason=self.name)


def _runner(local, cloud, **kw):
    kw.setdefault("search", lambda _p: "")
    return SovereignRunner(local=local, cloud=cloud, **kw)


def test_classify_intent():
    assert classify_intent("What is the cache policy?") == "question"
    assert classify_intent("search for the ram cache") == "search"
    assert classify_intent("refactor the executor module") == "architecture"
    assert classify_intent("check the tests pass") == "check"
    assert classify_intent("write a helper function to parse dates") == "simple_function"


def test_runner_local_pass_stays_free():
    local = Recorder("local", "pass")
    cloud = Recorder("cloud", "pass")
    result = _runner(local, cloud).run("What is X?")
    assert result.reason == "local"
    assert cloud.calls == 0


def test_runner_escalates_to_sonnet_tier_on_local_failure():
    local = Recorder("local", "needs_fix")
    cloud = Recorder("cloud", "pass")
    result = _runner(local, cloud).run("What is X?")
    assert result.reason == "cloud"
    assert cloud.tiers == ["standard"]


def test_runner_complex_work_goes_cloud_directly():
    local = Recorder("local", "pass")
    cloud = Recorder("cloud", "pass")
    result = _runner(local, cloud).run("refactor the whole module")
    assert result.reason == "cloud"
    assert local.calls == 0


def test_runner_uses_injected_classifier():
    local = Recorder("local", "pass")
    cloud = Recorder("cloud", "pass")
    runner = _runner(local, cloud, classify=lambda _p: "architecture")
    runner.run("anything")
    assert local.calls == 0
    assert cloud.calls == 1


def test_runner_grounds_question_with_brain_search():
    local = Recorder("local", "pass")
    cloud = Recorder("cloud", "pass")
    runner = SovereignRunner(local=local, cloud=cloud, search=lambda _p: "auth.py handles login")
    runner.run("What handles login?")
    assert "auth.py handles login" in local.contexts[0]
    assert "workspace brain" in local.contexts[0]


def test_runner_does_not_ground_non_search_intents():
    local = Recorder("local", "pass")
    cloud = Recorder("cloud", "pass")
    called = {"n": 0}

    def search(_p):
        called["n"] += 1
        return "should not be used"

    runner = SovereignRunner(local=local, cloud=cloud, classify=lambda _p: "simple_function", search=search)
    runner.run("write a helper")
    assert called["n"] == 0
    assert local.contexts[0] == ""
