"""scu.py — Senatus Consultum Ultimum (System 5/6): a Circuit Breaker + bounded privilege escalation.

The historical SCU granted *unrestricted* emergency power — the catastrophic-misuse weak spot. The fix keeps
the emergency but bounds it on every axis:

- **Circuit Breaker** — the SCU only trips after systemic failure (failures cross a threshold); it does not
  fire on a single error, and it half-opens after a cooldown so the system can recover on its own.
- **Auto-expiring lease** — tripping appoints a `Dictator` whose broad mask rides a **short TTL lease**; the
  reaper collects it automatically, so absolute power is temporary by construction.
- **Bulkhead** — even under the SCU, a **Tribune-sacrosanct** process is never condemned (the stop-gate and
  operator channel survive any emergency), and a **MagisterEquitum** standby is pre-named.
- **Full audit** — every declaration / condemnation / stand-down is recorded (metadata only).
"""

import time
from dataclasses import dataclass

from citadel.services.authority.empire import Dictator, appoint_dictator
from citadel.services.authority.lease import LeaseReaper
from citadel.services.authority.pomerium import Pomerium
from citadel.services.authority.tribune import SacrosanctRegistry

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"


class CircuitBreaker:
    def __init__(self, *, threshold: int = 5, cooldown_s: float = 30.0, now=time.time) -> None:
        self._threshold = max(1, threshold)
        self._cooldown = cooldown_s
        self._now = now
        self._failures = 0
        self._state = CLOSED
        self._opened_at = 0.0

    def record_success(self) -> None:
        self._failures = 0
        self._state = CLOSED

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._state = OPEN
            self._opened_at = self._now()

    def state(self, *, now: float | None = None) -> str:
        t = self._now() if now is None else now
        if self._state == OPEN and (t - self._opened_at) >= self._cooldown:
            return HALF_OPEN
        return self._state

    def is_tripped(self, *, now: float | None = None) -> bool:
        return self.state(now=now) == OPEN


@dataclass(slots=True)
class SCUEvent:
    ts: float
    event: str


class SenatusConsultumUltimum:
    def __init__(
        self,
        *,
        reaper: LeaseReaper | None = None,
        tribune: SacrosanctRegistry | None = None,
        pomerium: Pomerium | None = None,
        threshold: int = 5,
        cooldown_s: float = 30.0,
        ttl_seconds: float = 60.0,
        magister_equitum_id: str = "magister-equitum",
        bus=None,
        now=time.time,
    ) -> None:
        self.breaker = CircuitBreaker(threshold=threshold, cooldown_s=cooldown_s, now=now)
        self.reaper = reaper or LeaseReaper()
        self.tribune = tribune or SacrosanctRegistry()
        self.pomerium = pomerium or Pomerium()
        self._ttl = ttl_seconds
        self._magister = magister_equitum_id
        self._bus = bus
        self._now = now
        self._dictator: Dictator | None = None
        self._audit: list[SCUEvent] = []

    def record_failure(self) -> None:
        self.breaker.record_failure()

    def record_success(self) -> None:
        self.breaker.record_success()

    def should_declare(self, *, now: float | None = None) -> bool:
        """True when systemic failure has tripped the breaker and no dictatorship is already in force."""
        return self.breaker.is_tripped(now=now) and not self.is_active(now=now)

    def declare(self, *, now: float | None = None) -> Dictator:
        """Trip the SCU: appoint a Dictator on a short auto-expiring lease (bounded escalation)."""
        t = self._now() if now is None else now
        self._dictator = appoint_dictator(
            self.pomerium, self.reaper, ttl_seconds=self._ttl, magister_equitum_id=self._magister, now=t
        )
        self._log("declared", t)
        if self._bus is not None:
            self._bus.publish("scu", {"event": "declared", "ttl": self._ttl, "lease": self._dictator.imperium.lease_id})
        return self._dictator

    def is_active(self, *, now: float | None = None) -> bool:
        if self._dictator is None:
            return False
        return self._dictator.is_in_command(now=self._now() if now is None else now)

    def may_condemn(self, pid: int, *, now: float | None = None) -> bool:
        """Even under the SCU, a Tribune-sacrosanct PID is never condemned (bulkhead)."""
        allowed = self.tribune.may_kill(pid)
        self._log(f"condemn:{pid}:{'allow' if allowed else 'refused'}", self._now() if now is None else now)
        return allowed

    def hand_to_magister(self):
        """Continuity: the MagisterEquitum assumes the same imperium if the Dictator falls (no new grant)."""
        return self._dictator.hand_to_magister() if self._dictator is not None else None

    def restore(self, *, now: float | None = None) -> None:
        """Stand down: revoke the lease early and clear the dictatorship; the breaker resets to closed."""
        t = self._now() if now is None else now
        if self._dictator is not None:
            self.reaper.revoke(self._dictator.imperium.lease_id)
        self._dictator = None
        self.breaker.record_success()
        self._log("restored", t)
        if self._bus is not None:
            self._bus.publish("scu", {"event": "restored"})

    @property
    def audit(self) -> list[dict]:
        return [{"ts": e.ts, "event": e.event} for e in self._audit]

    def _log(self, event: str, ts: float) -> None:
        self._audit.append(SCUEvent(ts, event))
