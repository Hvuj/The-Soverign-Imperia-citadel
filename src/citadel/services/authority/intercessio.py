"""Intercessio — dual-gate for irreversible acts (masterplan §5.3, directive D4).

An axe-class operation requires two independent PASS verdicts from UNCORRELATED validators (different model
families): a second instance of the same family shares its blind spots, so it is not an independent gate.
"""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Gate:
    family: str
    passed: bool


def dual_gate(gates: Iterable[Gate]) -> tuple[bool, str]:
    """Approve only when >=2 PASS verdicts come from DIFFERENT families (D4). Returns (approved, reason)."""
    passing_families = {gate.family for gate in gates if gate.passed}
    if len(passing_families) >= 2:
        return True, f"approved by uncorrelated families {sorted(passing_families)}"
    if len(passing_families) == 1:
        family = next(iter(passing_families))
        return False, f"only one family passed ({family}); an uncorrelated 2nd gate is required (D4)"
    return False, "no passing gate"
