#!/usr/bin/env python3
"""import_query.py — Query the internal import graph built by tools/import_graph.py.

`AstImportGraph` (services/index/imports.py) is import-only today — there is no
subagent-callable surface for "what does module X depend on", "what depends on
module X" (impact/blast-radius scoping), or "is X reachable from Y". This is that
surface, read straight from the persisted
`<workspace>/.citadel/state/workspace-intelligence/<repo>/import-graph.json`.

Usage:
    python tools/import_query.py --repo REPO --deps MODULE
    python tools/import_query.py --repo REPO --rdeps MODULE       # impact scoping
    python tools/import_query.py --repo REPO --reachable MODULE
    python tools/import_query.py --repo REPO --cycles
"""

import argparse
import json
import sys
from pathlib import Path

from citadel.paths import state_dir
from citadel.services.index.imports import AstImportGraph


def _repo_state_dir(repo_id: str) -> Path:
    return state_dir() / "state" / "workspace-intelligence" / repo_id


def _load_repo_graph(repo_id: str) -> AstImportGraph | None:
    path = _repo_state_dir(repo_id) / "import-graph.json"
    if not path.exists():
        return None
    try:
        return AstImportGraph.load(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query the internal import dependency graph.")
    parser.add_argument("--repo", required=True, help="Repo id")
    parser.add_argument("--deps", default=None, metavar="MODULE", help="Modules MODULE directly imports")
    parser.add_argument("--rdeps", default=None, metavar="MODULE", help="Modules that directly import MODULE")
    parser.add_argument("--reachable", default=None, metavar="MODULE", help="Full BFS closure from MODULE")
    parser.add_argument("--cycles", action="store_true", help="List import cycles (SCCs) in the repo")
    args = parser.parse_args(argv)

    graph = _load_repo_graph(args.repo)
    if graph is None:
        print(json.dumps({
            "missing": [f"{args.repo}: not indexed — run `python tools/import_graph.py --repo {args.repo}`"],
        }, indent=2))
        return 1

    if args.deps:
        result = {"mode": "deps", "module": args.deps, "matches": graph.neighbors(args.deps)}
    elif args.rdeps:
        result = {"mode": "rdeps", "module": args.rdeps, "matches": graph.reverse_neighbors(args.rdeps)}
    elif args.reachable:
        result = {"mode": "reachable", "module": args.reachable, "matches": sorted(graph.reachable(args.reachable))}
    elif args.cycles:
        result = {"mode": "cycles", "matches": graph.cycles()}
    else:
        parser.print_help(sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
