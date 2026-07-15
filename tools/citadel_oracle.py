#!/usr/bin/env python3
"""citadel_oracle.py — layered membership oracle + JIT content validation (masterplan §9.3, §9.8/R1).

- **L0 membership** — an exact key set built from the workspace symbol index. An exact set is
  *stronger* than the doc's PHM+fingerprint: it has **zero false positives by construction** and O(1)
  lookup. CMPH/BBHash minimal-perfect-hashing is a memory optimization (2-4 bits/key vs storing keys),
  deferred until a measured memory bottleneck — same posture as the LMDB migration.
- **L1 delta** — a mutable adds/tombstones layer for symbols created/removed since the last L0 build.
- **L2 JIT validation** — content-hash a file before serving any cached node; correctness never depends
  on a watcher being alive (mtime lies across the WSL/Windows boundary, so the check is content-based).

**Zero-IO pruning:** `absent(key)` is True only when the oracle can PROVE the key does not exist, so a
disk scan is legally halted before it starts (Ius Auspiciorum / Skill::ZeroIOPruning).
"""

import hashlib
import json
from pathlib import Path


def content_hash(path: str | Path) -> str:
    """64-bit content digest of a file (xxhash when installed, else blake2b) — content-based, never mtime."""
    try:
        import xxhash
        hasher = xxhash.xxh64()
    except ImportError:
        hasher = hashlib.blake2b(digest_size=8)
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(chunk)
    except OSError:
        return ""
    return hasher.hexdigest()


def is_fresh(path: str | Path, cached_hash: str) -> bool:
    """JIT validation (D3/R1): True iff the file's current content hash matches the cached node's hash."""
    return bool(cached_hash) and content_hash(path) == cached_hash


class MembershipOracle:
    """Exact O(1) membership with a mutable delta layer. Zero false positives by construction."""

    def __init__(self, keys=()) -> None:
        self._l0 = frozenset(keys)
        self._adds: set[str] = set()
        self._tombstones: set[str] = set()

    def add(self, key: str) -> None:
        self._tombstones.discard(key)
        self._adds.add(key)

    def tombstone(self, key: str) -> None:
        self._adds.discard(key)
        self._tombstones.add(key)

    def contains(self, key: str) -> bool:
        if key in self._tombstones:
            return False
        return key in self._adds or key in self._l0

    def absent(self, key: str) -> bool:
        """True when the oracle PROVES absence — the Zero-IO pruning gate on any disk scan."""
        return not self.contains(key)

    def stats(self) -> dict:
        return {"l0": len(self._l0), "adds": len(self._adds), "tombstones": len(self._tombstones)}


def load_symbol_keys(index_path: str | Path) -> list[str]:
    """Load symbol keys from the workspace symbol-index.json (dict keyed by symbol). Empty on any miss."""
    try:
        data = json.loads(Path(index_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list(data.keys()) if isinstance(data, dict) else []


def degree_one(adjacency: dict, node: str, k: int = 10) -> dict:
    """Degree-1 capped graph view (masterplan §9.5): direct children only, capped at k, with a
    total_count — the graph is explored one hop at a time, never dumped."""
    children = list(adjacency.get(node, []))
    return {"node": node, "children": children[:k], "total_count": len(children)}
