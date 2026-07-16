"""forge.py — decompose a goal into atomic tasks, each routed to a tier + effort (Phase Z5).

The Sovereign's doctrine: the smartest model plans, then splits the work into tasks so small a tiny local
model is 100% correct — so most tasks route to the free local tier. `TaskForge` takes an injectable `plan_fn`
(the real one calls the planner model; the default is a cheap deterministic splitter) and routes each atomic
task through the existing local-first `policy.route`, so tier/effort/free-ness are decided by the same rules
the rest of the system uses. Learned per-intent confidence can pull a flaky intent up to the cloud.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from citadel.services.execute.policy import LocalConfidence, route

_SPLIT = re.compile(r"(?:^\s*\d+[.)]\s+)|(?:\n\s*[-*]\s+)|(?:\.\s+)|(?:\s+(?:and then|then|and)\s+)", re.I | re.M)


def _default_split(goal: str) -> list[str]:
    """A cheap deterministic decomposition — numbered lists, bullets, sentences, 'and/then' clauses."""
    parts = [p.strip(" .\n\t-*") for p in _SPLIT.split(goal or "") if p and p.strip(" .\n\t-*")]
    return parts or ([goal.strip()] if goal and goal.strip() else [])


@dataclass(slots=True)
class AtomicTask:
    id: str
    instruction: str
    tier: str
    free: bool
    intent: str


class TaskForge:
    def __init__(
        self,
        *,
        plan_fn: Callable[[str], list[str]] | None = None,
        confidence: LocalConfidence | None = None,
        classify: Callable[[str], str] | None = None,
    ) -> None:
        self._plan = plan_fn or _default_split
        self._confidence = confidence
        self._classify = classify or (lambda _t: "simple_function")

    def forge(self, goal: str, *, items: list[str] | None = None) -> list[AtomicTask]:
        """Return the atomic tasks for a goal. `items` supplies pre-split subtasks (skip the planner)."""
        subtasks = items if items is not None else self._plan(goal)
        tasks: list[AtomicTask] = []
        for index, sub in enumerate(subtasks):
            intent = self._classify(sub)
            conf = self._confidence.confidence(intent) if self._confidence else 1.0
            decision = route(intent, complexity="low", local_confidence=conf)
            tasks.append(AtomicTask(
                id=f"t{index}", instruction=sub, tier=decision.tier, free=decision.free, intent=intent))
        return tasks
