"""learning_executor.py — the self-improving loop as a Decorator over any Executor (System 3 wiring).

Wraps any `Executor` so that, transparently, it **recalls before generating** (prior lessons for similar
tasks are injected into the blueprint's context) and **records after** (the pass/fail folds into the task
signature's EWMA; a failure leaves a recallable lesson). Because it's a Decorator on the `Executor` seam,
*every* executor — local Ollama, Groq, NVIDIA, Claude — learns into the one shared brain without any of
them knowing the ledger exists (Open/Closed, Dependency Inversion). The lesson extractor is injectable, so
callers can capture richer "what worked" notes when they have them.
"""

from collections.abc import Callable
from dataclasses import replace

from citadel.services.brain.learning import LearningStore
from citadel.services.consensus.identity import identity_of
from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor


def _default_lesson(result: ExecutionResult) -> tuple[str, str]:
    """Store a lesson only when there's signal: on failure keep the reason/error snippet; on success, none
    (the outcome still folds into the EWMA — we just don't clutter recall with 'it worked')."""
    if result.status == "pass":
        return "", ""
    note = (result.reason or result.output or "").strip().splitlines()
    return "failed", (note[0][:200] if note else "failed with no detail")


class LearningExecutor(Executor):
    def __init__(
        self,
        inner: Executor,
        store: LearningStore,
        *,
        lesson_of: Callable[[ExecutionResult], tuple[str, str]] = _default_lesson,
        recall_limit: int = 5,
        inject: bool = True,
    ) -> None:
        self.inner = inner
        self.store = store
        self.name = inner.name
        self._identity = identity_of(inner.name)
        _id = self._identity
        self._identity_key = f"{_id.model_id}#{_id.effort}" if _id.effort else _id.model_id
        self._lesson_of = lesson_of
        self._recall_limit = recall_limit
        self._inject = inject

    def execute(self, blueprint: Blueprint) -> ExecutionResult:
        bp = blueprint
        if self._inject:
            recalled = self.store.recall_context(blueprint.instruction, limit=self._recall_limit)
            if recalled:
                merged = f"{blueprint.context}\n\n{recalled}" if blueprint.context else recalled
                bp = replace(blueprint, context=merged)
        result = self.inner.execute(bp)
        category, summary = self._lesson_of(result)
        self.store.record(
            blueprint.instruction, self._identity_key,
            success=(result.status == "pass"), category=category, summary=summary,
        )
        return result

    def healthcheck(self) -> bool:
        return self.inner.healthcheck()
