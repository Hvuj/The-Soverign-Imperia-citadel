"""service.py — the shared zero-token retrieval API (read · search · context).

One implementation that the MCP server, a future FastMCP server, and `citadel ask` all call, so retrieval
logic lives in exactly one place (DIP). Every response is passed through `citadel_custos.guard_output`
(count-first + splice + secret redaction, gate G4) and carries provenance (path + byte range), so an AI can
cite what it used and never pays model tokens to scan or search — the tool does it locally. `search` is the
dense half of hybrid retrieval over the vectors the embedder Z-worker maintains; it degrades to an empty
result (never a crash) when the engine or index is unavailable.
"""

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from citadel.services.retrieval.embed_cache import EmbedCache
from citadel.services.retrieval.indexer import search as _dense_search
from citadel.services.retrieval.vector_store import VectorStore

_DEFAULT_EMBED_MODEL = "nomic-embed-text"
_DEFAULT_DIM = 768


def _guard():
    try:
        from citadel.services._tools_bridge import import_tool

        return import_tool("citadel_custos").guard_output
    except Exception:
        return None


@dataclass(slots=True)
class Hit:
    path: str
    score: float
    start_byte: int
    end_byte: int
    snippet: str


class RetrievalService:
    def __init__(self, *, engine, store: VectorStore, embed_model: str, workspace: str | Path) -> None:
        self.engine = engine
        self.store = store
        self.embed_model = embed_model
        self.workspace = Path(workspace).resolve()

    @classmethod
    def for_workspace(cls, workspace: str | Path, *, engine=None, embed_model: str | None = None) -> "RetrievalService":
        from citadel.config import get_settings

        ws = Path(workspace)
        model = embed_model or get_settings().embed_model
        state = ws / ".claude" / "state" / "retrieval"
        if engine is None:
            from citadel.services.execute.local.engine import OllamaEngine

            engine = OllamaEngine()
        store = VectorStore(embed_model=model, dim=_DEFAULT_DIM, path=state / "vectors.json")
        return cls(engine=engine, store=store, embed_model=model, workspace=ws)

    def search(self, query: str, *, top_k: int = 8, min_score: float = 0.0, alpha: float = 0.7) -> dict:
        """Hybrid search: dense KNN candidates re-scored with sparse keyword overlap (weak-spot #8). Returns
        cited hits + a count preamble (0 model tokens). `alpha` weights dense vs keyword in the fused score."""
        try:
            results = _dense_search(
                query, engine=self.engine, store=self.store, embed_model=self.embed_model,
                top_k=max(top_k * 4, top_k), min_score=min_score,
            )
        except Exception:
            results = []
        q_tokens = set(re.findall(r"[a-z0-9_]+", query.lower()))
        fused = []
        for dense, rec in results:
            kw = self._keyword_score(q_tokens, rec.text)
            fused.append((alpha * dense + (1 - alpha) * kw, dense, rec))
        fused.sort(key=lambda t: t[0], reverse=True)
        hits = [
            Hit(path=rec.path, score=round(score, 4), start_byte=rec.start_byte,
                end_byte=rec.end_byte, snippet=self._snippet(rec.text))
            for score, _dense, rec in fused[:top_k]
        ]
        return {
            "query": query,
            "count": len(hits),
            "backend": self.store.backend_name,
            "hits": [asdict(h) for h in hits],
        }

    @staticmethod
    def _keyword_score(q_tokens: set[str], text: str) -> float:
        if not q_tokens:
            return 0.0
        t_tokens = set(re.findall(r"[a-z0-9_]+", text.lower()))
        return len(q_tokens & t_tokens) / len(q_tokens) if t_tokens else 0.0

    def read(self, rel_path: str, *, max_bytes: int = 16 * 1024) -> dict:
        """Read a workspace file, redacted + spliced + count-first (G4). Refuses paths outside the workspace."""
        target = (self.workspace / rel_path).resolve()
        if not target.is_relative_to(self.workspace):
            return {"error": "path escapes the workspace", "path": rel_path}
        if not target.is_file():
            return {"error": "not a file", "path": rel_path}
        text = target.read_text(encoding="utf-8", errors="ignore")
        guard = _guard()
        if guard is None:
            return {"path": rel_path, "preamble": f"[{len(text)} bytes]", "body": text[:max_bytes]}
        out = guard(text, max_bytes=max_bytes)
        out["path"] = rel_path
        return out

    def context(self, task: str, *, top_k: int = 8, budget_bytes: int = 24 * 1024) -> dict:
        """Assemble a budgeted, deduped, cited context capsule for a task — the pre-digested pack for any AI."""
        found = self.search(task, top_k=top_k)
        seen: set[str] = set()
        packed: list[dict] = []
        used = 0
        for hit in found["hits"]:
            key = f"{hit['path']}#{hit['start_byte']}"
            if key in seen:
                continue
            seen.add(key)
            size = len(hit["snippet"].encode("utf-8"))
            if used + size > budget_bytes:
                break
            used += size
            packed.append(hit)
        return {
            "task": task,
            "preamble": f"[{len(packed)} chunks, {used} bytes assembled from {found['count']} candidates]",
            "chunks": packed,
        }

    @staticmethod
    def _snippet(text: str, max_bytes: int = 1200) -> str:
        raw = text.encode("utf-8")
        return text if len(raw) <= max_bytes else raw[:max_bytes].decode("utf-8", errors="ignore")
