"""indexer.py — the Z0 coordinator: file → redacted chunks → (cached) embeddings → vector store.

One entry point (`index_file`) ties the pieces together and honours the cheap-first / JIT contract: a file
whose stored `file_hash` still matches its content is skipped (no re-embed), and embeddings for unchanged
chunk text are reused from the cache. `search` is the read side: embed the query once, KNN the store.
Freshness is content-based (D3) via `citadel_oracle` — a stale index never survives a branch switch.
"""

from dataclasses import dataclass
from pathlib import Path

from citadel.services.execute.local.engine import LocalEngine
from citadel.services.retrieval.chunker import chunk_file
from citadel.services.retrieval.embed_cache import EmbedCache
from citadel.services.retrieval.redact_gate import redact_chunks
from citadel.services.retrieval.vector_store import VectorRecord, VectorStore


def _oracle():
    try:
        from citadel.services._tools_bridge import import_tool

        return import_tool("citadel_oracle")
    except Exception:
        return None


def _file_hash(path: str | Path) -> str:
    oracle = _oracle()
    return oracle.content_hash(path) if oracle else ""


def is_stale(store: VectorStore, abs_path: str | Path, rel_path: str) -> bool:
    """True when the path is unindexed or its stored file_hash no longer matches the file (D3)."""
    stored = store.stored_file_hash(rel_path)
    if not stored:
        return True
    oracle = _oracle()
    if oracle is None:
        return True
    return not oracle.is_fresh(abs_path, stored)


@dataclass(slots=True)
class IndexResult:
    path: str
    chunks: int
    embedded: int  # chunks that needed a fresh embedding (cache misses)
    skipped_fresh: bool


def index_file(
    abs_path: str | Path,
    *,
    engine: LocalEngine,
    store: VectorStore,
    cache: EmbedCache,
    embed_model: str,
    repo_root: str | Path | None = None,
    force: bool = False,
) -> IndexResult:
    """Embed + store a file's chunks. Skips a file whose index is still fresh unless `force`."""
    chunks = redact_chunks(chunk_file(abs_path, repo_root=repo_root))
    rel = chunks[0].path if chunks else str(Path(abs_path)).replace("\\", "/")
    if not force and not is_stale(store, abs_path, rel):
        return IndexResult(rel, len(chunks), 0, skipped_fresh=True)
    if not chunks:
        store.delete_by_path(rel)
        return IndexResult(rel, 0, 0, skipped_fresh=False)

    hashes = [c.content_hash for c in chunks]
    cached = cache.get_many(hashes)
    misses = [c for c in chunks if c.content_hash not in cached]
    if misses:
        fresh = engine.embed([c.text for c in misses], embed_model)
        new_vectors = {c.content_hash: vec for c, vec in zip(misses, fresh)}
        cache.put_many(new_vectors)
        cached.update(new_vectors)

    fhash = _file_hash(abs_path)
    dim = len(next(iter(cached.values()))) if cached else store.dim
    records = [
        VectorRecord(
            id=c.id, path=c.path, index=c.index, start_byte=c.start_byte, end_byte=c.end_byte,
            content_hash=c.content_hash, file_hash=fhash, embed_model=embed_model, dim=dim,
            vector=cached.get(c.content_hash, []), text=c.text,
        )
        for c in chunks
    ]
    store.delete_by_path(rel)
    store.upsert(records)
    return IndexResult(rel, len(chunks), len(misses), skipped_fresh=False)


def search(
    query: str,
    *,
    engine: LocalEngine,
    store: VectorStore,
    embed_model: str,
    top_k: int = 8,
    min_score: float = 0.0,
) -> list[tuple[float, VectorRecord]]:
    """Embed the query once and KNN the vector store — the dense half of hybrid retrieval."""
    vecs = engine.embed([query], embed_model)
    if not vecs or not vecs[0]:
        return []
    return store.query(vecs[0], top_k=top_k, min_score=min_score)
