"""citadel.services.consensus — the multi-model consensus engine (map-reduce-shuffle).

Run N models on the same task **in parallel** (MAP), have many models cross-validate every candidate **in
parallel** plus deterministic gates (SHUFFLE+REDUCE), then either pick the winner that clears the hard gates
or **synthesize** one correct solution from the critiques. The panel spans uncorrelated model families
(local Ollama · Groq · NVIDIA · Claude), so the dual-gate (Intercessio) is meaningful. Every member/judge is
just an `Executor`, so the same engine drives local and cloud models unchanged.
"""

from citadel.services.consensus.engine import (
    Candidate,
    ConsensusEngine,
    ConsensusResult,
    Critique,
    ModelJudge,
    family_of,
)

__all__ = [
    "Candidate",
    "ConsensusEngine",
    "ConsensusResult",
    "Critique",
    "ModelJudge",
    "family_of",
]
