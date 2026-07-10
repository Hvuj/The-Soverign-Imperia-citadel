#!/usr/bin/env python3
"""build_workspace_intelligence_index.py — Build/update the workspace intelligence index.

Scans all included workspace repos, parses files (text + AST only, never imports/executes),
and writes O(1) exact-lookup indexes plus inverted/BM25 sparse indexes for near-instant
reuse/feature retrieval.

Usage:
    python tools/build_workspace_intelligence_index.py [OPTIONS]

Options:
    --workspace PATH    Workspace root (default from config)
    --config PATH       Config file path (default: .claude/brain/workspace-index-config.json)
    --rebuild           Force clean rebuild (ignore previous index)
    --quiet             Suppress output (for startup script)
    --pretty            Print summary after build
    --check             Validate-only smoke test (no write)
"""

import argparse
import ast
import concurrent.futures
import fnmatch
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from _workspace_intel_common import (  # noqa: E402
    BM25,
    FEATURE_ALIASES,
    FEATURE_KEYWORDS,
    IDX,
    ROOT,
    SCHEMA_VERSION,
    acquire_lock,
    atomic_write_json,
    build_reuse_tags,
    content_hash,
    detect_features,
    dir_id,
    file_id,
    is_excluded_dir,
    is_sensitive_content,
    is_sensitive_path,
    load_config,
    load_json,
    module_name_from_path,
    normalize_tokens,
    release_lock,
    resolve_workers,
    sync_fts5_code_corpus,
    versioned,
)
from workspace_discoverer import (  # noqa: E402
    _FRAMEWORK_KEYWORDS,
    _FRAMEWORK_SCAN_LIMIT,
    _MARKER_TO_LANGUAGE,
)


BINARY_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".o", ".a",
    ".jpg", ".jpeg", ".png", ".gif", ".ico", ".svg", ".webp", ".bmp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".pdf", ".docx", ".xlsx", ".pptx", ".zip", ".tar", ".gz", ".bz2", ".xz",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pkl", ".pickle", ".parquet", ".arrow", ".db", ".sqlite",
}

PARSER_VERSION = "1.1"
_PARALLEL_PARSE_THRESHOLD = 64

# Workspace-agnostic: the Citadel ships with NO framework-specific detection vocabulary. Which
# decorators mark an "asset"/"job"/"schedule"/"sensor", which base classes mark a config/schema
# model, and which import markers signify a compute/dataframe/query library are all DISCOVERED per
# workspace by the learning layer and written to framework-signals.json. See _framework_signals().
FRAMEWORK_SIGNALS_PATH = ROOT / ".claude" / "brain" / "framework-signals.json"

_FRAMEWORK_SIGNAL_KEYS = (
    "asset_decorators",
    "check_decorators",
    "job_decorators",
    "schedule_decorators",
    "sensor_decorators",
    "config_model_bases",
    "schema_model_bases",
    "dataframe_import_markers",
    "distributed_import_markers",
    "query_import_markers",
)

_framework_signals_cache: "dict[str, frozenset[str]] | None" = None


def _framework_signals() -> "dict[str, frozenset[str]]":
    """Framework-detection vocabulary, DISCOVERED per workspace — never hardcoded.

    The learning layer (feature-implementation-learner / the auto-mapper) inspects the workspace's
    own code, docs, imports and commit history, decides which decorators / base classes / import
    markers signify orchestration assets, schema models, dataframe usage, etc., and writes them to
    framework-signals.json. On a fresh install the file is absent, so every category is empty: the
    indexer records raw decorators and imports (see meta["decorators"]/["imports"]) without imposing
    any tech-specific categorization. Cached per process so a parallel parse stays cheap/consistent.
    """
    global _framework_signals_cache
    if _framework_signals_cache is not None:
        return _framework_signals_cache
    signals: "dict[str, frozenset[str]]" = {k: frozenset() for k in _FRAMEWORK_SIGNAL_KEYS}
    try:
        raw = json.loads(FRAMEWORK_SIGNALS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = None
    if isinstance(raw, dict):
        for key in _FRAMEWORK_SIGNAL_KEYS:
            vals = raw.get(key)
            if isinstance(vals, list):
                signals[key] = frozenset(v for v in vals if isinstance(v, str))
    _framework_signals_cache = signals
    return signals

CONFIG_TYPE_SIGNALS = {
    "pyproject": ["tool.poetry", "tool.pytest", "build-system", "project"],
    "workflow_manifest": ["workflows", "task_type_to_workflow"],
    "artifact_policy": ["artifact_types", "task_type_to_artifacts"],
    "memory_policy": ["memory_policy_rules", "domain_join_rules"],
    "scheduler_config": ["scheduler", "advisory_tier", "effort_tier"],
    "model_effort_config": ["model_effort", "effort_tiers"],
    "graph_aware_config": ["automation_mode", "topic_aliases", "domain_to_agents"],
    "citadel_config": ["citadel", "allowed_context_files", "max_question_chars"],
    "orchestration_config": ["orchestration", "run_launcher", "telemetry"],
}


def _log(msg: str, quiet: bool) -> None:
    if not quiet:
        print(msg, flush=True)


def _is_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with open(path, "rb") as f:
            chunk = f.read(512)
        if b"\x00" in chunk:
            return True
    except Exception:
        pass
    return False


def _read_text_safe(path: Path) -> str | None:
    """Read text file, returning None on any error."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _content_signature(entry: Path) -> tuple[list[str], list[str]]:
    """Reuse workspace_discoverer's marker/framework detection, bounded to one dir.

    Non-recursive (unlike WorkspaceDiscoverer.discover_projects, which walks the whole
    tree) — this is an O(1)-per-candidate check, the same cost class as the existing
    is_git/_detect_py_root probes, so it's safe to run on every glob-selected candidate.
    """
    languages: set[str] = set()
    for marker, lang in _MARKER_TO_LANGUAGE.items():
        if lang and (entry / marker).exists():
            languages.add(lang)

    frameworks: set[str] = set()
    try:
        py_files = [f for f in os.listdir(entry) if f.endswith(".py")]
    except OSError:
        py_files = []
    for fname in py_files[:_FRAMEWORK_SCAN_LIMIT]:
        content = _read_text_safe(entry / fname)
        if not content:
            continue
        for kw in _FRAMEWORK_KEYWORDS:
            if kw in content:
                frameworks.add(kw)

    return sorted(languages), sorted(frameworks)


def discover_repos(workspace_root: str | Path, cfg: dict) -> list[dict]:
    """Find all included repos under workspace_root.

    Content-discovered, not glob-only: every glob-selected candidate is annotated with
    workspace_discoverer's signature-based languages/frameworks. When the operator uses
    the wildcard default (`repo_include_globs == ["*"]`), a candidate with no recognized
    project signature AND no `.git` is treated as workspace noise and skipped — an
    explicit non-wildcard include list is trusted as-is (the operator named it on purpose).

    When `cfg["repo_include_paths"]` is set (populated from a `*.code-workspace` file's
    `folders[]` — see `resolve_vscode_folders` in `_workspace_intel_common.py` /
    `paths.py`), those exact paths are discovered directly instead of globbing
    `workspace_root`'s children, so repos need not share a common parent and only what
    the operator's editor workspace actually opens is discovered.
    """
    exclude_globs = cfg.get("repo_exclude_globs", [])
    seen_realpaths: set[str] = set()
    name_counts: dict[str, int] = {}
    repos: list[dict] = []

    explicit_paths = cfg.get("repo_include_paths")
    if explicit_paths:
        for entry in sorted((Path(p) for p in explicit_paths), key=lambda p: p.name):
            repo = _evaluate_repo_candidate(
                entry, exclude_globs=exclude_globs, wildcard_default=False,
                seen_realpaths=seen_realpaths, name_counts=name_counts,
            )
            if repo:
                repos.append(repo)
        return repos

    workspace = Path(workspace_root)
    if not workspace.exists():
        return []

    include_globs = cfg.get("repo_include_globs", ["*"])
    wildcard_default = list(include_globs) == ["*"]

    try:
        entries = sorted(workspace.iterdir(), key=lambda e: e.name)
    except PermissionError:
        return []

    for entry in entries:
        if not entry.is_dir():
            continue
        if not any(fnmatch.fnmatch(entry.name, g) for g in include_globs):
            continue
        repo = _evaluate_repo_candidate(
            entry, exclude_globs=exclude_globs, wildcard_default=wildcard_default,
            seen_realpaths=seen_realpaths, name_counts=name_counts,
        )
        if repo:
            repos.append(repo)

    return repos


def _evaluate_repo_candidate(
    entry: Path,
    *,
    exclude_globs: list[str],
    wildcard_default: bool,
    seen_realpaths: set[str],
    name_counts: dict[str, int],
) -> dict | None:
    """Build the repo-info dict for one candidate directory, or None if excluded/noise/duplicate."""
    if not entry.is_dir():
        return None
    name = entry.name
    if any(fnmatch.fnmatch(name, g) for g in exclude_globs):
        return None

    is_git = (entry / ".git").exists()
    languages, frameworks = _content_signature(entry)
    if wildcard_default and not is_git and not languages:
        return None

    try:
        rp = str(entry.resolve())
    except OSError:
        return None
    if rp in seen_realpaths:
        return None
    seen_realpaths.add(rp)

    name_counts[name] = name_counts.get(name, 0) + 1
    repo_id = name if name_counts[name] == 1 else f"{name}_{name_counts[name]}"
    py_root = _detect_py_root(entry)

    return {
        "repo_id": repo_id,
        "name": name,
        "path": str(entry),
        "realpath": rp,
        "is_git": is_git,
        "python_root": py_root,
        "languages": languages,
        "frameworks": frameworks,
    }


def _detect_py_root(repo_path: Path) -> str:
    """Return the relative path to the Python source root."""
    for candidate in ["src", "."]:
        p = repo_path / candidate
        if candidate == "." or p.exists():
            return candidate
    return "."


def scan_repo(repo: dict, cfg: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Scan a repo, returning (file_stats, dir_stats, skipped)."""
    repo_path = Path(repo["path"])
    include_exts = set(cfg.get("include_extensions", []))
    max_size = cfg.get("max_file_size_bytes", 1_000_000)
    do_hash = cfg.get("content_hash_for_small_files", True)
    hash_max = cfg.get("content_hash_max_bytes", 262_144)

    file_stats: list[dict] = []
    dir_stats: list[dict] = []
    skipped: list[dict] = []
    visited_dirs: set[str] = set()

    def _scan_dir(dirpath: Path, rel_prefix: str) -> None:
        try:
            rp = str(dirpath.resolve())
        except Exception:
            return
        if rp in visited_dirs:
            return
        visited_dirs.add(rp)

        try:
            entries = list(os.scandir(str(dirpath)))
        except PermissionError:
            skipped.append({"repo": repo["repo_id"], "path": str(dirpath), "reason": "permission_denied"})
            return

        entries.sort(key=lambda e: e.name)

        exclude_paths = set(cfg.get("exclude_dirs", []))

        for entry in entries:
            name = entry.name
            rel = f"{rel_prefix}/{name}".lstrip("/") if rel_prefix else name

            if entry.is_dir(follow_symlinks=False):
                if is_excluded_dir(name, cfg):
                    continue
                if any(rel == exc or rel.startswith(exc + "/") for exc in exclude_paths if "/" in exc):
                    continue
                if entry.is_symlink():
                    try:
                        tr = str(Path(entry.path).resolve())
                        if tr in visited_dirs:
                            continue
                    except Exception:
                        continue
                dir_stats.append({
                    "repo": repo["repo_id"],
                    "dir_id": dir_id(repo["repo_id"], rel),
                    "relative_path": rel,
                    "absolute_path": entry.path,
                    "name": name,
                })
                _scan_dir(Path(entry.path), rel)

            elif entry.is_file(follow_symlinks=False):
                suffix = Path(name).suffix.lower()
                if suffix not in include_exts:
                    continue

                try:
                    st = entry.stat()
                except OSError:
                    skipped.append({"repo": repo["repo_id"], "path": entry.path, "reason": "stat_failed"})
                    continue

                size = st.st_size
                mtime_ns = st.st_mtime_ns

                abs_path = Path(entry.path)
                sensitive, sens_reason = is_sensitive_path(abs_path, cfg)
                if sensitive:
                    skipped.append({"repo": repo["repo_id"], "path": entry.path,
                                    "reason": f"sensitive_path: {sens_reason}"})
                    continue

                if size == 0:
                    skipped.append({"repo": repo["repo_id"], "path": entry.path, "reason": "empty"})
                    continue
                if size > max_size:
                    skipped.append({"repo": repo["repo_id"], "path": entry.path, "reason": "too_large"})
                    continue

                fhash = None
                if do_hash and size <= hash_max:
                    fhash = content_hash(abs_path, hash_max)

                fid = file_id(repo["repo_id"], rel)
                file_stats.append({
                    "file_id": fid,
                    "repo": repo["repo_id"],
                    "relative_path": rel,
                    "absolute_path": entry.path,
                    "extension": suffix,
                    "size": size,
                    "mtime_ns": mtime_ns,
                    "content_hash": fhash,
                })

    _scan_dir(repo_path, "")
    return file_stats, dir_stats, skipped


def compute_diff(
    current_stats: list[dict],
    previous_fingerprints: dict,
    previous_file_index: dict,
    cfg: dict,
) -> tuple[list[dict], list[dict], list[str]]:
    """Return (unchanged, changed, deleted_file_ids)."""
    unchanged: list[dict] = []
    changed: list[dict] = []
    current_ids = {f["file_id"] for f in current_stats}

    deleted = [fid for fid in previous_fingerprints if fid not in current_ids]

    for fs in current_stats:
        fid = fs["file_id"]
        prev = previous_fingerprints.get(fid)
        if prev is None:
            changed.append(fs)
            continue

        if fs["mtime_ns"] != prev.get("mtime_ns") or fs["size"] != prev.get("size"):
            changed.append(fs)
            continue

        if fs.get("content_hash") and prev.get("content_hash"):
            if fs["content_hash"] != prev["content_hash"]:
                changed.append(fs)
                continue

        prev_meta = previous_file_index.get(fid, {})
        if prev_meta.get("parser_version") != PARSER_VERSION:
            changed.append(fs)
            continue

        unchanged.append(fs)

    return unchanged, changed, deleted


def _parse_decorators(decorator_list) -> list[str]:
    """Extract decorator name strings from AST decorator_list."""
    result = []
    for d in decorator_list:
        if isinstance(d, ast.Name):
            result.append(d.id)
        elif isinstance(d, ast.Attribute):
            result.append(d.attr)
        elif isinstance(d, ast.Call):
            func = d.func
            if isinstance(func, ast.Name):
                result.append(func.id)
            elif isinstance(func, ast.Attribute):
                result.append(func.attr)
    return result


def _flag_import_usage(name: str, sig: "dict[str, frozenset[str]]", meta: dict) -> None:
    """Flag compute/dataframe/query library usage from an import name using workspace-learned
    markers (framework-signals.json). No markers configured (fresh install) -> nothing flagged."""
    low = name.lower()
    if any(marker in low for marker in sig["distributed_import_markers"]):
        meta["distributed_usage"] = True
    if any(marker in low for marker in sig["dataframe_import_markers"]):
        meta["dataframe_usage"] = True
    if any(marker in low for marker in sig["query_import_markers"]):
        meta["query_usage"] = True


def _extract_python_metadata(path: Path, source: str) -> dict:
    """Parse Python file with AST. Returns rich metadata dict."""
    meta: dict = {
        "parse_status": "ok",
        "parser_version": PARSER_VERSION,
        "imports": [],
        "classes": [],
        "functions": [],
        "constants": [],
        "decorators": [],
        "symbols_defined": [],
        "symbols_referenced": [],
        "orchestration_assets": [],
        "schema_checks": [],
        "orchestration_jobs": [],
        "orchestration_schedules": [],
        "orchestration_sensors": [],
        "schema_models": [],
        "config_models": [],
        "distributed_usage": False,
        "dataframe_usage": False,
        "query_usage": False,
        "tests_related": [],
        "short_summary": "",
        "reuse_tags": [],
        "likely_feature_area": [],
        "line_count": source.count("\n") + 1,
    }

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        meta["parse_status"] = f"syntax_error: {exc}"
        meta["line_count"] = source.count("\n") + 1
        return meta

    imports_set: set[str] = set()
    all_decorators: list[str] = []
    classes_list: list[str] = []
    functions_list: list[str] = []

    sig = _framework_signals()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports_set.add(alias.name)
                _flag_import_usage(alias.name, sig, meta)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imports_set.add(mod)
            _flag_import_usage(mod, sig, meta)

        elif isinstance(node, (ast.ClassDef,)):
            cname = node.name
            classes_list.append(cname)
            decs = _parse_decorators(node.decorator_list)
            all_decorators.extend(decs)

            bases = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.append(b.id)
                elif isinstance(b, ast.Attribute):
                    bases.append(b.attr)

            if sig["config_model_bases"] and any(b in sig["config_model_bases"] for b in bases):
                meta["config_models"].append(cname)

            if sig["schema_model_bases"] and any(b in sig["schema_model_bases"] for b in bases):
                meta["schema_models"].append(cname)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fname = node.name
            functions_list.append(fname)
            decs = _parse_decorators(node.decorator_list)
            all_decorators.extend(decs)

            dec_set = set(decs)
            if dec_set & sig["asset_decorators"]:
                meta["orchestration_assets"].append(fname)
            if dec_set & sig["check_decorators"]:
                meta["schema_checks"].append(fname)
            if dec_set & sig["job_decorators"]:
                meta["orchestration_jobs"].append(fname)
            if dec_set & sig["schedule_decorators"]:
                meta["orchestration_schedules"].append(fname)
            if dec_set & sig["sensor_decorators"]:
                meta["orchestration_sensors"].append(fname)

            if fname.startswith("test_"):
                meta["tests_related"].append(fname)

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    if name.isupper() or (name[0].isupper() and "_" in name):
                        meta["constants"].append(name)

        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                meta["constants"].append(node.target.id)

    src_lower = source.lower()
    if "dataframeschema" in src_lower or "dataframemodel" in src_lower:
        meta["schema_models"] = list(set(meta["schema_models"]))
        if not meta["schema_models"]:
            meta["schema_models"] = ["_detected_usage"]

    meta["imports"] = sorted(imports_set)
    meta["classes"] = classes_list
    meta["functions"] = functions_list
    meta["decorators"] = sorted(set(all_decorators))
    meta["symbols_defined"] = classes_list + functions_list
    meta["reuse_tags"] = build_reuse_tags(meta)

    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)):
        meta["short_summary"] = tree.body[0].value.value.strip()[:200]

    return meta


def _extract_markdown_metadata(path: Path, source: str) -> dict:
    headings = re.findall(r"^#+\s+(.+)$", source, re.MULTILINE)
    links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", source)
    code_langs = re.findall(r"```(\w+)", source)
    title = headings[0] if headings else path.stem
    snippet = source[:300].replace("\n", " ").strip()
    return {
        "parse_status": "ok",
        "parser_version": PARSER_VERSION,
        "headings": headings[:20],
        "title": title,
        "links": [l[1] for l in links[:30]],
        "code_fence_languages": sorted(set(code_langs)),
        "short_summary": snippet,
        "line_count": source.count("\n") + 1,
        "symbols_defined": [],
        "imports": [],
        "reuse_tags": [],
        "likely_feature_area": [],
    }


def _classify_config_type(data: dict) -> str:
    for ctype, signals in CONFIG_TYPE_SIGNALS.items():
        for sig in signals:
            if sig in str(data).lower():
                return ctype
    return "generic_config"


def _extract_config_metadata(path: Path, source: str, extension: str) -> dict:
    meta = {
        "parse_status": "ok",
        "parser_version": PARSER_VERSION,
        "config_type": "unknown",
        "short_summary": "",
        "line_count": source.count("\n") + 1,
        "symbols_defined": [],
        "imports": [],
        "reuse_tags": [],
        "likely_feature_area": [],
    }
    try:
        if extension in (".json",):
            data = json.loads(source)
        elif extension in (".yaml", ".yml"):
            keys = re.findall(r"^(\w[\w_-]*):", source, re.MULTILINE)
            data = {"_keys": keys}
        elif extension == ".toml":
            sections = re.findall(r"^\[([^\]]+)\]", source, re.MULTILINE)
            data = {"_sections": sections}
        else:
            data = {}
        meta["config_type"] = _classify_config_type(data)
        if isinstance(data, dict):
            meta["short_summary"] = f"{meta['config_type']} ({len(data)} keys)"
    except Exception as exc:
        meta["parse_status"] = f"parse_error: {exc}"
    return meta


def _extract_shell_metadata(path: Path, source: str) -> dict:
    scripts = re.findall(r'(?:^|[;\s])(?:scripts/|tools/)([a-zA-Z0-9_.\-]+)', source, re.MULTILINE)
    commands = re.findall(r'(?:python3?|uv run|bash)\s+([\w./\-]+\.(?:py|sh))', source)
    return {
        "parse_status": "ok",
        "parser_version": PARSER_VERSION,
        "called_scripts": sorted(set(scripts))[:30],
        "called_commands": sorted(set(commands))[:30],
        "short_summary": f"Shell script ({source.count(chr(10))+1} lines)",
        "line_count": source.count("\n") + 1,
        "symbols_defined": [],
        "imports": [],
        "reuse_tags": [],
        "likely_feature_area": [],
    }


def _extract_sql_metadata(path: Path, source: str) -> dict:
    tables = re.findall(r'\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+([`"\[]?[\w.]+[`"\]]?)', source, re.IGNORECASE)
    return {
        "parse_status": "ok",
        "parser_version": PARSER_VERSION,
        "tables_referenced": sorted(set(t.strip('`"[]') for t in tables))[:30],
        "short_summary": f"SQL ({source.count(chr(10))+1} lines, {len(set(tables))} tables)",
        "line_count": source.count("\n") + 1,
        "symbols_defined": [],
        "imports": [],
        "reuse_tags": [],
        "likely_feature_area": [],
        "query_usage": True,
    }


def _extract_feature_metadata(path: Path, source: str) -> dict:
    feature_match = re.search(r'^\s*Feature:\s*(.+)$', source, re.MULTILINE)
    scenarios = re.findall(r'^\s*(?:Scenario|Scenario Outline):\s*(.+)$', source, re.MULTILINE)
    steps = re.findall(r'^\s+(?:Given|When|Then|And|But)\s+(.+)$', source, re.MULTILINE)
    return {
        "parse_status": "ok",
        "parser_version": PARSER_VERSION,
        "feature_name": feature_match.group(1).strip() if feature_match else path.stem,
        "scenarios": scenarios[:30],
        "step_texts": steps[:50],
        "short_summary": f"Feature: {feature_match.group(1).strip() if feature_match else path.stem} ({len(scenarios)} scenarios)",
        "line_count": source.count("\n") + 1,
        "symbols_defined": [],
        "imports": [],
        "reuse_tags": ["tests", "bdd"],
        "likely_feature_area": [],
    }


def _worker_parse_file(args: tuple) -> dict:
    """Top-level ProcessPoolExecutor worker (must be module-level for pickle on macOS spawn).

    Returns the same error-shaped dict as the sequential path on failure so callers
    never see an exception from pool.map().
    """
    fs, cfg = args
    try:
        return parse_file(fs, cfg)
    except Exception as exc:
        return {
            **fs,
            "parse_status": f"error: {exc}",
            "parser_version": PARSER_VERSION,
            "symbols_defined": [], "imports": [], "reuse_tags": [],
            "likely_feature_area": [], "short_summary": "",
        }


def parse_file(fs: dict, cfg: dict) -> dict:
    """Parse a single file and return enriched file metadata."""
    path = Path(fs["absolute_path"])
    ext = fs["extension"]
    repo = fs["repo"]
    rel = fs["relative_path"]

    base_meta = {
        "file_id": fs["file_id"],
        "repo": repo,
        "relative_path": rel,
        "absolute_path": fs["absolute_path"],
        "extension": ext,
        "language": _ext_to_language(ext),
        "size": fs["size"],
        "mtime_ns": fs["mtime_ns"],
        "content_hash": fs.get("content_hash"),
    }

    if _is_binary(path):
        return {**base_meta, "parse_status": "binary", "parser_version": PARSER_VERSION,
                "symbols_defined": [], "imports": [], "reuse_tags": [], "likely_feature_area": [],
                "short_summary": "", "line_count": 0}

    if fs["size"] > cfg.get("max_text_index_bytes", 1_000_000):
        return {**base_meta, "parse_status": "too_large", "parser_version": PARSER_VERSION,
                "symbols_defined": [], "imports": [], "reuse_tags": [], "likely_feature_area": [],
                "short_summary": "", "line_count": 0}

    sens_content, sens_reason = is_sensitive_content(path, cfg)
    if sens_content:
        return {**base_meta, "parse_status": f"sensitive_content: {sens_reason}",
                "parser_version": PARSER_VERSION,
                "symbols_defined": [], "imports": [], "reuse_tags": [], "likely_feature_area": [],
                "short_summary": "[redacted: sensitive content]", "line_count": 0}

    source = path.read_text(encoding="utf-8", errors="replace")

    if ext == ".py":
        parsed = _extract_python_metadata(path, source)
    elif ext in (".md", ".txt"):
        parsed = _extract_markdown_metadata(path, source)
    elif ext in (".json", ".yaml", ".yml", ".toml"):
        parsed = _extract_config_metadata(path, source, ext)
    elif ext == ".sh":
        parsed = _extract_shell_metadata(path, source)
    elif ext == ".sql":
        parsed = _extract_sql_metadata(path, source)
    elif ext == ".feature":
        parsed = _extract_feature_metadata(path, source)
    else:
        parsed = {"parse_status": "ok", "parser_version": PARSER_VERSION,
                  "short_summary": "", "line_count": source.count("\n") + 1,
                  "symbols_defined": [], "imports": [], "reuse_tags": [], "likely_feature_area": []}

    content_tokens = normalize_tokens(source[:2000]) if len(source) <= 50_000 else []
    features = detect_features(
        path=Path(rel),
        repo=repo,
        symbols=parsed.get("symbols_defined", []) + parsed.get("classes", []),
        imports=parsed.get("imports", []),
        decorators=parsed.get("decorators", []),
        content_tokens=content_tokens,
    )
    parsed["likely_feature_area"] = features
    if parsed.get("reuse_tags") is not None:
        parsed["reuse_tags"] = build_reuse_tags({**parsed, "likely_feature_area": features})

    return {**base_meta, **parsed}


def _ext_to_language(ext: str) -> str:
    return {
        ".py": "python", ".md": "markdown", ".json": "json",
        ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
        ".sh": "shell", ".feature": "gherkin", ".sql": "sql",
        ".txt": "text",
    }.get(ext, "unknown")


def aggregate_indexes(all_file_meta: list[dict], all_dir_stats: list[dict],
                      repos: list[dict], cfg: dict, build_id: str) -> dict:
    """Build all O(1) and inverted indexes from file/dir metadata."""

    repo_index: dict = {}
    path_index: dict = {}
    path_by_key: dict = {}
    file_index: dict = {}
    dir_index: dict = {}
    module_index: dict = {}
    symbol_index: dict = {}
    qualified_symbol_index: dict = {}
    import_index: dict = {}
    reverse_import_index: dict = {}
    test_index: dict = {}
    feature_index: dict = {}
    artifact_index: dict = {}
    alias_index: dict = {}
    graph_adjacency: dict = {}

    alias_index.update({k: v for k, v in FEATURE_ALIASES.items()})

    for repo in repos:
        rid = repo["repo_id"]
        repo_index[rid] = {
            "repo_id": rid,
            "name": repo["name"],
            "path": repo["path"],
            "is_git": repo["is_git"],
            "python_root": repo["python_root"],
            "file_count": 0,
            "module_count": 0,
            "feature_ids": [],
        }

    for ds in all_dir_stats:
        did = ds["dir_id"]
        dir_index[did] = ds

    for fm in all_file_meta:
        fid = fm["file_id"]
        repo = fm["repo"]
        rel = fm["relative_path"]

        file_index[fid] = fm
        path_index[fm["absolute_path"]] = fm
        path_by_key[fid] = fid

        if repo in repo_index:
            repo_index[repo]["file_count"] += 1

        mod = module_name_from_path(repo, rel)
        if mod:
            module_index.setdefault(mod, [])
            if fid not in module_index[mod]:
                module_index[mod].append(fid)
            if repo in repo_index:
                repo_index[repo]["module_count"] = repo_index[repo].get("module_count", 0) + 1

        for sym in fm.get("symbols_defined", []):
            symbol_index.setdefault(sym, []).append({"file_id": fid, "repo": repo})
            if mod:
                qkey = f"{repo}:{mod}.{sym}"
                qualified_symbol_index[qkey] = fid
            alias_index[sym.lower()] = sym

        imports = fm.get("imports", [])
        if imports:
            import_index[fid] = imports
            for imp in imports:
                reverse_import_index.setdefault(imp, []).append(fid)

        tests = fm.get("tests_related", [])
        if tests:
            for feat in fm.get("likely_feature_area", ["unknown"]):
                test_index.setdefault(feat, []).append({"file_id": fid, "tests": tests})

        for feat in fm.get("likely_feature_area", []):
            fi = feature_index.setdefault(feat, {
                "feature_id": feat,
                "files": [],
                "modules": [],
                "symbols": [],
                "tests": [],
                "docs": [],
                "graph_nodes": [],
                "description": FEATURE_KEYWORDS.get(feat, set()) and f"Feature: {feat}",
            })
            fi["files"].append(fid)
            if mod:
                fi["modules"].append(mod)
            fi["symbols"].extend(fm.get("symbols_defined", []))
            if tests:
                fi["tests"].append(fid)
            if fm.get("extension") in (".md", ".txt"):
                fi["docs"].append(fid)
            if repo in repo_index:
                if feat not in repo_index[repo]["feature_ids"]:
                    repo_index[repo]["feature_ids"].append(feat)

        _classify_artifacts(fm, fid, artifact_index, cfg)

        adj = {"imports": imports, "referenced_by": [], "feature_siblings": []}
        graph_adjacency[fid] = adj

    for feat, fi in feature_index.items():
        fi["modules"] = sorted(set(fi["modules"]))
        fi["symbols"] = sorted(set(fi["symbols"]))

    corpus: dict[str, list[str]] = {}
    for fid, fm in file_index.items():
        tokens = normalize_tokens(fm.get("short_summary", ""))
        tokens += fm.get("symbols_defined", [])
        tokens += [s for imp in fm.get("imports", []) for s in normalize_tokens(imp)]
        tokens += fm.get("likely_feature_area", [])
        tokens += fm.get("reuse_tags", [])
        if tokens:
            corpus[fid] = tokens
    bm25_index = BM25.build(corpus)

    inverted: dict[str, dict[str, list[str]]] = {
        "files": {}, "modules": {}, "symbols": {}, "features": {},
        "docs": {}, "tests": {},
    }

    for fid, fm in file_index.items():
        tokens = set(normalize_tokens(fm.get("short_summary", "")))
        tokens.update(normalize_tokens(fm.get("relative_path", "")))
        tokens.update(fm.get("symbols_defined", []))
        tokens.update(fm.get("likely_feature_area", []))
        for t in tokens:
            inverted["files"].setdefault(t, []).append(fid)
            if fm.get("extension") in (".md", ".txt"):
                inverted["docs"].setdefault(t, []).append(fid)
            if fm.get("tests_related"):
                inverted["tests"].setdefault(t, []).append(fid)

    for mod, fids in module_index.items():
        for t in normalize_tokens(mod):
            inverted["modules"].setdefault(t, []).append(mod)

    for sym, defs in symbol_index.items():
        for t in normalize_tokens(sym):
            inverted["symbols"].setdefault(t, []).append(sym)

    for feat in feature_index:
        for t in normalize_tokens(feat):
            inverted["features"].setdefault(t, []).append(feat)

    for cat in inverted:
        for t in inverted[cat]:
            inverted[cat][t] = sorted(set(inverted[cat][t]))

    reuse_index = _build_reuse_candidate_index(feature_index, file_index, module_index,
                                                symbol_index, test_index, bm25_index, alias_index)

    for fm in all_file_meta:
        stem = Path(fm["relative_path"]).stem.lower()
        canonical = re.sub(r"[\s\-]+", "_", stem)
        if canonical and canonical not in alias_index:
            alias_index[canonical] = canonical
        phrase = re.sub(r"[_\-]", " ", canonical)
        if phrase != canonical and phrase not in alias_index:
            alias_index[phrase] = canonical

    return {
        "repo_index": repo_index,
        "path_index": path_index,
        "path_by_key": path_by_key,
        "file_index": file_index,
        "dir_index": dir_index,
        "module_index": module_index,
        "symbol_index": symbol_index,
        "qualified_symbol_index": qualified_symbol_index,
        "import_index": import_index,
        "reverse_import_index": reverse_import_index,
        "test_index": test_index,
        "feature_index": feature_index,
        "artifact_index": artifact_index,
        "alias_index": alias_index,
        "inverted_token_index": inverted,
        "bm25_index": bm25_index,
        "reuse_candidate_index": reuse_index,
        "graph_adjacency_index": graph_adjacency,
    }


def _classify_artifacts(fm: dict, fid: str, artifact_index: dict, cfg: dict) -> None:
    """Classify file into artifact types based on path and content signals."""
    rel = fm.get("relative_path", "")
    rel_lower = rel.lower()

    important_rules = cfg.get("important_file_rules", [])
    for rule in important_rules:
        if rule in rel_lower:
            artifact_index.setdefault(rule, []).append({"file_id": fid, "path": rel})
            return

    if fm.get("orchestration_assets"):
        artifact_index.setdefault("orchestration_asset", []).append({"file_id": fid, "path": rel})
    if fm.get("schema_models"):
        artifact_index.setdefault("schema_model", []).append({"file_id": fid, "path": rel})
    if fm.get("config_models"):
        artifact_index.setdefault("configmodel_model", []).append({"file_id": fid, "path": rel})
    if fm.get("tests_related"):
        artifact_index.setdefault("test_file", []).append({"file_id": fid, "path": rel})


def _build_reuse_candidate_index(feature_index: dict, file_index: dict,
                                  module_index: dict, symbol_index: dict,
                                  test_index: dict, bm25_index: dict,
                                  alias_index: dict) -> dict:
    """Build reuse candidates keyed by feature/alias."""
    reuse: dict = {}

    for feat_id, fi in feature_index.items():
        files = fi.get("files", [])[:10]
        modules = fi.get("modules", [])[:10]
        symbols = fi.get("symbols", [])[:20]
        tests_files = fi.get("tests", [])[:10]
        docs_files = fi.get("docs", [])[:5]

        aliases = [k for k, v in alias_index.items() if v == feat_id or v == feat_id.replace("_", " ")]

        evidence = []
        if files:
            evidence.append(f"{len(files)} files implement this feature")
        if modules:
            evidence.append(f"modules: {', '.join(modules[:3])}")
        if tests_files:
            evidence.append(f"{len(tests_files)} test files")

        confidence = "high" if (files and tests_files) else "medium" if files else "low"

        reuse[feat_id] = {
            "query_aliases": aliases[:10],
            "exact_matches": files[:5],
            "candidate_files": files,
            "candidate_modules": modules,
            "candidate_symbols": symbols[:10],
            "candidate_tests": tests_files,
            "candidate_docs": docs_files,
            "candidate_graph_nodes": [f"topic:{feat_id}"],
            "why_reusable": [
                f"Existing implementation in {len(files)} file(s)",
            ] + (["Has test coverage"] if tests_files else []),
            "confidence": confidence,
            "evidence": evidence,
        }

    return reuse


def _refresh_fingerprints_after_phase7(all_file_meta: list[dict]) -> None:
    """Re-stat files that Phase 7 may have written and update their mtime_ns in-place.

    Phase 7 writes docs/brain/workspace/**/*.md. These files' mtimes change but
    their fingerprints were captured in Phase 3 (before Phase 7 ran). Without this
    refresh, the NEXT incremental build always sees those ~30 files as "changed".
    After refresh, fingerprints.json carries the post-Phase-7 mtime_ns and the
    next build correctly reports changed=0.
    """
    ws_docs = ROOT / "docs" / "brain" / "workspace"
    if not ws_docs.exists():
        return
    path_to_idx: dict[str, int] = {
        fm["absolute_path"]: i
        for i, fm in enumerate(all_file_meta)
        if "absolute_path" in fm
    }
    for p in ws_docs.rglob("*.md"):
        abs_str = str(p)
        if abs_str in path_to_idx:
            try:
                st = p.stat()
                fm = all_file_meta[path_to_idx[abs_str]]
                fm["mtime_ns"] = st.st_mtime_ns
                fm["size"] = st.st_size
            except Exception:
                pass


def write_human_summaries(repos: list[dict], indexes: dict, quiet: bool) -> None:
    """Write concise markdown summaries for repos, features, and important dirs."""
    ws_docs = ROOT / "docs" / "brain" / "workspace"

    _write_workspace_index(ws_docs, repos, indexes)

    for repo in repos:
        _write_repo_summary(ws_docs, repo, indexes)

    feature_index = indexes.get("feature_index", {})
    feat_dir = ws_docs / "features"
    feat_dir.mkdir(parents=True, exist_ok=True)
    for feat_id, fi in list(feature_index.items())[:20]:
        feat_path = feat_dir / f"{feat_id}.md"
        file_count = len(fi.get("files", []))
        mod_count = len(fi.get("modules", []))
        test_count = len(fi.get("tests", []))
        content = f"""# Feature: {feat_id}

| Metric | Count |
|--------|-------|
| Files | {file_count} |
| Modules | {mod_count} |
| Test files | {test_count} |

## Key files
{chr(10).join("- " + f for f in fi.get("files", [])[:5])}

## Key modules
{chr(10).join("- " + m for m in fi.get("modules", [])[:5])}
"""
        _write_if_changed(feat_path, content)


def _write_if_changed(path: Path, content: str) -> None:
    """Only write file if content differs from existing content (avoids mtime churn)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == content:
                return
        except Exception:
            pass
    path.write_text(content, encoding="utf-8")


def _write_workspace_index(ws_docs: Path, repos: list[dict], indexes: dict) -> None:
    ws_docs.mkdir(parents=True, exist_ok=True)
    repo_index = indexes.get("repo_index", {})
    file_index = indexes.get("file_index", {})
    feature_index = indexes.get("feature_index", {})

    lines = [
        "# Workspace Intelligence Index",
        "",
        "<!-- generated by build_workspace_intelligence_index.py -->",
        "",
        "## Repos",
        "",
    ]
    for repo in repos:
        rid = repo["repo_id"]
        ri = repo_index.get(rid, {})
        lines.append(f"- **{rid}** — {ri.get('file_count', 0)} files, "
                     f"{ri.get('module_count', 0)} modules, "
                     f"{len(ri.get('feature_ids', []))} features")

    lines += ["", "## Features", ""]
    for feat_id, fi in list(feature_index.items())[:30]:
        lines.append(f"- `{feat_id}` — {len(fi.get('files', []))} files, "
                     f"{len(fi.get('tests', []))} test files")

    lines += ["", f"**Total:** {len(file_index)} files indexed across {len(repos)} repos", ""]
    _write_if_changed(ws_docs / "index.md", "\n".join(lines))


def _write_repo_summary(ws_docs: Path, repo: dict, indexes: dict) -> None:
    repos_dir = ws_docs / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)
    rid = repo["repo_id"]
    repo_index = indexes.get("repo_index", {})
    ri = repo_index.get(rid, {})
    file_count = ri.get("file_count", 0)
    mod_count = ri.get("module_count", 0)
    feature_ids = ri.get("feature_ids", [])

    content = f"""# Repo: {rid}

| Field | Value |
|-------|-------|
| Path | `{repo["path"]}` |
| Git | {repo["is_git"]} |
| Files | {file_count} |
| Python modules | {mod_count} |
| Features | {", ".join(f"`{f}`" for f in feature_ids[:10]) or "none"} |

## Source: machine index
See `.claude/state/workspace-intelligence/repo-index.json` for full details.
"""
    _write_if_changed(repos_dir / f"{rid}.md", content)


def write_indexes(indexes: dict, all_file_meta: list[dict], all_dir_stats: list[dict],
                  repos: list[dict], skipped: list[dict], deleted: list[str],
                  build_id: str, build_start: float, incremental: bool,
                  changed_count: int, cfg: dict, quiet: bool) -> None:
    """Atomically write all index files."""
    _log("Writing indexes...", quiet)

    repo_count = len(repos)
    file_count = len(all_file_meta)
    dir_count = len(all_dir_stats)
    module_count = len(indexes["module_index"])
    symbol_count = sum(len(v) for v in indexes["symbol_index"].values())
    feature_count = len(indexes["feature_index"])
    test_count = sum(len(v) for v in indexes["test_index"].values())
    duration = round(time.monotonic() - build_start, 2)

    ws_index = versioned({
        "workspace_root": cfg.get("workspace_root", str(ROOT.parent)),
        "build_id": build_id,
        "build_duration_sec": duration,
        "incremental": incremental,
        "repos": [r["repo_id"] for r in repos],
        "repo_count": repo_count,
        "file_count": file_count,
        "dir_count": dir_count,
        "module_count": module_count,
        "symbol_count": symbol_count,
        "feature_count": feature_count,
        "test_count": test_count,
        "changed_files": changed_count,
        "skipped_files_summary": _summarize_skipped(skipped),
        "indexes": {
            "repo_index": str(IDX["repo"]),
            "file_index": str(IDX["file"]),
            "module_index": str(IDX["module"]),
            "symbol_index": str(IDX["symbol"]),
            "reuse_candidate_index": str(IDX["reuse_candidate"]),
        },
    }, build_id)

    atomic_write_json(IDX["workspace"], ws_index)
    atomic_write_json(IDX["repo"], versioned(indexes["repo_index"], build_id))
    atomic_write_json(IDX["path"], versioned(indexes["path_index"], build_id))
    atomic_write_json(IDX["file"], versioned(indexes["file_index"], build_id))
    atomic_write_json(IDX["dir"], versioned(indexes["dir_index"], build_id))
    atomic_write_json(IDX["module"], versioned(indexes["module_index"], build_id))
    atomic_write_json(IDX["symbol"], versioned(indexes["symbol_index"], build_id))
    atomic_write_json(IDX["qualified_symbol"], versioned(indexes["qualified_symbol_index"], build_id))
    atomic_write_json(IDX["import"], versioned(indexes["import_index"], build_id))
    atomic_write_json(IDX["reverse_import"], versioned(indexes["reverse_import_index"], build_id))
    atomic_write_json(IDX["test"], versioned(indexes["test_index"], build_id))
    atomic_write_json(IDX["feature"], versioned(indexes["feature_index"], build_id))
    atomic_write_json(IDX["artifact"], versioned(indexes["artifact_index"], build_id))
    atomic_write_json(IDX["alias"], versioned(indexes["alias_index"], build_id))
    atomic_write_json(IDX["inverted_token"], versioned(indexes["inverted_token_index"], build_id))
    atomic_write_json(IDX["bm25"], versioned(indexes["bm25_index"], build_id))
    atomic_write_json(IDX["reuse_candidate"], versioned(indexes["reuse_candidate_index"], build_id))
    atomic_write_json(IDX["graph_adjacency"], versioned(indexes["graph_adjacency_index"], build_id))

    fingerprints = {
        fm["file_id"]: {
            "mtime_ns": fm["mtime_ns"],
            "size": fm["size"],
            "content_hash": fm.get("content_hash"),
            "parser_version": PARSER_VERSION,
        }
        for fm in all_file_meta
    }
    atomic_write_json(IDX["fingerprints"], versioned({"fingerprints": fingerprints}, build_id))

    atomic_write_json(IDX["deleted"], versioned({"deleted_file_ids": deleted}, build_id))
    atomic_write_json(IDX["skipped"], versioned({"skipped_files": skipped[:500]}, build_id))

    manifest = versioned({
        "indexes": {k: str(v) for k, v in IDX.items() if k != "lock"},
    }, build_id)
    atomic_write_json(IDX["index_manifest"], manifest)

    build_meta = versioned({
        "build_id": build_id,
        "build_duration_sec": duration,
        "incremental": incremental,
        "changed_count": changed_count,
        "repo_count": repo_count,
        "file_count": file_count,
        "workspace_root": cfg.get("workspace_root", ""),
        "parser_version": PARSER_VERSION,
        "is_consistent": True,
    }, build_id)
    atomic_write_json(IDX["build_metadata"], build_meta)


def _summarize_skipped(skipped: list[dict]) -> dict:
    reasons: dict[str, int] = {}
    for s in skipped:
        r = s.get("reason", "unknown")
        if "sensitive" in r:
            r = "sensitive"
        reasons[r] = reasons.get(r, 0) + 1
    return reasons


def run_check_mode() -> int:
    """Validate-only: check indexes exist and are valid. Returns exit code."""
    required = [IDX["workspace"], IDX["repo"], IDX["file"], IDX["module"],
                IDX["symbol"], IDX["feature"], IDX["alias"], IDX["reuse_candidate"],
                IDX["build_metadata"]]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        print(f"MISSING indexes: {', '.join(missing)}")
        return 1
    for p in required:
        data = load_json(p, None)
        if data is None:
            print(f"INVALID JSON: {p}")
            return 1
        if isinstance(data, dict) and data.get("schema_version") != SCHEMA_VERSION:
            print(f"SCHEMA_VERSION mismatch: {p}")
            return 1
    print("workspace-intelligence: check pass")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build workspace intelligence indexes")
    parser.add_argument("--workspace", help="Workspace root path")
    parser.add_argument("--config", help="Config file path")
    parser.add_argument("--rebuild", action="store_true", help="Force clean rebuild")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")
    parser.add_argument("--pretty", action="store_true", help="Print summary")
    parser.add_argument("--check", action="store_true", help="Validate-only smoke test")
    parser.add_argument(
        "--skip-if-locked", action="store_true",
        help="Exit 0 (benign skip) instead of 1 when the lock is already held — "
             "used at startup, where the workspace-intelligence daemon may "
             "already hold the lock and keep the index fresh on its own.",
    )
    args = parser.parse_args()

    if args.check:
        return run_check_mode()

    build_start = time.monotonic()
    build_id = str(uuid.uuid4())[:8]

    cfg = load_config(args.config)
    if args.workspace:
        cfg["workspace_root"] = args.workspace
    workspace_root = cfg["workspace_root"]

    quiet = args.quiet

    _log(f"workspace-intelligence: starting build (id={build_id})", quiet)

    if not acquire_lock():
        if args.skip_if_locked:
            _log("workspace-intelligence: lock held (daemon likely building) — skipping", quiet)
            return 0
        print("workspace-intelligence: could not acquire lock — another build may be running")
        return 1

    try:
        return _build(cfg, workspace_root, build_id, build_start, args.rebuild, quiet, args.pretty)
    finally:
        release_lock()


def _write_workspace_discovery(repos: list[dict]) -> None:
    """Persist `.claude/state/workspace-discovery.json` from the already-computed
    per-repo content signature (languages/frameworks) — the shared discovery artifact
    that `bi_logic_discoverer.py` and `corporate_spine_compiler.py` read, kept fresh on
    every index build instead of requiring a separate `workspace_discoverer.py` run."""
    out = Path(ROOT) / ".claude" / "state" / "workspace-discovery.json"
    projects = [
        {
            "root_path": r["path"],
            "languages": r.get("languages", []),
            "frameworks": r.get("frameworks", []),
            "build_system": "detected",
        }
        for r in repos
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"projects": projects}, indent=2), encoding="utf-8")


def _build(cfg: dict, workspace_root: str, build_id: str, build_start: float,
           force_rebuild: bool, quiet: bool, pretty: bool) -> int:
    """Execute the full 9-phase build pipeline."""

    _log("Phase 1: discovering repos...", quiet)
    repos = discover_repos(workspace_root, cfg)
    _write_workspace_discovery(repos)
    if not repos:
        _log(f"workspace-intelligence: no repos found under {workspace_root} matching "
             f"{cfg.get('repo_include_globs')}", quiet)
        indexes = aggregate_indexes([], [], [], cfg, build_id)
        write_indexes(indexes, [], [], [], [], [], build_id, build_start,
                      False, 0, cfg, quiet)
        return 0
    _log(f"  found {len(repos)} repo(s): {[r['repo_id'] for r in repos]}", quiet)

    incremental = cfg.get("incremental", True) and not force_rebuild
    previous_fingerprints: dict = {}
    previous_file_index: dict = {}

    if incremental:
        fp_data = load_json(IDX["fingerprints"], None)
        if isinstance(fp_data, dict):
            stored_sv = fp_data.get("schema_version")
            if stored_sv != SCHEMA_VERSION:
                _log("  schema_version mismatch — forcing clean rebuild", quiet)
                incremental = False
            else:
                previous_fingerprints = fp_data.get("fingerprints", {})
        else:
            incremental = False

        if incremental:
            fi_data = load_json(IDX["file"], None)
            if isinstance(fi_data, dict):
                previous_file_index = {k: v for k, v in fi_data.items()
                                       if k not in ("schema_version", "generated_at", "build_id")}

    workers = resolve_workers(cfg)

    _log("Phase 3: scanning repos...", quiet)
    all_file_stats: list[dict] = []
    all_dir_stats: list[dict] = []
    all_skipped: list[dict] = []

    if workers > 1 and len(repos) > 1:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(workers, len(repos))
        ) as pool:
            futures = {pool.submit(scan_repo, repo, cfg): repo for repo in repos}
            _scan_results: dict[str, tuple] = {}
            for fut in concurrent.futures.as_completed(futures):
                _repo = futures[fut]
                _scan_results[_repo["repo_id"]] = fut.result()
        for repo in sorted(repos, key=lambda r: r["repo_id"]):
            fstats, dstats, skipped = _scan_results[repo["repo_id"]]
            all_file_stats.extend(fstats)
            all_dir_stats.extend(dstats)
            all_skipped.extend(skipped)
            _log(f"  {repo['repo_id']}: {len(fstats)} files, {len(skipped)} skipped", quiet)
    else:
        for repo in repos:
            fstats, dstats, skipped = scan_repo(repo, cfg)
            all_file_stats.extend(fstats)
            all_dir_stats.extend(dstats)
            all_skipped.extend(skipped)
            _log(f"  {repo['repo_id']}: {len(fstats)} files, {len(skipped)} skipped", quiet)

    _log("Phase 4: incremental diff...", quiet)
    if incremental and previous_fingerprints:
        unchanged, changed, deleted = compute_diff(
            all_file_stats, previous_fingerprints, previous_file_index, cfg
        )
    else:
        unchanged, changed, deleted = [], all_file_stats, []

    changed_count = len(changed)
    _log(f"  unchanged={len(unchanged)}, changed={changed_count}, deleted={len(deleted)}", quiet)

    if incremental and changed_count == 0 and not deleted:
        duration = round(time.monotonic() - build_start, 2)
        repo_count = len(repos)
        file_count = len(all_file_stats)
        _log(f"workspace-intelligence: green, repos={repo_count}, files={file_count}, "
             f"changed=0, duration={duration}s", quiet)
        build_meta = versioned({
            "build_id": build_id,
            "build_duration_sec": duration,
            "incremental": True,
            "changed_count": 0,
            "repo_count": repo_count,
            "file_count": file_count,
            "workspace_root": cfg.get("workspace_root", ""),
            "parser_version": PARSER_VERSION,
            "is_consistent": True,
        }, build_id)
        atomic_write_json(IDX["build_metadata"], build_meta)
        return 0

    _log(f"Phase 5: parsing {changed_count} changed file(s)...", quiet)
    parsed_changed: dict[str, dict] = {}
    _use_parallel_parse = workers > 1 and changed_count >= _PARALLEL_PARSE_THRESHOLD

    if _use_parallel_parse:
        try:
            work_items = [(fs, cfg) for fs in changed]
            with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
                for pm in pool.map(_worker_parse_file, work_items, chunksize=16):
                    parsed_changed[pm["file_id"]] = pm
            _log(f"  parsed {len(parsed_changed)} file(s) (parallel, workers={workers})", quiet)
        except Exception as exc:
            _log(f"  parallel parse error ({exc}) — falling back to sequential", quiet)
            parsed_changed.clear()
            _use_parallel_parse = False

    if not _use_parallel_parse:
        for fs in changed:
            try:
                pm = parse_file(fs, cfg)
                parsed_changed[fs["file_id"]] = pm
            except Exception as exc:
                parsed_changed[fs["file_id"]] = {
                    **fs, "parse_status": f"error: {exc}",
                    "parser_version": PARSER_VERSION,
                    "symbols_defined": [], "imports": [], "reuse_tags": [],
                    "likely_feature_area": [], "short_summary": "",
                }

    all_file_meta: list[dict] = []

    for fs in unchanged:
        fid = fs["file_id"]
        if fid in previous_file_index:
            all_file_meta.append(previous_file_index[fid])
        else:
            try:
                pm = parse_file(fs, cfg)
                all_file_meta.append(pm)
            except Exception as exc:
                all_file_meta.append({**fs, "parse_status": f"error: {exc}",
                                      "parser_version": PARSER_VERSION,
                                      "symbols_defined": [], "imports": [],
                                      "reuse_tags": [], "likely_feature_area": [],
                                      "short_summary": ""})

    all_file_meta.extend(parsed_changed.values())

    _log("Phase 6: aggregating indexes...", quiet)
    indexes = aggregate_indexes(all_file_meta, all_dir_stats, repos, cfg, build_id)

    if cfg.get("write_human_summaries", True):
        _log("Phase 7: writing human summaries...", quiet)
        try:
            write_human_summaries(repos, indexes, quiet)
            _refresh_fingerprints_after_phase7(all_file_meta)
        except Exception as exc:
            _log(f"  warning: human summaries failed: {exc}", quiet)

    _log("Phase 8: writing indexes...", quiet)
    write_indexes(indexes, all_file_meta, all_dir_stats, repos, all_skipped, deleted,
                  build_id, build_start, incremental, changed_count, cfg, quiet)

    if cfg.get("fts5_sync", True):
        _log("Phase 9: syncing FTS5 code corpus...", quiet)
        try:
            fts5_docs = all_file_meta if not incremental else list(parsed_changed.values())
            sync_fts5_code_corpus(fts5_docs, deleted, cfg, quiet=quiet)
        except Exception as exc:
            _log(f"  warning: FTS5 sync failed: {exc}", quiet)

    duration = round(time.monotonic() - build_start, 2)
    repo_count = len(repos)
    file_count = len(all_file_meta)
    _log(f"workspace-intelligence: green, repos={repo_count}, files={file_count}, "
         f"changed={changed_count}, duration={duration}s", quiet)

    if pretty:
        print(json.dumps({
            "status": "ok",
            "repos": repo_count,
            "files": file_count,
            "changed": changed_count,
            "deleted": len(deleted),
            "skipped": len(all_skipped),
            "duration_sec": duration,
            "build_id": build_id,
        }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
