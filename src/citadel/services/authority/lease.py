"""Leases (masterplan §5.4) — no grant of authority is forever.

Every lease carries a TTL. The `LeaseReaper` holds a min-heap keyed by expiry: O(1) peek at the next lease
to die, O(log L) grant. Nothing polls — the reaper wakes exactly when the next lease expires
(`next_expiry`), and `reap()` returns everything expired or revoked so the caller can run the enforcement
ladder. A dict alongside the heap keeps `is_valid` O(1).
"""

import heapq
import itertools
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Lease:
    lease_id: str
    subject: str
    expiry: float


class LeaseReaper:
    def __init__(self) -> None:
        self._heap: list[tuple[float, int, Lease]] = []
        self._leases: dict[str, Lease] = {}
        self._revoked: set[str] = set()
        self._counter = itertools.count()

    def grant(self, lease_id: str, subject: str, ttl_seconds: float, *, now: float | None = None) -> Lease:
        current = time.time() if now is None else now
        lease = Lease(lease_id, subject, current + ttl_seconds)
        self._leases[lease_id] = lease
        self._revoked.discard(lease_id)
        heapq.heappush(self._heap, (lease.expiry, next(self._counter), lease))
        return lease

    def revoke(self, lease_id: str) -> None:
        self._revoked.add(lease_id)

    def is_valid(self, lease_id: str, *, now: float | None = None) -> bool:
        if lease_id in self._revoked:
            return False
        lease = self._leases.get(lease_id)
        if lease is None:
            return False
        return (time.time() if now is None else now) < lease.expiry

    def next_expiry(self) -> float | None:
        while self._heap and self._heap[0][2].lease_id in self._revoked:
            heapq.heappop(self._heap)
        return self._heap[0][0] if self._heap else None

    def reap(self, *, now: float | None = None) -> list[Lease]:
        """Pop and return every lease that has expired or been revoked; the caller runs the ladder on each."""
        current = time.time() if now is None else now
        dead: list[Lease] = []
        while self._heap and (self._heap[0][0] <= current or self._heap[0][2].lease_id in self._revoked):
            _, _, lease = heapq.heappop(self._heap)
            self._leases.pop(lease.lease_id, None)
            dead.append(lease)
        return dead
