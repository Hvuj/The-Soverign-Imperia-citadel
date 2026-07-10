#!/usr/bin/env python3
"""build_cross_repo_edges.py — Detect real Python cross-repo import dependencies.

For each workspace repo (company), determines its own importable top-level package
name(s) — from `pyproject.toml`'s `[project].name`/`[tool.poetry].name` (normalized to
underscores) and any top-level package/module actually present directly under its
`python_root` — then scans every OTHER repo's absolute (non-relative) imports for a
top-level name matching one of those. These are genuine Python import edges, not a
name-guessing heuristic: a repo is never credited with owning a name unless that name
is either its declared package name or a real directory/module on disk, and stdlib
names are excluded from candidacy so a repo cannot "claim" e.g. `import os`.

Writes the aggregated edge list to:
    <workspace>/docs/brain/workspace/cross-repo-edges.json

Usage:
    python tools/build_cross_repo_edges.py
    python tools/build_cross_repo_edges.py --quiet
"""

import argparse
import ast
import json
import sys
import tomllib
from collections import defaultdict
from datetime import UTC, datetime

from citadel.paths import docs_brain_dir
from citadel.services.corporate import Company, Legion
from citadel.services.index.symbols import iter_python_files

SCHEMA_VERSION = "1.0"
_MAX_EXAMPLE_FILES = 5
_STDLIB_NAMES = frozenset(sys.stdlib_module_names) | frozenset({"__future__"})


def _pyproject_name(company: Company) -> str | None:
    pp = company.path / "pyproject.toml"
    if not pp.is_file():
        return None
    try:
        with pp.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    name = (
        data.get("project", {}).get("name")
        or data.get("tool", {}).get("poetry", {}).get("name")
    )
    return name.replace("-", "_") if isinstance(name, str) and name else None


def _top_level_packages(company: Company) -> set[str]:
    """Return this company's verified importable top-level names (never a name guess)."""
    names: set[str] = set()
    pkg_name = _pyproject_name(company)
    if pkg_name and pkg_name not in _STDLIB_NAMES:
        names.add(pkg_name)
    root = company.python_path
    if root.is_dir():
        for entry in root.iterdir():
            if entry.name in _STDLIB_NAMES:
                continue
            if entry.is_dir() and (entry / "__init__.py").is_file():
                names.add(entry.name)
            elif entry.is_file() and entry.suffix == ".py" and entry.stem != "__init__":
                names.add(entry.stem)
    return names


def _top_level_imports(source: str) -> set[str]:
    """Return top-level package names from absolute (non-relative) imports only."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def build_cross_repo_edges(companies: list[Company]) -> dict:
    """Scan every company's imports for a name verifiably owned by another company."""
    owner_of: dict[str, str] = {}
    ambiguous: set[str] = set()
    for company in companies:
        for name in _top_level_packages(company):
            if name in owner_of and owner_of[name] != company.repo_id:
                ambiguous.add(name)
            else:
                owner_of[name] = company.repo_id
    for name in ambiguous:
        owner_of.pop(name, None)

    edge_examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    for company in companies:
        root = company.python_path if company.python_path.is_dir() else company.path
        for py in iter_python_files(root):
            try:
                source = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for name in _top_level_imports(source):
                target_repo = owner_of.get(name)
                if target_repo is None or target_repo == company.repo_id:
                    continue
                key = (company.repo_id, target_repo)
                edge_counts[key] += 1
                if len(edge_examples[key]) < _MAX_EXAMPLE_FILES:
                    rel = py.relative_to(root).as_posix()
                    edge_examples[key].append(f"{rel} (import {name})")

    edges = [
        {
            "from_repo": frm,
            "to_repo": to,
            "import_count": edge_counts[(frm, to)],
            "example_files": edge_examples[(frm, to)],
        }
        for (frm, to) in sorted(edge_counts)
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "repo_count": len(companies),
        "ambiguous_package_names_skipped": sorted(ambiguous),
        "edge_count": len(edges),
        "edges": edges,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect cross-repo Python import edges.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    legion = Legion.discover()
    companies = legion.companies()
    payload = build_cross_repo_edges(companies)

    out = docs_brain_dir() / "workspace" / "cross-repo-edges.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(out)

    if not args.quiet:
        print(f"[cross-repo-edges] {payload['edge_count']} edge(s) across "
              f"{payload['repo_count']} repo(s) -> {out}")
        if payload["ambiguous_package_names_skipped"]:
            print(f"  skipped ambiguous package names: {payload['ambiguous_package_names_skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
