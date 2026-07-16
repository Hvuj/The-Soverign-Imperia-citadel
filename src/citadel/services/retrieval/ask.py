"""ask.py — the grounded, zero-token answer path (Phase Z3).

Retrieve cited context locally → build a grounded prompt → answer on the local model (free) → cache the
answer with the content hashes of every file it cited. A repeated question is served from cache **only** if
every cited file is still fresh (D3, weak-spot #1); a changed file forces a fresh answer. `generate` is
injected so this is testable without a live model and swappable for the cloud tier as a last resort. The
answer always carries citations (path + byte range), so it is verifiable — never a confident guess.
"""

from collections.abc import Callable
from pathlib import Path

from citadel.services.retrieval.answer_cache import AnswerCache, make_query_key
from citadel.services.retrieval.service import RetrievalService


def _oracle():
    try:
        from citadel.services._tools_bridge import import_tool

        return import_tool("citadel_oracle")
    except Exception:
        return None


def _citations_fresh(citations: list[dict], workspace: str | Path) -> bool:
    """True only if every distinct cited file still hashes to the value stored with the answer (D3)."""
    oracle = _oracle()
    if oracle is None:
        return False
    ws = Path(workspace)
    checked: dict[str, bool] = {}
    for cite in citations:
        path, fhash = cite.get("path"), cite.get("file_hash")
        if not path or not fhash:
            return False
        if path not in checked:
            checked[path] = oracle.is_fresh(ws / path, fhash)
        if not checked[path]:
            return False
    return True


def _build_prompt(query: str, chunks: list[dict]) -> str:
    blocks = []
    for chunk in chunks:
        blocks.append(f"# {chunk['path']} (bytes {chunk['start_byte']}-{chunk['end_byte']})\n{chunk['snippet']}")
    context = "\n\n".join(blocks)
    return (
        "You are answering a question using ONLY the workspace context below. Cite files by path. If the "
        "context is insufficient, say so plainly.\n\n"
        f"## Context\n{context}\n\n## Question\n{query}\n\n## Answer\n"
    )


def answer_question(
    query: str,
    *,
    service: RetrievalService,
    generate: Callable[[str], str],
    workspace: str | Path,
    cache: AnswerCache | None = None,
    top_k: int = 6,
    budget_bytes: int = 24 * 1024,
) -> dict:
    """Answer a question grounded in local retrieval. Returns {answer, citations, cached, grounded}."""
    key = make_query_key(query)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            if _citations_fresh(hit.get("citations", []), workspace):
                return {"answer": hit["answer"], "citations": hit["citations"], "cached": True, "grounded": True}
            cache.invalidate(key)  # a cited file changed → the cached answer is stale

    capsule = service.context(query, top_k=top_k, budget_bytes=budget_bytes)
    chunks = capsule["chunks"]
    citations = [
        {
            "path": c["path"], "start_byte": c["start_byte"], "end_byte": c["end_byte"],
            "file_hash": service.store.stored_file_hash(c["path"]) or "",
        }
        for c in chunks
    ]
    prompt = _build_prompt(query, chunks) if chunks else query
    text = generate(prompt).strip()

    if cache is not None and citations and all(c["file_hash"] for c in citations):
        cache.put(key, text, citations)
    return {"answer": text, "citations": citations, "cached": False, "grounded": bool(chunks)}
