"""access.py — BrainAccess, the single Facade onto the brain (System 0, the central nervous system).

Every subsystem reads the brain ONLY through this Facade (Dependency Inversion — nothing couples to storage
or to the retrieval internals). The read hot path is a **cheap-first cascade that short-circuits**:

    prune  O(1)  — MembershipOracle proves a key absent → no disk/index scan at all (zero false positives)
    search O(log N) — hybrid BM25 + dense HNSW retrieval over the vector store (dominant cost)
    expand O(1)  — degree-1 graph neighbours around the cited chunks, capped
    recall O(1)  — keyed learnings for the task (Redis hash; wired in P2)

Everything but the ANN step is O(1). Responses carry provenance (path + byte range) so any model — local or
cloud — can cite what it used. The write edge is thin here (`emit` onto the event bus); the full learning
CQRS write model lands in P2. Storage stays hidden behind the retrieval/oracle collaborators, so this Facade
never knows whether a hit came from Redis or from the on-disk fallback.
"""

from collections.abc import Callable
from pathlib import Path

from citadel.services.brain.bus import EventBus, event_hash


def _load_oracle(workspace: Path):
    """Build a MembershipOracle from the workspace symbol index, degrading to an empty oracle on any miss."""
    try:
        from citadel.services._tools_bridge import import_tool

        oracle_mod = import_tool("citadel_oracle")
        from citadel.paths import index_paths

        symbols = index_paths(workspace).get("symbol") if workspace else None
        keys = oracle_mod.load_symbol_keys(symbols) if symbols and Path(symbols).exists() else []
        return oracle_mod.MembershipOracle(keys), oracle_mod.degree_one
    except Exception:
        return _NullOracle(), _null_degree_one


def _load_adjacency(workspace: Path) -> dict:
    """Load the workspace graph-adjacency index for degree-1 expansion; empty dict on any miss."""
    try:
        import json

        from citadel.paths import index_paths

        path = index_paths(workspace).get("graph_adjacency")
        if path and Path(path).exists():
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


class _NullOracle:
    """A degenerate oracle used when no symbol index exists: it can never prove absence, so it never prunes."""

    def absent(self, key: str) -> bool:
        return False

    def contains(self, key: str) -> bool:
        return False

    def stats(self) -> dict:
        return {"l0": 0, "adds": 0, "tombstones": 0}


def _null_degree_one(adjacency: dict, node: str, k: int = 10) -> dict:
    children = list(adjacency.get(node, []))
    return {"node": node, "children": children[:k], "total_count": len(children)}


class BrainAccess:
    def __init__(
        self,
        *,
        retrieval,
        oracle,
        degree_one: Callable,
        adjacency: dict | None = None,
        bus: EventBus | None = None,
        recall: Callable[[str], list] | None = None,
        expand_k: int = 6,
    ) -> None:
        self.retrieval = retrieval
        self._oracle = oracle
        self._degree_one = degree_one
        self._adjacency = adjacency or {}
        self.bus = bus
        self._recall = recall
        self._expand_k = expand_k

    @classmethod
    def for_workspace(
        cls, workspace: str | Path, *, retrieval=None, bus: EventBus | None = None, recall=None, adjacency=None
    ) -> "BrainAccess":
        ws = Path(workspace).resolve()
        if retrieval is None:
            from citadel.services.retrieval.service import RetrievalService

            retrieval = RetrievalService.for_workspace(ws)
        oracle, degree_one = _load_oracle(ws)
        adjacency = adjacency if adjacency is not None else _load_adjacency(ws)
        return cls(retrieval=retrieval, oracle=oracle, degree_one=degree_one, adjacency=adjacency, bus=bus, recall=recall)

    # ── read cascade ──────────────────────────────────────────────────────────────────
    def prune(self, key: str) -> bool:
        """O(1) proof of absence — True means 'do not scan disk/index for this key' (zero false positives)."""
        return self._oracle.absent(key)

    def known(self, key: str) -> bool:
        return self._oracle.contains(key)

    def search(self, query: str, *, top_k: int = 8, **kw) -> dict:
        return self.retrieval.search(query, top_k=top_k, **kw)

    def read(self, rel_path: str, **kw) -> dict:
        return self.retrieval.read(rel_path, **kw)

    def neighbors(self, node: str, *, k: int | None = None) -> dict:
        return self._degree_one(self._adjacency, node, k or self._expand_k)

    def context(self, task: str, *, top_k: int = 8, budget_bytes: int = 24 * 1024, expand: bool = True, key: str | None = None) -> dict:
        """The cheap-first cascade → a budgeted, cited context capsule for a task.

        `key` (optional) is a specific symbol the task hinges on: if the oracle PROVES it absent, the whole
        scan is skipped (O(1)) and an empty, annotated capsule is returned — the model never pays to search
        for something that provably does not exist.
        """
        if key is not None and self.prune(key):
            return {
                "task": task,
                "preamble": f"[pruned: '{key}' proven absent — no scan]",
                "chunks": [],
                "pruned": True,
            }
        capsule = self.retrieval.context(task, top_k=top_k, budget_bytes=budget_bytes)
        capsule["pruned"] = False
        if expand and self._adjacency:
            nodes = {c["path"] for c in capsule.get("chunks", [])}
            capsule["neighbors"] = {n: self._degree_one(self._adjacency, n, self._expand_k)["children"] for n in nodes}
        if self._recall is not None:
            capsule["learnings"] = self._recall(task)
        return capsule

    # ── write edge (thin; full learning model in P2) ───────────────────────────────────
    def emit(self, topic: str, event: dict) -> str | None:
        """Publish a brain event onto the bus (idempotent by content hash). No-op when no bus is attached."""
        if self.bus is None:
            return None
        return self.bus.publish(topic, event)

    def content_id(self, event: dict) -> str:
        """Stable content address for a brain event/node (dedup + idempotency key)."""
        return event_hash(event)

    def stats(self) -> dict:
        return {
            "oracle": self._oracle.stats(),
            "adjacency_nodes": len(self._adjacency),
            "bus": self.bus.backend() if self.bus is not None else "none",
        }
