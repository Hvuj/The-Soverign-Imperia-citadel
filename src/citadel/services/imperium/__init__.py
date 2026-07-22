"""citadel.services.imperium — the Imperia (System 2): one Imperium governs one family of models.

Each Imperium pairs a **jurisdiction** (`Rails` — allow/deny op-patterns, O(L) trie) with a **capability
mask** (fasces), governing its family's **Legion** (model members) and **Auxilia** (helper tools). The
`ImperiumRegistry` routes a model to its Imperium by family in O(1).
"""

from citadel.services.imperium.rails import Rails, op_capability
from citadel.services.imperium.registry import Imperium, ImperiumRegistry

__all__ = ["Imperium", "ImperiumRegistry", "Rails", "op_capability"]
