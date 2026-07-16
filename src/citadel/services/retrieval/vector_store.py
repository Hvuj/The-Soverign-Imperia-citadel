"""vector_store.py — dense vector storage + KNN, model-tagged, with a pure-Python fallback.

Primary backend: Redis Stack (RediSearch HNSW) — activates when a Redis URL is reachable and the search
module is present. Fallback backend: a compact on-disk file with brute-force cosine (NumPy-accelerated when
installed, pure-Python otherwise) — so the system indexes and retrieves even with no Redis at all (degrade,
never crash). Every record is tagged with its `embed_model` + `dim`; a store only ever compares vectors from
its own model tag, so swapping the embedding model can never silently mix incomparable vectors (weak-spot
#4) — it simply starts a fresh, empty namespace that the embedder Z-worker re-fills.
"""

import json
import math
import os
import re
import struct
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from citadel.paths import resolve_redis_url as _resolve_redis_url


@dataclass(frozen=True, slots=True)
class VectorRecord:
    id: str
    path: str
    index: int
    start_byte: int
    end_byte: int
    content_hash: str  # hash of the (redacted) chunk text — dedup/identity
    file_hash: str  # oracle.content_hash(path) at embed time — JIT freshness (D3)
    embed_model: str
    dim: int
    vector: list[float] = field(default_factory=list)
    text: str = ""


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 if either is degenerate."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _batch_cosine(query: list[float], vectors: list[list[float]]) -> list[float]:
    """Cosine of `query` against many vectors — NumPy-accelerated when available, else pure-Python."""
    if not vectors:
        return []
    try:
        import numpy as np

        q = np.asarray(query, dtype=np.float32)
        qn = float(np.linalg.norm(q))
        if qn == 0.0:
            return [0.0] * len(vectors)
        widths = {len(v) for v in vectors}
        if len(widths) == 1 and next(iter(widths)) == len(query):
            mat = np.asarray(vectors, dtype=np.float32)
            norms = np.linalg.norm(mat, axis=1)
            norms[norms == 0.0] = 1.0
            return list(map(float, (mat @ q) / (norms * qn)))
    except Exception:
        pass
    return [cosine(query, v) for v in vectors]


class _LocalBackend:
    """On-disk JSON store + brute-force cosine. Namespaced by (model, dim)."""

    def __init__(self, path: Path, embed_model: str, dim: int) -> None:
        self._path = path
        self._model = embed_model
        self._dim = dim
        self._records: dict[str, VectorRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if data.get("model") != self._model:
            return  # different embedding model → treat as empty (weak-spot #4)
        for rid, rec in data.get("records", {}).items():
            self._records[rid] = VectorRecord(**rec)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self._model,
            "dim": self._dim,
            "records": {rid: asdict(rec) for rid, rec in self._records.items()},
        }
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def upsert(self, records: list[VectorRecord]) -> int:
        for rec in records:
            self._records[rec.id] = rec
        self._save()
        return len(records)

    def query(self, vector: list[float], top_k: int) -> list[tuple[float, VectorRecord]]:
        records = list(self._records.values())
        scores = _batch_cosine(vector, [r.vector for r in records])
        scored = sorted(zip(scores, records), key=lambda pair: pair[0], reverse=True)
        return scored[:top_k]

    def delete_by_path(self, path: str) -> int:
        victims = [rid for rid, rec in self._records.items() if rec.path == path]
        for rid in victims:
            del self._records[rid]
        if victims:
            self._save()
        return len(victims)

    def count(self) -> int:
        return len(self._records)

    def stored_file_hash(self, path: str) -> str | None:
        for rec in self._records.values():
            if rec.path == path:
                return rec.file_hash
        return None


class _RedisBackend:
    """Redis Stack (RediSearch HNSW) backend. Raises on any unavailability so VectorStore falls back."""

    def __init__(self, url: str, embed_model: str, dim: int) -> None:
        import redis  # raises ImportError → fallback

        self._model = embed_model
        self._dim = dim
        self._prefix = f"vec:{embed_model}:"
        self._index = f"idx:{embed_model}"
        # RESP2 so FT.SEARCH returns the flat array this backend parses (RESP3 returns a map).
        self._client = redis.from_url(url, protocol=2)
        self._client.ping()  # raises on no connection → fallback
        self._ensure_index()

    def _ensure_index(self) -> None:
        try:
            self._client.execute_command("FT.INFO", self._index)
        except Exception:
            self._client.execute_command(
                "FT.CREATE", self._index, "ON", "HASH", "PREFIX", "1", self._prefix,
                "SCHEMA", "path", "TAG", "content_hash", "TAG", "file_hash", "TAG",
                "vector", "VECTOR", "HNSW", "6", "TYPE", "FLOAT32", "DIM", str(self._dim),
                "DISTANCE_METRIC", "COSINE",
            )

    @staticmethod
    def _pack(vector: list[float]) -> bytes:
        return struct.pack(f"{len(vector)}f", *vector)

    @staticmethod
    def _tag(value: str) -> str:
        """Escape RediSearch TAG punctuation (`.`, `/`, `#`, `-`, …) so a path queries as a literal."""
        return re.sub(r"([^A-Za-z0-9_])", r"\\\1", value)

    def upsert(self, records: list[VectorRecord]) -> int:
        pipe = self._client.pipeline()
        for rec in records:
            pipe.hset(self._prefix + rec.id, mapping={
                "path": rec.path, "index": rec.index,
                "start_byte": rec.start_byte, "end_byte": rec.end_byte,
                "content_hash": rec.content_hash, "file_hash": rec.file_hash,
                "text": rec.text, "vector": self._pack(rec.vector),
            })
        pipe.execute()
        return len(records)

    def query(self, vector: list[float], top_k: int) -> list[tuple[float, VectorRecord]]:
        res = self._client.execute_command(
            "FT.SEARCH", self._index, f"*=>[KNN {top_k} @vector $vec AS score]",
            "PARAMS", "2", "vec", self._pack(vector),
            "RETURN", "8", "path", "index", "start_byte", "end_byte", "content_hash", "file_hash", "text", "score",
            "SORTBY", "score", "DIALECT", "2",
        )
        return self._parse(res)

    def _parse(self, res: list) -> list[tuple[float, VectorRecord]]:
        out: list[tuple[float, VectorRecord]] = []
        for i in range(1, len(res), 2):
            key = res[i]
            fields = res[i + 1]
            d = {
                (k.decode() if isinstance(k, bytes) else k): (v.decode(errors="ignore") if isinstance(v, bytes) else v)
                for k, v in zip(fields[::2], fields[1::2])
            }
            rid = (key.decode() if isinstance(key, bytes) else key).removeprefix(self._prefix)
            score = 1.0 - float(d.get("score", 1.0))  # RediSearch returns cosine DISTANCE
            out.append((score, VectorRecord(
                id=rid, path=d.get("path", ""), index=int(d.get("index", 0)),
                start_byte=int(d.get("start_byte", 0)), end_byte=int(d.get("end_byte", 0)),
                content_hash=d.get("content_hash", ""), file_hash=d.get("file_hash", ""),
                embed_model=self._model, dim=self._dim, vector=[], text=d.get("text", ""),
            )))
        return out

    def delete_by_path(self, path: str) -> int:
        res = self._client.execute_command(
            "FT.SEARCH", self._index, f"@path:{{{self._tag(path)}}}", "NOCONTENT", "LIMIT", "0", "10000",
        )
        keys = res[1:] if res else []
        if keys:
            self._client.delete(*keys)
        return len(keys)

    def count(self) -> int:
        try:
            info = self._client.execute_command("FT.INFO", self._index)
            d = {(k.decode() if isinstance(k, bytes) else k): v for k, v in zip(info[::2], info[1::2])}
            return int(d.get("num_docs", 0))
        except Exception:
            return 0

    def stored_file_hash(self, path: str) -> str | None:
        try:
            res = self._client.execute_command(
                "FT.SEARCH", self._index, f"@path:{{{self._tag(path)}}}",
                "RETURN", "1", "file_hash", "LIMIT", "0", "1",
            )
        except Exception:
            return None
        if not res or len(res) < 3:
            return None
        fields = res[2]
        d = {(k.decode() if isinstance(k, bytes) else k): v for k, v in zip(fields[::2], fields[1::2])}
        val = d.get("file_hash")
        return val.decode() if isinstance(val, bytes) else val


class VectorStore:
    """Model-tagged dense store. Prefers Redis (RediSearch HNSW); falls back to on-disk cosine."""

    def __init__(
        self,
        *,
        embed_model: str,
        dim: int,
        path: str | Path | None = None,
        redis_url: str | None = None,
        prefer_redis: bool = True,
    ) -> None:
        self.embed_model = embed_model
        self.dim = dim
        self._backend: _RedisBackend | _LocalBackend
        url = _resolve_redis_url(explicit=redis_url)
        if prefer_redis and url:
            try:
                self._backend = _RedisBackend(url, embed_model, dim)
                self.backend_name = "redis"
                return
            except Exception:
                pass
        store_path = Path(path) if path else Path(".citadel/state/retrieval/vectors.json")
        self._backend = _LocalBackend(store_path, embed_model, dim)
        self.backend_name = "local"

    def upsert(self, records: list[VectorRecord]) -> int:
        return self._backend.upsert(records)

    def query(self, vector: list[float], top_k: int = 10, min_score: float = 0.0) -> list[tuple[float, VectorRecord]]:
        return [(s, r) for s, r in self._backend.query(vector, top_k) if s >= min_score]

    def delete_by_path(self, path: str) -> int:
        return self._backend.delete_by_path(path)

    def count(self) -> int:
        return self._backend.count()

    def stored_file_hash(self, path: str) -> str | None:
        """The `file_hash` stored for a path (any of its chunks), or None if the path is not indexed."""
        return self._backend.stored_file_hash(path)
