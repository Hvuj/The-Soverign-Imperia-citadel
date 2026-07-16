"""embed_cache.py — content-hash-keyed embedding cache (compute-once, reuse-forever).

Embedding is the one non-free step (local GPU cycles); this cache makes it happen at most once per distinct
(redacted) chunk text. Keyed by `(embed_model, content_hash)`, so a model swap never reuses an incomparable
vector. Redis-backed when a URL is reachable, on-disk JSON otherwise (degrade, never crash).
"""

import json
import os
import tempfile
from pathlib import Path

from citadel.paths import resolve_redis_url as _resolve_redis_url


class EmbedCache:
    def __init__(
        self,
        embed_model: str,
        *,
        path: str | Path | None = None,
        redis_url: str | None = None,
        prefer_redis: bool = True,
    ) -> None:
        self._model = embed_model
        self._prefix = f"emb:{embed_model}:"
        self._redis = None
        url = _resolve_redis_url(explicit=redis_url)
        if prefer_redis and url:
            try:
                import redis

                self._redis = redis.from_url(url)
                self._redis.ping()
            except Exception:
                self._redis = None
        self._path = Path(path) if path else Path(".citadel/state/retrieval/embed-cache.json")
        self._mem: dict[str, list[float]] = {}
        if self._redis is None:
            self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if data.get("model") == self._model:
            self._mem = data.get("vectors", {})

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"model": self._model, "vectors": self._mem}, handle)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def get_many(self, content_hashes: list[str]) -> dict[str, list[float]]:
        """Return cached vectors for the hashes that hit (missing keys are simply absent)."""
        if self._redis is not None:
            keys = [self._prefix + h for h in content_hashes]
            raw = self._redis.mget(keys) if keys else []
            hits: dict[str, list[float]] = {}
            for h, blob in zip(content_hashes, raw):
                if blob:
                    try:
                        hits[h] = json.loads(blob)
                    except (ValueError, TypeError):
                        pass
            return hits
        return {h: self._mem[h] for h in content_hashes if h in self._mem}

    def put_many(self, vectors: dict[str, list[float]]) -> None:
        if not vectors:
            return
        if self._redis is not None:
            pipe = self._redis.pipeline()
            for h, vec in vectors.items():
                pipe.set(self._prefix + h, json.dumps(vec))
            pipe.execute()
            return
        self._mem.update(vectors)
        self._save()
