"""Lazy loader for tools/model_backend.py.

Keeps the execute package importable when the tools dir is not on sys.path (installed layout) and when
no ML libraries are present. Returns None when model_backend cannot be located, so callers degrade.
"""

import sys
from pathlib import Path
from types import ModuleType

_cache: ModuleType | None = None


def load_model_backend() -> ModuleType | None:
    global _cache
    if _cache is not None:
        return _cache
    try:
        import model_backend as mb
    except ImportError:
        tools = Path(__file__).resolve().parents[5] / "tools"
        if tools.is_dir() and str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        try:
            import model_backend as mb
        except ImportError:
            return None
    _cache = mb
    return mb
