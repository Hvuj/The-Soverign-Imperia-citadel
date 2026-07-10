#!/usr/bin/env python3
"""legion_compile.py — compile source into the `__legion__` cache (like `python -m compileall`).

Walks a company's Python files and compiles each into a `.legion` unit (cached, deduped).
On a warm cache the second run reports ~100% hits and near-zero `ast` re-parses.

Usage:
    python tools/legion_compile.py --repo <id>
    python tools/legion_compile.py --all [--stats]
    python tools/legion_compile.py --file <abs-or-repo-relative-path> --repo <id>
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from citadel.services.compile import LegionStore
from citadel.services.corporate import Company, Legion
from citadel.services.index.symbols import iter_python_files

_WORKERS = max(2, min(8, os.cpu_count() or 2))
_PARALLEL_THRESHOLD = 16


def compile_company(store: LegionStore, company: Company, *, quiet: bool = False) -> int:
    root = company.python_path
    files = [(py.relative_to(root).as_posix(), py) for py in iter_python_files(root)]

    def _one(item: tuple[str, Path]) -> bool:
        relpath, py = item
        return store.get_path(company.repo_id, relpath, py) is not None

    if _WORKERS > 1 and len(files) >= _PARALLEL_THRESHOLD:
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            results = list(pool.map(_one, files))
        count = sum(1 for ok in results if ok)
    else:
        count = sum(1 for item in files if _one(item))

    if not quiet:
        print(f"  [legion-compile] {company.repo_id}: {count} files")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile source into the __legion__ cache.")
    parser.add_argument("--repo", default=None, help="Company id to compile")
    parser.add_argument("--all", action="store_true", help="Compile all companies")
    parser.add_argument("--file", default=None, help="Single file (needs --repo)")
    parser.add_argument("--stats", action="store_true", help="Print cache hit/compile stats")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    legion = Legion.discover()
    store = LegionStore()

    if args.file:
        if not args.repo or legion.company(args.repo) is None:
            print("ERROR: --file requires a valid --repo", file=sys.stderr)
            return 1
        company = legion.company(args.repo)
        p = Path(args.file)
        abs_path = p if p.is_absolute() else company.python_path / p
        relpath = abs_path.relative_to(company.python_path).as_posix()
        store.get_path(company.repo_id, relpath, abs_path)
    elif args.all:
        for company in legion.companies():
            compile_company(store, company, quiet=args.quiet)
    elif args.repo:
        one = legion.company(args.repo)
        if one is None:
            print(f"ERROR: unknown repo id: {args.repo}", file=sys.stderr)
            return 1
        compile_company(store, one, quiet=args.quiet)
    else:
        parser.error("one of --repo / --all / --file is required")

    if args.stats or not args.quiet:
        s = store.stats
        total = s.hits + s.compiles
        rate = (100.0 * s.hits / total) if total else 0.0
        print(f"[legion-compile] hits={s.hits} compiled={s.compiles} stale={s.stale} "
              f"hit_rate={rate:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
