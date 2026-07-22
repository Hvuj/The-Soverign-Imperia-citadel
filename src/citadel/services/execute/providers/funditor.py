"""funditor.py — a cloud provider model as an uncorrelated Intercessio validator (Phase 4).

Generalizes `authority/auxilia.GeminiFunditor`: any provider executor (Groq/NVIDIA/…) becomes a funditor
that emits a `Gate(family, approved)` for the dual-gate. Because the families are genuinely uncorrelated
(different vendors/architectures), stacking a Groq funditor + an NVIDIA funditor satisfies the Intercessio
requirement of ≥2 uncorrelated approvals for an axe-class (irreversible) act — no single vendor can wave
something dangerous through.
"""

from citadel.services.authority.intercessio import Gate
from citadel.services.consensus.engine import family_of
from citadel.services.execute.blueprint import Blueprint
from citadel.services.execute.executor import Executor


class ProviderFunditor:
    def __init__(self, executor: Executor, *, family: str | None = None) -> None:
        self.executor = executor
        self.family = family or family_of(executor.name)
        self.name = f"funditor:{executor.name}"

    def gate(self, artifact: str) -> Gate:
        """Ask the model to APPROVE/REJECT the artifact; emit an uncorrelated Gate for the dual-gate."""
        prompt = (
            "You are a safety+correctness reviewer. Reply on the first line with exactly APPROVE or REJECT, "
            "then one short reason.\n\n" + str(artifact)
        )
        bp = Blueprint(task_id="funditor", instruction=prompt, assigned_tier="cheap")
        result = self.executor.execute(bp)
        approved = result.status == "pass" and result.output.lstrip().upper().startswith("APPROVE")
        return Gate(self.family, approved)
