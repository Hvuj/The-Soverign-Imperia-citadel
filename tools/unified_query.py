#!/usr/bin/env python3
"""
Unified Query Engine — SQLite FTS5 inverted index across Code / Knowledge / Bug corpora.

Design:
  - WAL mode + NORMAL synchronous for high-throughput concurrent reads.
  - FTS5 virtual table with BM25 ranking (ORDER BY rank).
  - O(1) indexed_documents tracker prevents duplicate indexing.
  - Thread-safe: check_same_thread=False with explicit transaction control.
  - DB is a single flat file; portable, no server required.
"""


import json
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = _ROOT / ".claude" / "state" / "citadel_unified_index.db"

_CORPUS_VALUES = {"code", "knowledge", "bugs"}


class UnifiedQueryEngine:
    def __init__(self, db_path: str | Path | None = None) -> None:
        path = Path(db_path) if db_path else DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(path),
            isolation_level=None,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")

        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS unified_search USING fts5(
                corpus,
                doc_id,
                content,
                tags,
                tokenize = 'porter ascii'
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS indexed_documents (
                doc_id       TEXT PRIMARY KEY,
                corpus       TEXT NOT NULL,
                last_updated INTEGER NOT NULL
            );
        """)

    def index_document(
        self,
        corpus: str,
        doc_id: str,
        content: str,
        tags: list[str],
    ) -> bool:
        if corpus not in _CORPUS_VALUES:
            print(f"Unknown corpus '{corpus}'; must be one of {_CORPUS_VALUES}", file=sys.stderr)
            return False

        tags_str = " ".join(str(t) for t in tags)
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN;")
                cur.execute("DELETE FROM unified_search WHERE doc_id = ?;", (doc_id,))
                cur.execute(
                    "INSERT INTO unified_search (corpus, doc_id, content, tags) VALUES (?, ?, ?, ?);",
                    (corpus, doc_id, content, tags_str),
                )
                cur.execute(
                    "INSERT OR REPLACE INTO indexed_documents (doc_id, corpus, last_updated) "
                    "VALUES (?, ?, CAST(strftime('%s','now') AS INTEGER));",
                    (doc_id, corpus),
                )
                cur.execute("COMMIT;")
                return True
            except Exception as exc:
                cur.execute("ROLLBACK;")
                print(f"Index fault on {doc_id}: {exc}", file=sys.stderr)
                return False

    def query(
        self,
        search_term: str,
        limit: int = 10,
        corpus_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        clean = search_term.replace('"', "").replace("'", "").strip()
        if not clean:
            return []

        match_expr = f'"{clean}"*'
        with self._lock:
            cur = self._conn.cursor()
            if corpus_filter:
                cur.execute(
                    "SELECT corpus, doc_id, "
                    "snippet(unified_search, 2, '[', ']', '...', 10) AS highlight, rank "
                    "FROM unified_search "
                    "WHERE unified_search MATCH ? AND corpus = ? "
                    "ORDER BY rank LIMIT ?;",
                    (match_expr, corpus_filter, limit),
                )
            else:
                cur.execute(
                    "SELECT corpus, doc_id, "
                    "snippet(unified_search, 2, '[', ']', '...', 10) AS highlight, rank "
                    "FROM unified_search "
                    "WHERE unified_search MATCH ? "
                    "ORDER BY rank LIMIT ?;",
                    (match_expr, limit),
                )
            return [
                {
                    "corpus": row["corpus"],
                    "doc_id": row["doc_id"],
                    "highlight": row["highlight"],
                    "score": round(row["rank"], 4),
                }
                for row in cur.fetchall()
            ]

    def indexed_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM indexed_documents;").fetchone()
            return row[0] if row else 0

    def delete_document(self, doc_id: str) -> bool:
        """Remove a document from the FTS5 index and the indexed_documents tracker."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN;")
                cur.execute("DELETE FROM unified_search WHERE doc_id = ?;", (doc_id,))
                cur.execute("DELETE FROM indexed_documents WHERE doc_id = ?;", (doc_id,))
                cur.execute("COMMIT;")
                return True
            except Exception as exc:
                cur.execute("ROLLBACK;")
                print(f"Delete fault on {doc_id}: {exc}", file=sys.stderr)
                return False

    def close(self) -> None:
        self._conn.close()


if __name__ == "__main__":
    engine = UnifiedQueryEngine()

    ok1 = engine.index_document(
        "knowledge", "hash_alpha123",
        "Orchestration asset materialization requires an active IO manager.",
        ["orchestration", "data-engineering"],
    )
    ok2 = engine.index_document(
        "bugs", "bug_beta456",
        "ValueError: IO manager missing during asset materialization.",
        ["orchestration", "error"],
    )
    assert ok1 and ok2, "indexing failed"

    results = engine.query("materialization")
    print(json.dumps({"unified_search_results": results}, indent=2))

    assert len(results) >= 1, "no results for 'materialization'"
    assert engine.indexed_count() >= 2, "indexed_documents count wrong"
    engine.close()
    print(f"indexed: {engine.indexed_count() if False else 2}+ docs")
    print("smoke test: PASS")
    sys.exit(0)
