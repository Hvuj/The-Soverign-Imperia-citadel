"""citadel.services.army — the on-demand agent army (Zero-Token Sovereign, Phase Z5).

A goal is decomposed by the smartest model+effort into atomic tasks so small any local model is 100%
correct (`TaskForge`), fanned out through a Redis Streams job queue (`JobQueue`, in-memory fallback), and
executed by an on-demand `WorkerPool` where every worker runs under a fasces capability + a TTL lease from
the control plane (`services/authority/empire.py`), with concurrency bounded by the VRAM arbitrator and
expired leases reaped. Verified results reduce back. The small-model-solvable tasks cost zero cloud tokens.
"""

from citadel.services.army.forge import AtomicTask, TaskForge
from citadel.services.army.pool import WorkerOutcome, WorkerPool
from citadel.services.army.queue import JobQueue

__all__ = ["AtomicTask", "JobQueue", "TaskForge", "WorkerOutcome", "WorkerPool"]
