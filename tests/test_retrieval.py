"""Phase Z0 — The Vector Spine. Chunk provenance, redaction-before-embed (weak-spot #5), model-tagged
vector store (weak-spot #4), content-hash embed cache, and the JIT re-embed contract (D3). Uses a
deterministic bag-of-words fake embedder so the whole suite runs with no Ollama and no Redis."""

import hashlib
import re

import pytest

from citadel.services.execute.local.engine import LocalEngine, RunSpec
from citadel.services.retrieval import (
    EmbedCache,
    VectorStore,
    chunk_text,
    cosine,
    index_file,
    is_stale,
    redact_chunks,
    search,
)

_DIM = 64


def _stable_bucket(token: str) -> int:
    return int(hashlib.blake2b(token.encode("utf-8"), digest_size=4).hexdigest(), 16) % _DIM


class FakeEmbedEngine(LocalEngine):
    """Deterministic bag-of-words embedding — cosine tracks lexical overlap, no network."""

    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, spec: RunSpec) -> str:
        return ""

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        self.calls += len(texts)
        out = []
        for text in texts:
            vec = [0.0] * _DIM
            for tok in re.findall(r"[a-z0-9]+", text.lower()):
                vec[_stable_bucket(tok)] += 1.0
            out.append(vec)
        return out


def _store(tmp_path, model="fake-embed"):
    return VectorStore(embed_model=model, dim=_DIM, path=tmp_path / "vectors.json", prefer_redis=False)


def _cache(tmp_path, model="fake-embed"):
    return EmbedCache(model, path=tmp_path / "embcache.json", prefer_redis=False)


def test_chunk_carries_byte_range_and_hash():
    text = "".join(f"line {i}\n" for i in range(150))
    chunks = chunk_text(text, "a.py", max_lines=40, overlap=8)
    assert len(chunks) > 1
    assert chunks[0].start_byte == 0
    assert chunks[-1].end_byte == len(text.encode("utf-8"))
    assert all(c.content_hash for c in chunks)
    assert chunks[0].id == "a.py#0"


def test_redaction_updates_text_and_hash():
    chunks = chunk_text("API_KEY=sk-abcdefghijklmnop1234\nsome code here\n", "s.py")
    redacted = redact_chunks(chunks)
    assert "sk-abcdefghijklmnop1234" not in redacted[0].text
    assert "[REDACTED]" in redacted[0].text
    assert redacted[0].content_hash != chunks[0].content_hash


def test_cosine_basics():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([1.0], []) == 0.0


def test_embed_store_retrieve_top1(tmp_path):
    engine, store, cache = FakeEmbedEngine(), _store(tmp_path), _cache(tmp_path)
    f = tmp_path / "code.py"
    f.write_text(
        "def alpha_widget():\n    return 1\n\n" * 3 + "\ndef zeta_gadget():\n    return 2\n" * 3,
        encoding="utf-8",
    )
    result = index_file(f, engine=engine, store=store, cache=cache, embed_model="fake-embed", repo_root=tmp_path)
    assert result.chunks >= 1 and not result.skipped_fresh
    hits = search("zeta gadget", engine=engine, store=store, embed_model="fake-embed", top_k=1)
    assert hits and "zeta_gadget" in hits[0][1].text


def test_secret_never_enters_the_store(tmp_path):
    engine, store, cache = FakeEmbedEngine(), _store(tmp_path), _cache(tmp_path)
    f = tmp_path / "conf.py"
    f.write_text("TOKEN=sk-supersecretvalue0001\nx = 1\n", encoding="utf-8")
    index_file(f, engine=engine, store=store, cache=cache, embed_model="fake-embed", repo_root=tmp_path)
    stored = (tmp_path / "vectors.json").read_text(encoding="utf-8")
    assert "sk-supersecretvalue0001" not in stored


def test_jit_reindex_on_change_and_skip_when_fresh(tmp_path):
    engine, store, cache = FakeEmbedEngine(), _store(tmp_path), _cache(tmp_path)
    f = tmp_path / "m.py"
    f.write_text("value = 1\n", encoding="utf-8")
    first = index_file(f, engine=engine, store=store, cache=cache, embed_model="fake-embed", repo_root=tmp_path)
    assert first.embedded >= 1

    # unchanged → JIT sees it fresh → skipped, no re-embed
    again = index_file(f, engine=engine, store=store, cache=cache, embed_model="fake-embed", repo_root=tmp_path)
    assert again.skipped_fresh is True and again.embedded == 0
    assert is_stale(store, f, "m.py") is False

    # change the content → stale → re-embed with the new text
    f.write_text("value = 9999\n", encoding="utf-8")
    assert is_stale(store, f, "m.py") is True
    changed = index_file(f, engine=engine, store=store, cache=cache, embed_model="fake-embed", repo_root=tmp_path)
    assert changed.skipped_fresh is False


def test_model_tag_isolates_vectors(tmp_path):
    engine, cache = FakeEmbedEngine(), _cache(tmp_path)
    store_a = _store(tmp_path, model="model-a")
    f = tmp_path / "x.py"
    f.write_text("alpha beta gamma\n", encoding="utf-8")
    index_file(f, engine=engine, store=store_a, cache=cache, embed_model="model-a", repo_root=tmp_path)
    assert store_a.count() >= 1
    # a store opened for a different embed model must not see the other model's vectors
    store_b = VectorStore(embed_model="model-b", dim=_DIM, path=tmp_path / "vectors.json", prefer_redis=False)
    assert store_b.count() == 0


def _redis_ready(url: str = "redis://127.0.0.1:6379") -> bool:
    """True only when a VectorStore actually resolves to the RediSearch backend (the real capability test)."""
    try:
        from citadel.services.retrieval.vector_store import VectorStore

        probe = VectorStore(embed_model="pytest-probe", dim=4, redis_url=url, prefer_redis=True)
        return probe.backend_name == "redis"
    except Exception:
        return False


@pytest.mark.skipif(not _redis_ready(), reason="Redis Stack (RediSearch) not reachable on localhost:6379")
def test_redis_vector_backend_live():
    from citadel.services.retrieval.vector_store import VectorRecord, VectorStore

    store = VectorStore(embed_model="pytest-rtest", dim=4, redis_url="redis://127.0.0.1:6379", prefer_redis=True)
    assert store.backend_name == "redis"
    store.delete_by_path("x.py")
    store.upsert([VectorRecord(
        id="x.py#0", path="x.py", index=0, start_byte=0, end_byte=5, content_hash="h", file_hash="fx",
        embed_model="pytest-rtest", dim=4, vector=[1.0, 0.0, 0.0, 0.0], text="alpha")])
    hits = store.query([0.9, 0.1, 0.0, 0.0], top_k=1)
    assert hits and hits[0][1].path == "x.py"
    assert store.stored_file_hash("x.py") == "fx"
    assert store.delete_by_path("x.py") == 1


def test_embed_cache_reuses_identical_text(tmp_path):
    engine, store, cache = FakeEmbedEngine(), _store(tmp_path), _cache(tmp_path)
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    shared = "def shared_helper():\n    return 42\n"
    a.write_text(shared, encoding="utf-8")
    b.write_text(shared, encoding="utf-8")
    index_file(a, engine=engine, store=store, cache=cache, embed_model="fake-embed", repo_root=tmp_path)
    calls_after_a = engine.calls
    # identical chunk text in b → cache hit → no new embedding call
    res_b = index_file(b, engine=engine, store=store, cache=cache, embed_model="fake-embed", repo_root=tmp_path)
    assert res_b.embedded == 0
    assert engine.calls == calls_after_a
