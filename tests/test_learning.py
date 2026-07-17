"""P2 — the shared LearningLedger: SimHash signature buckets similar tasks, O(1) record/recall, content-hash
dedup, EWMA success-rate, time-decay retirement, and the recall-before/record-after executor Decorator so a
recorded failure surfaces on the next similar task. In-memory (no Redis) so it runs anywhere."""

from citadel.services.brain.bus import EventBus
from citadel.services.brain.learning import LearningStore, task_signature
from citadel.services.brain.learning_executor import LearningExecutor
from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor


def _store(**kw) -> LearningStore:
    return LearningStore(prefer_redis=False, **kw)


def test_similar_tasks_share_a_signature():
    a = task_signature("fix the off by one bug in the parser loop")
    b = task_signature("fix the off-by-one bug in the parser loop!")  # punctuation only
    assert a == b
    assert task_signature("write a redis cache layer") != a           # different intent → different bucket


def test_record_then_recall_roundtrip_o1():
    s = _store()
    assert s.record("optimize the query planner", "groq:gpt-oss-120b", success=False,
                    category="bug", summary="planner OOMs on wide joins") is True
    got = s.recall("optimize the query planner")
    assert len(got) == 1 and got[0]["summary"] == "planner OOMs on wide joins"
    assert got[0]["category"] == "bug"


def test_content_hash_dedup_holds():
    s = _store()
    first = s.record("t", "id-a", success=False, summary="same lesson")
    dup = s.record("t", "id-a", success=False, summary="same lesson")   # identical → deduped
    assert first is True and dup is False
    assert len(s.recall("t")) == 1


def test_two_models_same_lesson_are_distinct_entries():
    s = _store()
    s.record("t", "groq:a", success=False, summary="watch nulls")
    s.record("t", "nvidia:b", success=False, summary="watch nulls")     # diff identity → distinct
    assert len(s.recall("t")) == 2


def test_ewma_success_rate_tracks_recent_outcomes():
    s = _store(ewma_alpha=0.5)
    for _ in range(3):
        s.record("flaky task", "id", success=False)
    rate0, n0 = s.success_rate("flaky task")
    assert rate0 == 0.0 and n0 == 3
    for _ in range(3):
        s.record("flaky task", "id", success=True)
    rate1, n1 = s.success_rate("flaky task")
    assert rate1 > 0.5 and n1 == 6                                       # recent passes pull the rate up


def test_time_decay_retires_stale_lessons():
    clock = {"t": 1000.0}
    s = _store(ttl_s=100.0, now=lambda: clock["t"])
    s.record("t", "id", success=False, summary="old lesson")
    clock["t"] += 1000.0                                                 # age past the TTL
    assert s.recall("t") == []                                          # lazily retired on read


class _StubExecutor(Executor):
    def __init__(self, name: str, status: str, reason: str = "") -> None:
        self.name = name
        self._status = status
        self._reason = reason
        self.last_context = ""

    def execute(self, blueprint: Blueprint) -> ExecutionResult:
        self.last_context = blueprint.context
        return ExecutionResult(task_id=blueprint.task_id, status=self._status, reason=self._reason)


def test_decorator_records_failure_and_recalls_it_next_run():
    s = _store()
    task = "parse the csv with embedded quotes"
    # first run fails → the failure is recorded as a lesson
    failing = LearningExecutor(_StubExecutor("provider:groq:gpt-oss-120b", "fail", "unterminated quote"), s)
    r1 = failing.execute(Blueprint(task_id="t1", instruction=task))
    assert r1.status == "fail"
    # second run (a different member) recalls that lesson into its injected context
    passing_inner = _StubExecutor("provider:nvidia:llama-3.3-70b", "pass")
    passing = LearningExecutor(passing_inner, s)
    passing.execute(Blueprint(task_id="t2", instruction=task + " today"))
    assert "unterminated quote" in passing_inner.last_context           # recalled-before-generate


def test_decorator_publishes_learn_events_on_the_bus():
    bus = EventBus(prefer_redis=False)
    s = _store(bus=bus)
    bus.subscribe("learn", "sink")
    LearningExecutor(_StubExecutor("provider:groq:x", "pass"), s).execute(Blueprint(task_id="t", instruction="do x"))
    got = bus.poll("learn", "sink", "c", block_ms=0)
    assert len(got) == 1 and got[0][1]["success"] is True
