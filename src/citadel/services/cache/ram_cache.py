"""ram_cache.py — byte-budgeted, thread-safe LRU cache.

The in-memory structure the request asked for and the system lacked. Backed by an
``OrderedDict``: reads/writes move the key to the most-recently-used end
(``move_to_end``) and eviction pops the least-recently-used end
(``popitem(last=False)``) — both O(1). Values are stored as ``bytes`` so the byte
budget is exact. A single ``threading.Lock`` guards all mutations so the cache is
safe to share across the daemon's request-handler threads.
"""

import threading
from collections import OrderedDict
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


class RamCache:
    """Thread-safe LRU with both an entry-count cap and a byte budget."""

    def __init__(self, max_entries: int = 1024, max_bytes: int = 128 * 1024 * 1024) -> None:
        if max_entries <= 0 or max_bytes <= 0:
            raise ValueError("max_entries and max_bytes must be positive")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._store: OrderedDict[str, bytes] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> bytes | None:
        """Return the value and mark it most-recently-used, or None on miss. O(1)."""
        with self._lock:
            value = self._store.get(key)
            if value is None:
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: str, value: bytes) -> None:
        """Insert/replace `key`, evicting LRU entries until within budget. O(1) amortized.

        A single value larger than the whole byte budget is rejected silently (it can
        never fit and would evict everything) — callers fall back to disk for such blobs.
        """
        if not isinstance(value, (bytes, bytearray)):
            raise TypeError("RamCache values must be bytes")
        value = bytes(value)
        size = len(value)
        with self._lock:
            if key in self._store:
                self._bytes -= len(self._store[key])
                del self._store[key]
            if size > self._max_bytes:
                return
            self._store[key] = value
            self._bytes += size
            self._store.move_to_end(key)
            self._evict_locked()

    def delete(self, key: str) -> bool:
        with self._lock:
            value = self._store.pop(key, None)
            if value is None:
                return False
            self._bytes -= len(value)
            return True

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._bytes = 0

    def _evict_locked(self) -> None:
        while len(self._store) > self._max_entries or self._bytes > self._max_bytes:
            _key, evicted = self._store.popitem(last=False)
            self._bytes -= len(evicted)
            self._evictions += 1

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._store

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                entries=len(self._store),
                bytes_used=self._bytes,
                max_entries=self._max_entries,
                max_bytes=self._max_bytes,
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
            )
