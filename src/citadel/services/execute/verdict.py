"""Verdict ledger + condemned set (masterplan §4.3).

Every artifact receives a `PASS | FAIL | CAPITAL` verdict keyed by its content hash. A CAPITAL
(condemned) artifact can never be re-proposed — an O(1) membership check rejects the identical content on
every future submission. Pre-image backups are content-addressed, so a hundred backups of an unchanged
file cost one blob (the free-dedup dividend).
"""

import hashlib
import json
import time
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
CAPITAL = "CAPITAL"


def artifact_hash(content: str) -> str:
    """Stable content digest used as the verdict/condemned-set key."""
    return hashlib.blake2b(content.encode("utf-8"), digest_size=16).hexdigest()


class VerdictLedger:
    """Records artifact verdicts and the condemned set. Persists to JSONL when given a root."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root is not None else None
        self._verdicts: dict[str, str] = {}
        self._condemned: set[str] = set()
        self._load()

    def _ledger_path(self) -> Path | None:
        return self._root / "verdicts.jsonl" if self._root is not None else None

    def _load(self) -> None:
        path = self._ledger_path()
        if path is None or not path.exists():
            return
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                digest, status = record.get("hash"), record.get("status")
                if digest:
                    self._verdicts[digest] = status
                    if status == CAPITAL:
                        self._condemned.add(digest)
        except (OSError, ValueError):
            pass

    def record(self, content_hash: str, status: str) -> None:
        self._verdicts[content_hash] = status
        if status == CAPITAL:
            self._condemned.add(content_hash)
        path = self._ledger_path()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"ts": time.time(), "hash": content_hash, "status": status}) + "\n")

    def condemn(self, content_hash: str) -> None:
        self.record(content_hash, CAPITAL)

    def is_condemned(self, content_hash: str) -> bool:
        return content_hash in self._condemned

    def verdict(self, content_hash: str) -> str | None:
        return self._verdicts.get(content_hash)

    def backup(self, path: str | Path) -> str | None:
        """Content-addressed pre-image backup of an existing file. Returns the digest, or None if the file
        is absent or no root is configured. Identical pre-images are stored once (free dedup)."""
        source = Path(path)
        if self._root is None or not source.is_file():
            return None
        try:
            content = source.read_bytes()
        except OSError:
            return None
        digest = hashlib.blake2b(content, digest_size=16).hexdigest()
        cas = self._root / "pre-images"
        cas.mkdir(parents=True, exist_ok=True)
        dest = cas / digest
        if not dest.exists():
            dest.write_bytes(content)
        return digest
