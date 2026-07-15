"""Membership oracle + JIT content validation (masterplan §9.3/§9.8). Covers gate G1 (warm resolve),
G2 (zero false positive), G3 (JIT catches stale content under a branch-switch)."""

import sys
import time
from pathlib import Path

_TOOLS = str(Path(__file__).resolve().parents[1] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import citadel_oracle as co  # noqa: E402


def test_membership_zero_false_positive():
    oracle = co.MembershipOracle(["auth_login", "jwt_validate"])
    assert oracle.contains("auth_login") is True
    assert oracle.contains("does_not_exist") is False
    assert oracle.absent("does_not_exist") is True


def test_delta_adds_and_tombstones():
    oracle = co.MembershipOracle(["a"])
    oracle.add("b")
    assert oracle.contains("b") is True
    oracle.tombstone("a")
    assert oracle.contains("a") is False
    oracle.add("a")
    assert oracle.contains("a") is True


def test_zero_io_pruning_gate():
    oracle = co.MembershipOracle(["known"])
    assert oracle.absent("unknown") is True
    assert oracle.absent("known") is False


def test_content_hash_deterministic_and_change_sensitive(tmp_path):
    target = tmp_path / "mod.py"
    target.write_text("A = 1\n", encoding="utf-8")
    first = co.content_hash(target)
    assert first and co.content_hash(target) == first
    target.write_text("A = 2\n", encoding="utf-8")
    assert co.content_hash(target) != first


def test_jit_catches_stale_after_branch_switch(tmp_path):
    target = tmp_path / "mod.py"
    target.write_text("A = 1\n", encoding="utf-8")
    cached = co.content_hash(target)
    assert co.is_fresh(target, cached) is True
    target.write_text("A = 999\n", encoding="utf-8")
    assert co.is_fresh(target, cached) is False
    assert co.is_fresh(target, "") is False


def test_degree_one_caps_and_counts():
    adjacency = {"mod": [f"fn{i}" for i in range(50)]}
    view = co.degree_one(adjacency, "mod", k=10)
    assert len(view["children"]) == 10
    assert view["total_count"] == 50
    assert co.degree_one(adjacency, "absent")["total_count"] == 0


def test_load_symbol_keys(tmp_path):
    index = tmp_path / "symbol-index.json"
    index.write_text('{"foo": [1], "bar": [2]}', encoding="utf-8")
    assert set(co.load_symbol_keys(index)) == {"foo", "bar"}
    assert co.load_symbol_keys(tmp_path / "nope.json") == []


def test_g1_warm_resolve_is_fast():
    oracle = co.MembershipOracle([f"sym_{i}" for i in range(20000)])
    start = time.perf_counter()
    for i in range(0, 20000, 2):
        oracle.contains(f"sym_{i}")
    per_lookup = (time.perf_counter() - start) / 10000
    assert per_lookup < 0.001
