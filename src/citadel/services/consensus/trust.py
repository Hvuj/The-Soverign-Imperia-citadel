"""trust.py — feed the control-plane TrustLedger into the consensus engine (Phase 4).

A model family that has earned a long clean streak gets a heavier vote in the consensus reduction; a family
that was ever revoked (a CAPITAL — reward-hack / unsafe output) gets **zero** weight. This reuses the same
`TrustLedger` the control plane uses (`authority/trust.py`) — the ensemble becomes self-improving: good
families count more over time, and a betrayal drops a family out of the vote entirely.
"""

from citadel.services.authority.trust import TrustLedger
from citadel.services.consensus.engine import ConsensusResult
from citadel.services.execute.verdict import PASS


def weights_from_trust(trust: TrustLedger, families: list[str], *, threshold: int = 10) -> dict[str, float]:
    """Map each family to a consensus weight from its trust: 0 if revoked, else 0.5 + up to 0.5 by streak."""
    weights: dict[str, float] = {}
    for family in families:
        if family in trust.revoked:
            weights[family] = 0.0
        else:
            weights[family] = 0.5 + 0.5 * min(1.0, trust.clean_streak(family) / max(1, threshold))
    return weights


def record_consensus_outcome(trust: TrustLedger, result: ConsensusResult) -> None:
    """Reward the winning family (a clean rod-class verdict). CAPITAL revocation is recorded elsewhere."""
    if result.winner is not None:
        trust.record(result.winner.family, PASS, axe=False)
