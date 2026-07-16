"""pool.py — the on-demand worker pool (Phase Z5).

Workers pull atomic tasks from the shared queue and run them concurrently, each **under a TTL lease** granted
by the control plane (`services/authority`) and a **Legatus fasces** attenuated from the root Imperium to
reversible rods only (no axe — a worker can never do something irreversible). Concurrency is bounded (the
VRAM ceiling); a worker whose lease has expired is skipped and reaped, so no work outlives its grant. Results
are verified before they count (the house rule) and reduced back to the caller. Small-model-solvable tasks
cost zero cloud tokens.
"""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from citadel.services.authority import LeaseReaper, Pomerium, imperium_maius
from citadel.services.authority.fasces import WRITE_FILE
from citadel.services.army.queue import JobQueue


@dataclass(slots=True)
class WorkerOutcome:
    task_id: str
    worker_id: str
    tier: str
    status: str  # pass | fail | error | rejected
    output: str
    verified: bool


class WorkerPool:
    def __init__(
        self,
        queue: JobQueue,
        *,
        run_fn: Callable[[dict], tuple[str, str]],
        verify: Callable[[dict, str], bool] | None = None,
        concurrency: int = 4,
        lease_ttl: float = 30.0,
        pomerium: Pomerium | None = None,
    ) -> None:
        self.queue = queue
        self.run_fn = run_fn
        self.verify = verify
        self.concurrency = max(1, concurrency)
        self.lease_ttl = lease_ttl
        self.reaper = LeaseReaper()
        self.pomerium = pomerium or Pomerium(domi_prefixes=[], militiae_prefixes=["/"])
        self.maius = imperium_maius(self.pomerium, "army-root")
        self._outcomes: list[WorkerOutcome] = []
        self._lock = threading.Lock()

    def _worker(self, worker_id: str, now: float) -> None:
        # a worker is a Legatus: reversible rods only (attenuation drops the axe), on a TTL lease
        lease_id = f"lease-{worker_id}"
        self.reaper.grant(lease_id, worker_id, self.lease_ttl, now=now)
        legatus = self.maius.delegate(worker_id, WRITE_FILE, lease_id)
        try:
            while True:
                claimed = self.queue.claim(worker_id, block_ms=200)
                if claimed is None:
                    return
                msg_id, task = claimed
                outcome = self._run_one(worker_id, legatus, lease_id, task, now)
                self.queue.ack(msg_id)
                with self._lock:
                    self._outcomes.append(outcome)
        finally:
            self.reaper.revoke(lease_id)

    def _run_one(self, worker_id, legatus, lease_id, task, now) -> WorkerOutcome:
        tid = task.get("id", "?")
        tier = task.get("tier", "local")
        # governance: no work without a valid lease and the capability for it
        if not self.reaper.is_valid(lease_id, now=now) or not legatus.permits(WRITE_FILE, "/task"):
            return WorkerOutcome(tid, worker_id, tier, "rejected", "no valid lease/capability", False)
        try:
            status, output = self.run_fn(task)
        except Exception as exc:
            return WorkerOutcome(tid, worker_id, tier, "error", str(exc), False)
        verified = True if self.verify is None else bool(self.verify(task, output))
        final = status if verified else "fail"
        return WorkerOutcome(tid, worker_id, tier, final, output, verified)

    def run(self, *, now: float = 0.0) -> list[WorkerOutcome]:
        """Drain the queue across up to `concurrency` lease-governed workers. Returns verified outcomes."""
        self._outcomes = []
        workers = self.concurrency
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i in range(workers):
                pool.submit(self._worker, f"w{i}", now)
        return list(self._outcomes)

    def reap(self, *, now: float) -> list[str]:
        """Reap expired/revoked leases — no worker's grant outlives its TTL."""
        return [lease.lease_id for lease in self.reaper.reap(now=now)]
