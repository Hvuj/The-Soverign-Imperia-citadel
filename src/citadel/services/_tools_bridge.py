"""_tools_bridge — import symbols from the bundled tools/ scripts without duplication.

The tools/*.py scripts are standalone (they run as subprocesses / daemons) but a
handful expose reusable pure functions the service layer wants to call directly
(DRY — one implementation of repo discovery, BM25, etc.). This module resolves the
tools directory the same way the CLI runner does and makes it importable, so the
services never re-implement logic that already lives in tools/.
"""

import importlib
import sys
from types import ModuleType

from citadel.commands._runner import _tools_dir


def import_tool(module_name: str) -> ModuleType:
    """Import a bundled tool module by its file stem (e.g. "_workspace_intel_common").

    Raises ModuleNotFoundError if the tools directory or module is absent, so callers
    can fall back gracefully rather than silently mis-behaving.
    """
    tools_dir = _tools_dir()
    tools_str = str(tools_dir)
    if tools_str not in sys.path:
        sys.path.insert(0, tools_str)
    return importlib.import_module(module_name)
