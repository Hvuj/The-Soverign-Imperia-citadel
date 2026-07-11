"""CloudClaudeExecutor — the Tier-2 executor backed by the Claude Code CLI (cloud).

The prompt is built stable-prefix-first so the provider's prompt-prefix cache stays warm across tasks
(the cheapest cloud win). ``invoke`` is injectable so the whole path is testable without the CLI.
A Phase-2 local executor implements the same ``Executor.execute`` contract behind the seam.
"""

import subprocess
from collections.abc import Callable

from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import TIER_MODEL, Executor

_STABLE_PREFIX = (
    "You are a Tier-2 executor in the Sovereign Imperia Citadel. Follow the blueprint exactly, "
    "edit only allowed files, and return the result and nothing else."
)


def _default_invoke(cmd: list[str], stdin: str) -> tuple[int, str]:
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=300)
    return proc.returncode, proc.stdout


class CloudClaudeExecutor(Executor):
    name = "cloud-claude"

    def __init__(
        self,
        invoke: Callable[[list[str], str], tuple[int, str]] | None = None,
        command: str = "claude",
    ) -> None:
        self._invoke = invoke or _default_invoke
        self._command = command

    def _build_prompt(self, blueprint: Blueprint) -> str:
        parts = [_STABLE_PREFIX]
        if blueprint.allowed_files:
            parts.append("Allowed files: " + ", ".join(blueprint.allowed_files))
        if blueprint.injection_anchors:
            parts.append("Injection anchors: " + ", ".join(blueprint.injection_anchors))
        if blueprint.context:
            parts.append("Context:\n" + blueprint.context)
        parts.append("Task:\n" + blueprint.instruction)
        return "\n\n".join(parts)

    def execute(self, blueprint: Blueprint) -> ExecutionResult:
        model = TIER_MODEL.get(blueprint.assigned_tier, TIER_MODEL["standard"])
        cmd = [self._command, "--print", "--model", model]
        try:
            code, out = self._invoke(cmd, self._build_prompt(blueprint))
        except Exception as exc:
            return ExecutionResult(blueprint.task_id, "error", tier_used=blueprint.assigned_tier, reason=str(exc))
        if code != 0:
            return ExecutionResult(
                blueprint.task_id, "error", output=out, tier_used=blueprint.assigned_tier, reason=f"exit_{code}"
            )
        return ExecutionResult(blueprint.task_id, "pass", output=out.strip(), tier_used=blueprint.assigned_tier)
