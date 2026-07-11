"""Cloud Resource Arbitrator — the cloud-side analog of the pasted plan's Hardware Resource Arbitrator.

There is no VRAM to budget in a cloud pipeline; the real ceilings are context-token size (the KV-cache
OOM analog) and the provider request rate limit. This arbitrator guards both. The Phase-2 hardware HRA
(VRAM / KV cache / quantization / PCIe) implements the same ``arbitrate()`` contract behind the seam.
"""

import time
from dataclasses import dataclass

from citadel.services.execute.blueprint import Blueprint


@dataclass(slots=True)
class ArbitrationDecision:
    admit: bool
    tier: str
    reason: str = ""
    run_spec: object | None = None


class NullArbitrator:
    """Always admits. Use when the executor arbitrates internally (e.g. the local HRA)."""

    def arbitrate(self, blueprint: Blueprint) -> ArbitrationDecision:
        return ArbitrationDecision(admit=True, tier=blueprint.assigned_tier)


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


class ResourceArbitrator:
    def __init__(self, max_calls_per_hour: int = 20) -> None:
        self._max_calls = max_calls_per_hour
        self._calls: list[float] = []

    def _prune(self, now: float) -> None:
        cutoff = now - 3600.0
        self._calls = [t for t in self._calls if t >= cutoff]

    def arbitrate(self, blueprint: Blueprint) -> ArbitrationDecision:
        context_tokens = estimate_tokens(blueprint.context) + estimate_tokens(blueprint.instruction)
        if context_tokens > blueprint.context_token_budget:
            return ArbitrationDecision(
                admit=False,
                tier=blueprint.assigned_tier,
                reason=f"context_over_budget: {context_tokens} > {blueprint.context_token_budget}",
            )
        now = time.time()
        self._prune(now)
        if len(self._calls) >= self._max_calls:
            return ArbitrationDecision(admit=False, tier=blueprint.assigned_tier, reason="rate_limited")
        self._calls.append(now)
        return ArbitrationDecision(admit=True, tier=blueprint.assigned_tier)
