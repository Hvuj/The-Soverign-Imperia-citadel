"""Tests for the internal import graph — edges, BFS reachability, cycle detection."""

from citadel.services.index.imports import (
    AstImportGraph,
    extract_import_targets,
    module_name,
)


def test_module_name(tmp_path):
    root = tmp_path
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    assert module_name(root, root / "pkg" / "mod.py") == "pkg.mod"
    assert module_name(root, root / "pkg" / "__init__.py") == "pkg"


def test_relative_import_resolution():
    targets = extract_import_targets("from . import sibling\n", "pkg.sub.mod")
    assert "pkg.sub" in targets or "pkg.sub.sibling" in targets
    targets2 = extract_import_targets("from ..other import thing\n", "pkg.sub.mod")
    assert "pkg.other" in targets2


def test_neighbors_and_reverse():
    graph = AstImportGraph({"a": ["b", "c"], "b": ["c"], "c": []})
    assert graph.neighbors("a") == ["b", "c"]
    assert graph.reverse_neighbors("c") == ["a", "b"]
    assert graph.neighbors("missing") == []


def test_reachable_bfs():
    graph = AstImportGraph({"a": ["b"], "b": ["c"], "c": ["d"], "d": []})
    assert graph.reachable("a") == {"b", "c", "d"}
    assert graph.reachable("d") == set()


def test_cycle_detection_simple():
    graph = AstImportGraph({"a": ["b"], "b": ["c"], "c": ["a"]})
    cycles = graph.cycles()
    assert len(cycles) == 1
    assert set(cycles[0]) == {"a", "b", "c"}


def test_self_loop_is_cycle():
    graph = AstImportGraph({"a": ["a"], "b": []})
    cycles = graph.cycles()
    assert cycles == [["a"]]


def test_acyclic_has_no_cycles():
    graph = AstImportGraph({"a": ["b", "c"], "b": ["c"], "c": []})
    assert graph.cycles() == []


def test_two_disjoint_cycles():
    graph = AstImportGraph(
        {"a": ["b"], "b": ["a"], "x": ["y"], "y": ["z"], "z": ["x"], "iso": []}
    )
    cycles = {frozenset(c) for c in graph.cycles()}
    assert frozenset({"a", "b"}) in cycles
    assert frozenset({"x", "y", "z"}) in cycles
    assert len(cycles) == 2


def test_roundtrip_save_load(tmp_path):
    graph = AstImportGraph({"a": ["b"], "b": ["a"]})
    out = tmp_path / "g.json"
    cyc = tmp_path / "c.json"
    graph.save(out, cyc)
    reloaded = AstImportGraph.load(out)
    assert reloaded.neighbors("a") == ["b"]
    assert reloaded.cycles() == [["a", "b"]]
