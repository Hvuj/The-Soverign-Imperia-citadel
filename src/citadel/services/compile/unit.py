"""unit.py — a `.legion` compiled fact unit: marshal payload + .pyc-style header.

Serialization mirrors CPython's hash-based `.pyc` (PEP 552): a magic prefix, a schema
version, the interpreter cache tag, and the source SHA-256. `loads()` refuses (raises
`StaleUnit`) on any mismatch, so a unit is used only when it provably matches the current
source and legion schema. The payload is `marshal` — the same fast, stdlib serializer
CPython uses for bytecode — restricted to plain dict/list/str/int (marshal-safe).
"""
import marshal
import sys
from dataclasses import dataclass, field
from typing import Self

from citadel.services.index.base import Symbol

MAGIC = b"LGN1"
SCHEMA_VERSION = 1
PY_TAG = sys.implementation.cache_tag or "py"


class StaleUnit(Exception):
    """Raised when a serialized unit does not match the current source/schema/interpreter."""


@dataclass(slots=True)
class LegionUnit:
    """Source-derived facts for one file, cached independently of which repo reads it.

    Symbols are stored repo-agnostic (their ``path`` is the file's repo-relative path but
    ``repo`` is empty); ``symbols_for(repo)`` re-tags them for a specific company at read
    time. This lets an identical file shared across repos compile once.
    """

    source_sha: str
    cache_key: str
    relpath: str
    module: str | None
    imports: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    line_count: int = 0
    symbols: list[dict] = field(default_factory=list)

    def symbols_for(self, repo: str) -> list[Symbol]:
        """Re-attach a repo tag to the cached, repo-agnostic symbols."""
        return [
            Symbol(
                repo=repo,
                path=self.relpath,
                qualname=s["qualname"],
                kind=s["kind"],
                start_line=s["start_line"],
                end_line=s["end_line"],
            )
            for s in self.symbols
        ]

    def dumps(self) -> bytes:
        payload = {
            "v": SCHEMA_VERSION,
            "py": PY_TAG,
            "sha": self.source_sha,
            "key": self.cache_key,
            "relpath": self.relpath,
            "module": self.module,
            "imports": self.imports,
            "features": self.features,
            "line_count": self.line_count,
            "symbols": self.symbols,
        }
        return MAGIC + marshal.dumps(payload)

    @classmethod
    def loads(cls, blob: bytes, *, expected_key: str | None = None) -> Self:
        """Deserialize, verifying magic/version/interpreter/key. Raises StaleUnit on mismatch."""
        if blob[:4] != MAGIC:
            raise StaleUnit("bad magic")
        try:
            payload = marshal.loads(blob[4:])
        except (ValueError, EOFError, TypeError) as exc:
            raise StaleUnit(f"corrupt payload: {exc}") from exc
        if not isinstance(payload, dict):
            raise StaleUnit("payload is not a dict")
        if payload.get("v") != SCHEMA_VERSION:
            raise StaleUnit(f"schema {payload.get('v')} != {SCHEMA_VERSION}")
        if payload.get("py") != PY_TAG:
            raise StaleUnit(f"interpreter {payload.get('py')} != {PY_TAG}")
        if expected_key is not None and payload.get("key") != expected_key:
            raise StaleUnit("cache key mismatch (source changed)")
        return cls(
            source_sha=payload["sha"],
            cache_key=payload["key"],
            relpath=payload["relpath"],
            module=payload.get("module"),
            imports=list(payload.get("imports", [])),
            features=list(payload.get("features", [])),
            line_count=int(payload.get("line_count", 0)),
            symbols=list(payload.get("symbols", [])),
        )
