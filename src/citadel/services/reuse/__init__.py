"""citadel.services.reuse — close the zero-token reuse loop.

ReuseDecider scores a task against learned patterns and the template registry;
when a proven template matches with high confidence, ReplicationExecutor applies it
in pure Python via the existing feature_replicator engine — no model tokens spent.
"""

from citadel.services.reuse.decider import ReuseDecider, ReuseDecision
from citadel.services.reuse.executor import ReplicationExecutor

__all__ = ["ReplicationExecutor", "ReuseDecider", "ReuseDecision"]
