"""Phase Z2 (buildable core) — the shared RetrievalService: dense search over the embedder's index, plus
scoped/redacted read and budgeted context. Fake engine → no Ollama/Redis. The MCP wiring is covered in
test_mcp_server.py."""

import hashlib
import re

from citadel.services.execute.local.engine import LocalEngine, RunSpec
from citadel.services.retrieval import EmbedCache, VectorStore, index_file
from citadel.services.retrieval.service import RetrievalService

_DIM = 48


class FakeEmbedEngine(LocalEngine):
    name = "fake"

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, spec: RunSpec) -> str:
        return ""

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * _DIM
            for tok in re.findall(r"[a-z0-9]+", text.lower()):
                vec[int(hashlib.blake2b(tok.encode(), digest_size=4).hexdigest(), 16) % _DIM] += 1.0
            out.append(vec)
        return out


def _service(tmp_path):
    engine = FakeEmbedEngine()
    store = VectorStore(embed_model="fake", dim=_DIM, path=tmp_path / "v.json", prefer_redis=False)
    cache = EmbedCache("fake", path=tmp_path / "c.json", prefer_redis=False)
    (tmp_path / "src").mkdir(exist_ok=True)
    f = tmp_path / "src" / "code.py"
    f.write_text(
        "def parse_yaml_config(path):\n    import yaml\n    return yaml.safe_load(open(path))\n\n\n"
        "def sha256_digest(data):\n    import hashlib\n    return hashlib.sha256(data).hexdigest()\n",
        encoding="utf-8",
    )
    index_file(f, engine=engine, store=store, cache=cache, embed_model="fake", repo_root=tmp_path)
    return RetrievalService(engine=engine, store=store, embed_model="fake", workspace=tmp_path)


def test_search_returns_cited_hits(tmp_path):
    svc = _service(tmp_path)
    out = svc.search("yaml config parse", top_k=3)
    assert out["count"] >= 1
    top = out["hits"][0]
    assert top["path"] == "src/code.py"
    assert "start_byte" in top and "end_byte" in top and "yaml" in top["snippet"]


def test_read_is_scoped_and_redacted(tmp_path):
    svc = _service(tmp_path)
    secret = tmp_path / "secret.py"
    secret.write_text("TOKEN=sk-abcdefghijklmnop1234\nvalue = 1\n", encoding="utf-8")
    out = svc.read("secret.py")
    assert "preamble" in out
    assert "sk-abcdefghijklmnop1234" not in out["body"]
    # path escaping the workspace is refused
    assert svc.read("../../etc/passwd").get("error")


def test_context_is_budgeted_and_deduped(tmp_path):
    svc = _service(tmp_path)
    out = svc.context("yaml config", top_k=5, budget_bytes=4096)
    assert "preamble" in out
    assert isinstance(out["chunks"], list)
    total = sum(len(c["snippet"].encode("utf-8")) for c in out["chunks"])
    assert total <= 4096


def test_search_degrades_when_engine_offline(tmp_path):
    class Offline(FakeEmbedEngine):
        def available(self) -> bool:
            return False

        def embed(self, texts, model):
            raise RuntimeError("offline")

    store = VectorStore(embed_model="fake", dim=_DIM, path=tmp_path / "v2.json", prefer_redis=False)
    svc = RetrievalService(engine=Offline(), store=store, embed_model="fake", workspace=tmp_path)
    out = svc.search("anything")
    assert out["count"] == 0 and out["hits"] == []
