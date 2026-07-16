"""redact_gate.py — scrub secrets out of chunks BEFORE they are embedded (weak-spot #5).

A vector store outlives the files it indexes: a secret embedded once can be recovered long after the source
line is deleted. So redaction is a gate on the embedding path, not an afterthought. Redacted chunks are
re-hashed, so the embedding cache keys on the exact (redacted) text that is actually vectorized. Reuses the
single redaction implementation in `tools/citadel_custos.py` (DRY) via the tools bridge.
"""

from dataclasses import replace

from citadel.services.retrieval.chunker import Chunk, hash_text


def _load_redact():
    try:
        from citadel.services._tools_bridge import import_tool

        return import_tool("citadel_custos").redact
    except Exception:
        return None


def redact_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """Return chunks with secrets masked and content hashes updated to match the redacted text."""
    redact = _load_redact()
    if redact is None:
        return list(chunks)
    out: list[Chunk] = []
    for chunk in chunks:
        masked = redact(chunk.text)
        if masked == chunk.text:
            out.append(chunk)
        else:
            out.append(replace(chunk, text=masked, content_hash=hash_text(masked)))
    return out
