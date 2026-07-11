"""The Tier-2 Executor seam and a minimal arbitrated orchestration loop.

Everything upstream (Architect, Blueprint, Sequencer, Arbitrator) depends only on the ``Executor`` ABC,
so swapping cloud Claude for a local Ollama/hardware executor in Phase 2 changes nothing but the impl.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable

from citadel.services.execute.arbitrator import ResourceArbitrator
from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.policy import LocalConfidence, route

TIER_MODEL = {
    "cheap": "claude-haiku-4-5-20251001",
    "standard": "claude-sonnet-4-6",
    "strong": "claude-sonnet-4-6",
    "ultra": "claude-opus-4-8",
}


class Executor(ABC):
    name: str = "executor"

    @abstractmethod
    def execute(self, blueprint: Blueprint) -> ExecutionResult: ...

    def healthcheck(self) -> bool:
        return True


def orchestrate(
    executor: Executor,
    blueprints: Iterable[Blueprint],
    arbitrator: ResourceArbitrator | None = None,
) -> list[ExecutionResult]:
    """Run each blueprint through the arbitrator, then the executor. Any Executor impl works here."""
    arb = arbitrator or ResourceArbitrator()
    results: list[ExecutionResult] = []
    for bp in blueprints:
        decision = arb.arbitrate(bp)
        if not decision.admit:
            results.append(
                ExecutionResult(task_id=bp.task_id, status="blocked", reason=decision.reason)
            )
            continue
        if decision.tier != bp.assigned_tier:
            bp.assigned_tier = decision.tier
        results.append(executor.execute(bp))
    return results


def resilient_orchestrate(
    primary: Executor,
    blueprints: Iterable[Blueprint],
    *,
    alt: Executor | None = None,
    architect: Executor | None = None,
) -> list[ExecutionResult]:
    """Self-heal ladder. L1: retry the primary (its model stays resident). L2 (down-quantize / down-tier)
    is handled inside the local HRA. L3: re-route to an alternate executor. L4: escalate to a Tier-1
    architect executor (e.g. cloud). L5: human circuit-breaker (blocked / architecturally_blocked). No
    100%-success guarantee — the ladder maximizes success and stops at a human."""
    results: list[ExecutionResult] = []
    for bp in blueprints:
        result = primary.execute(bp)
        if result.status != "pass":
            result = primary.execute(bp)
        if result.status != "pass" and alt is not None:
            result = alt.execute(bp)
        if result.status != "pass" and architect is not None:
            result = architect.execute(bp)
        if result.status != "pass":
            result = ExecutionResult(task_id=bp.task_id, status="blocked", reason="architecturally_blocked")
        results.append(result)
    return results


def sovereign_run(
    blueprint: Blueprint,
    intent: str,
    *,
    local: Executor,
    cloud: Executor,
    confidence: LocalConfidence | None = None,
    complexity: str = "low",
    high_risk: bool = False,
) -> ExecutionResult:
    """Run one blueprint The Sovereign way: try the FREE local tier first when policy allows, escalate to
    the cloud tier only on failure, and feed the outcome back into the local-tier confidence so routing
    self-learns. Returns the winning ExecutionResult."""
    local_conf = confidence.confidence(intent) if confidence is not None else 1.0
    decision = route(intent, complexity=complexity, high_risk=high_risk, local_confidence=local_conf)
    if decision.tier == "local":
        result = local.execute(blueprint)
        if confidence is not None:
            confidence.record(intent, "local", result.status)
        if result.status == "pass":
            return result
    if blueprint.assigned_tier == "cheap":
        blueprint.assigned_tier = "standard"
    result = cloud.execute(blueprint)
    if confidence is not None:
        confidence.record(intent, "cloud", result.status)
    return result
