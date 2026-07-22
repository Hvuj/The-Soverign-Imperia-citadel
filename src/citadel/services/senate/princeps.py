"""princeps.py — the Princeps Senatus (System 5): priority speaker, but never a dictator.

The Princeps is the highest-trust identity — it **speaks first** (a max-heap by trust weight) to set the
baseline for a debate. But that is *all* it does: a decision still requires a **quorum** — a strict majority
of **distinct identities** (not-self, so one model voting twice counts once, and a lone Princeps can never
carry a motion). This is the weak-spot fix for "Princeps speaks first = single priority / SPOF": priority
without unilateral power.
"""

import heapq

from citadel.services.consensus.identity import identity_of


class Princeps:
    def __init__(self, trust: dict[str, float] | None = None, *, default_weight: float = 0.0) -> None:
        self._trust = {k.lower(): float(v) for k, v in (trust or {}).items()}
        self._default = default_weight

    def weight(self, name: str) -> float:
        n = (name or "").lower()
        if n in self._trust:
            return self._trust[n]
        return self._trust.get(identity_of(name).model_id.lower(), self._default)

    def order(self, names: list[str]) -> list[str]:
        """Speaking order: highest trust first (max-heap). Ties break by name for determinism."""
        heap = [(-self.weight(n), n) for n in names]
        heapq.heapify(heap)
        return [heapq.heappop(heap)[1] for _ in range(len(heap))]

    def speaker(self, names: list[str]) -> str | None:
        ordered = self.order(names)
        return ordered[0] if ordered else None

    def decide(self, participants: list[str], accepting: list[str]) -> tuple[bool, str]:
        """A motion carries only on a strict majority of DISTINCT participant identities — the Princeps sets
        the baseline but cannot dictate (needs ≥2 distinct participants and a real majority)."""
        distinct = {identity_of(n).self_key() for n in participants}
        yes = {identity_of(n).self_key() for n in accepting} & distinct
        need = len(distinct) // 2 + 1
        carried = len(distinct) >= 2 and len(yes) >= need
        return carried, f"{len(yes)}/{len(distinct)} distinct identities in favour (need {need})"
