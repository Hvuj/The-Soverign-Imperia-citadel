"""P0 — BrainAccess Facade: the O(1) prune short-circuit, the cited context cascade with degree-1 graph
expansion and keyed-learning recall, and graceful behaviour with a null oracle. Uses a fake retrieval so no
Ollama/network is needed."""

from citadel.services._tools_bridge import import_tool
from citadel.services.brain.access import BrainAccess, _null_degree_one, _NullOracle
from citadel.services.brain.bus import EventBus

_oracle_mod = import_tool("citadel_oracle")


class FakeRetrieval:
    def __init__(self) -> None:
        self.searched: list[str] = []

    def context(self, task: str, *, top_k: int = 8, budget_bytes: int = 24 * 1024) -> dict:
        self.searched.append(task)
        return {
            "task": task,
            "preamble": "[1 chunk]",
            "chunks": [{"path": "src/a.py", "start_byte": 0, "end_byte": 10, "snippet": "def a(): ...", "score": 0.9}],
        }

    def search(self, query: str, *, top_k: int = 8, **kw) -> dict:
        self.searched.append(query)
        return {"query": query, "count": 0, "hits": []}

    def read(self, rel_path: str, **kw) -> dict:
        return {"path": rel_path, "body": "x"}


def _brain(**kw) -> BrainAccess:
    oracle = _oracle_mod.MembershipOracle(["src/a.py:a", "src/b.py:b"])
    return BrainAccess(
        retrieval=FakeRetrieval(),
        oracle=oracle,
        degree_one=_oracle_mod.degree_one,
        adjacency={"src/a.py": ["src/b.py", "src/c.py"]},
        **kw,
    )


def test_prune_proves_absence_and_skips_the_scan():
    brain = _brain()
    assert brain.prune("does/not/exist.py:ghost") is True       # oracle proves absence → prune
    assert brain.prune("src/a.py:a") is False                    # known symbol → do not prune
    capsule = brain.context("find ghost", key="does/not/exist.py:ghost")
    assert capsule["pruned"] is True
    assert capsule["chunks"] == []
    assert brain.retrieval.searched == []                        # the scan never ran


def test_context_returns_cited_chunks_with_graph_expansion():
    brain = _brain()
    capsule = brain.context("what does a do")
    assert capsule["pruned"] is False
    assert capsule["chunks"][0]["path"] == "src/a.py"            # cited provenance
    assert capsule["neighbors"]["src/a.py"] == ["src/b.py", "src/c.py"]  # degree-1 expand


def test_context_injects_recalled_learnings():
    brain = _brain(recall=lambda task: [{"category": "bug", "summary": "watch off-by-one"}])
    capsule = brain.context("do the thing")
    assert capsule["learnings"][0]["summary"] == "watch off-by-one"


def test_emit_publishes_onto_the_bus_idempotently():
    bus = EventBus(prefer_redis=False)
    brain = _brain(bus=bus)
    a = brain.emit("brain", {"kind": "worked", "summary": "s"})
    b = brain.emit("brain", {"summary": "s", "kind": "worked"})
    assert a == b
    assert bus.depth("brain") == 1
    assert brain.content_id({"x": 1}) == brain.content_id({"x": 1})


def test_null_oracle_never_prunes():
    assert _NullOracle().absent("anything") is False
    assert _null_degree_one({"n": ["a", "b", "c"]}, "n", 2)["children"] == ["a", "b"]


def test_stats_reports_backend_and_shape():
    brain = _brain(bus=EventBus(prefer_redis=False))
    s = brain.stats()
    assert s["bus"] == "memory"
    assert s["adjacency_nodes"] == 1
    assert s["oracle"]["l0"] == 2
