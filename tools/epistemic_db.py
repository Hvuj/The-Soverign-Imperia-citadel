#!/usr/bin/env python3
"""
Epistemic Database Manager — Phase 14: The Autonomous Skill Factory & FTS5 Cache.

Manages a persistent SQLite database with an FTS5 virtual table for ultra-fast,
zero-token full-text search over historical task records.  The database powers
the Prior Art injection pipeline: past successful task resolutions are retrieved
by SOVEREIGN-IMPERIA-CITADEL before each new task dispatch, giving Tier 5 Squads proven
implementation patterns without trial-and-error reasoning loops.

FTS5 enables native SQLite full-text search with inverted-index performance.
On FTS5-unavailable builds, a plain table + LIKE fallback is used transparently.

Database: .claude/brain/epistemic_history.db
Schema:   task_history (FTS5 virtual table)
"""


import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent.resolve()
_DB_PATH = _ROOT / ".claude" / "brain" / "epistemic_history.db"

_PUNCTUATION_RE = re.compile(r'["\'\-*+^():\[\]{}|&!~<>]')

_CREATE_FTS5 = """
    CREATE VIRTUAL TABLE IF NOT EXISTS task_history USING fts5(
        task_id,
        task_description,
        files_modified,
        git_diff_summary,
        ast_symbols_touched,
        resolution_timestamp UNINDEXED
    );
"""

_CREATE_FALLBACK = """
    CREATE TABLE IF NOT EXISTS task_history_fallback (
        task_id TEXT,
        task_description TEXT,
        files_modified TEXT,
        git_diff_summary TEXT,
        ast_symbols_touched TEXT,
        resolution_timestamp TEXT
    );
"""

_COLUMNS = (
    "task_id",
    "task_description",
    "files_modified",
    "git_diff_summary",
    "ast_symbols_touched",
    "resolution_timestamp",
)


class EpistemicDatabaseManager:
    """Manages the FTS5 epistemic task history database.

    Supports the `:memory:` SQLite special path for in-process testing —
    pass `db_path=Path(":memory:")` to open an ephemeral in-memory database.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _DB_PATH
        _path_str = str(self.db_path)
        if _path_str != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(_path_str)
        self._conn.row_factory = sqlite3.Row
        self._fts5_available: bool = False
        self._init_schema()

    def _init_schema(self) -> None:
        """Create the FTS5 table if not present; fall back to a plain table."""
        try:
            self._conn.execute(_CREATE_FTS5)
            self._conn.commit()
            self._fts5_available = True
        except sqlite3.OperationalError:
            self._conn.execute(_CREATE_FALLBACK)
            self._conn.commit()
            self._fts5_available = False

    def log_resolved_task(self, task_data: dict[str, str]) -> bool:
        """Insert a historical task record into the database.

        Args:
            task_data: Dict with any subset of the table columns:
                task_id, task_description, files_modified, git_diff_summary,
                ast_symbols_touched, resolution_timestamp.
                Missing keys default to empty string.

        Returns:
            True on successful insert.
        """
        table = "task_history" if self._fts5_available else "task_history_fallback"
        row = tuple(task_data.get(col, "") for col in _COLUMNS)
        placeholders = ", ".join("?" * len(_COLUMNS))
        try:
            self._conn.execute(
                f"INSERT INTO {table} VALUES ({placeholders})",  # noqa: S608
                row,
            )
            self._conn.commit()
            return True
        except sqlite3.Error as exc:
            print(f"EpistemicDB: insert failed — {exc}", file=sys.stderr)
            return False

    def search_prior_art(self, search_query: str, limit: int = 3) -> list[dict[str, Any]]:
        """Full-text search task history for prior art.

        Uses FTS5 MATCH when available, with sanitization + LIKE fallback on
        parse errors or unavailable FTS5.

        Args:
            search_query: Free-text query (task description, symbols, etc.)
            limit:        Maximum number of results.

        Returns:
            List of row dicts with the FTS5 table columns.
        """
        if not search_query.strip():
            return []
        if self._fts5_available:
            return self._fts5_search(search_query, limit)
        return self._like_search(search_query, limit)

    def _fts5_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Execute an FTS5 MATCH query; fall back to LIKE on syntax errors."""
        sanitized = self._sanitize_fts5(query)
        if not sanitized:
            return []
        try:
            cur = self._conn.execute(
                "SELECT * FROM task_history WHERE task_history MATCH :query LIMIT :limit",
                {"query": sanitized, "limit": limit},
            )
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.OperationalError:
            return self._like_search(query, limit)

    def _like_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Naive LIKE search; used as fallback when FTS5 is absent or fails."""
        table = "task_history" if self._fts5_available else "task_history_fallback"
        words = query.strip().split()
        if not words:
            return []
        keyword = words[0]
        try:
            cur = self._conn.execute(
                f"SELECT * FROM {table} WHERE task_description LIKE :kw LIMIT :limit",  # noqa: S608
                {"kw": f"%{keyword}%", "limit": limit},
            )
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error:
            return []

    @staticmethod
    def _sanitize_fts5(query: str) -> str:
        """Strip FTS5 special characters so the parser does not throw.

        Replaces punctuation with spaces and collapses runs of whitespace.
        """
        clean = _PUNCTUATION_RE.sub(" ", query)
        return re.sub(r"\s+", " ", clean).strip()

    def close(self) -> None:
        """Close the SQLite connection."""
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="SOVEREIGN-IMPERIA-CITADEL Epistemic Database Manager (FTS5)")
    cli.add_argument(
        "--test",
        action="store_true",
        help="Run FTS5 write+query smoke test using in-memory SQLite (no disk writes)",
    )
    cli.add_argument(
        "--log",
        metavar="JSON",
        help="Insert a task record (JSON string with task_id, task_description, etc.)",
    )
    cli.add_argument(
        "--search",
        metavar="QUERY",
        help="Search task history for prior art and print results as JSON",
    )
    cargs = cli.parse_args()

    if cargs.test:
        db = EpistemicDatabaseManager(db_path=Path(":memory:"))

        record: dict[str, str] = {
            "task_id": "test-001",
            "task_description": "Implement a JSON schema validator using jsonschema library",
            "files_modified": "tools/schema_validator.py",
            "git_diff_summary": "Added validate_schema() and _load_schema() helpers",
            "ast_symbols_touched": "validate_schema, _load_schema, SchemaError",
            "resolution_timestamp": "2026-06-22T00:00:00Z",
        }
        ok = db.log_resolved_task(record)
        assert ok, "log_resolved_task returned False"

        hits = db.search_prior_art("JSON schema validate")
        assert hits, "search_prior_art returned no results for known record"
        assert hits[0]["task_id"] == "test-001", f"Wrong task_id: {hits[0]['task_id']}"

        hits2 = db.search_prior_art("JSON schema: validate+helpers")
        assert isinstance(hits2, list), "Sanitized search must return a list"

        hits3 = db.search_prior_art("")
        assert hits3 == [], f"Empty query should return [], got {hits3}"

        db.close()
        print(f"EpistemicDatabaseManager --test passed. FTS5 available: {db._fts5_available}")
        print(f"  Inserted: {record['task_id']}")
        print(f"  Search hit: {hits[0]['task_id']} — {hits[0]['task_description'][:60]}")
        sys.exit(0)

    if cargs.log:
        try:
            data = json.loads(cargs.log)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        mgr = EpistemicDatabaseManager()
        result = mgr.log_resolved_task(data)
        mgr.close()
        sys.exit(0 if result else 1)

    if cargs.search:
        mgr = EpistemicDatabaseManager()
        found = mgr.search_prior_art(cargs.search)
        mgr.close()
        print(json.dumps(found, indent=2))
        sys.exit(0)

    cli.print_help()
    sys.exit(1)
