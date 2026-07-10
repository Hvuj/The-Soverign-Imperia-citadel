"""Tests for tools/brain_context_builder._warm_preload_on_proven_reuse — closes the
M3-A prompt_usage_miner reuse loop: on a route-cache hit, consult the learned usage
index and warm-preload into RAM. Unit-scoped (mocks prompt_usage_miner/_publish_to_ram)
since a full build() end-to-end test needs unrelated brain-search/config fixtures.
"""
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import brain_context_builder as bcb  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_telemetry(tmp_path, monkeypatch):
    monkeypatch.setattr(bcb, "TELEMETRY_PATH", tmp_path / "capsule-telemetry.json")


def test_no_usage_data_leaves_capsule_unmodified(monkeypatch):
    fake_miner = type("M", (), {"lookup": staticmethod(lambda text: None)})
    monkeypatch.setattr(bcb, "prompt_usage_miner", fake_miner)

    cap = {"query": "how does X work"}
    bcb._warm_preload_on_proven_reuse(cap, "sig123", "how does X work")

    assert "learned_reuse" not in cap
    assert "ram_ref" not in cap


def test_proven_reuse_warms_ram_and_annotates(monkeypatch):
    fake_usage = {"signature": "abc123", "intent": "question", "count": 5, "unit": "core"}
    fake_miner = type("M", (), {"lookup": staticmethod(lambda text: fake_usage)})
    monkeypatch.setattr(bcb, "prompt_usage_miner", fake_miner)
    monkeypatch.setattr(bcb, "_publish_to_ram", lambda key, cap: "ram:" + key)

    cap = {"query": "how does X work"}
    bcb._warm_preload_on_proven_reuse(cap, "sig123", "how does X work")

    assert cap["learned_reuse"] == {
        "signature": "abc123", "intent": "question", "count": 5, "unit": "core",
    }
    assert cap["ram_ref"] == "ram:capsule:sig123"


def test_ram_publish_failure_still_annotates_learned_reuse(monkeypatch):
    fake_usage = {"signature": "abc123", "intent": "question", "count": 2, "unit": None}
    fake_miner = type("M", (), {"lookup": staticmethod(lambda text: fake_usage)})
    monkeypatch.setattr(bcb, "prompt_usage_miner", fake_miner)
    monkeypatch.setattr(bcb, "_publish_to_ram", lambda key, cap: None)

    cap = {"query": "how does X work"}
    bcb._warm_preload_on_proven_reuse(cap, "sig123", "how does X work")

    assert cap["learned_reuse"]["count"] == 2
    assert "ram_ref" not in cap


def test_miner_unavailable_is_a_no_op(monkeypatch):
    monkeypatch.setattr(bcb, "prompt_usage_miner", None)

    cap = {"query": "how does X work"}
    bcb._warm_preload_on_proven_reuse(cap, "sig123", "how does X work")

    assert cap == {"query": "how does X work"}


def test_lookup_exception_is_fail_soft(monkeypatch):
    def _raise(text):
        raise RuntimeError("index corrupt")
    fake_miner = type("M", (), {"lookup": staticmethod(_raise)})
    monkeypatch.setattr(bcb, "prompt_usage_miner", fake_miner)

    cap = {"query": "how does X work"}
    bcb._warm_preload_on_proven_reuse(cap, "sig123", "how does X work")

    assert cap == {"query": "how does X work"}
