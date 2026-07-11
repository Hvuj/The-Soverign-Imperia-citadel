"""citadel.services.execute — the Tier-2 execution seam.

Cloud Claude executes today (CloudClaudeExecutor); a local Ollama/hardware executor swaps in as Phase 2
behind the same Executor ABC + ResourceArbitrator contract, with no change upstream.
"""

from citadel.services.execute.arbitrator import (
    ArbitrationDecision,
    NullArbitrator,
    ResourceArbitrator,
    estimate_tokens,
)
from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.cloud import CloudClaudeExecutor
from citadel.services.execute.executor import (
    TIER_MODEL,
    Executor,
    orchestrate,
    resilient_orchestrate,
    sovereign_run,
)
from citadel.services.execute.policy import ExecutionRoute, LocalConfidence, route
from citadel.services.execute.local import (
    HardwareResourceArbitrator,
    LlamaCppEngine,
    LocalEngine,
    LocalExecutor,
    OllamaEngine,
    RunSpec,
    get_local_engine,
)
from citadel.services.execute.sequencer import sequence
from citadel.services.execute.sovereign import SovereignRunner, classify_intent

__all__ = [
    "ArbitrationDecision",
    "Blueprint",
    "CloudClaudeExecutor",
    "ExecutionResult",
    "ExecutionRoute",
    "Executor",
    "HardwareResourceArbitrator",
    "LocalConfidence",
    "SovereignRunner",
    "classify_intent",
    "LlamaCppEngine",
    "LocalEngine",
    "LocalExecutor",
    "NullArbitrator",
    "OllamaEngine",
    "ResourceArbitrator",
    "RunSpec",
    "TIER_MODEL",
    "estimate_tokens",
    "get_local_engine",
    "orchestrate",
    "resilient_orchestrate",
    "route",
    "sequence",
    "sovereign_run",
]
