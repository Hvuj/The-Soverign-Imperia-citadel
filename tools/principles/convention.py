#!/usr/bin/env python3
"""Convention Co. (CoC) — PEP8 naming compliance for classes, functions, and arguments."""


import ast
import re
import sys
from pathlib import Path

_CAPWORDS = re.compile(r"^_?[A-Z][a-zA-Z0-9]*$")
_SNAKE = re.compile(r"^[a-z_][a-z0-9_]*$")
_DUNDER = re.compile(r"^__[a-z0-9_]+__$")
_EXEMPT_ARGS = frozenset({"self", "cls"})


class ConventionAnalyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.total = 0
        self.violations = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.total += 1
        if not _CAPWORDS.match(node.name):
            self.violations += 1
        self.generic_visit(node)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.total += 1
        if not (_SNAKE.match(node.name) or _DUNDER.match(node.name)):
            self.violations += 1
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if arg.arg in _EXEMPT_ARGS:
                continue
            self.total += 1
            if not _SNAKE.match(arg.arg):
                self.violations += 1
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node)


def analyze_file(file_path: str) -> float:
    path = Path(file_path)
    if not path.exists():
        return 1.0
    try:
        analyzer = ConventionAnalyzer()
        analyzer.visit(ast.parse(path.read_text(encoding="utf-8")))
        if analyzer.total == 0:
            return 1.0
        return max(0.0, min(1.0, 1.0 - analyzer.violations / analyzer.total))
    except Exception:
        return 0.5


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else __file__
    print(round(analyze_file(target), 4))
