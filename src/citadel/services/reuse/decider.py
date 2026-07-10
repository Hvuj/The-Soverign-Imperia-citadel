"""decider.py — decide whether a task can be done zero-token via replication.

Wraps the fast-path scorer (tools/reuse_fast_path.evaluate) and cross-references the
template registry (tools/feature_replicator). It routes to execution ONLY when both
hold: (a) fast-path confidence is "high", and (b) an active registry template matches
the query. Otherwise it returns the routing hints for the model to act on — the old
behaviour, unchanged. This is the gate that turns "here's a hint" into "just run it".
"""

from dataclasses import dataclass, field

from citadel.services._tools_bridge import import_tool


@dataclass(frozen=True, slots=True)
class ReuseDecision:
    query: str
    confidence: str
    fast_path_available: bool
    template_id: str | None
    files: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)

    @property
    def can_execute(self) -> bool:
        """True when the task can be replicated in pure Python (zero tokens)."""
        return self.confidence == "high" and self.template_id is not None


def _match_template(query: str, patterns: list[dict]) -> str | None:
    """Return an active template_id matching the query, or None.

    Matches a registry template when its id equals a scored pattern's id, or when the
    query tokens overlap the template description. Disabled templates are ignored.
    """
    fr = import_tool("feature_replicator")
    registry = fr._load_registry()
    active = {
        tid: t
        for tid, t in registry.items()
        if isinstance(t, dict) and t.get("status") != "disabled"
    }
    if not active:
        return None

    pattern_ids = {p.get("id", "").lower() for p in patterns}
    for tid in active:
        if tid.lower() in pattern_ids:
            return tid

    rfp = import_tool("reuse_fast_path")
    q_tokens = set(rfp.tokens(query))
    best: tuple[int, str] | None = None
    for tid, tmpl in active.items():
        desc_tokens = set(rfp.tokens(f"{tid} {tmpl.get('description', '')}"))
        overlap = len(q_tokens & desc_tokens)
        if overlap >= 2 and (best is None or overlap > best[0]):
            best = (overlap, tid)
    return best[1] if best else None


class ReuseDecider:
    """Scores a task and decides between zero-token replication and model routing."""

    def decide(self, query: str, *, limit: int = 3) -> ReuseDecision:
        rfp = import_tool("reuse_fast_path")
        result = rfp.evaluate(query, limit)
        patterns = result.get("patterns", [])
        template_id = None
        if result.get("confidence") == "high":
            template_id = _match_template(query, patterns)

        files: list[str] = []
        agents: list[str] = []
        if patterns:
            files = list(patterns[0].get("files", []))
            agents = list(patterns[0].get("agents", []))

        return ReuseDecision(
            query=query,
            confidence=result.get("confidence", "none"),
            fast_path_available=bool(result.get("fast_path_available")),
            template_id=template_id,
            files=files,
            agents=agents,
        )
