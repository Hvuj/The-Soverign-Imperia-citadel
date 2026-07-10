#!/usr/bin/env python3
"""Frugality Co. (YAGNI) — detects over-building via pass-body and ellipsis-only functions."""


import ast
import sys
from pathlib import Path


class YAGNIAnalyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.unused_count = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if len(node.body) == 1 and isinstance(node.body[0], (ast.Pass, ast.Expr)):
            stmt = node.body[0]
            is_ellipsis = (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and stmt.value.value is ...
            )
            is_pass = isinstance(stmt, ast.Pass)
            if is_pass or is_ellipsis:
                self.unused_count += 1
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]


def analyze_file(file_path: str) -> float:
    path = Path(file_path)
    if not path.exists():
        return 1.0
    try:
        root = ast.parse(path.read_text(encoding="utf-8"))
        analyzer = YAGNIAnalyzer()
        analyzer.visit(root)
        return max(0.0, min(1.0, 1.0 - analyzer.unused_count * 0.1))
    except Exception:
        return 0.5


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else __file__
    print(round(analyze_file(target), 4))
