"""pandidakterion.py — governance for the Cartographer's learned domain logic (the imperial university).

The Cartographer *learns* and the cascade keeps it current; the Pandidakterion *governs* what becomes durable
knowledge. Modeled on the chartered university (Cth. 14.9.3):

- **Charter / monopoly** — only the **faculty** (the Cartographer + its Chairs) may write learned knowledge to
  the brain; an unapproved writer is refused (`charter_admits`).
- **Chairs (faculty)** — each discipline (metric / rule / transform / policy / term) has a Chair, a specialist
  order with its own distinct validator identity, so cross-validation is genuinely *not-self*.
- **Cursus Honorum + not-self quorum** — a learned unit becomes an authoritative **Senatus Consultum** only
  after ≥N **distinct not-self** validators confirm it (the Cartographer cannot self-certify; grok≠grok).
- **JIT decay** — a unit's Consultum is demoted the moment its source changes (`is_fresh`), so durable
  knowledge is revived, never stale — the university's declines-and-revivals, made mechanical.

Composes the Republic (`build_republic`): its `cursus`, `consulta`, and the not-self `identity` rule.
"""

from dataclasses import dataclass

from citadel.services.brain.bus import event_hash
from citadel.services.consensus.identity import distinct_witnesses, identity_of
from citadel.services.senate.cursus import Proposal
from citadel.services.senate.decay import sweep

_KINDS = ("metric", "rule", "transform", "policy", "term")


@dataclass(frozen=True, slots=True)
class Chair:
    discipline: str      # the unit kind this Chair owns
    order: str           # the specialist order (agnostic agent) that staffs it
    identity: str        # its distinct validator identity (for the not-self quorum)


def default_faculty() -> dict[str, Chair]:
    """One Chair per discipline, each a distinct not-self validator identity (the agnostic specialists)."""
    return {
        "metric": Chair("metric", "dataframe-specialist", "chair:dataframe"),
        "rule": Chair("rule", "domain-logic-validator", "chair:domain-logic"),
        "transform": Chair("transform", "orchestration-specialist", "chair:orchestration"),
        "policy": Chair("policy", "semantics-reviewer", "chair:semantics"),
        "term": Chair("term", "domain-doc-curator", "chair:doc-curator"),
    }


class Pandidakterion:
    def __init__(self, republic, *, min_witnesses: int = 2, faculty: dict[str, Chair] | None = None) -> None:
        self.republic = republic
        self.faculty = faculty or default_faculty()
        self._min = max(1, min_witnesses)

    # ── charter (monopoly) ─────────────────────────────────────────────────────────────
    def charter_admits(self, writer_identity: str) -> bool:
        """Only the Cartographer or a seated Chair may write learned knowledge (state monopoly)."""
        w = (writer_identity or "").lower()
        return w.startswith("cartographer:") or w in {c.identity for c in self.faculty.values()}

    def chair_for(self, unit: dict) -> Chair:
        return self.faculty.get(unit.get("kind", "term"), self.faculty["term"])

    # ── promotion (not-self quorum → Cursus Honorum → Senatus Consultum) ────────────────
    def promote_unit(self, province: str, unit: dict, *, accepting: list[str], sources=()) -> object | None:
        """Promote a learned unit to a durable Senatus Consultum iff ≥N distinct not-self validators accept.
        Idempotent: a re-promotion of the same content returns the existing Consultum (no new version)."""
        author = f"cartographer:{province}"
        witnesses = distinct_witnesses(identity_of(author), [identity_of(a) for a in accepting])
        if len(witnesses) < self._min:
            return None

        key = f"logic:{province}:{unit['name']}"
        content = {"province": province, "unit": unit["name"], "kind": unit.get("kind", "term"),
                   "confidence": unit.get("confidence", 0), "content_hash": unit.get("content_hash", "")}
        prev = self.republic.consulta.latest(key)
        if prev is not None and prev.is_binding and prev.content_hash == event_hash(content):
            return prev

        proposal = Proposal(id=key, author=author, content=content)
        self.republic.cursus.run_to_consul(proposal, validators=accepting, accepting=accepting,
                                           sources=tuple(sources))
        return self.republic.consulta.latest(key) if proposal.is_consul else None

    # ── JIT decay ───────────────────────────────────────────────────────────────────────
    def decay_stale(self, *, is_fresh=None) -> list[str]:
        """Demote every unit Consultum whose source went stale (revival on next re-learn). Returns keys."""
        return sweep(self.republic.consulta, is_fresh=is_fresh)

    def status(self) -> dict:
        binding = self.republic.consulta.binding_keys()
        return {
            "faculty": {k: c.order for k, c in self.faculty.items()},
            "durable_units": len([k for k in binding if k.startswith("logic:")]),
            "min_witnesses": self._min,
        }
