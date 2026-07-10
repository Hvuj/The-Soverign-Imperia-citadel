#!/usr/bin/env python3
"""Encapsulation Co. (OOP) — rewards private/property members over bare public data attributes."""


import ast
import sys
from pathlib import Path


def _property_names(cls: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for item in cls.body:
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            for dec in item.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "property":
                    names.add(item.name)
    return names


def _self_attribute_targets(cls: ast.ClassDef) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(cls):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Attribute)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == "self"
                ):
                    targets.add(tgt.attr)
    return targets


def _class_score(cls: ast.ClassDef) -> float:
    properties = _property_names(cls)
    attrs = _self_attribute_targets(cls)
    internal = {a for a in attrs if a.startswith("_")}
    public_data = {a for a in attrs if not a.startswith("_") and a not in properties}
    total = len(internal) + len(public_data) + len(properties)
    if total == 0:
        return 1.0
    return (len(internal) + len(properties)) / total


def analyze_file(file_path: str) -> float:
    path = Path(file_path)
    if not path.exists():
        return 1.0
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        if not classes:
            return 1.0
        scores = [_class_score(c) for c in classes]
        return max(0.0, min(1.0, sum(scores) / len(scores)))
    except Exception:
        return 0.5


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else __file__
    print(round(analyze_file(target), 4))
