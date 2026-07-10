"""citadel.services.compile — the `__legion__` compiled-cache layer.

Python source is not a form the legion can read efficiently — it must re-parse `.py`
with `ast` on every index build. This package compiles each file's source-derived facts
(symbols with line spans, imports, module, line count) **once** into a compact `marshal`
binary unit (`.legion`), keyed by content hash, exactly like CPython's `.pyc`/`__pycache__`.
Every consumer (symbol index, import graph, workspace-intel) then reads the unit instead
of re-parsing — the legion's own machine-readable representation.
"""

from citadel.services.compile.compiler import LegionCompiler
from citadel.services.compile.store import LegionStore
from citadel.services.compile.unit import LegionUnit, StaleUnit

__all__ = ["LegionCompiler", "LegionStore", "LegionUnit", "StaleUnit"]
