"""aerarium.py — the treasury (System 5): token-bucket credit allocation across imperia.

The Aerarium is the state treasury pointer: it allocates dynamic resource blocks to the imperia. Unbounded,
it exhausts credit (the weak spot). So each imperium gets a **token bucket** — tokens refill at a steady rate
up to a capacity; an allocation succeeds only if the bucket holds the cost. This caps sustained spend while
smoothing bursts (O(1) per allocation), the same shape as the provider `BudgetGuard` but generalized to any
resource across families.
"""

import time
from dataclasses import dataclass


@dataclass(slots=True)
class Bucket:
    capacity: float
    tokens: float
    refill_per_s: float
    updated: float


class Aerarium:
    def __init__(self, *, now=time.time) -> None:
        self._now = now
        self._buckets: dict[str, Bucket] = {}

    def grant_bucket(self, imperium: str, *, capacity: float, refill_per_s: float) -> "Aerarium":
        self._buckets[imperium] = Bucket(capacity, capacity, refill_per_s, self._now())
        return self

    def _refill(self, bucket: Bucket) -> None:
        t = self._now()
        dt = max(0.0, t - bucket.updated)
        bucket.tokens = min(bucket.capacity, bucket.tokens + dt * bucket.refill_per_s)
        bucket.updated = t

    def allocate(self, imperium: str, cost: float = 1.0) -> bool:
        """Spend `cost` tokens from the imperium's bucket; False if it can't afford it (or is ungoverned)."""
        bucket = self._buckets.get(imperium)
        if bucket is None:
            return False  # no treasury line → no spend (default-deny)
        self._refill(bucket)
        if bucket.tokens >= cost:
            bucket.tokens -= cost
            return True
        return False

    def balance(self, imperium: str) -> float:
        bucket = self._buckets.get(imperium)
        if bucket is None:
            return 0.0
        self._refill(bucket)
        return bucket.tokens

    def stats(self) -> dict:
        return {name: round(self.balance(name), 3) for name in self._buckets}
