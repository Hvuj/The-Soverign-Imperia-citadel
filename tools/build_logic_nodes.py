#!/usr/bin/env python3
"""build_logic_nodes.py — Build per-symbol line-level "logic nodes" with intra-file call edges.

Reuses `citadel.services.index.symbols.extract_symbols` (the same AST parse the
line-level symbol index already does) rather than re-deriving symbol spans, then does one
extra lightweight walk per file to collect `ast.Call` sites and attribute each call to its
innermost enclosing symbol. A call only becomes an edge when its name matches another
symbol defined in the *same file* — this is deliberately intra-file only (per-repo/
cross-repo edges are `build_cross_repo_edges.py`'s job), so it stays a cheap O(file size)
pass with no false cross-file/cross-repo resolution.

Writes one JSON per repo under:
    <workspace>/.citadel/state/workspace-intelligence/<repo>/logic-nodes.json

Usage:
    python tools/build_logic_nodes.py                 # all discovered repos
    python tools/build_logic_nodes.py --repo <id>      # one repo
    python tools/build_logic_nodes.py --max-nodes 5000
    python tools/build_logic_nodes.py --quiet
"""

import argparse
import ast
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from citadel.paths import state_dir
from citadel.services.corporate import Company, Legion
from citadel.services.index.base import Symbol
from citadel.services.index.symbols import extract_symbols, iter_python_files

SCHEMA_VERSION = "1.0"
DEFAULT_MAX_NODES_PER_REPO = 2000


def _repo_state_dir(repo_id: str) -> Path:
    return state_dir() / "state" / "workspace-intelligence" / repo_id


def _extract_calls(source: str) -> list[tuple[int, str]]:
    """Return (lineno, call_name) for every simple-named call site. Fail-soft on parse error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    calls: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            calls.append((node.lineno, func.id))
        elif isinstance(func, ast.Attribute):
            calls.append((node.lineno, func.attr))
    return calls


def _assign_calls_to_symbols(symbols: list[Symbol], calls: list[tuple[int, str]]) -> dict[str, list[str]]:
    """Map each symbol's qualname -> sorted unique call names in its innermost span.

    Spans are checked smallest-first so a call inside a method is attributed to the
    method, not its enclosing class.
    """
    by_qualname: dict[str, list[str]] = {s.qualname: [] for s in symbols}
    seen: dict[str, set[str]] = {s.qualname: set() for s in symbols}
    ordered = sorted(symbols, key=lambda s: s.end_line - s.start_line)
    for lineno, name in calls:
        for sym in ordered:
            if sym.contains(lineno):
                if name not in seen[sym.qualname]:
                    seen[sym.qualname].add(name)
                    by_qualname[sym.qualname].append(name)
                break
    return by_qualname


def build_repo_logic_nodes(repo_id: str, repo_path: Path, *, max_nodes: int = DEFAULT_MAX_NODES_PER_REPO) -> dict:
    """Build the logic-node payload for one repo (file/module/symbol + intra-file call edges)."""
    nodes: list[dict] = []
    root = Path(repo_path)
    for py in iter_python_files(root):
        try:
            source = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relpath = py.relative_to(root).as_posix()
        symbols = extract_symbols(source, repo_id, relpath)
        if not symbols:
            continue
        local_names = {sym.qualname.split(".")[-1] for sym in symbols}
        call_map = _assign_calls_to_symbols(symbols, _extract_calls(source))
        for sym in symbols:
            own_name = sym.qualname.split(".")[-1]
            calls = sorted(
                name for name in call_map.get(sym.qualname, [])
                if name in local_names and name != own_name
            )
            nodes.append({
                "id": f"{repo_id}:{relpath}:{sym.qualname}",
                "repo": repo_id,
                "path": relpath,
                "qualname": sym.qualname,
                "kind": sym.kind,
                "start_line": sym.start_line,
                "end_line": sym.end_line,
                "calls": calls,
            })

    truncated = max(0, len(nodes) - max_nodes)
    if truncated:
        nodes = nodes[:max_nodes]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "repo": repo_id,
        "node_count": len(nodes),
        "truncated": truncated,
        "nodes": nodes,
    }


def save_payload(payload: dict, repo_id: str) -> Path:
    out = _repo_state_dir(repo_id) / "logic-nodes.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out


def build_repo(company: Company, *, max_nodes: int, quiet: bool = False) -> int:
    payload = build_repo_logic_nodes(company.repo_id, company.path, max_nodes=max_nodes)
    out = save_payload(payload, company.repo_id)
    if not quiet:
        note = f" ({payload['truncated']} truncated)" if payload["truncated"] else ""
        print(f"  [logic-nodes] {company.repo_id}: {payload['node_count']} nodes{note} -> {out}")
    return payload["node_count"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build line-level logic nodes with intra-file call edges.")
    parser.add_argument("--repo", default=None, help="Only index this repo id")
    parser.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES_PER_REPO, help="Per-repo node cap")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    legion = Legion.discover()
    companies = legion.companies()
    if args.repo:
        one = legion.company(args.repo)
        if one is None:
            print(f"ERROR: unknown repo id: {args.repo}", file=sys.stderr)
            return 1
        companies = [one]

    total = 0
    for company in companies:
        total += build_repo(company, max_nodes=args.max_nodes, quiet=args.quiet)
    if not args.quiet:
        print(f"[logic-nodes] indexed {total} logic nodes across {len(companies)} repos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
