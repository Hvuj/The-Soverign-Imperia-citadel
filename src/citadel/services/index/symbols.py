"""symbols.py — AST-based symbol index with O(1) lookup and O(log N) line resolution.

Parses Python source with the stdlib `ast` module into `Symbol` records carrying an
inclusive line span, then backs them with two structures:

  * ``_by_qualname``: dict (repo, qualname) -> Symbol           — O(1) exact lookup
  * ``_by_file``: (repo, path) -> parallel arrays of start lines — O(log N) via bisect

``enclosing(repo, path, line)`` returns the *innermost* symbol whose span contains the
line, which is what lets the commit indexer map a changed line range to the function it
lives in (Phase 3). No third-party dependencies.
"""
import ast
import bisect
import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from citadel.services.index.base import Symbol, SymbolIndex

SCHEMA_VERSION = "1.0"

_EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", ".eggs", "node_modules",
    "dist", "build", "target", ".idea", ".vscode", ".parcompute-worker-space",
    ".ipynb_checkpoints", "coverage", "htmlcov",
}


def extract_symbols(source: str, repo: str, relpath: str) -> list[Symbol]:
    """Extract every function/class/method from `source` with its line span.

    Nested definitions get dotted qualnames (``Class.method``, ``outer.inner``). A
    syntax error yields an empty list rather than raising — one unparseable file must
    not abort a whole-repo build (fail-soft on untrusted input).
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []

    out: list[Symbol] = []

    def visit(node: ast.AST, prefix: str, parent_is_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = child.name
                qualname = f"{prefix}.{name}" if prefix else name
                if isinstance(child, ast.ClassDef):
                    kind = "class"
                elif parent_is_class:
                    kind = "method"
                elif isinstance(child, ast.AsyncFunctionDef):
                    kind = "async_function"
                else:
                    kind = "function"
                end_line = child.end_lineno or child.lineno
                out.append(
                    Symbol(
                        repo=repo,
                        path=relpath,
                        qualname=qualname,
                        kind=kind,
                        start_line=child.lineno,
                        end_line=end_line,
                    )
                )
                visit(child, qualname, isinstance(child, ast.ClassDef))

    visit(tree, "", False)
    return out


def iter_python_files(root: Path) -> Iterator[Path]:
    """Yield .py files under `root`, skipping virtualenv/cache/vcs directories."""
    for path in root.rglob("*.py"):
        if any(part in _EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


class AstSymbolIndex(SymbolIndex):
    """In-memory symbol index built from `Symbol` records; JSON-serializable."""

    def __init__(self, symbols: Iterable[Symbol] = ()) -> None:
        self._symbols: list[Symbol] = list(symbols)
        self._by_qualname: dict[tuple[str, str], Symbol] = {}
        self._by_file: dict[tuple[str, str], tuple[list[int], list[Symbol]]] = {}
        self._reindex()

    def _reindex(self) -> None:
        self._by_qualname.clear()
        self._by_file.clear()
        buckets: dict[tuple[str, str], list[Symbol]] = {}
        for sym in self._symbols:
            self._by_qualname[(sym.repo, sym.qualname)] = sym
            buckets.setdefault((sym.repo, sym.path), []).append(sym)
        for key, syms in buckets.items():
            syms.sort(key=lambda s: (s.start_line, s.end_line))
            starts = [s.start_line for s in syms]
            self._by_file[key] = (starts, syms)

    @classmethod
    def build_for_repo(cls, repo_id: str, repo_path: Path) -> Self:
        """Parse every .py file under `repo_path`, tagging symbols with `repo_id`."""
        symbols: list[Symbol] = []
        root = Path(repo_path)
        for py in iter_python_files(root):
            try:
                source = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            relpath = py.relative_to(root).as_posix()
            symbols.extend(extract_symbols(source, repo_id, relpath))
        return cls(symbols)

    def lookup(self, repo: str, qualname: str) -> Symbol | None:
        return self._by_qualname.get((repo, qualname))

    def enclosing(self, repo: str, path: str, line: int) -> Symbol | None:
        entry = self._by_file.get((repo, path))
        if entry is None:
            return None
        starts, syms = entry
        idx = bisect.bisect_right(starts, line) - 1
        best: Symbol | None = None
        while idx >= 0:
            candidate = syms[idx]
            if candidate.contains(line):
                if best is None or candidate.start_line > best.start_line:
                    best = candidate
                break
            idx -= 1
        return best

    def symbols(self) -> Iterable[Symbol]:
        return iter(self._symbols)

    def __len__(self) -> int:
        return len(self._symbols)

    def to_payload(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "symbols": [asdict(s) for s in self._symbols],
        }

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_payload(), indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        symbols = [Symbol(**rec) for rec in data.get("symbols", [])]
        return cls(symbols)
