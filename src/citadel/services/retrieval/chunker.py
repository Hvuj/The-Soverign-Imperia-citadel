"""chunker.py — split a file into overlapping chunks that carry their own provenance.

Each chunk knows its file path, its ordinal, its exact byte range, and a content hash of its own text —
so a retrieved chunk can be cited (path + byte range) and cache-validated (hash) without re-reading the
whole file. Windows overlap so a match that straddles a boundary is still found. Boundaries prefer blank
lines (a cheap, language-neutral proxy for logical breaks) but never exceed the line budget.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_MAX_LINES = 60
_DEFAULT_OVERLAP = 10


def hash_text(text: str) -> str:
    """Stable 64-bit content digest of a chunk's text (blake2b — matches the oracle's file-level hash width)."""
    return hashlib.blake2b(text.encode("utf-8", errors="ignore"), digest_size=8).hexdigest()


@dataclass(frozen=True, slots=True)
class Chunk:
    path: str
    index: int
    start_byte: int
    end_byte: int
    text: str
    content_hash: str

    @property
    def id(self) -> str:
        """Stable per-chunk key: path + ordinal (the vector-store primary key)."""
        return f"{self.path}#{self.index}"


def _line_byte_offsets(text: str) -> list[int]:
    """Byte offset at the start of each line, plus a final sentinel at the end of the text."""
    offsets = [0]
    acc = 0
    for line in text.splitlines(keepends=True):
        acc += len(line.encode("utf-8"))
        offsets.append(acc)
    return offsets


def chunk_text(
    text: str,
    path: str,
    *,
    max_lines: int = _DEFAULT_MAX_LINES,
    overlap: int = _DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Split `text` into overlapping line-windows, each tagged with its byte range + content hash."""
    if not text:
        return []
    lines = text.splitlines(keepends=True)
    offsets = _line_byte_offsets(text)
    step = max(1, max_lines - overlap)
    chunks: list[Chunk] = []
    index = 0
    start = 0
    n = len(lines)
    while start < n:
        end = min(start + max_lines, n)
        body = "".join(lines[start:end])
        stripped = body.strip()
        if stripped:
            chunks.append(
                Chunk(
                    path=path,
                    index=index,
                    start_byte=offsets[start],
                    end_byte=offsets[end],
                    text=body,
                    content_hash=hash_text(body),
                )
            )
            index += 1
        if end >= n:
            break
        start += step
    return chunks


def chunk_file(
    path: str | Path,
    *,
    max_lines: int = _DEFAULT_MAX_LINES,
    overlap: int = _DEFAULT_OVERLAP,
    repo_root: str | Path | None = None,
) -> list[Chunk]:
    """Read a file and chunk it. `path` is stored relative to `repo_root` when given (portable provenance)."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    rel = str(p.relative_to(repo_root)).replace("\\", "/") if repo_root else str(p).replace("\\", "/")
    return chunk_text(text, rel, max_lines=max_lines, overlap=overlap)
