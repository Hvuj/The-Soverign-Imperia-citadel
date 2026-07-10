#!/usr/bin/env python3
"""Structure Co. (SOLID) — class cohesion via method-to-field intersection."""


import ast
import sys
from pathlib import Path


class SOLIDAnalyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.classes_cohesion: list[float] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if len(methods) <= 1:
            self.classes_cohesion.append(1.0)
            self.generic_visit(node)
            return

        method_fields: dict[str, set[str]] = {}
        for method in methods:
            fields: set[str] = set()
            for child in ast.walk(method):
                if (
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "self"
                ):
                    fields.add(child.attr)
            method_fields[method.name] = fields

        connected = 0
        total = 0
        names = list(method_fields)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                total += 1
                if method_fields[names[i]] & method_fields[names[j]]:
                    connected += 1

        self.classes_cohesion.append(connected / total if total > 0 else 1.0)
        self.generic_visit(node)


def analyze_file(file_path: str) -> float:
    path = Path(file_path)
    if not path.exists():
        return 1.0
    try:
        root = ast.parse(path.read_text(encoding="utf-8"))
        analyzer = SOLIDAnalyzer()
        analyzer.visit(root)
        if not analyzer.classes_cohesion:
            return 1.0
        return sum(analyzer.classes_cohesion) / len(analyzer.classes_cohesion)
    except Exception:
        return 0.5


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else __file__
    print(round(analyze_file(target), 4))
