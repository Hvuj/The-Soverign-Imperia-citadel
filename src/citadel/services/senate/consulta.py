"""consulta.py — Senatus Consulta (System 5): durable, versioned, weighted governance configs.

The Senate does **not** compile absolute laws (a brittle global rule crashes everything downstream). It
issues **Senatus Consulta** — high-weight *configs* that executors reconcile against, **appealable**
(*provocatio*) rather than fatal. Each is **content-addressed** (dedup/idempotency) and **versioned**;
**repeal is a tombstone** (a new version with status `repealed`, never a destructive delete — full audit).
Lookup by key is **O(1)**. Enact/repeal/appeal/demote are **broadcast on the event bus** (Observer), so every
subsystem learns of a config change without the Senate knowing who listens.
"""

import time
from dataclasses import dataclass, replace

from citadel.services.brain.bus import EventBus, event_hash

ACTIVE, REPEALED, DEMOTED, APPEALED = "active", "repealed", "demoted", "appealed"


@dataclass(frozen=True, slots=True)
class SenatusConsultum:
    key: str
    version: int
    content: dict
    content_hash: str
    quorum: tuple[str, ...]                 # the distinct not-self validator identities that carried it
    ts: float
    weight: float = 1.0                     # a weight, not an absolute — downstream reconciles, may appeal
    status: str = ACTIVE
    sources: tuple[tuple[str, str], ...] = ()  # (path, content_hash) refs for JIT freshness (System 5 decay)

    @property
    def is_binding(self) -> bool:
        return self.status == ACTIVE


class ConsultaStore:
    def __init__(self, *, bus: EventBus | None = None, now=time.time) -> None:
        self.bus = bus
        self._now = now
        self._latest: dict[str, SenatusConsultum] = {}
        self._history: dict[str, list[SenatusConsultum]] = {}

    def enact(self, key: str, content: dict, *, quorum=(), weight: float = 1.0, sources=()) -> SenatusConsultum:
        prev = self._latest.get(key)
        version = (prev.version + 1) if prev else 1
        consultum = SenatusConsultum(
            key=key, version=version, content=dict(content), content_hash=event_hash(content),
            quorum=tuple(quorum), ts=self._now(), weight=weight, status=ACTIVE,
            sources=tuple(tuple(s) for s in sources),
        )
        self._commit(consultum, "enacted")
        return consultum

    def _commit(self, consultum: SenatusConsultum, event: str) -> None:
        self._latest[consultum.key] = consultum
        self._history.setdefault(consultum.key, []).append(consultum)
        if self.bus is not None:
            self.bus.publish("consulta", {
                "event": event, "key": consultum.key, "version": consultum.version,
                "status": consultum.status, "content_hash": consultum.content_hash,
            })

    def _transition(self, key: str, status: str, event: str) -> SenatusConsultum | None:
        prev = self._latest.get(key)
        if prev is None or prev.status == status:
            return prev
        moved = replace(prev, version=prev.version + 1, status=status, ts=self._now())
        self._commit(moved, event)
        return moved

    def repeal(self, key: str) -> SenatusConsultum | None:
        """Tombstone the config (a new repealed version; history is preserved)."""
        return self._transition(key, REPEALED, "repealed")

    def appeal(self, key: str) -> SenatusConsultum | None:
        """Provocatio: mark the config appealed → reconciled/suspended, not crashed."""
        return self._transition(key, APPEALED, "appealed")

    def demote(self, key: str) -> SenatusConsultum | None:
        """JIT decay: a config whose sources went stale is demoted (System 5 freshness)."""
        return self._transition(key, DEMOTED, "demoted")

    def latest(self, key: str) -> SenatusConsultum | None:
        return self._latest.get(key)

    def is_binding(self, key: str) -> bool:
        c = self._latest.get(key)
        return bool(c and c.status == ACTIVE)

    def history(self, key: str) -> list[SenatusConsultum]:
        return list(self._history.get(key, ()))

    def binding_keys(self) -> list[str]:
        return sorted(k for k, c in self._latest.items() if c.status == ACTIVE)
