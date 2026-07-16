"""Trust & citizenship for the Auxilia (masterplan §7.3).

An auxiliary (a non-citizen validator such as GeminiFunditor) earns standing the slow way: every rod-class
(reversible) verdict it validates with no CAPITAL raises its clean streak. Once the streak reaches the
citizenship threshold it is trusted to gate rod-class work *solo* — the second gate is dropped for reversible
acts only. Two rules never bend: axe-class (irreversible) work is ALWAYS dual-gated regardless of trust, and
a single CAPITAL verdict revokes citizenship permanently (demote-instantly; trust is expensive to earn and
cheap to lose). This generalizes the per-intent LocalConfidence knob into per-component trust counters.
"""

from citadel.services.execute.verdict import CAPITAL, PASS


class TrustLedger:
    def __init__(self, threshold: int = 10) -> None:
        self._threshold = threshold
        self._clean: dict[str, int] = {}
        self._revoked: set[str] = set()

    def record(self, component: str, status: str, *, axe: bool = False) -> None:
        """Log one verdict. A CAPITAL revokes the component forever; a clean rod-class PASS extends its streak.
        Axe-class verdicts never build trust (an auxiliary cannot earn its way out of dual-gating on the axe)."""
        if status == CAPITAL:
            self._clean[component] = 0
            self._revoked.add(component)
            return
        if status == PASS and not axe:
            self._clean[component] = self._clean.get(component, 0) + 1

    def is_citizen(self, component: str) -> bool:
        """True iff the component was never revoked and has enough clean rod-class verdicts to gate solo."""
        if component in self._revoked:
            return False
        return self._clean.get(component, 0) >= self._threshold

    def requires_dual_gate(self, component: str, *, axe: bool) -> bool:
        """Axe-class ALWAYS needs two uncorrelated gates. Rod-class needs two until the component is a citizen."""
        if axe:
            return True
        return not self.is_citizen(component)

    def clean_streak(self, component: str) -> int:
        return self._clean.get(component, 0)

    @property
    def revoked(self) -> frozenset[str]:
        return frozenset(self._revoked)
