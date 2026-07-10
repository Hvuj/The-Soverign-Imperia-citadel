"""citadel.services.cache — the resident RAM cache and its socket client.

RamCache is a byte-budgeted, thread-safe cache with a pluggable eviction policy
(default SIEVE — scan-resistant, simpler than LRU; ``lru`` also available). The cache
daemon (tools/ram_cache_daemon.py) holds hot artifacts in RAM and serves them over a
local unix socket; CacheClient is the thin client with disk fallback. This is what lets
context carry a small ``ram_ref`` pointer instead of an inlined bulk payload.
"""

from citadel.services.cache.client import CacheClient, socket_path
from citadel.services.cache.ram_cache import RamCache

__all__ = ["CacheClient", "RamCache", "socket_path"]
