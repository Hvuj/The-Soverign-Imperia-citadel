"""ram_cache.py — byte-budgeted, thread-safe cache with a pluggable eviction policy.

Backed by an intrusive doubly-linked list (newest at head, oldest at tail) plus a dict for O(1)
key lookup. Values are stored as ``bytes`` so the byte budget is exact. A single ``threading.Lock``
guards all mutations so the cache is safe to share across the daemon's request-handler threads.

Two policies:
  - ``sieve`` (default): scan-resistant and simpler than LRU. Access sets a per-node visited bit
    without reordering; eviction advances a "hand" from the tail toward the head, clearing visited
    bits and evicting the first unvisited node. Resists one-hit-wonder scans flushing hot entries.
  - ``lru``: classic — access moves the node to the head, eviction pops the tail.
"""

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CacheStats:
    entries: int
    bytes_used: int
    max_entries: int
    max_bytes: int
    hits: int
    misses: int
    evictions: int
    policy: str


class _Node:
    __slots__ = ("key", "value", "size", "visited", "newer", "older")

    def __init__(self, key: str, value: bytes, size: int) -> None:
        self.key = key
        self.value = value
        self.size = size
        self.visited = False
        self.newer: _Node | None = None
        self.older: _Node | None = None


_POLICIES = frozenset({"sieve", "lru"})


class RamCache:
    """Thread-safe cache with an entry-count cap, a byte budget, and a pluggable eviction policy."""

    def __init__(
        self,
        max_entries: int = 1024,
        max_bytes: int = 128 * 1024 * 1024,
        policy: str = "sieve",
    ) -> None:
        if max_entries <= 0 or max_bytes <= 0:
            raise ValueError("max_entries and max_bytes must be positive")
        if policy not in _POLICIES:
            raise ValueError(f"policy must be one of {sorted(_POLICIES)}")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._policy = policy
        self._nodes: dict[str, _Node] = {}
        self._head: _Node | None = None
        self._tail: _Node | None = None
        self._hand: _Node | None = None
        self._bytes = 0
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> bytes | None:
        with self._lock:
            node = self._nodes.get(key)
            if node is None:
                self._misses += 1
                return None
            self._hits += 1
            if self._policy == "sieve":
                node.visited = True
            else:
                self._move_to_head(node)
            return node.value

    def put(self, key: str, value: bytes) -> None:
        if not isinstance(value, (bytes, bytearray)):
            raise TypeError("RamCache values must be bytes")
        value = bytes(value)
        size = len(value)
        with self._lock:
            existing = self._nodes.get(key)
            if existing is not None:
                self._bytes -= existing.size
                self._unlink(existing)
                del self._nodes[key]
            if size > self._max_bytes:
                return
            node = _Node(key, value, size)
            self._nodes[key] = node
            self._link_at_head(node)
            self._bytes += size
            self._evict_locked()

    def delete(self, key: str) -> bool:
        with self._lock:
            node = self._nodes.pop(key, None)
            if node is None:
                return False
            self._bytes -= node.size
            self._unlink(node)
            return True

    def clear(self) -> None:
        with self._lock:
            self._nodes.clear()
            self._head = self._tail = self._hand = None
            self._bytes = 0

    def _link_at_head(self, node: _Node) -> None:
        node.older = self._head
        node.newer = None
        if self._head is not None:
            self._head.newer = node
        self._head = node
        if self._tail is None:
            self._tail = node

    def _unlink(self, node: _Node) -> None:
        if node is self._hand:
            self._hand = node.newer
        if node.newer is not None:
            node.newer.older = node.older
        else:
            self._head = node.older
        if node.older is not None:
            node.older.newer = node.newer
        else:
            self._tail = node.newer
        node.newer = node.older = None

    def _move_to_head(self, node: _Node) -> None:
        if node is self._head:
            return
        self._unlink(node)
        self._link_at_head(node)

    def _evict_locked(self) -> None:
        while len(self._nodes) > self._max_entries or self._bytes > self._max_bytes:
            victim = self._pick_victim()
            if victim is None:
                return
            self._bytes -= victim.size
            del self._nodes[victim.key]
            self._unlink(victim)
            self._evictions += 1

    def _pick_victim(self) -> _Node | None:
        """Next node to evict. SIEVE advances the hand from tail toward head, clearing visited bits;
        it terminates because after at most one full pass every bit is 0 and an unvisited node is hit."""
        if self._policy == "lru":
            return self._tail
        node = self._hand or self._tail
        while node is not None and node.visited:
            node.visited = False
            node = node.newer or self._tail
        if node is not None:
            self._hand = node.newer
        return node

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._nodes

    def __len__(self) -> int:
        with self._lock:
            return len(self._nodes)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                entries=len(self._nodes),
                bytes_used=self._bytes,
                max_entries=self._max_entries,
                max_bytes=self._max_bytes,
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                policy=self._policy,
            )
