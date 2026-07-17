"""citadel.services.brain — System 0, the shared brain (the central nervous system).

One Facade (`BrainAccess`) exposes the cheap-first read cascade (O(1) prune → HNSW → degree-1 graph → keyed
learnings) that every model reads through, and one event bus (`EventBus`) carries the learn/promote/decision
events that keep the subsystems decoupled (Observer / Pub-Sub, idempotent, DLQ). Storage stays hidden behind
these interfaces; both degrade to a pure-Python/in-memory path with no Redis.
"""

from citadel.services.brain.access import BrainAccess
from citadel.services.brain.bus import EventBus, event_hash
from citadel.services.brain.injection import BrainContextExecutor, attach_brain, render_capsule
from citadel.services.brain.learning import Learning, LearningStore, task_signature
from citadel.services.brain.learning_executor import LearningExecutor

__all__ = [
    "BrainAccess",
    "BrainContextExecutor",
    "EventBus",
    "Learning",
    "LearningExecutor",
    "LearningStore",
    "attach_brain",
    "event_hash",
    "render_capsule",
    "task_signature",
]
