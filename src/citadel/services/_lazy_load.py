"""_lazy_load.py — process-local, mtime-cached JSON loader.

Generalizes the lazy pattern from tools/workspace_intelligence_query.py so any long-lived
consumer (a daemon, an agent loop, a process that queries the same index repeatedly) reads
a JSON file from disk only when its mtime actually changes. On the hot path this turns
"re-read + re-parse N sidecars per query" into an O(1) dict lookup after the first read.

Correctness contract: identical to a fresh read when the file is unchanged; re-reads and
re-caches the moment mtime advances. Fail-soft: returns `default` on missing/corrupt files.
"""

import json
import threading
from pathlib import Path
from typing import Any

_cache: dict[str, tuple[int, Any]] = {}
_lock = threading.Lock()
_reads = 0


def lazy_json(path: str | Path, default: Any = None) -> Any:
    """Return parsed JSON for `path`, reading from disk only when its mtime changed."""
    global _reads
    p = Path(path)
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        return default
    key = str(p)
    with _lock:
        entry = _cache.get(key)
        if entry is not None and entry[0] == mtime:
            return entry[1]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    with _lock:
        _cache[key] = (mtime, data)
        _reads += 1
    return data


def invalidate(path: str | Path | None = None) -> None:
    """Drop one path (or the whole cache) — mainly for tests and explicit refresh."""
    with _lock:
        if path is None:
            _cache.clear()
        else:
            _cache.pop(str(Path(path)), None)


def _read_count() -> int:
    """Number of actual disk reads performed (for tests)."""
    return _reads
