"""worker.py — the EmbedderWorker: the learning Z-worker's core (Phase Z1).

Embeds changed files into the vector store, deletes vectors for removed files, and writes a small live
stats file that `citadel workers` reads to show the Z-worker running. The heavy logic is here (testable
with a fake engine); `tools/embedder_daemon.py` is just the watch loop that calls `sync`. Embedding is
skipped whenever the engine is offline (degrade, never crash) and whenever a file's index is still fresh
(the JIT contract from Z0), so the worker is cheap on a quiet tree and only works when there is real change.
"""

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from citadel.services.retrieval.embed_cache import EmbedCache
from citadel.services.retrieval.indexer import index_file
from citadel.services.retrieval.vector_store import VectorStore

_INDEXABLE_SUFFIXES = {
    ".py", ".md", ".txt", ".rst", ".js", ".ts", ".tsx", ".jsx", ".json", ".sh",
    ".rs", ".go", ".java", ".c", ".h", ".cpp", ".yaml", ".yml", ".toml", ".sql",
}
_MAX_FILE_BYTES = 1_000_000
_DEFAULT_EMBED_MODEL = "nomic-embed-text"
_DEFAULT_DIM = 768  # nomic-embed-text; only matters for the Redis index (local backend is dim-agnostic)


class EmbedderWorker:
    def __init__(
        self,
        *,
        engine,
        store: VectorStore,
        cache: EmbedCache,
        embed_model: str,
        repo_root: str | Path,
        stats_path: str | Path,
    ) -> None:
        self.engine = engine
        self.store = store
        self.cache = cache
        self.embed_model = embed_model
        self.repo_root = Path(repo_root)
        self.stats_path = Path(stats_path)
        self._embedded_total = 0
        self._last_synced = 0

    @classmethod
    def for_workspace(cls, workspace: str | Path, *, engine=None, embed_model: str | None = None) -> "EmbedderWorker":
        ws = Path(workspace)
        model = embed_model or os.environ.get("CITADEL_EMBED_MODEL", _DEFAULT_EMBED_MODEL)
        state = ws / ".claude" / "state" / "retrieval"
        if engine is None:
            from citadel.services.execute.local.engine import OllamaEngine

            engine = OllamaEngine()
        store = VectorStore(embed_model=model, dim=_DEFAULT_DIM, path=state / "vectors.json")
        cache = EmbedCache(model, path=state / "embed-cache.json")
        return cls(
            engine=engine, store=store, cache=cache, embed_model=model,
            repo_root=ws, stats_path=state / "embedder-stats.json",
        )

    def _indexable(self, path: Path) -> bool:
        if path.suffix.lower() not in _INDEXABLE_SUFFIXES:
            return False
        try:
            return path.is_file() and path.stat().st_size <= _MAX_FILE_BYTES
        except OSError:
            return False

    def sync(self, changed: Iterable[str | Path], deleted: Iterable[str] = ()) -> int:
        """Embed changed files + drop deleted ones. Returns how many files were (re)indexed this pass."""
        for rel in deleted:
            self.store.delete_by_path(str(rel).replace("\\", "/"))
        online = False
        try:
            online = self.engine.available()
        except Exception:
            online = False
        indexed = 0
        if online:
            for raw in changed:
                path = Path(raw)
                if not self._indexable(path):
                    continue
                try:
                    result = index_file(
                        path, engine=self.engine, store=self.store, cache=self.cache,
                        embed_model=self.embed_model, repo_root=self.repo_root,
                    )
                except Exception:
                    continue
                self._embedded_total += result.embedded
                if not result.skipped_fresh:
                    indexed += 1
        self._last_synced = indexed
        self._write_stats(online)
        return indexed

    def sweep(self, roots: Iterable[str | Path]) -> int:
        """Initial full index of everything indexable under `roots`."""
        files: list[Path] = []
        for root in roots:
            base = self.repo_root / root if not Path(root).is_absolute() else Path(root)
            if base.is_dir():
                files.extend(p for p in base.rglob("*") if self._indexable(p))
            elif self._indexable(base):
                files.append(base)
        return self.sync(files)

    def stats(self) -> dict:
        try:
            online = self.engine.available()
        except Exception:
            online = False
        return {
            "worker": "embedder",
            "chunks": self.store.count(),
            "embedded_total": self._embedded_total,
            "last_synced": self._last_synced,
            "model": self.embed_model,
            "backend": self.store.backend_name,
            "online": online,
        }

    def _write_stats(self, online: bool) -> None:
        data = self.stats()
        data["online"] = online
        self.stats_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.stats_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            os.replace(tmp, self.stats_path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
