"""build.py — construct code indexes from the `__legion__` cache (one compile, many readers).

This is the seam that unifies extraction: instead of each index re-parsing every `.py`, both
the symbol index and the import graph are assembled from cached `LegionUnit`s (compile-on-miss
via `LegionStore`). Lives in its own module so `services.index` has no dependency on
`services.compile` (which already depends on `services.index`) — no import cycle.
"""

from citadel.services.compile import LegionStore
from citadel.services.corporate import Company
from citadel.services.index.imports import AstImportGraph, _internal_edge
from citadel.services.index.symbols import AstSymbolIndex, Symbol, iter_python_files


def _units_for_company(store: LegionStore, company: Company):
    """Yield (relpath, unit) for every Python file in a company, via the cache."""
    root = company.python_path
    for py in iter_python_files(root):
        relpath = py.relative_to(root).as_posix()
        unit = store.get_path(company.repo_id, relpath, py)
        if unit is not None:
            yield relpath, unit


def build_symbol_index(store: LegionStore, company: Company) -> AstSymbolIndex:
    """Symbol index for a company, sourced from cached units."""
    symbols: list[Symbol] = []
    for _relpath, unit in _units_for_company(store, company):
        symbols.extend(unit.symbols_for(company.repo_id))
    return AstSymbolIndex(symbols)


def build_import_graph(store: LegionStore, company: Company) -> AstImportGraph:
    """Internal import DAG for a company, sourced from cached units.

    Resolution (absolute import target → internal module edge) happens here, from the set
    of modules present in the repo — the cached unit stores the raw absolute targets.
    """
    module_imports: dict[str, list[str]] = {}
    for _relpath, unit in _units_for_company(store, company):
        if unit.module:
            module_imports[unit.module] = unit.imports
    internal = set(module_imports)
    adjacency: dict[str, list[str]] = {}
    for module, targets in module_imports.items():
        edges = set()
        for target in targets:
            dst = _internal_edge(target, internal)
            if dst and dst != module:
                edges.add(dst)
        adjacency[module] = sorted(edges)
    return AstImportGraph(adjacency)
