"""compiler.py — turn source bytes into a `LegionUnit` (one `ast` parse, cached forever).

Reuses the Phase-2 extractors (`services.index.symbols.extract_symbols` and
`services.index.imports.extract_import_targets`) so there is exactly one implementation of
"what facts we pull from a file" (DRY). The result is repo-agnostic: symbols carry only
their qualname/kind/line-span, so an identical file shared across companies compiles once.
"""

import hashlib
from dataclasses import asdict
from pathlib import Path

from citadel.services.compile.unit import LegionUnit
from citadel.services.index.imports import extract_import_targets
from citadel.services.index.symbols import extract_symbols


def _sha256_hex(data: bytes) -> str:
    """Full SHA-256 hex — identical to tools/_content_address.content_hash."""
    return hashlib.sha256(data).hexdigest()


def compute_keys(relpath: str, source_bytes: bytes) -> tuple[str, str]:
    """Return (source_sha, cache_key). cache_key folds in relpath so identical content at
    identical paths dedups across repos, while different paths never collide."""
    source_sha = _sha256_hex(source_bytes)
    cache_key = _sha256_hex(f"{source_sha}::{relpath}".encode())
    return source_sha, cache_key


def module_from_relpath(relpath: str) -> str | None:
    """Dotted module name from a repo-relative .py path (drops __init__)."""
    parts = list(Path(relpath).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


class LegionCompiler:
    """Compiles source → LegionUnit. Stateless; safe to share across threads."""

    def compile(self, relpath: str, source_bytes: bytes) -> LegionUnit:
        source_sha, cache_key = compute_keys(relpath, source_bytes)
        try:
            source = source_bytes.decode("utf-8")
        except UnicodeDecodeError:
            source = ""
        module = module_from_relpath(relpath)
        symbols = [
            {k: v for k, v in asdict(s).items() if k not in ("repo",)}
            for s in extract_symbols(source, "", relpath)
        ]
        imports = sorted(extract_import_targets(source, module or ""))
        return LegionUnit(
            source_sha=source_sha,
            cache_key=cache_key,
            relpath=relpath,
            module=module,
            imports=imports,
            features=[],
            line_count=source.count("\n") + 1 if source else 0,
            symbols=symbols,
        )
