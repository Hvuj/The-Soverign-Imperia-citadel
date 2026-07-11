"""Local-first execution policy — the heart of The Sovereign's Ollama-first model.

Everything cheap runs FREE on the local tier (Ollama + CPU/RAM, zero tokens): questions, search, simple
functions, checks. Only genuinely complex or high-risk work goes straight to the cloud tier. A per-intent
confidence, learned from recorded outcomes, decides when the local tier has earned a first attempt — so as
the system learns, more work stays free.
"""

import json
from dataclasses import dataclass
from pathlib import Path

_LOCAL_FIRST_INTENTS = frozenset({
    "question",
    "search",
    "lookup",
    "terminal_help",
    "docstring_only",
    "validation_only",
    "docs_ingestion",
    "simple_function",
    "check",
})
_CLOUD_FIRST_INTENTS = frozenset({"architecture", "migration", "security", "cross_repo"})


@dataclass(slots=True)
class ExecutionRoute:
    tier: str
    free: bool
    reason: str


def route(
    intent: str,
    complexity: str = "low",
    high_risk: bool = False,
    local_confidence: float = 1.0,
) -> ExecutionRoute:
    """Decide the tier for a task. Local (free) unless it is high-risk, a cloud-first intent, high
    complexity, or the local tier's learned confidence for this intent has fallen too low."""
    intent = (intent or "").lower()
    if high_risk or intent in _CLOUD_FIRST_INTENTS or complexity == "high":
        return ExecutionRoute("cloud", False, f"escalate: intent={intent} complexity={complexity} risk={high_risk}")
    if local_confidence < 0.5:
        return ExecutionRoute("cloud", False, f"local confidence too low for {intent}: {local_confidence:.2f}")
    return ExecutionRoute("local", True, f"local-first: intent={intent} conf={local_confidence:.2f}")


class LocalConfidence:
    """Per-intent success rate for the local tier, learned from recorded outcomes and persisted as JSONL.

    A repeatedly-failing intent loses confidence, so `route()` escalates it; a recovering intent regains
    confidence and returns to the free local tier. This is the self-learning knob that lets Ollama take on
    more work over time.
    """

    def __init__(self, path: Path | None = None, min_attempts: int = 3) -> None:
        self._path = path
        self._min_attempts = min_attempts
        self._stats: dict[str, list[int]] = {}
        self._load()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            for raw in self._path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                rec = json.loads(raw)
                if rec.get("tier") != "local":
                    continue
                intent = rec.get("intent", "")
                passed, attempts = self._stats.get(intent, [0, 0])
                self._stats[intent] = [passed + (1 if rec.get("status") == "pass" else 0), attempts + 1]
        except (OSError, ValueError):
            pass

    def record(self, intent: str, tier: str, status: str) -> None:
        if tier == "local":
            passed, attempts = self._stats.get(intent, [0, 0])
            self._stats[intent] = [passed + (1 if status == "pass" else 0), attempts + 1]
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"intent": intent, "tier": tier, "status": status}) + "\n")

    def confidence(self, intent: str, prior: float = 1.0) -> float:
        passed, attempts = self._stats.get(intent, [0, 0])
        if attempts < self._min_attempts:
            return prior
        return passed / attempts
