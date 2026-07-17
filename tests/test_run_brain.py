"""W4 — the sovereign run path also learns: executors are armed with the learning loop (recall prior lessons
before generating, record the outcome after), so every everyday run feeds the one shared brain."""

from citadel.services.brain.learning import LearningStore
from citadel.services.brain.learning_executor import LearningExecutor
from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor
from citadel.services.execute.sovereign import SovereignRunner


class _Stub(Executor):
    def __init__(self, name: str, status: str = "pass", reason: str = "") -> None:
        self.name = name
        self._status = status
        self._reason = reason
        self.seen = ""

    def execute(self, blueprint: Blueprint) -> ExecutionResult:
        self.seen = blueprint.context
        return ExecutionResult(task_id=blueprint.task_id, status=self._status, reason=self._reason)


def test_arm_wraps_with_learning_loop():
    runner = SovereignRunner(ledger=LearningStore(prefer_redis=False))
    armed = runner._arm(_Stub("local"))
    assert isinstance(armed, LearningExecutor)


def test_brain_arm_false_leaves_executor_unwrapped():
    runner = SovereignRunner(brain_arm=False)
    stub = _Stub("local")
    assert runner._arm(stub) is stub          # opt-out → today's behaviour, no wrapping


def test_failure_is_recorded_then_recalled_across_models():
    store = LearningStore(prefer_redis=False)
    runner = SovereignRunner(ledger=store)
    # a local run fails → the reason is recorded as a lesson
    failing = runner._arm(_Stub("local", "fail", "boom on quotes"))
    failing.execute(Blueprint(task_id="t1", instruction="parse the csv"))
    # a later run on a similar task (a different model) recalls that lesson into its context
    capturing = _Stub("provider:groq:openai/gpt-oss-120b", "pass")
    runner._arm(capturing).execute(Blueprint(task_id="t2", instruction="parse the csv again"))
    assert "boom on quotes" in capturing.seen


def test_full_run_records_an_outcome():
    store = LearningStore(prefer_redis=False)
    runner = SovereignRunner(local=_Stub("local"), cloud=_Stub("cloud-claude"), ledger=store, search=lambda p: "")
    runner.run("write a helper function")
    assert store.success_rate("write a helper function")[1] >= 1   # the run fed the shared ledger
