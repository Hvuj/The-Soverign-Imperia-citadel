#!/usr/bin/env python3
"""symbol_query.py — Query the line-span symbol index built by tools/symbol_index.py.

`AstSymbolIndex` (services/index/symbols.py) is import-only today — there is no
subagent-callable surface for "give me the exact line span of symbol X" or "what
symbol encloses file F, line N". This is that surface: O(1) exact lookup, O(log N)
line resolution, read straight from the persisted
`<workspace>/.citadel/state/workspace-intelligence/<repo>/symbols.json` per repo.

Usage:
    python tools/symbol_query.py --name QUALNAME [--repo REPO]
    python tools/symbol_query.py --file PATH --line N [--repo REPO]
    python tools/symbol_query.py --repo REPO --list [--prefix PREFIX]

If --repo is omitted for --name/--file lookups, every indexed repo is searched and
all matches are returned (rare qualname/path collisions across repos are reported,
not silently merged). Repos with no built symbols.json are reported under `missing`
rather than silently skipped.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from citadel.paths import state_dir
from citadel.services.corporate import Legion
from citadel.services.index.symbols import AstSymbolIndex


def _repo_state_dir(repo_id: str) -> Path:
    return state_dir() / "state" / "workspace-intelligence" / repo_id


def _load_repo_index(repo_id: str) -> AstSymbolIndex | None:
    path = _repo_state_dir(repo_id) / "symbols.json"
    if not path.exists():
        return None
    try:
        return AstSymbolIndex.load(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _candidate_repo_ids(explicit_repo: str | None) -> list[str]:
    if explicit_repo:
        return [explicit_repo]
    return [c.repo_id for c in Legion.discover().companies()]


def _result(mode: str, matches: list[dict], missing: list[str]) -> dict:
    return {"mode": mode, "matches": matches, "missing": missing}


def cmd_name(args: argparse.Namespace) -> dict:
    matches: list[dict] = []
    missing: list[str] = []
    for repo_id in _candidate_repo_ids(args.repo):
        idx = _load_repo_index(repo_id)
        if idx is None:
            missing.append(f"{repo_id}: not indexed — run `python tools/symbol_index.py --repo {repo_id}`")
            continue
        sym = idx.lookup(repo_id, args.name)
        if sym is not None:
            matches.append({**asdict(sym), "why": f"exact qualname match in {repo_id}"})
    if not matches and not missing:
        missing.append(f"symbol not found: {args.name}")
    return _result("name", matches, missing)


def cmd_enclosing(args: argparse.Namespace) -> dict:
    matches: list[dict] = []
    missing: list[str] = []
    for repo_id in _candidate_repo_ids(args.repo):
        idx = _load_repo_index(repo_id)
        if idx is None:
            missing.append(f"{repo_id}: not indexed — run `python tools/symbol_index.py --repo {repo_id}`")
            continue
        sym = idx.enclosing(repo_id, args.file, args.line)
        if sym is not None:
            matches.append({**asdict(sym), "why": f"encloses {args.file}:{args.line} in {repo_id}"})
    if not matches and not missing:
        missing.append(f"no symbol encloses {args.file}:{args.line}")
    return _result("enclosing", matches, missing)


def cmd_list(args: argparse.Namespace) -> dict:
    idx = _load_repo_index(args.repo)
    if idx is None:
        return _result("list", [], [f"{args.repo}: not indexed — run `python tools/symbol_index.py --repo {args.repo}`"])
    matches = [
        asdict(s) for s in idx.symbols()
        if not args.prefix or s.qualname.startswith(args.prefix)
    ]
    matches.sort(key=lambda m: (m["path"], m["start_line"]))
    return _result("list", matches[: args.limit], [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query the line-span symbol index.")
    parser.add_argument("--repo", default=None, help="Restrict to this repo id")
    parser.add_argument("--name", default=None, help="Exact qualname lookup (e.g. Foo.method)")
    parser.add_argument("--file", default=None, help="Repo-relative path (used with --line)")
    parser.add_argument("--line", type=int, default=None, help="1-based line number (used with --file)")
    parser.add_argument("--list", action="store_true", help="List all symbols for --repo")
    parser.add_argument("--prefix", default=None, help="Filter --list by qualname prefix")
    parser.add_argument("--limit", type=int, default=200, help="Max results for --list")
    parser.add_argument("--json", action="store_true", help="Force JSON output (default)")
    args = parser.parse_args(argv)

    if args.list:
        if not args.repo:
            print("ERROR: --list requires --repo", file=sys.stderr)
            return 1
        result = cmd_list(args)
    elif args.name:
        result = cmd_name(args)
    elif args.file is not None and args.line is not None:
        result = cmd_enclosing(args)
    else:
        parser.print_help(sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0 if result["matches"] or args.list else 1


if __name__ == "__main__":
    sys.exit(main())
