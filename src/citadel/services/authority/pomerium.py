"""Pomerium — filesystem boundary / zone policy (masterplan §4.8).

Inside the sacred boundary (DOMI) — protected branches, `.git/`, state dirs, and the WSL/OneDrive wall —
the axe is removed from any fasces. Outside (MILITIAE — /tmp, worktrees, sandboxes) the full token stands.
Zone lookup is a longest-prefix path walk: O(depth), bounded, never O(corpus). Unknown paths default to
DOMI (fail-safe: protect what you cannot classify).
"""

from dataclasses import dataclass, field

DOMI = "domi"
MILITIAE = "militiae"


def _norm(path: object) -> str:
    return str(path).replace("\\", "/")


@dataclass
class Pomerium:
    domi_prefixes: list[str] = field(default_factory=list)
    militiae_prefixes: list[str] = field(default_factory=list)
    default_zone: str = DOMI

    def zone(self, path: object) -> str:
        normalized = _norm(path)
        if "/mnt/c/" in normalized or any(seg.lower().startswith("onedrive") for seg in normalized.split("/")):
            return DOMI
        best_zone, best_len = self.default_zone, -1
        for prefix in self.domi_prefixes:
            norm_prefix = _norm(prefix)
            if normalized.startswith(norm_prefix) and len(norm_prefix) > best_len:
                best_zone, best_len = DOMI, len(norm_prefix)
        for prefix in self.militiae_prefixes:
            norm_prefix = _norm(prefix)
            if normalized.startswith(norm_prefix) and len(norm_prefix) > best_len:
                best_zone, best_len = MILITIAE, len(norm_prefix)
        return best_zone

    def in_domi(self, path: object) -> bool:
        return self.zone(path) == DOMI
