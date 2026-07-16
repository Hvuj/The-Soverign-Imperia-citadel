"""answer_cache.py — a content-hash-gated answer cache (reference-plan weak-spot #1).

A semantic answer may be reused only when the files it was grounded on are UNCHANGED. Query similarity alone
is unsafe: the cited code may have moved on since the answer was written. So every cached answer stores the
`(path, file_hash)` of each chunk it cited; a hit is served only when every cited file is still `is_fresh`
(D3). This class is the storage (Redis-or-local KV of JSON); the freshness gate lives in `ask.py` next to the
oracle. Keys are a normalized hash of the question, so trivial rewordings share a cache slot.
"""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from citadel.paths import resolve_redis_url as _resolve_redis_url


def make_query_key(query: str) -> str:
    """Normalize (lowercase, collapse whitespace) then hash — so cosmetic reworderings hit the same slot."""
    norm = re.sub(r"\s+", " ", (query or "").strip().lower())
    return hashlib.blake2b(norm.encode("utf-8"), digest_size=16).hexdigest()


class AnswerCache:
    def __init__(
        self,
        *,
        path: str | Path | None = None,
        redis_url: str | None = None,
        prefer_redis: bool = True,
        namespace: str = "ans",
    ) -> None:
        self._prefix = f"{namespace}:"
        self._redis = None
        url = _resolve_redis_url(explicit=redis_url)
        if prefer_redis and url:
            try:
                import redis

                self._redis = redis.from_url(url, protocol=2)
                self._redis.ping()
            except Exception:
                self._redis = None
        self._path = Path(path) if path else Path(".citadel/state/retrieval/answer-cache.json")
        self._mem: dict[str, dict] = {}
        if self._redis is None:
            self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            self._mem = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._mem = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._mem, handle)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def get(self, key: str) -> dict | None:
        if self._redis is not None:
            blob = self._redis.get(self._prefix + key)
            if not blob:
                return None
            try:
                return json.loads(blob)
            except (ValueError, TypeError):
                return None
        return self._mem.get(key)

    def put(self, key: str, answer: str, citations: list[dict]) -> None:
        record = {"answer": answer, "citations": citations}
        if self._redis is not None:
            self._redis.set(self._prefix + key, json.dumps(record))
            return
        self._mem[key] = record
        self._save()

    def invalidate(self, key: str) -> None:
        if self._redis is not None:
            self._redis.delete(self._prefix + key)
            return
        if key in self._mem:
            del self._mem[key]
            self._save()
