"""Local inference engines behind one LocalEngine interface.

Both engines are lazy and degrade gracefully: on a host without llama-cpp / Ollama / a GPU,
``available()`` returns False and nothing crashes. GPU use is automatic — LlamaCppEngine inherits
model_backend's hardware detection (CUDA/MPS ``n_gpu_layers``), and OllamaEngine forwards ``num_gpu`` so
Ollama offloads to the GPU when one is present.
"""

import json
import os
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from citadel.services.execute.local._backend import load_model_backend


@dataclass(slots=True)
class RunSpec:
    model: str
    quantization: str = "Q4_K_M"
    n_gpu_layers: int = 0
    n_ctx: int = 2048
    threads: int = 1
    max_tokens: int = 512


class LocalEngine(ABC):
    name: str = "local-engine"

    @abstractmethod
    def generate(self, prompt: str, spec: RunSpec) -> str: ...

    @abstractmethod
    def available(self) -> bool: ...

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """Return one dense vector per input text (zero cloud tokens — the dense-retrieval seam).

        Not every engine supports embeddings; the base raises so callers can fall back gracefully
        (the vector store degrades to sparse-only rather than crashing)."""
        raise NotImplementedError(f"{self.name} has no embedding backend")


class LlamaCppEngine(LocalEngine):
    name = "llama_cpp"

    def __init__(self) -> None:
        self._backend = None

    def _get_backend(self):
        if self._backend is not None:
            return self._backend
        mb = load_model_backend()
        if mb is None:
            return None
        try:
            self._backend = mb.get_backend()
        except Exception:
            return None
        return self._backend

    def available(self) -> bool:
        backend = self._get_backend()
        if backend is None:
            return False
        try:
            return bool(backend.is_fully_operational())
        except Exception:
            return False

    def generate(self, prompt: str, spec: RunSpec) -> str:
        backend = self._get_backend()
        if backend is None:
            raise RuntimeError("llama_cpp backend unavailable")
        return backend.generate(prompt, max_tokens=spec.max_tokens)

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        backend = self._get_backend()
        embed_fn = getattr(backend, "embed", None) if backend is not None else None
        if embed_fn is None:
            raise NotImplementedError("llama_cpp backend has no embed()")
        return [list(embed_fn(text)) for text in texts]


def _default_http_post(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _default_http_get(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class OllamaEngine(LocalEngine):
    name = "ollama"

    def __init__(
        self,
        host: str | None = None,
        http_post: Callable[[str, dict, float], dict] | None = None,
        http_get: Callable[[str, float], dict] | None = None,
        timeout: float = 120.0,
    ) -> None:
        # Default to CITADEL_OLLAMA_HOST when set (e.g. http://host.docker.internal:11434 inside a container),
        # else localhost. An explicit `host=` argument always wins.
        resolved = host or os.environ.get("CITADEL_OLLAMA_HOST") or "http://localhost:11434"
        self._host = resolved.rstrip("/")
        self._http_post = http_post or _default_http_post
        self._http_get = http_get or _default_http_get
        self._timeout = timeout

    def available(self) -> bool:
        try:
            self._http_get(f"{self._host}/api/tags", 2.0)
            return True
        except Exception:
            return False

    def generate(self, prompt: str, spec: RunSpec) -> str:
        payload = {
            "model": spec.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": spec.n_ctx, "num_gpu": spec.n_gpu_layers, "num_thread": spec.threads},
        }
        result = self._http_post(f"{self._host}/api/generate", payload, self._timeout)
        return str(result.get("response", "")).strip()

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """Batch via /api/embed; fall back to per-text /api/embeddings on older Ollama builds."""
        if not texts:
            return []
        try:
            result = self._http_post(f"{self._host}/api/embed", {"model": model, "input": texts}, self._timeout)
            vectors = result.get("embeddings")
            if isinstance(vectors, list) and len(vectors) == len(texts):
                return [[float(x) for x in vec] for vec in vectors]
        except Exception:
            pass
        out: list[list[float]] = []
        for text in texts:
            single = self._http_post(f"{self._host}/api/embeddings", {"model": model, "prompt": text}, self._timeout)
            out.append([float(x) for x in single.get("embedding", [])])
        return out


_ENGINES: dict[str, type[LocalEngine]] = {"llama_cpp": LlamaCppEngine, "ollama": OllamaEngine}


def get_local_engine(name: str | None = None) -> LocalEngine:
    key = (name or os.environ.get("CITADEL_LOCAL_ENGINE", "llama_cpp")).lower()
    engine_cls = _ENGINES.get(key)
    if engine_cls is None:
        raise ValueError(f"unknown local engine {key!r}; choose from {sorted(_ENGINES)}")
    return engine_cls()
