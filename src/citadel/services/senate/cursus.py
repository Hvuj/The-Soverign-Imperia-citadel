"""cursus.py — the Cursus Honorum (System 5): a validation-gated promotion pipeline for knowledge.

A proposed learning/config climbs a **State Machine** of ranks, each a gate in a **Chain of Responsibility**:

    proposed → quaestor (ingest/audit) → aedile (optimize/dedup) → praetor (security/verify) → consul

Every rung requires **both**: a deterministic check for that rung AND a **not-self distinct-identity
quorum** — ≥N validators whose identities are pairwise distinct *and* ≠ the author's (the user's rule: a
model can't rubber-stamp its own promotion; grok can't validate grok, but opus-low may validate opus-med).
Reaching **consul** is authoritative → the proposal is enacted as a **Senatus Consultum** (a durable brain
node). A failed gate holds the proposal at its current rank (no regression, no self-promotion).
"""

import time
from dataclasses import dataclass, field

from citadel.services.consensus.identity import distinct_witnesses, identity_of
from citadel.services.senate.consulta import ConsultaStore

RANKS = ("proposed", "quaestor", "aedile", "praetor", "consul")
_NEXT = {RANKS[i]: RANKS[i + 1] for i in range(len(RANKS) - 1)}


@dataclass(slots=True)
class Proposal:
    id: str
    author: str                                   # identity of the model that produced the knowledge
    content: dict
    rank: str = "proposed"
    quorum: tuple[str, ...] = ()                   # distinct validator identities on the last passed rung
    log: list[tuple[str, str]] = field(default_factory=list)  # (rank, note) audit trail

    @property
    def is_consul(self) -> bool:
        return self.rank == "consul"


class CursusHonorum:
    def __init__(self, consulta: ConsultaStore, *, min_witnesses: int = 2, now=time.time) -> None:
        self.consulta = consulta
        self._min = max(1, min_witnesses)
        self._now = now

    def advance(
        self,
        proposal: Proposal,
        *,
        validators: list[str],
        accepting: list[str],
        deterministic_ok: bool,
        weight: float = 1.0,
        sources=(),
    ) -> tuple[bool, str]:
        """Attempt to promote `proposal` one rung. Requires the rung's deterministic check to pass AND a
        not-self distinct-identity quorum among the accepting validators. Returns (advanced, reason)."""
        if proposal.is_consul:
            return False, "already at consul (authoritative)"
        nxt = _NEXT.get(proposal.rank)
        if nxt is None:
            return False, f"no rung above {proposal.rank}"
        if not deterministic_ok:
            proposal.log.append((nxt, "held: deterministic check failed"))
            return False, f"deterministic check for {nxt} failed"

        # an accept only counts if it comes from the declared validator panel (when one is given)
        panel = set(validators)
        eligible = [a for a in accepting if a in panel] if panel else accepting
        author = identity_of(proposal.author)
        witnesses = distinct_witnesses(author, [identity_of(v) for v in eligible])
        if len(witnesses) < self._min:
            proposal.log.append((nxt, f"held: {len(witnesses)}/{self._min} not-self witnesses"))
            return False, f"need {self._min} distinct not-self validators, got {len(witnesses)}"

        proposal.rank = nxt
        proposal.quorum = tuple(sorted(f"{m}#{e}" if e else m for m, e in witnesses))
        proposal.log.append((nxt, f"promoted by {len(witnesses)} not-self validators"))
        if proposal.is_consul:
            self.consulta.enact(proposal.id, proposal.content, quorum=proposal.quorum, weight=weight, sources=sources)
        return True, f"promoted to {nxt}"

    def run_to_consul(
        self, proposal: Proposal, *, validators: list[str], accepting: list[str],
        deterministic_ok=lambda _rank: True, **kw,
    ) -> Proposal:
        """Convenience: drive the proposal up the ladder until a gate blocks or it reaches consul."""
        while not proposal.is_consul:
            ok, _ = self.advance(
                proposal, validators=validators, accepting=accepting,
                deterministic_ok=deterministic_ok(_NEXT.get(proposal.rank, proposal.rank)), **kw,
            )
            if not ok:
                break
        return proposal
