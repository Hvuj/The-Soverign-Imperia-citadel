"""citadel.services.execute.local — the local (Phase-2) execution tier.

Pluggable engines (llama-cpp via model_backend, or Ollama) behind the Phase-1 Executor seam, with a
hardware-aware arbitrator that auto-discovers the GPU and budgets VRAM.
"""

from citadel.services.execute.local.engine import (
    LlamaCppEngine,
    LocalEngine,
    OllamaEngine,
    RunSpec,
    get_local_engine,
)
from citadel.services.execute.local.executor import LocalExecutor
from citadel.services.execute.local.hra import HardwareResourceArbitrator

__all__ = [
    "HardwareResourceArbitrator",
    "LlamaCppEngine",
    "LocalEngine",
    "LocalExecutor",
    "OllamaEngine",
    "RunSpec",
    "get_local_engine",
]
