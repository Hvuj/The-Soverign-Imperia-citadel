#!/usr/bin/env python3
"""workspace_intelligence_query.py — Query the workspace intelligence indexes.

Exact lookups are O(1); semantic/reuse retrieval is precomputed and near-instant
using inverted/BM25/optional-local-vector indexes.

Usage:
    python tools/workspace_intelligence_query.py COMMAND [ARGS] [OPTIONS]

Commands:
    summary                   Print workspace summary
    repos                     List all repos
    repo NAME                 Repo metadata
    path REPO:RELPATH         File metadata by repo:path key
    file REPO:RELPATH         Alias for path
    module MODULE.NAME        Module metadata
    symbol SYMBOL_NAME        Symbol definitions
    feature FEATURE_ID        Feature metadata
    tests FEATURE_ID          Test files for feature
    reuse QUERY               Reuse candidates for query
    search QUERY              Full-text sparse search
    explain QUERY             Explain what to reuse for a question

Options:
    --pretty    Pretty-print JSON (default: True)
    --limit N   Max results (default from config)
    --quiet     Suppress warnings
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from _workspace_intel_common import (  # noqa: E402
    BM25,
    FEATURE_ALIASES,
    IDX,
    ROOT,
    alias_normalize,
    load_json,
    normalize_tokens,
)


_index_cache: dict[str, tuple[float, object]] = {}


def _load_index(key: str) -> dict | None:
    path = IDX.get(key)
    if path is None:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    entry = _index_cache.get(key)
    if entry and entry[0] == mtime:
        return entry[1]  # type: ignore[return-value]
    data = load_json(path, None)
    if data is not None:
        _index_cache[key] = (mtime, data)
    return data


def _ix(key: str) -> dict:
    """Load index, unwrapping versioned wrapper. Returns empty dict on miss."""
    raw = _load_index(key)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {k: v for k, v in raw.items()
                if k not in ("schema_version", "generated_at", "build_id")}
    return {}


def _ensure_index() -> bool:
    """Ensure indexes exist, triggering a rebuild if missing."""
    if IDX["build_metadata"].exists():
        return True
    try:
        subprocess.run(
            [sys.executable, str(_TOOLS / "build_workspace_intelligence_index.py"), "--quiet"],
            cwd=str(ROOT), timeout=120
        )
        return IDX["build_metadata"].exists()
    except Exception:
        return False


def _result(query: str, mode: str, results: list, evidence: list,
             missing: list, latency_ms: float) -> dict:
    return {
        "query": query,
        "mode": mode,
        "results": results,
        "evidence": evidence,
        "missing": missing,
        "latency_ms": round(latency_ms, 1),
    }


def _normalize_query(query: str) -> tuple[str, list[str]]:
    """Return (normalized_phrase, [tokens])."""
    norm = alias_normalize(query)
    tokens = normalize_tokens(query)
    return norm, tokens


def _alias_lookup(norm_query: str, tokens: list[str]) -> str | None:
    """Return canonical feature id from alias index."""
    alias_idx = _ix("alias")
    if norm_query in alias_idx:
        return str(alias_idx[norm_query])
    if norm_query in FEATURE_ALIASES:
        return FEATURE_ALIASES[norm_query]
    spaced = norm_query.replace("_", " ")
    if spaced in alias_idx:
        return str(alias_idx[spaced])
    if spaced in FEATURE_ALIASES:
        return FEATURE_ALIASES[spaced]
    for t in tokens:
        if t in alias_idx:
            return str(alias_idx[t])
    return None


def _bm25_search(tokens: list[str], top_k: int = 20) -> list[tuple[float, str]]:
    bm25_raw = _load_index("bm25")
    if not bm25_raw or not isinstance(bm25_raw, dict):
        return []
    bm25 = {k: v for k, v in bm25_raw.items()
            if k not in ("schema_version", "generated_at", "build_id")}
    return BM25.score(tokens, bm25, top_k=top_k)


def _graph_expand(file_ids: list[str], limit: int = 10) -> list[str]:
    """Expand file IDs via graph adjacency (imports + siblings)."""
    adj = _ix("graph_adjacency")
    extra: set[str] = set()
    for fid in file_ids[:5]:
        node = adj.get(fid, {})
        for imp in node.get("imports", [])[:3]:
            imp_tail = imp.split(".")[-1] if "." in imp else imp
            extra.add(imp_tail)
    return list(extra)[:limit]


def query_reuse(query: str, limit: int = 20) -> dict:
    """Full reuse retrieval pipeline."""
    t0 = time.monotonic()
    norm, tokens = _normalize_query(query)
    results: list[dict] = []
    evidence: list[str] = []
    missing: list[str] = []

    reuse_idx = _ix("reuse_candidate")
    feature_idx = _ix("feature")
    file_idx = _ix("file")
    alias_idx = _ix("alias")

    canonical = _alias_lookup(norm, tokens)
    if canonical and canonical in reuse_idx:
        rc = reuse_idx[canonical]
        results.append({
            "type": "reuse_candidate",
            "feature": canonical,
            "confidence": rc.get("confidence", "medium"),
            "candidate_files": rc.get("candidate_files", [])[:5],
            "candidate_modules": rc.get("candidate_modules", [])[:5],
            "candidate_symbols": rc.get("candidate_symbols", [])[:5],
            "candidate_tests": rc.get("candidate_tests", [])[:3],
            "candidate_docs": rc.get("candidate_docs", [])[:3],
            "why_reusable": rc.get("why_reusable", []),
            "evidence": rc.get("evidence", []),
        })
        evidence.append(f"exact alias match: {canonical}")

    if canonical and canonical in feature_idx and not results:
        fi = feature_idx[canonical]
        results.append({
            "type": "feature",
            "feature_id": canonical,
            "files": fi.get("files", [])[:5],
            "modules": fi.get("modules", [])[:5],
            "tests": fi.get("tests", [])[:3],
        })
        evidence.append(f"feature index match: {canonical}")

    inv_idx = _ix("inverted_token")
    file_candidates: dict[str, int] = {}
    for t in tokens:
        for fid in inv_idx.get("files", {}).get(t, []):
            file_candidates[fid] = file_candidates.get(fid, 0) + 1
        for feat in inv_idx.get("features", {}).get(t, []):
            if feat in reuse_idx and not any(r.get("feature") == feat for r in results):
                rc = reuse_idx[feat]
                results.append({
                    "type": "reuse_candidate",
                    "feature": feat,
                    "confidence": rc.get("confidence", "low"),
                    "candidate_files": rc.get("candidate_files", [])[:5],
                    "candidate_modules": rc.get("candidate_modules", [])[:5],
                    "candidate_symbols": rc.get("candidate_symbols", [])[:5],
                    "candidate_tests": rc.get("candidate_tests", [])[:3],
                    "why_reusable": rc.get("why_reusable", []),
                    "evidence": rc.get("evidence", []),
                })
                evidence.append(f"inverted token match: {feat}")

    bm25_results = _bm25_search(tokens, top_k=10)
    bm25_files = []
    for score, fid in bm25_results:
        fm = file_idx.get(fid, {})
        if fm and score > 0.1:
            bm25_files.append({
                "file_id": fid,
                "score": round(score, 3),
                "path": fm.get("relative_path", fid),
                "repo": fm.get("repo", ""),
                "summary": fm.get("short_summary", "")[:100],
            })
    if bm25_files:
        results.append({"type": "bm25_files", "files": bm25_files[:5]})
        evidence.append(f"BM25 scored {len(bm25_files)} file candidates")

    if not results:
        missing.append(f"No reuse candidates found for: {query}")

    latency = (time.monotonic() - t0) * 1000
    return _result(query, "reuse", results[:limit], evidence, missing, latency)


def query_search(query: str, limit: int = 20) -> dict:
    """Full-text sparse search."""
    t0 = time.monotonic()
    norm, tokens = _normalize_query(query)
    evidence: list[str] = []
    missing: list[str] = []

    bm25_results = _bm25_search(tokens, top_k=limit)
    file_idx = _ix("file")
    results = []
    for score, fid in bm25_results:
        fm = file_idx.get(fid, {})
        if fm:
            results.append({
                "type": "file",
                "file_id": fid,
                "repo": fm.get("repo", ""),
                "path": fm.get("relative_path", fid),
                "score": round(score, 3),
                "language": fm.get("language", ""),
                "summary": fm.get("short_summary", "")[:100],
                "features": fm.get("likely_feature_area", []),
            })
    if results:
        evidence.append(f"BM25 search over {len(_ix('file'))} files")
    else:
        missing.append(f"No results for: {query}")

    latency = (time.monotonic() - t0) * 1000
    return _result(query, "search", results, evidence, missing, latency)


def cmd_summary(args) -> dict:
    t0 = time.monotonic()
    bm = load_json(IDX["build_metadata"], {})
    ws = load_json(IDX["workspace"], {})
    if not isinstance(bm, dict):
        return _result("summary", "summary", [], [], ["build_metadata missing"], 0)
    result = {
        "type": "workspace_summary",
        "build_id": bm.get("build_id", ""),
        "build_duration_sec": bm.get("build_duration_sec", 0),
        "incremental": bm.get("incremental", False),
        "repo_count": bm.get("repo_count", 0),
        "file_count": bm.get("file_count", 0),
        "changed_count": bm.get("changed_count", 0),
        "workspace_root": bm.get("workspace_root", ""),
        "repos": ws.get("repos", []) if isinstance(ws, dict) else [],
        "feature_count": ws.get("feature_count", 0) if isinstance(ws, dict) else 0,
    }
    latency = (time.monotonic() - t0) * 1000
    return _result("summary", "summary", [result], ["build_metadata.json"], [], latency)


def cmd_repos(args) -> dict:
    t0 = time.monotonic()
    repo_idx = _ix("repo")
    results = [{"type": "repo", **v} for v in repo_idx.values() if isinstance(v, dict)]
    latency = (time.monotonic() - t0) * 1000
    ev = ["repo-index.json"] if results else []
    return _result("repos", "exact", results, ev, [] if results else ["no repos"], latency)


def cmd_repo(args) -> dict:
    t0 = time.monotonic()
    name = args.name
    repo_idx = _ix("repo")
    match = repo_idx.get(name)
    if not match:
        for rid, rd in repo_idx.items():
            if isinstance(rd, dict) and name.lower() in rid.lower():
                match = rd
                break
    latency = (time.monotonic() - t0) * 1000
    if match:
        return _result(name, "exact", [{"type": "repo", **match}], ["repo-index.json"], [], latency)
    return _result(name, "exact", [], [], [f"repo not found: {name}"], latency)


def cmd_path(args) -> dict:
    t0 = time.monotonic()
    key = getattr(args, "key", None) or getattr(args, "path", None)
    file_idx = _ix("file")
    match = file_idx.get(key)
    if not match:
        for fid, fm in file_idx.items():
            if isinstance(fm, dict) and (fid.endswith(key) or fm.get("relative_path", "") == key):
                match = fm
                break
    latency = (time.monotonic() - t0) * 1000
    if match:
        return _result(key, "exact", [{"type": "file", **match}], ["file-index.json"], [], latency)
    return _result(key, "exact", [], [], [f"path not found: {key}"], latency)


def cmd_module(args) -> dict:
    t0 = time.monotonic()
    name = args.name
    mod_idx = _ix("module")
    file_idx = _ix("file")
    file_ids = mod_idx.get(name, [])
    results = []
    for fid in file_ids:
        fm = file_idx.get(fid, {})
        if fm:
            results.append({"type": "module_file", "module": name, "file_id": fid,
                             "path": fm.get("relative_path", fid), "repo": fm.get("repo", "")})
    latency = (time.monotonic() - t0) * 1000
    ev = ["module-index.json"] if results else []
    return _result(name, "exact", results, ev, [] if results else [f"module not found: {name}"], latency)


def cmd_symbol(args) -> dict:
    t0 = time.monotonic()
    name = args.name
    sym_idx = _ix("symbol")
    file_idx = _ix("file")
    definitions = sym_idx.get(name, [])
    results = []
    for d in definitions:
        fid = d.get("file_id", "")
        fm = file_idx.get(fid, {})
        results.append({"type": "symbol_definition", "symbol": name,
                         "file_id": fid, "repo": d.get("repo", ""),
                         "path": fm.get("relative_path", fid) if fm else fid})
    latency = (time.monotonic() - t0) * 1000
    ev = ["symbol-index.json"] if results else []
    return _result(name, "exact", results, ev, [] if results else [f"symbol not found: {name}"], latency)


def cmd_feature(args) -> dict:
    t0 = time.monotonic()
    feat_id = args.feature_id
    feat_idx = _ix("feature")
    fi = feat_idx.get(feat_id)
    if not fi:
        norm = alias_normalize(feat_id)
        fi = feat_idx.get(norm)
        if not fi:
            from _workspace_intel_common import FEATURE_ALIASES
            canonical = FEATURE_ALIASES.get(norm)
            if canonical:
                fi = feat_idx.get(canonical)
                feat_id = canonical
    latency = (time.monotonic() - t0) * 1000
    if fi:
        return _result(feat_id, "exact", [{"type": "feature", **fi}],
                       ["feature-index.json"], [], latency)
    return _result(feat_id, "exact", [], [], [f"feature not found: {feat_id}"], latency)


def cmd_tests(args) -> dict:
    t0 = time.monotonic()
    feat_id = args.feature_id
    test_idx = _ix("test")
    file_idx = _ix("file")
    test_entries = test_idx.get(feat_id, [])
    results = []
    for te in test_entries:
        fid = te.get("file_id", "")
        fm = file_idx.get(fid, {})
        results.append({"type": "test_file", "feature": feat_id,
                         "file_id": fid, "path": fm.get("relative_path", fid) if fm else fid,
                         "repo": fm.get("repo", "") if fm else "",
                         "test_names": te.get("tests", [])})
    latency = (time.monotonic() - t0) * 1000
    ev = ["test-index.json"] if results else []
    return _result(feat_id, "exact", results, ev, [] if results else [f"no tests for: {feat_id}"], latency)


def cmd_reuse(args) -> dict:
    query = " ".join(args.query) if isinstance(args.query, list) else args.query
    limit = getattr(args, "limit", 20) or 20
    return query_reuse(query, limit)


def cmd_search(args) -> dict:
    query = " ".join(args.query) if isinstance(args.query, list) else args.query
    limit = getattr(args, "limit", 20) or 20
    return query_search(query, limit)


def cmd_explain(args) -> dict:
    """Answer 'what should I reuse for X?' — wrapper over reuse + feature."""
    query = " ".join(args.query) if isinstance(args.query, list) else args.query
    t0 = time.monotonic()
    reuse_r = query_reuse(query, 10)
    feat_r = cmd_feature(type("A", (), {"feature_id": alias_normalize(query)})())
    results = reuse_r.get("results", []) + feat_r.get("results", [])
    evidence = reuse_r.get("evidence", []) + feat_r.get("evidence", [])
    latency = (time.monotonic() - t0) * 1000
    return _result(query, "explain", results[:10], evidence, [], latency)


def main() -> int:
    _parent = argparse.ArgumentParser(add_help=False)
    _parent.add_argument("--pretty", action="store_true", default=True)
    _parent.add_argument("--limit", type=int, default=None)
    _parent.add_argument("--quiet", action="store_true")

    parser = argparse.ArgumentParser(
        description="Query workspace intelligence indexes",
        parents=[_parent],
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("summary", parents=[_parent])
    sub.add_parser("repos", parents=[_parent])
    p_repo = sub.add_parser("repo", parents=[_parent]); p_repo.add_argument("name")
    p_path = sub.add_parser("path", parents=[_parent]); p_path.add_argument("key")
    p_file = sub.add_parser("file", parents=[_parent]); p_file.add_argument("key")
    p_mod = sub.add_parser("module", parents=[_parent]); p_mod.add_argument("name")
    p_sym = sub.add_parser("symbol", parents=[_parent]); p_sym.add_argument("name")
    p_feat = sub.add_parser("feature", parents=[_parent]); p_feat.add_argument("feature_id")
    p_tests = sub.add_parser("tests", parents=[_parent]); p_tests.add_argument("feature_id")
    p_reuse = sub.add_parser("reuse", parents=[_parent]); p_reuse.add_argument("query", nargs="+")
    p_search = sub.add_parser("search", parents=[_parent]); p_search.add_argument("query", nargs="+")
    p_explain = sub.add_parser("explain", parents=[_parent]); p_explain.add_argument("query", nargs="+")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        return 1

    if not _ensure_index():
        print(json.dumps({"error": "workspace intelligence index not found; run build first"}))
        return 1

    dispatch = {
        "summary": cmd_summary,
        "repos": cmd_repos,
        "repo": cmd_repo,
        "path": cmd_path,
        "file": cmd_path,
        "module": cmd_module,
        "symbol": cmd_symbol,
        "feature": cmd_feature,
        "tests": cmd_tests,
        "reuse": cmd_reuse,
        "search": cmd_search,
        "explain": cmd_explain,
    }
    fn = dispatch.get(args.cmd)
    if fn is None:
        print(f"Unknown command: {args.cmd}")
        return 1

    result = fn(args)
    indent = 2 if args.pretty else None
    print(json.dumps(result, indent=indent, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
