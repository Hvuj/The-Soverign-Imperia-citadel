"""registry.py — the Imperia (System 2): one Imperium governs one family of models.

The Citadel is built out of **Imperia**. Each Imperium governs a **family of models** (its **Legion** = the
model members; its **Auxilia** = the free helper tools it may call) and holds a **jurisdiction** (`Rails` —
guard scopes: what ops are allowed / denied) plus a **capability mask** (its `fasces`). Authorizing an op is
**two independent gates that both must pass** (defense in depth):

1. **Jurisdiction** — is this op inside the family's rails? (O(L) trie check)
2. **Capability** — does the caller hold a valid, unexpired, correctly-scoped **fasces token** granting the
   op's capability bit? (O(1) bitwise check; the axe is stripped inside the pomerium)

`ImperiumRegistry` is a **Registry** (family → Imperium, O(1) hash map) and routes a model to its Imperium by
`identity_of(name).family`, so every model is governed by exactly the Imperium of its family. Consistent
hashing across machines is deliberately deferred (single-node until multi-node — YAGNI).
"""

from dataclasses import dataclass, field

from citadel.services.authority.fasces import FascesToken, permitted
from citadel.services.authority.pomerium import Pomerium
from citadel.services.consensus.identity import identity_of
from citadel.services.imperium.rails import Rails, op_capability


@dataclass(slots=True)
class Imperium:
    family: str
    rails: Rails
    fasces_mask: int = 0
    legion: list[str] = field(default_factory=list)   # model member names in this family
    auxilia: list[str] = field(default_factory=list)  # free helper tools this Imperium may call
    pomerium: Pomerium | None = None

    def within_jurisdiction(self, op: str) -> tuple[bool, str]:
        return self.rails.check(op)

    def authorize(
        self,
        op: str,
        *,
        token: FascesToken | None = None,
        key: bytes | None = None,
        path: str = "",
        now: float | None = None,
    ) -> tuple[bool, str]:
        """Both gates: jurisdiction (rails) AND capability (fasces token). A mutate/axe op with no valid,
        sufficiently-scoped token is refused even if rails allow it — the capability token is required."""
        ok, reason = self.rails.check(op)
        if not ok:
            return False, reason
        required = op_capability(op)
        if required:
            if token is None:
                return False, f"'{op}' requires a fasces capability token (none presented)"
            in_domi = self.pomerium.in_domi(path) if self.pomerium is not None else False
            if not permitted(required, token, in_domi=in_domi, key=key, now=now):
                return False, f"fasces token does not grant the capability required for '{op}'"
        return True, "authorized"


class ImperiumRegistry:
    def __init__(self) -> None:
        self._by_family: dict[str, Imperium] = {}

    def register(self, imperium: Imperium) -> "ImperiumRegistry":
        self._by_family[imperium.family.lower()] = imperium
        return self

    def of_family(self, family: str) -> Imperium | None:
        return self._by_family.get((family or "").lower())

    def for_model(self, model_name: str) -> Imperium | None:
        """Route a model to its governing Imperium via its identity's family (O(1))."""
        return self.of_family(identity_of(model_name).family)

    def authorize(self, model_name: str, op: str, **kw) -> tuple[bool, str]:
        """Authorize an op for a model under its family's Imperium. Ungoverned families are default-deny."""
        imperium = self.for_model(model_name)
        if imperium is None:
            return False, f"no Imperium governs '{identity_of(model_name).family}' (ungoverned → denied)"
        return imperium.authorize(op, **kw)

    def families(self) -> list[str]:
        return sorted(self._by_family)
