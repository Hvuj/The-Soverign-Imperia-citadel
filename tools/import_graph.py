#!/usr/bin/env python3
"""import_graph.py — CLI to build the internal import dependency graph per repo.

Thin entry point over citadel.services.index.AstImportGraph (DIP). Writes two
JSON files per repo under <workspace>/.citadel/state/workspace-intelligence/<repo>/:

    import-graph.json   adjacency (module -> imported internal modules)
    import-cycles.json  strongly-connected components (import cycles)

Usage:
    python tools/import_graph.py                 # all discovered repos
    python tools/import_graph.py --repo <id>
    python tools/import_graph.py --quiet
"""

import argparse
import sys
from pathlib import Path

from citadel.paths import state_dir
from citadel.services.compile import LegionStore
from citadel.services.corporate import Company, Legion
from citadel.services.index.build import build_import_graph


def _repo_state_dir(repo_id: str) -> Path:
    return state_dir() / "state" / "workspace-intelligence" / repo_id


def build_repo(company: Company, store: LegionStore, *, quiet: bool = False) -> int:
    """Build and persist the import graph for one company (via the __legion__ cache)."""
    graph = build_import_graph(store, company)
    base = _repo_state_dir(company.repo_id)
    graph.save(base / "import-graph.json", base / "import-cycles.json")
    cycles = graph.cycles()
    if not quiet:
        note = f"{len(cycles)} cycle(s)" if cycles else "acyclic"
        print(f"  [imports] {company.repo_id}: {note} -> {base}")
    return len(cycles)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the internal import graph.")
    parser.add_argument("--repo", default=None, help="Only index this repo id")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    legion = Legion.discover()
    store = LegionStore()
    companies = legion.companies()
    if args.repo:
        one = legion.company(args.repo)
        if one is None:
            print(f"ERROR: unknown repo id: {args.repo}", file=sys.stderr)
            return 1
        companies = [one]

    total_cycles = 0
    for company in companies:
        total_cycles += build_repo(company, store, quiet=args.quiet)
    if not args.quiet:
        print(f"[imports] {total_cycles} total cycle(s) across {len(companies)} repos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
