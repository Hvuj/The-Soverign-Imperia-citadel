#!/usr/bin/env python3
"""explore_map.py — fused "exact read targets" façade for token-efficient exploration.

Explore subagents were paying broad-grep token costs even though the workspace
already has everything needed to answer "where do I look for X" precisely:
BM25 + inverted-token + reuse-candidate retrieval (workspace_intelligence_query.py)
finds the right FILES; the AST symbol index (symbol_query.py / AstSymbolIndex)
finds the right SYMBOLS + exact line spans inside those files; the workspace
graph-adjacency index resolves 1-hop related files. Nothing here re-implements
those — this is a thin fusion layer over the three, keyed consistently by
(repo, repo-relative path) throughout.

Usage:
    python tools/explore_map.py "<query>" [--limit N]

Output: {"query", "targets": [{path, repo, symbol, kind, start_line, end_line,
score, why, related_paths}], "evidence": [...], "missing": [...]}. `missing`
names any repo whose symbol/import index hasn't been built yet (with the exact
command to build it) rather than silently degrading to file-only results.
"""

import argparse
import json
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from _workspace_intel_common import normalize_tokens  # noqa: E402
from workspace_intelligence_query import (  # noqa: E402
    _ensure_index,
    _ix,
    query_reuse,
    query_search,
)

from citadel.paths import state_dir
from citadel.services.index.symbols import AstSymbolIndex

_symbol_cache: dict[str, AstSymbolIndex | None] = {}


def _repo_symbols_path(repo_id: str) -> Path:
    return state_dir() / "state" / "workspace-intelligence" / repo_id / "symbols.json"


def _load_symbols(repo_id: str) -> AstSymbolIndex | None:
    if repo_id in _symbol_cache:
        return _symbol_cache[repo_id]
    path = _repo_symbols_path(repo_id)
    idx: AstSymbolIndex | None = None
    if path.exists():
        try:
            idx = AstSymbolIndex.load(path)
        except (OSError, ValueError, json.JSONDecodeError):
            idx = None
    _symbol_cache[repo_id] = idx
    return idx


def _split_file_id(file_id: str) -> tuple[str, str]:
    repo, _, path = file_id.partition(":")
    return repo, path


def _resolve_related(file_id: str, limit: int) -> list[str]:
    """1-hop related files via the workspace graph-adjacency + module indexes."""
    adj = _ix("graph_adjacency").get(file_id, {})
    module_idx = _ix("module")
    file_idx = _ix("file")
    related: list[str] = []
    seen: set[str] = {file_id}
    for imp in adj.get("imports", []):
        fids = module_idx.get(imp)
        if not fids:
            parts = imp.split(".")
            for cut in range(len(parts) - 1, 0, -1):
                fids = module_idx.get(".".join(parts[:cut]))
                if fids:
                    break
        for fid in (fids or [])[:1]:
            if fid in seen:
                continue
            seen.add(fid)
            fm = file_idx.get(fid, {})
            related.append(fm.get("relative_path", fid))
            if len(related) >= limit:
                return related
    return related


def _collect_candidates(query: str, limit: int) -> tuple[dict[tuple[str, str], dict], list[str], list[str]]:
    candidates: dict[tuple[str, str], dict] = {}
    evidence: list[str] = []
    missing: list[str] = []

    def _touch(repo: str, path: str, score: float, why: str) -> None:
        if not repo or not path:
            return
        c = candidates.setdefault((repo, path), {"score": 0.0, "why": []})
        c["score"] = max(c["score"], score)
        c["why"].append(why)

    search_r = query_search(query, limit)
    evidence += search_r.get("evidence", [])
    missing += search_r.get("missing", [])
    for r in search_r.get("results", []):
        _touch(r.get("repo", ""), r.get("path", ""), r.get("score", 0.0), f"BM25 search score={r.get('score')}")

    reuse_r = query_reuse(query, limit)
    evidence += reuse_r.get("evidence", [])
    missing += reuse_r.get("missing", [])
    for r in reuse_r.get("results", []):
        rtype = r.get("type")
        if rtype == "reuse_candidate":
            for fid in r.get("candidate_files", []):
                repo, path = _split_file_id(fid)
                _touch(repo, path, 0.8, f"reuse candidate for '{r.get('feature')}' ({r.get('confidence')})")
        elif rtype == "feature":
            for fid in r.get("files", []):
                repo, path = _split_file_id(fid)
                _touch(repo, path, 0.7, f"feature index match '{r.get('feature_id')}'")
        elif rtype == "bm25_files":
            for f in r.get("files", []):
                _touch(f.get("repo", ""), f.get("path", ""), f.get("score", 0.0), f"BM25 reuse score={f.get('score')}")

    return candidates, evidence, missing


def build_explore_map(query: str, *, limit: int = 10, symbols_per_file: int = 3, related_limit: int = 3) -> dict:
    candidates, evidence, missing = _collect_candidates(query, limit * 2)
    ranked = sorted(candidates.items(), key=lambda kv: kv[1]["score"], reverse=True)[:limit]
    tokens = set(normalize_tokens(query))
    seen_missing_repos: set[str] = set()
    targets: list[dict] = []

    for (repo, path), meta in ranked:
        file_id = f"{repo}:{path}"
        idx = _load_symbols(repo)
        symbol_entries = []
        if idx is None:
            if repo not in seen_missing_repos:
                missing.append(f"{repo}: symbols not indexed — run `python tools/symbol_index.py --repo {repo}`")
                seen_missing_repos.add(repo)
        else:
            file_syms = sorted((s for s in idx.symbols() if s.path == path), key=lambda s: s.start_line)
            scored = sorted(
                file_syms,
                key=lambda s: (-len(set(normalize_tokens(s.qualname)) & tokens), s.start_line),
            )
            symbol_entries = scored[:symbols_per_file]

        related = _resolve_related(file_id, related_limit)
        why = meta["why"][:3]
        score = round(meta["score"], 3)

        if symbol_entries:
            for sym in symbol_entries:
                targets.append({
                    "path": path, "repo": repo,
                    "symbol": sym.qualname, "kind": sym.kind,
                    "start_line": sym.start_line, "end_line": sym.end_line,
                    "score": score, "why": why, "related_paths": related,
                })
        else:
            targets.append({
                "path": path, "repo": repo,
                "symbol": None, "kind": None,
                "start_line": None, "end_line": None,
                "score": score, "why": why, "related_paths": related,
            })

    return {
        "query": query,
        "targets": targets,
        "evidence": sorted(set(evidence)),
        "missing": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fused exact-read-target lookup for exploration.")
    parser.add_argument("query", nargs="+", help="Keywords describing what to explore")
    parser.add_argument("--limit", type=int, default=10, help="Max ranked file/symbol targets")
    parser.add_argument("--json", action="store_true", help="No-op — output is always JSON")
    args = parser.parse_args(argv)

    _ensure_index()
    result = build_explore_map(" ".join(args.query), limit=args.limit)
    print(json.dumps(result, indent=2))
    return 0 if result["targets"] else 1


if __name__ == "__main__":
    sys.exit(main())
