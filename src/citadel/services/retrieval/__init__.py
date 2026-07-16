"""citadel.services.retrieval — the dense/semantic layer (Zero-Token Sovereign, Phase Z0).

Turns files into redacted, provenance-carrying chunks, embeds them behind the model-agnostic
`LocalEngine.embed()` seam, and stores/queries vectors in Redis (RediSearch HNSW) with a pure-Python
cosine fallback. Every cached read is content-hash-gated (D3) and every chunk is secret-scrubbed before it
is ever vectorized (weak-spot #5). Nothing here spends a model token.
"""

from citadel.services.retrieval.answer_cache import AnswerCache, make_query_key
from citadel.services.retrieval.ask import answer_question
from citadel.services.retrieval.chunker import Chunk, chunk_file, chunk_text, hash_text
from citadel.services.retrieval.embed_cache import EmbedCache
from citadel.services.retrieval.indexer import IndexResult, index_file, is_stale, search
from citadel.services.retrieval.learner import RetrieverLearner
from citadel.services.retrieval.redact_gate import redact_chunks
from citadel.services.retrieval.service import RetrievalService
from citadel.services.retrieval.vector_store import VectorRecord, VectorStore, cosine
from citadel.services.retrieval.worker import EmbedderWorker

__all__ = [
    "AnswerCache",
    "Chunk",
    "EmbedCache",
    "EmbedderWorker",
    "IndexResult",
    "RetrievalService",
    "RetrieverLearner",
    "VectorRecord",
    "VectorStore",
    "answer_question",
    "chunk_file",
    "chunk_text",
    "cosine",
    "hash_text",
    "index_file",
    "is_stale",
    "make_query_key",
    "redact_chunks",
    "search",
]
