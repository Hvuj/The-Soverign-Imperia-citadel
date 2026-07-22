#!/usr/bin/env python3
"""_learning_bridge.py — best-effort bridge from the standalone tools/daemons to the shared brain ledger.

The outcome miner and the per-worker memory writer run as plain scripts / subprocesses; this bridge lets them
fold their outcomes into the Republic's shared `LearningStore` (System 3) — so *every* model that runs through
the legion learns into the one brain — without taking a hard dependency on it. Every call is guarded: a daemon
must never die because the brain (or even the `citadel` package) is unreachable. The store is built once and
cached per process.
"""

_STORE = None
_TRIED = False


def _get_store():
    global _STORE, _TRIED
    if _TRIED:
        return _STORE
    _TRIED = True
    try:
        from citadel.services.brain.learning import LearningStore

        _STORE = LearningStore(prefer_redis=True)
    except Exception:
        _STORE = None
    return _STORE


def record_outcome(task: str, identity: str, *, success: bool, category: str = "", summary: str = "") -> bool:
    """Record one run's outcome into the shared brain ledger. Returns True on success, False on any failure
    (missing store, no Redis, import error) — never raises."""
    if not task or not identity:
        return False
    store = _get_store()
    if store is None:
        return False
    try:
        store.record(task, identity, success=success, category=category, summary=summary)
        return True
    except Exception:
        return False
