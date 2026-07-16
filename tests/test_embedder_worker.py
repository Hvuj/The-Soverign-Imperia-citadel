"""Phase Z1 — the learning Z-worker. EmbedderWorker embeds on change / skips fresh / no-ops offline;
RetrieverLearner self-tunes its threshold; worker_status surfaces the roster in `citadel workers`. Uses a
deterministic fake engine — no Ollama, no Redis, no daemon spawn."""

import hashlib
import json
import re
import sys
from pathlib import Path

from citadel.services.execute.local.engine import LocalEngine, RunSpec
from citadel.services.retrieval import EmbedCache, RetrieverLearner, VectorStore
from citadel.services.retrieval.worker import EmbedderWorker

_DIM = 48


class FakeEmbedEngine(LocalEngine):
    name = "fake"

    def __init__(self, online: bool = True) -> None:
        self._online = online
        self.calls = 0

    def available(self) -> bool:
        return self._online

    def generate(self, prompt: str, spec: RunSpec) -> str:
        return ""

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        self.calls += len(texts)
        out = []
        for text in texts:
            vec = [0.0] * _DIM
            for tok in re.findall(r"[a-z0-9]+", text.lower()):
                vec[int(hashlib.blake2b(tok.encode(), digest_size=4).hexdigest(), 16) % _DIM] += 1.0
            out.append(vec)
        return out


def _worker(tmp_path, engine):
    state = tmp_path / ".claude" / "state" / "retrieval"
    store = VectorStore(embed_model="fake", dim=_DIM, path=state / "vectors.json", prefer_redis=False)
    cache = EmbedCache("fake", path=state / "cache.json", prefer_redis=False)
    return EmbedderWorker(
        engine=engine, store=store, cache=cache, embed_model="fake",
        repo_root=tmp_path, stats_path=state / "embedder-stats.json",
    )


def test_embedder_embeds_changed_and_publishes_stats(tmp_path):
    (tmp_path / "src").mkdir()
    f = tmp_path / "src" / "mod.py"
    f.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    worker = _worker(tmp_path, FakeEmbedEngine())

    indexed = worker.sync([f])
    assert indexed == 1
    stats = worker.stats()
    assert stats["chunks"] >= 1 and stats["worker"] == "embedder"

    # the published stats file exists and is readable (what `citadel workers` reads)
    published = json.loads((tmp_path / ".claude" / "state" / "retrieval" / "embedder-stats.json").read_text())
    assert published["chunks"] >= 1


def test_embedder_skips_when_fresh(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    engine = FakeEmbedEngine()
    worker = _worker(tmp_path, engine)
    worker.sync([f])
    calls = engine.calls
    # unchanged → JIT fresh → no new embedding work
    second = worker.sync([f])
    assert second == 0
    assert engine.calls == calls


def test_embedder_noops_when_engine_offline(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    engine = FakeEmbedEngine(online=False)
    worker = _worker(tmp_path, engine)
    indexed = worker.sync([f])
    assert indexed == 0
    assert engine.calls == 0
    assert worker.stats()["chunks"] == 0


def test_embedder_deletes_removed_files(tmp_path):
    f = tmp_path / "gone.py"
    f.write_text("y = 2\n", encoding="utf-8")
    worker = _worker(tmp_path, FakeEmbedEngine())
    worker.sync([f])
    assert worker.store.count() >= 1
    worker.sync([], deleted=["gone.py"])
    assert worker.store.count() == 0


def test_retriever_learner_tunes_threshold_and_persists(tmp_path):
    path = tmp_path / "retriever-stats.json"
    learner = RetrieverLearner(path, min_samples=5, target_precision=0.7, step=0.05)
    base = learner.tuned_threshold()
    for _ in range(10):  # all misses → precision below target → raise the bar
        learner.record(hit=False)
    assert learner.tuned_threshold() > base
    # reload from disk keeps the learned threshold
    reloaded = RetrieverLearner(path)
    assert reloaded.tuned_threshold() == learner.tuned_threshold()
    assert reloaded.stats()["queries"] == 10


def test_worker_status_shows_z_workers(tmp_path):
    tools = Path(__file__).resolve().parents[1] / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import worker_status

    state = tmp_path / ".claude" / "state" / "retrieval"
    state.mkdir(parents=True)
    (state / "embedder-stats.json").write_text(
        json.dumps({"worker": "embedder", "chunks": 12, "embedded_total": 12, "model": "nomic-embed-text",
                    "backend": "local", "online": True}), encoding="utf-8")
    (state / "retriever-stats.json").write_text(
        json.dumps({"worker": "retriever", "queries": 30, "hits": 24, "hit_rate": 0.8, "threshold": 0.55}),
        encoding="utf-8")

    status = worker_status.build_status(tmp_path)
    kinds = {z["worker"] for z in status["z_workers"]}
    assert {"embedder", "retriever"} <= kinds
    text = worker_status.render_text(status)
    assert "embedder" in text and "12 chunks" in text
    assert "retriever" in text and "hit-rate 0.8" in text
