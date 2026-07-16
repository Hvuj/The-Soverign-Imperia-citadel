"""Phase Z3 — the grounded answer path + content-hash-gated cache (weak-spot #1). Fake engine + fake
generator → no Ollama. Proves: grounded answer with citations; cache hit only while cited files are fresh;
an edited cited file forces a fresh answer (never a stale cached answer)."""

import hashlib
import re

from citadel.services.execute.local.engine import LocalEngine, RunSpec
from citadel.services.retrieval import (
    AnswerCache,
    EmbedCache,
    RetrievalService,
    VectorStore,
    answer_question,
    index_file,
    make_query_key,
)

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
    cache = EmbedCache("fake", path=tmp_path / "ec.json", prefer_redis=False)
    (tmp_path / "src").mkdir(exist_ok=True)
    f = tmp_path / "src" / "cfg.py"
    f.write_text("def parse_yaml_config(path):\n    import yaml\n    return yaml.safe_load(open(path))\n",
                 encoding="utf-8")
    index_file(f, engine=engine, store=store, cache=cache, embed_model="fake", repo_root=tmp_path)
    return RetrievalService(engine=engine, store=store, embed_model="fake", workspace=tmp_path), f


def test_grounded_answer_has_citations(tmp_path):
    service, _ = _service(tmp_path)
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return "Use parse_yaml_config in src/cfg.py."

    out = answer_question("how do I parse yaml config", service=service, generate=generate, workspace=tmp_path)
    assert out["grounded"] is True and out["cached"] is False
    assert any(c["path"] == "src/cfg.py" for c in out["citations"])
    assert "src/cfg.py" in calls[0]  # context was actually injected into the prompt


def test_cache_hit_when_files_unchanged(tmp_path):
    service, _ = _service(tmp_path)
    cache = AnswerCache(path=tmp_path / "ans.json", prefer_redis=False)
    gen_calls = []

    def generate(prompt):
        gen_calls.append(1)
        return "answer body"

    q = "explain the yaml config loader"
    first = answer_question(q, service=service, generate=generate, workspace=tmp_path, cache=cache)
    assert first["cached"] is False and len(gen_calls) == 1
    second = answer_question(q, service=service, generate=generate, workspace=tmp_path, cache=cache)
    assert second["cached"] is True and len(gen_calls) == 1  # served from cache, model NOT called again
    assert second["answer"] == "answer body"


def test_cache_invalidated_when_cited_file_changes(tmp_path):
    service, f = _service(tmp_path)
    cache = AnswerCache(path=tmp_path / "ans.json", prefer_redis=False)
    gen_calls = []

    def generate(prompt):
        gen_calls.append(1)
        return "v1 answer"

    q = "what does the config loader do"
    answer_question(q, service=service, generate=generate, workspace=tmp_path, cache=cache)
    assert len(gen_calls) == 1

    # edit the cited file → the cached answer must NOT be served (weak-spot #1)
    f.write_text(f.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    # re-index so the store's file_hash reflects the new content
    engine = service.engine
    from citadel.services.retrieval import EmbedCache as _EC
    index_file(f, engine=engine, store=service.store,
               cache=_EC("fake", path=tmp_path / "ec.json", prefer_redis=False),
               embed_model="fake", repo_root=tmp_path)

    def generate2(prompt):
        gen_calls.append(1)
        return "v2 answer"

    out = answer_question(q, service=service, generate=generate2, workspace=tmp_path, cache=cache)
    assert out["cached"] is False and out["answer"] == "v2 answer"
    assert len(gen_calls) == 2


def test_query_key_normalizes_whitespace_and_case():
    assert make_query_key("How  Do I?") == make_query_key("how do i?")
