"""Universal free memoization: compute once, reuse forever until inputs change.

Any deterministic step wraps its work with ``@cached`` (or ``cached_call``). Results are
content-addressed by ``(op_id, hash(inputs))`` and served from a hot in-process ``RamCache`` backed by
an optional content-addressed disk tier. Everything is local, so every repeat is a zero-cost hit — no
API call, no tokens, no recompute. The disk tier makes hits survive across processes and restarts.
"""

import functools
import hashlib
import pickle
from collections.abc import Callable
from pathlib import Path
from typing import Any

from citadel.services.cache.ram_cache import RamCache

_HOT = RamCache(max_entries=8192, max_bytes=64 * 1024 * 1024)
_DISK_ROOT: Path | None = None
_MISS = object()


def configure(disk_root: Path | None) -> None:
    """Point the cold tier at a directory (content-addressed). None disables disk persistence."""
    global _DISK_ROOT
    _DISK_ROOT = disk_root
    if disk_root is not None:
        disk_root.mkdir(parents=True, exist_ok=True)


def _key(op_id: str, args: tuple, kwargs: dict, key_fn: Callable | None) -> str:
    material = key_fn(*args, **kwargs) if key_fn is not None else (args, sorted(kwargs.items()))
    digest = hashlib.blake2b(repr(material).encode("utf-8"), digest_size=16).hexdigest()
    return f"{op_id}:{digest}"


def _disk_path(key: str) -> Path | None:
    if _DISK_ROOT is None:
        return None
    return _DISK_ROOT / f"{key.replace(':', '__')}.pkl"


def get(key: str) -> Any:
    """Return the memoized value or the module-level ``_MISS`` sentinel."""
    hot = _HOT.get(key)
    if hot is not None:
        return pickle.loads(hot)
    path = _disk_path(key)
    if path is not None and path.exists():
        blob = path.read_bytes()
        _HOT.put(key, blob)
        return pickle.loads(blob)
    return _MISS


def put(key: str, value: Any) -> None:
    blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    _HOT.put(key, blob)
    path = _disk_path(key)
    if path is not None:
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(path)


def cached_call(op_id: str, fn: Callable, *args: Any, key_fn: Callable | None = None, **kwargs: Any) -> Any:
    key = _key(op_id, args, kwargs, key_fn)
    hit = get(key)
    if hit is not _MISS:
        return hit
    result = fn(*args, **kwargs)
    put(key, result)
    return result


def cached(op_id: str, key_fn: Callable | None = None) -> Callable:
    """Decorator: memoize a deterministic function under ``op_id``, keyed by its inputs.

    Args must be ``repr``-stable, or pass ``key_fn`` to build the key material explicitly.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return cached_call(op_id, fn, *args, key_fn=key_fn, **kwargs)
        wrapper.cache_key = lambda *a, **k: _key(op_id, a, k, key_fn)
        return wrapper
    return decorator


def stats() -> Any:
    return _HOT.stats()


def clear() -> None:
    _HOT.clear()
