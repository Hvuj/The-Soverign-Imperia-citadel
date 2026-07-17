"""W5 — the tools→ledger bridge: mined/worker outcomes fold into the shared brain ledger, and the bridge
never raises even when the store is broken or absent."""

from citadel.services._tools_bridge import import_tool
from citadel.services.brain.learning import LearningStore

_bridge = import_tool("_learning_bridge")


def _reset(store):
    _bridge._STORE = store
    _bridge._TRIED = True


def test_record_outcome_folds_into_the_ledger():
    store = LearningStore(prefer_redis=False)
    _reset(store)
    ok = _bridge.record_outcome("parse the csv", "worker#opus", success=False,
                                category="failed", summary="unterminated quote")
    assert ok is True
    assert store.recall("parse the csv")[0]["summary"] == "unterminated quote"


def test_record_outcome_swallows_a_broken_store():
    class Boom:
        def record(self, *a, **k):
            raise RuntimeError("redis down")

    _reset(Boom())
    assert _bridge.record_outcome("t", "id", success=True) is False   # never raises


def test_record_outcome_noops_without_store():
    _reset(None)
    assert _bridge.record_outcome("t", "id", success=True) is False


def test_record_outcome_ignores_empty_identity():
    _reset(LearningStore(prefer_redis=False))
    assert _bridge.record_outcome("t", "", success=True) is False
