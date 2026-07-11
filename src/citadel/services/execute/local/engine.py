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
        host: str = "http://localhost:11434",
        http_post: Callable[[str, dict, float], dict] | None = None,
        http_get: Callable[[str, float], dict] | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._host = host.rstrip("/")
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


_ENGINES: dict[str, type[LocalEngine]] = {"llama_cpp": LlamaCppEngine, "ollama": OllamaEngine}


def get_local_engine(name: str | None = None) -> LocalEngine:
    key = (name or os.environ.get("CITADEL_LOCAL_ENGINE", "llama_cpp")).lower()
    engine_cls = _ENGINES.get(key)
    if engine_cls is None:
        raise ValueError(f"unknown local engine {key!r}; choose from {sorted(_ENGINES)}")
    return engine_cls()
