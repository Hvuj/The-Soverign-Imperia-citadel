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
    identity: str = ""  # finer not-self key (model_id[#effort]); falls back to family when empty


def _key(gate: "Gate") -> str:
    return gate.identity or gate.family


def dual_gate(gates: Iterable[Gate]) -> tuple[bool, str]:
    """Approve only when >=2 PASS verdicts come from DISTINCT, uncorrelated validators (D4).

    Distinctness keys on the gate's `identity` when set (so same-family/different-config counts as two
    independent validators — e.g. opus-4.8-low vs opus-4.8-medium), else on `family`. Two identical
    validators, or a single one, never approve — no model can wave its own axe-class act through."""
    passing = {_key(g) for g in gates if g.passed}
    if len(passing) >= 2:
        return True, f"approved by {len(passing)} uncorrelated validators {sorted(passing)}"
    if len(passing) == 1:
        return False, (f"only one validator passed ({next(iter(passing))}); "
                       "a distinct 2nd, uncorrelated validator is required (D4)")
    return False, "no passing gate"
