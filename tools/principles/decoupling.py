#!/usr/bin/env python3
"""Decoupling Co. (Law of Demeter) — penalizes attribute train-wrecks + efferent import fan-out."""


import ast
import sys
from pathlib import Path


class DecouplingAnalyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.attributes = 0
        self.train_wrecks = 0
        self.imports = 0

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.attributes += 1
        if isinstance(node.value, ast.Attribute):
            self.train_wrecks += 1
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.imports += len(node.names)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports += len(node.names)
        self.generic_visit(node)


def analyze_file(file_path: str) -> float:
    path = Path(file_path)
    if not path.exists():
        return 1.0
    try:
        analyzer = DecouplingAnalyzer()
        analyzer.visit(ast.parse(path.read_text(encoding="utf-8")))
        chain_score = 1.0 if analyzer.attributes == 0 else 1.0 - analyzer.train_wrecks / analyzer.attributes
        import_score = 10.0 / (10.0 + analyzer.imports)
        return max(0.0, min(1.0, (chain_score + import_score) / 2.0))
    except Exception:
        return 0.5


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else __file__
    print(round(analyze_file(target), 4))
