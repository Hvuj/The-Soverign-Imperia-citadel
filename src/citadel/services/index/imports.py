"""imports.py — internal import dependency graph with cycle detection.

Builds a directed graph whose nodes are the repo's *internal* modules (external /
stdlib imports are dropped — they cannot participate in an internal cycle and only
add noise). Provides:

  * O(1) neighbor / reverse-neighbor lookup (adjacency dicts),
  * BFS reachability closure (collections.deque),
  * cycle detection via iterative Tarjan strongly-connected-components — the literal
    "cyclic trees" the request asks for (a DAG that has become cyclic).

Iterative Tarjan is used (not recursive) so deep import chains cannot hit Python's
recursion limit. No third-party dependencies.
"""
import ast
import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from citadel.services.index.base import ImportGraphIndex
from citadel.services.index.symbols import iter_python_files

SCHEMA_VERSION = "1.0"


def module_name(python_root: Path, py_file: Path) -> str | None:
    """Dotted module name of `py_file` relative to `python_root` (None if outside)."""
    try:
        rel = py_file.relative_to(python_root)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _resolve_relative(current: str, level: int, module: str | None) -> str | None:
    """Resolve a relative import target to an absolute dotted module name."""
    parts = current.split(".")
    base = parts[: len(parts) - level] if level <= len(parts) else []
    if module:
        base = base + module.split(".")
    return ".".join(base) if base else None


def extract_import_targets(source: str, current_module: str) -> set[str]:
    """Return the set of dotted module names imported by `source`.

    Relative imports are resolved against `current_module`. Returns absolute-ish
    dotted names; the caller filters these against the set of internal modules.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                resolved = _resolve_relative(current_module, node.level, node.module)
                if resolved:
                    targets.add(resolved)
                    for alias in node.names:
                        targets.add(f"{resolved}.{alias.name}")
            elif node.module:
                targets.add(node.module)
                for alias in node.names:
                    targets.add(f"{node.module}.{alias.name}")
    return targets


def _internal_edge(target: str, internal: set[str]) -> str | None:
    """Map an import target to the longest internal module that is a prefix of it."""
    if target in internal:
        return target
    parts = target.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:cut])
        if candidate in internal:
            return candidate
    return None


class AstImportGraph(ImportGraphIndex):
    """Directed internal-import graph with traversal + Tarjan cycle detection."""

    def __init__(self, adjacency: dict[str, list[str]]) -> None:
        self._adj: dict[str, list[str]] = {m: sorted(set(t)) for m, t in adjacency.items()}
        for targets in list(self._adj.values()):
            for t in targets:
                self._adj.setdefault(t, [])
        self._radj: dict[str, list[str]] = {m: [] for m in self._adj}
        for src, targets in self._adj.items():
            for dst in targets:
                self._radj[dst].append(src)
        for m in self._radj:
            self._radj[m] = sorted(set(self._radj[m]))

    @classmethod
    def build_for_repo(cls, repo_path: Path, python_root: str = ".") -> Self:
        root = Path(repo_path) / python_root
        files: dict[str, Path] = {}
        for py in iter_python_files(root):
            mod = module_name(root, py)
            if mod:
                files[mod] = py
        internal = set(files)
        adjacency: dict[str, list[str]] = {mod: [] for mod in internal}
        for mod, py in files.items():
            try:
                source = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            edges: set[str] = set()
            for target in extract_import_targets(source, mod):
                dst = _internal_edge(target, internal)
                if dst and dst != mod:
                    edges.add(dst)
            adjacency[mod] = sorted(edges)
        return cls(adjacency)

    def neighbors(self, module: str) -> list[str]:
        return list(self._adj.get(module, []))

    def reverse_neighbors(self, module: str) -> list[str]:
        return list(self._radj.get(module, []))

    def reachable(self, module: str) -> set[str]:
        """BFS closure of modules reachable from `module` (excludes the seed)."""
        seen: set[str] = set()
        queue: deque[str] = deque(self._adj.get(module, []))
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            queue.extend(n for n in self._adj.get(node, []) if n not in seen)
        return seen

    def cycles(self) -> list[list[str]]:
        """Return non-trivial strongly-connected components (import cycles).

        Iterative Tarjan's algorithm. A component is a cycle if it has more than one
        node, or a single node with a self-edge.
        """
        index_counter = 0
        indices: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        on_stack: dict[str, bool] = {}
        stack: list[str] = []
        result: list[list[str]] = []

        for root in self._adj:
            if root in indices:
                continue
            work: list[tuple[str, int]] = [(root, 0)]
            while work:
                node, pos = work[-1]
                if pos == 0:
                    indices[node] = lowlink[node] = index_counter
                    index_counter += 1
                    stack.append(node)
                    on_stack[node] = True
                neighbors = self._adj.get(node, [])
                if pos < len(neighbors):
                    work[-1] = (node, pos + 1)
                    nxt = neighbors[pos]
                    if nxt not in indices:
                        work.append((nxt, 0))
                    elif on_stack.get(nxt):
                        lowlink[node] = min(lowlink[node], indices[nxt])
                else:
                    if lowlink[node] == indices[node]:
                        component: list[str] = []
                        while True:
                            w = stack.pop()
                            on_stack[w] = False
                            component.append(w)
                            if w == node:
                                break
                        if len(component) > 1 or node in neighbors:
                            result.append(sorted(component))
                    work.pop()
                    if work:
                        parent = work[-1][0]
                        lowlink[parent] = min(lowlink[parent], lowlink[node])
        return result

    def to_payload(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "adjacency": self._adj,
        }

    def save(self, path: Path, cycles_path: Path | None = None) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_payload(), indent=2), encoding="utf-8")
        tmp.replace(path)
        if cycles_path is not None:
            cyc = {
                "schema_version": SCHEMA_VERSION,
                "generated_at": datetime.now(UTC).isoformat(),
                "cycles": self.cycles(),
            }
            cycles_path = Path(cycles_path)
            ctmp = cycles_path.with_suffix(cycles_path.suffix + ".tmp")
            ctmp.write_text(json.dumps(cyc, indent=2), encoding="utf-8")
            ctmp.replace(cycles_path)

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data.get("adjacency", {}))
