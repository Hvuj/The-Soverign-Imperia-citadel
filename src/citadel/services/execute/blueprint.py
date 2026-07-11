"""Atomic Task Blueprint — the strict contract handed to a Tier-2 Executor.

Carries everything an executor needs and nothing about HOW it runs, so the same blueprint drives the
cloud Claude executor today and a local Ollama/hardware executor in Phase 2.
"""

from dataclasses import dataclass, field

VALID_TIERS = frozenset({"cheap", "standard", "strong", "ultra"})


@dataclass(slots=True)
class Blueprint:
    task_id: str
    instruction: str
    assigned_tier: str = "standard"
    context: str = ""
    context_token_budget: int = 8000
    injection_anchors: list[str] = field(default_factory=list)
    allowed_files: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.assigned_tier not in VALID_TIERS:
            raise ValueError(f"assigned_tier must be one of {sorted(VALID_TIERS)}")


@dataclass(slots=True)
class ExecutionResult:
    task_id: str
    status: str
    output: str = ""
    tier_used: str = ""
    reason: str = ""
