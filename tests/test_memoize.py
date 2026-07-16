"""Tests for the universal free memoization layer: compute-once, zero-recompute, disk persistence."""

from pathlib import Path

from citadel.services.cache import memoize
from citadel.services.cache.memoize import cached, cached_call


def _reset(disk_root: Path | None = None) -> None:
    memoize.clear()
    memoize.configure(disk_root)


def test_computed_once_then_reused():
    _reset()
    calls = {"n": 0}

    @cached("square")
    def square(x: int) -> int:
        calls["n"] += 1
        return x * x

    assert square(9) == 81
    assert square(9) == 81
    assert square(9) == 81
    assert calls["n"] == 1


def test_distinct_inputs_recompute():
    _reset()
    calls = {"n": 0}

    @cached("dbl")
    def dbl(x: int) -> int:
        calls["n"] += 1
        return x * 2

    assert dbl(2) == 4
    assert dbl(3) == 6
    assert calls["n"] == 2


def test_cached_none_is_a_hit_not_a_recompute():
    _reset()
    calls = {"n": 0}

    @cached("maybe")
    def maybe(_x: int) -> None:
        calls["n"] += 1
        return None

    assert maybe(1) is None
    assert maybe(1) is None
    assert calls["n"] == 1


def test_disk_tier_survives_hot_clear(tmp_path):
    _reset(tmp_path)
    calls = {"n": 0}

    def compute(x: int) -> dict:
        calls["n"] += 1
        return {"v": x + 1}

    assert cached_call("inc", compute, 41) == {"v": 42}
    memoize.clear()
    assert cached_call("inc", compute, 41) == {"v": 42}
    assert calls["n"] == 1
    _reset()


def test_key_fn_controls_identity():
    _reset()
    calls = {"n": 0}

    @cached("byid", key_fn=lambda obj: obj["id"])
    def load(obj: dict) -> str:
        calls["n"] += 1
        return obj["id"].upper()

    assert load({"id": "a", "extra": 1}) == "A"
    assert load({"id": "a", "extra": 999}) == "A"
    assert calls["n"] == 1
