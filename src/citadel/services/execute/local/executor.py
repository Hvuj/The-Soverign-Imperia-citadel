"""LocalExecutor — the Tier-2 executor for local models, behind the Phase-1 Executor seam.

Self-arbitrates via the HardwareResourceArbitrator (which auto-discovers the GPU and budgets VRAM),
then runs the selected engine. Runs identically under ``orchestrate()`` to ``CloudClaudeExecutor``.
"""

from dataclasses import replace

from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor
from citadel.services.execute.local.engine import LocalEngine, get_local_engine
from citadel.services.execute.local.hra import HardwareResourceArbitrator

_STABLE_PREFIX = (
    "You are a Tier-2 local executor in the Sovereign Imperia Citadel. Follow the blueprint exactly, "
    "edit only allowed files, and return the result and nothing else."
)


class LocalExecutor(Executor):
    name = "local"

    def __init__(
        self,
        engine: LocalEngine | None = None,
        hra: HardwareResourceArbitrator | None = None,
        model_override: str | None = None,
    ) -> None:
        self._engine = engine or get_local_engine()
        self._hra = hra or HardwareResourceArbitrator()
        self._model_override = model_override

    def healthcheck(self) -> bool:
        return self._engine.available()

    def _build_prompt(self, blueprint: Blueprint) -> str:
        parts = [_STABLE_PREFIX]
        if blueprint.context:
            parts.append("Context:\n" + blueprint.context)
        parts.append("Task:\n" + blueprint.instruction)
        return "\n\n".join(parts)

    def execute(self, blueprint: Blueprint) -> ExecutionResult:
        decision = self._hra.arbitrate(blueprint)
        if not decision.admit:
            return ExecutionResult(blueprint.task_id, "blocked", tier_used=blueprint.assigned_tier, reason=decision.reason)
        spec = decision.run_spec
        if spec is None:
            return ExecutionResult(blueprint.task_id, "error", tier_used=blueprint.assigned_tier, reason="no_run_spec")
        if self._model_override:
            spec = replace(spec, model=self._model_override)
        if not self._engine.available():
            return ExecutionResult(
                blueprint.task_id, "blocked", tier_used=blueprint.assigned_tier,
                reason=f"engine_unavailable:{self._engine.name}",
            )
        try:
            output = self._engine.generate(self._build_prompt(blueprint), spec)
        except Exception as exc:
            return ExecutionResult(blueprint.task_id, "error", tier_used=blueprint.assigned_tier, reason=str(exc))
        return ExecutionResult(blueprint.task_id, "pass", output=output.strip(), tier_used=blueprint.assigned_tier)
