#!/usr/bin/env python3
"""KISS / Simplicity Co. — cyclomatic complexity proxy via AST branch counting."""


import ast
import sys
from pathlib import Path


class KISSAnalyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.complexity_score = 1.0

    def visit_If(self, node: ast.If) -> None:
        self.complexity_score += 1.0
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity_score += 1.0
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity_score += 1.0
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.complexity_score += 1.0
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.complexity_score += len(node.values) - 1
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.complexity_score += 1.0 + len(node.ifs)
        self.generic_visit(node)


def analyze_file(file_path: str) -> float:
    path = Path(file_path)
    if not path.exists():
        return 1.0
    try:
        root = ast.parse(path.read_text(encoding="utf-8"))
        analyzer = KISSAnalyzer()
        analyzer.visit(root)
        raw = analyzer.complexity_score
        return max(0.0, min(1.0, 10.0 / (10.0 + raw - 1.0)))
    except Exception:
        return 0.5


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else __file__
    print(round(analyze_file(target), 4))
