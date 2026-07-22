"""republic.py — the composition root of the Republic (one wiring for every entry point).

`build_republic(ws)` assembles the shared brain substrate exactly once — a single `EventBus` that the
`LearningStore`, `BrainAccess`, and `ConsultaStore` all publish onto — so consensus, the legion run path, the
sovereign executor, and the `citadel senate` status view all read and write the *same* brain instead of each
standing up its own. This is the single seam callers depend on (Dependency Inversion); everything below it
degrades gracefully to an in-memory fallback with no Redis.
"""

from dataclasses import dataclass
from pathlib import Path

from citadel.services.brain.access import BrainAccess
from citadel.services.brain.bus import EventBus
from citadel.services.brain.learning import LearningStore
from citadel.services.imperium.rails import Rails
from citadel.services.imperium.registry import Imperium, ImperiumRegistry
from citadel.services.senate.consulta import ConsultaStore
from citadel.services.senate.cursus import CursusHonorum

# The model families that get a governing Imperium out of the box (identity_of(name).family).
_SEED_FAMILIES = ("gpt-oss", "llama", "nemotron", "qwen", "claude", "local")


def default_registry() -> ImperiumRegistry:
    """Seed one Imperium per known family with permissive read/generate rails. Jurisdiction is meaningful on
    the *execute* path (write/delete/etc.); text generation is governed only by the brain + not-self rule, so
    these rails simply admit read/generate and leave mutate ops to a capability token elsewhere."""
    registry = ImperiumRegistry()
    for family in _SEED_FAMILIES:
        registry.register(Imperium(family=family, rails=Rails(allow=["read:**", "generate:**"])))
    return registry


@dataclass(slots=True)
class Republic:
    bus: EventBus
    brain: BrainAccess
    ledger: LearningStore
    consulta: ConsultaStore
    cursus: CursusHonorum
    registry: ImperiumRegistry


def build_republic(ws: str | Path, *, prefer_redis: bool = True) -> Republic:
    """Assemble the Republic for a workspace: one bus shared by the ledger, brain, and consulta store."""
    bus = EventBus(prefer_redis=prefer_redis)
    ledger = LearningStore(bus=bus, prefer_redis=prefer_redis)
    brain = BrainAccess.for_workspace(ws, bus=bus)
    consulta = ConsultaStore(bus=bus)
    cursus = CursusHonorum(consulta, min_witnesses=2)
    return Republic(bus=bus, brain=brain, ledger=ledger, consulta=consulta, cursus=cursus, registry=default_registry())
