#!/usr/bin/env python3
"""Craft Co. — docstring coverage + type-annotation coverage as a code-craftsmanship proxy."""


import ast
import sys
from pathlib import Path

_EXEMPT_ARGS = frozenset({"self", "cls"})


def _doc_coverage(tree: ast.Module) -> tuple[int, int]:
    targets: list[ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef] = [tree]
    targets += [
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    covered = sum(1 for t in targets if ast.get_docstring(t) is not None)
    return covered, len(targets)


def _annotation_coverage(tree: ast.Module) -> tuple[int, int]:
    covered = 0
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        total += 1
        covered += 1 if node.returns is not None else 0
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if arg.arg in _EXEMPT_ARGS:
                continue
            total += 1
            covered += 1 if arg.annotation is not None else 0
    return covered, total


def analyze_file(file_path: str) -> float:
    path = Path(file_path)
    if not path.exists():
        return 1.0
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not tree.body:
            return 1.0
        doc_covered, doc_total = _doc_coverage(tree)
        ann_covered, ann_total = _annotation_coverage(tree)
        doc_score = 1.0 if doc_total == 0 else doc_covered / doc_total
        ann_score = 1.0 if ann_total == 0 else ann_covered / ann_total
        return max(0.0, min(1.0, (doc_score + ann_score) / 2.0))
    except Exception:
        return 0.5


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else __file__
    print(round(analyze_file(target), 4))
