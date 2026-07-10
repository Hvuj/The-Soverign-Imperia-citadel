"""executor.py — apply a proven template in pure Python (zero tokens).

Thin adapter over the existing tools/feature_replicator.FeatureReplicator engine
(per-file backup, validation_cmd, auto-rollback on failure, auto-disable after 3
rollbacks). No new execution logic — the value here is a typed service seam the CLI
and decider depend on rather than reaching into the tool directly (DIP).
"""

from dataclasses import dataclass
from pathlib import Path

from citadel.paths import workspace_root
from citadel.services._tools_bridge import import_tool


@dataclass(frozen=True, slots=True)
class ReplicationResult:
    template_id: str
    applied: int
    succeeded: int
    failed: int
    per_target: list[dict]

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.applied > 0


class ReplicationExecutor:
    """Execute a registered template across N targets, in pure Python."""

    def __init__(self, workspace: str | Path | None = None) -> None:
        fr = import_tool("feature_replicator")
        self._replicator = fr.FeatureReplicator(str(workspace or workspace_root()))

    def execute(self, template_id: str, targets: list[dict]) -> ReplicationResult:
        """Apply `template_id` to each target dict; validate + roll back per target."""
        results = self._replicator.replicate(template_id, targets)
        succeeded = sum(1 for r in results if r.get("success"))
        return ReplicationResult(
            template_id=template_id,
            applied=len(results),
            succeeded=succeeded,
            failed=len(results) - succeeded,
            per_target=results,
        )
