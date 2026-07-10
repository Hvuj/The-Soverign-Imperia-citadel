#!/usr/bin/env python3
"""symbol_index.py — CLI to build the line-level symbol index across workspace repos.

Thin entry point over citadel.services.index.AstSymbolIndex (DIP: the real
logic lives in the importable package; this script is just the executable/daemon
surface). Writes one JSON per repo under:

    <workspace>/.citadel/state/workspace-intelligence/<repo>/symbols.json

Usage:
    python tools/symbol_index.py                 # all discovered repos
    python tools/symbol_index.py --repo <id>     # one repo
    python tools/symbol_index.py --quiet
"""

import argparse
import sys
from pathlib import Path

from citadel.paths import state_dir
from citadel.services.compile import LegionStore
from citadel.services.corporate import Company, Legion
from citadel.services.index.build import build_symbol_index


def _repo_state_dir(repo_id: str) -> Path:
    return state_dir() / "state" / "workspace-intelligence" / repo_id


def build_repo(company: Company, store: LegionStore, *, quiet: bool = False) -> int:
    """Build and persist the symbol index for one company (via the __legion__ cache)."""
    idx = build_symbol_index(store, company)
    out = _repo_state_dir(company.repo_id) / "symbols.json"
    idx.save(out)
    if not quiet:
        print(f"  [symbols] {company.repo_id}: {len(idx)} symbols -> {out}")
    return len(idx)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the line-level symbol index.")
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

    total = 0
    for company in companies:
        total += build_repo(company, store, quiet=args.quiet)
    if not args.quiet:
        print(f"[symbols] indexed {total} symbols across {len(companies)} repos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
