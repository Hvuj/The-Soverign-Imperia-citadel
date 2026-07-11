"""Full-codebase smoke coverage: every tools/ + src/ file compiles (no syntax errors), and every
importable citadel module imports cleanly (catches import-time crashes like the importlib.util bug)."""

import importlib
import py_compile
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"


def _all_py(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


_COMPILE_TARGETS = _all_py(_ROOT / "tools") + _all_py(_SRC)


@pytest.mark.parametrize("path", _COMPILE_TARGETS, ids=lambda p: str(p.relative_to(_ROOT)))
def test_every_file_compiles(path: Path):
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        pytest.fail(f"{path.relative_to(_ROOT)} does not compile: {exc}")


def _citadel_modules() -> list[str]:
    base = _SRC / "citadel"
    mods = set()
    for p in base.rglob("*.py"):
        if "__pycache__" in p.parts or "assets" in p.parts:
            continue
        rel = p.relative_to(_SRC).with_suffix("")
        parts = [part for part in rel.parts if part != "__init__"]
        mods.add(".".join(parts))
    return sorted(m for m in mods if m)


@pytest.mark.parametrize("modname", _citadel_modules())
def test_citadel_module_imports(modname: str):
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    try:
        importlib.import_module(modname)
    except ImportError as exc:
        pytest.skip(f"optional dependency missing for {modname}: {exc}")
