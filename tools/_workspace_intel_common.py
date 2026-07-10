#!/usr/bin/env python3
"""_workspace_intel_common.py â€” Shared helpers for the workspace intelligence layer.

Provides: atomic writes, schema versioning, lock management, pure-Python BM25,
path helpers, config loading, token normalization, sensitivity checks.
"""

import fnmatch
import hashlib
import json
import math
import os
import re
import sys
import time
import tomllib
import uuid
from datetime import UTC, datetime
from pathlib import Path


def _resolve_workspace_root() -> Path:
    env = os.environ.get("CITADEL_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / ".citadel" / "config.toml").is_file():
            return candidate
    return Path(__file__).resolve().parents[1]


ROOT = _resolve_workspace_root()
STATE = ROOT / ".claude" / "state"
WS_STATE = STATE / "workspace-intelligence"
WS_CONFIG_PATH = ROOT / ".claude" / "brain" / "workspace-index-config.json"

IDX = {
    "workspace":          WS_STATE / "workspace-index.json",
    "repo":               WS_STATE / "repo-index.json",
    "path":               WS_STATE / "path-index.json",
    "file":               WS_STATE / "file-index.json",
    "dir":                WS_STATE / "dir-index.json",
    "module":             WS_STATE / "module-index.json",
    "symbol":             WS_STATE / "symbol-index.json",
    "qualified_symbol":   WS_STATE / "qualified-symbol-index.json",
    "import":             WS_STATE / "import-index.json",
    "reverse_import":     WS_STATE / "reverse-import-index.json",
    "test":               WS_STATE / "test-index.json",
    "feature":            WS_STATE / "feature-index.json",
    "artifact":           WS_STATE / "artifact-index.json",
    "alias":              WS_STATE / "alias-index.json",
    "inverted_token":     WS_STATE / "inverted-token-index.json",
    "bm25":               WS_STATE / "bm25-index.json",
    "reuse_candidate":    WS_STATE / "reuse-candidate-index.json",
    "graph_adjacency":    WS_STATE / "graph-adjacency-index.json",
    "fingerprints":       WS_STATE / "file-fingerprints.json",
    "deleted":            WS_STATE / "deleted-files.json",
    "skipped":            WS_STATE / "skipped-files.json",
    "build_metadata":     WS_STATE / "build-metadata.json",
    "index_manifest":     WS_STATE / "index-manifest.json",
    "lock":               WS_STATE / "index.lock",
    "vector_dir":         WS_STATE / "vector-index",
}

SCHEMA_VERSION = "1.0"


def versioned(payload: dict, build_id: str | None = None) -> dict:
    """Add schema_version, generated_at, build_id to any payload dict."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "build_id": build_id or str(uuid.uuid4())[:8],
        **payload,
    }


def load_json(path: str | Path, default=None):
    """Load JSON file, return default on any error."""
    try:
        p = Path(path)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_write_json(path: str | Path, data: dict | list) -> None:
    """Write JSON atomically: temp-file â†’ fsync â†’ os.replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + ".tmp")
    try:
        content = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        tmp.write_text(content, encoding="utf-8")
        try:
            fd = os.open(str(tmp), os.O_WRONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception:
            pass
        os.replace(str(tmp), str(p))
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


_DEFAULT_CFG_EXCLUDE_DIRS = [
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", ".eggs", "node_modules",
    "dist", "build", "target", ".idea", ".vscode", ".parcompute-worker-space",
    ".ipynb_checkpoints", "coverage", "htmlcov", "tmp", "temp",
    "logs", "data", "output", "outputs", "artifacts/generated",
    "generated", "cache", "caches", ".claude/state/workspace-intelligence",
]
_DEFAULT_CFG_SENSITIVE = [
    ".env", ".env.*", "*.pem", "*.key", "*.crt", "*.p12", "*.pfx",
    "id_rsa", "id_ed25519", "credentials*", "secrets*", "token*",
    "*token*", "*secret*", "*password*", "kubeconfig", ".netrc",
    "service-account*.json", "google-credentials*.json", "aws_credentials",
]
_PRIVATE_KEY_HEADERS = [
    b"-----BEGIN RSA PRIVATE KEY",
    b"-----BEGIN EC PRIVATE KEY",
    b"-----BEGIN OPENSSH PRIVATE KEY",
    b"-----BEGIN PRIVATE KEY",
    b"-----BEGIN PGP PRIVATE KEY",
]


def _strip_jsonc_comments(text: str) -> str:
    """Strip // and /* */ comments from a JSONC string (VS Code allows both).

    Mirrors src/citadel/paths.py::_strip_jsonc_comments â€” kept as a
    dependency-free duplicate so standalone tools never need the installed
    package on sys.path.
    """
    out: list[str] = []
    in_string = False
    escape = False
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def resolve_vscode_folders(root: Path, code_workspace: str | None = None) -> list[Path] | None:
    """Return absolute repo folder paths from a `*.code-workspace` file's `folders[]`, or None.

    Mirrors src/citadel/paths.py::resolve_vscode_folders â€” kept as a
    dependency-free duplicate so standalone tools never need the installed
    package on sys.path. See that function's docstring for lookup order / fallback
    semantics.
    """
    candidates: list[Path] = []
    if code_workspace:
        p = Path(code_workspace).expanduser()
        candidates.append(p if p.is_absolute() else (root / p).resolve())
    else:
        for base in (root, root.parent):
            try:
                found = sorted(base.glob("*.code-workspace"))
            except OSError:
                found = []
            if len(found) == 1:
                candidates.append(found[0])
                break
            if len(found) > 1:
                return None

    for ws_file in candidates:
        if not ws_file.is_file():
            continue
        try:
            data = json.loads(_strip_jsonc_comments(ws_file.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        folders = data.get("folders") if isinstance(data, dict) else None
        if not isinstance(folders, list) or not folders:
            continue
        base_dir = ws_file.parent
        resolved: list[Path] = []
        for entry in folders:
            raw_path = entry.get("path") if isinstance(entry, dict) else None
            if not raw_path:
                continue
            fp = Path(raw_path).expanduser()
            fp = fp.resolve() if fp.is_absolute() else (base_dir / fp).resolve()
            if fp.is_dir():
                resolved.append(fp)
        if resolved:
            return resolved
    return None


def _scope_from_toml() -> dict:
    """Read the drift-prone scope keys from .citadel/config.toml (SSOT).

    Mirrors src/citadel/paths.py::workspace_config() but stays dependency-free
    so standalone tools never need the installed package on sys.path. Returns an
    empty dict when config.toml is absent or unreadable.

    A `*.code-workspace` file takes priority when present: its `folders[]` become
    `repo_include_paths`, scoping discovery to exactly what the operator's editor
    Explorer shows, regardless of where those folders live on disk.
    """
    cfg_path = ROOT / ".citadel" / "config.toml"
    if not cfg_path.is_file():
        return {}
    try:
        with cfg_path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    index = data.get("index", {}) if isinstance(data, dict) else {}
    scope: dict = {}
    if "repo_exclude_globs" in index:
        scope["repo_exclude_globs"] = list(index["repo_exclude_globs"])

    vscode_folders = resolve_vscode_folders(ROOT, index.get("code_workspace"))
    if vscode_folders:
        scope["workspace_root"] = str(ROOT.parent)
        scope["repo_include_globs"] = [p.name for p in vscode_folders]
        scope["repo_include_paths"] = [str(p) for p in vscode_folders]
        return scope

    scan_root = index.get("scan_root")
    if scan_root:
        scope["workspace_root"] = str(Path(scan_root).expanduser().resolve())
    if "repo_include_globs" in index:
        scope["repo_include_globs"] = list(index["repo_include_globs"])
    scope["repo_include_paths"] = None
    return scope


def load_config(config_path: str | Path | None = None) -> dict:
    """Load workspace-index-config.json, with .citadel/config.toml as scope SSOT.

    The three scope values (workspace_root, repo_include_globs, repo_exclude_globs)
    are taken from config.toml when present so they can never drift from the CLI's
    view again; the JSON supplies the many detailed index knobs.
    """
    cfg = load_json(config_path or WS_CONFIG_PATH, {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.update(_scope_from_toml())
    cfg.setdefault("schema_version", SCHEMA_VERSION)
    cfg.setdefault("workspace_root", str(ROOT.parent))
    cfg.setdefault("repo_include_globs", ["*"])
    cfg.setdefault("repo_include_paths", None)
    cfg.setdefault("repo_exclude_globs", [])
    cfg.setdefault("include_extensions", [
        ".py", ".md", ".json", ".yaml", ".yml", ".toml",
        ".sh", ".feature", ".sql", ".txt",
    ])
    cfg.setdefault("exclude_dirs", _DEFAULT_CFG_EXCLUDE_DIRS)
    cfg.setdefault("sensitive_file_patterns", _DEFAULT_CFG_SENSITIVE)
    cfg.setdefault("max_file_size_bytes", 1_000_000)
    cfg.setdefault("max_text_index_bytes", 1_000_000)
    cfg.setdefault("content_hash_for_small_files", True)
    cfg.setdefault("content_hash_max_bytes", 262_144)
    cfg.setdefault("incremental", True)
    cfg.setdefault("write_human_summaries", True)
    cfg.setdefault("write_machine_indexes", True)
    cfg.setdefault("write_sparse_index", True)
    cfg.setdefault("write_vector_index", False)
    cfg.setdefault("vector_embedding_backend", "disabled_by_default")
    cfg.setdefault("vector_embedding_model", None)
    cfg.setdefault("graph_show_file_nodes", "important_only")
    cfg.setdefault("important_file_rules", [
        "assets", "schemas", "validators", "tests", "agents",
        "rules", "tools", "configs", "workflow_manifests", "feature_files",
    ])
    cfg.setdefault("query_max_results", 20)
    cfg.setdefault("query_default_mode", "hybrid")
    cfg.setdefault("atomic_writes", True)
    return cfg


def normalize_tokens(text: str) -> list[str]:
    """Canonical tokenizer: lowercased alphanumeric+underscore tokens, len >= 2."""
    return [t for t in re.findall(r"[a-zA-Z0-9_][a-zA-Z0-9_\-]{1,}", text.lower()) if len(t) > 1]


def alias_normalize(phrase: str) -> str:
    """Normalize a multi-word phrase to underscore-separated form: 'sample feature' â†’ 'sample_feature'."""
    return re.sub(r"[\s\-]+", "_", phrase.strip().lower())


def _matches_glob(name: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


def is_sensitive_path(path: Path, cfg: dict) -> tuple[bool, str]:
    """Return (is_sensitive, reason) for the given file path."""
    patterns = cfg.get("sensitive_file_patterns", _DEFAULT_CFG_SENSITIVE)
    name = path.name
    if _matches_glob(name, patterns):
        return True, f"name matches sensitive pattern: {name}"
    secret_terms = {"secret", "password", "credential", "private_key", "apikey", "api_key"}
    stem = path.stem.lower()
    if any(t in stem for t in secret_terms):
        if path.suffix in ("", ".env", ".txt", ".json", ".yaml", ".yml", ".toml"):
            return True, f"filename stem looks secret-like: {path.name}"
    return False, ""


def is_sensitive_content(path: Path, cfg: dict) -> tuple[bool, str]:
    """Check first bytes of a file for private-key headers. Best-effort, no content logging."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
        for header in _PRIVATE_KEY_HEADERS:
            if head.startswith(header):
                return True, "private key header detected"
    except Exception:
        pass
    return False, ""


def is_excluded_dir(name: str, cfg: dict) -> bool:
    """Return True if dir name should be excluded."""
    exclude = cfg.get("exclude_dirs", _DEFAULT_CFG_EXCLUDE_DIRS)
    return name in exclude


def file_id(repo: str, relpath: str) -> str:
    """Stable O(1) key: 'repo:relative/path'."""
    return f"{repo}:{relpath}"


def dir_id(repo: str, relpath: str) -> str:
    """Stable O(1) key for directories."""
    return f"{repo}:{relpath}"


def module_name_from_path(repo: str, relpath: str) -> str | None:
    """Convert a .py relative path to dotted module name, or None if not applicable."""
    p = Path(relpath)
    if p.suffix != ".py":
        return None
    parts = list(p.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    return ".".join(parts)


def content_hash(path: Path, max_bytes: int = 262_144) -> str | None:
    """Return SHA-256 hex of first max_bytes of file content."""
    try:
        with open(path, "rb") as f:
            data = f.read(max_bytes)
        return hashlib.sha256(data).hexdigest()[:16]
    except Exception:
        return None


LOCK_STALE_SECONDS = 300


def acquire_lock(max_wait: int = 30) -> bool:
    """Acquire index.lock. Returns True on success, False on timeout."""
    lock_path = IDX["lock"]
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if _try_acquire_lock(lock_path):
            return True
        time.sleep(0.5)
    return False


def _try_acquire_lock(lock_path: Path) -> bool:
    if lock_path.exists():
        try:
            lock_data = json.loads(lock_path.read_text())
            pid = lock_data.get("pid", 0)
            started = lock_data.get("started_at", 0)
            age = time.time() - started
            if age > LOCK_STALE_SECONDS:
                lock_path.unlink(missing_ok=True)
            else:
                try:
                    os.kill(pid, 0)
                    return False
                except (ProcessLookupError, PermissionError):
                    lock_path.unlink(missing_ok=True)
        except Exception:
            lock_path.unlink(missing_ok=True)
    try:
        tmp = Path(str(lock_path) + ".tmp")
        tmp.write_text(json.dumps({"pid": os.getpid(), "started_at": time.time()}))
        os.replace(str(tmp), str(lock_path))
        return True
    except Exception:
        return False


def release_lock() -> None:
    lock_path = IDX["lock"]
    try:
        if lock_path.exists():
            data = load_json(lock_path, {})
            if isinstance(data, dict) and data.get("pid") == os.getpid():
                lock_path.unlink(missing_ok=True)
    except Exception:
        pass


class BM25:
    """Pure-Python BM25 scorer. No external dependencies.
    k1=1.5, b=0.75 (standard defaults).
    """
    k1: float = 1.5
    b: float = 0.75

    @staticmethod
    def build(corpus: dict[str, list[str]]) -> dict:
        """Build BM25 index from {doc_id: [tokens]} corpus.

        Returns a dict suitable for JSON serialization and bm25_score().
        """
        N = len(corpus)
        if N == 0:
            return {"N": 0, "avgdl": 0.0, "df": {}, "tf": {}, "dl": {}}

        tf: dict[str, dict[str, int]] = {}
        dl: dict[str, int] = {}
        df: dict[str, int] = {}

        for doc_id, tokens in corpus.items():
            dl[doc_id] = len(tokens)
            term_counts: dict[str, int] = {}
            for t in tokens:
                term_counts[t] = term_counts.get(t, 0) + 1
            for term, count in term_counts.items():
                tf.setdefault(term, {})[doc_id] = count
                df[term] = df.get(term, 0) + 1

        avgdl = sum(dl.values()) / N if N > 0 else 0.0
        return {"N": N, "avgdl": avgdl, "df": df, "tf": tf, "dl": dl}

    @staticmethod
    def score(query_tokens: list[str], bm25_index: dict, top_k: int = 20) -> list[tuple[float, str]]:
        """Score all documents for query_tokens. Returns sorted [(score, doc_id)]."""
        if not bm25_index or not query_tokens:
            return []
        N = bm25_index.get("N", 0)
        if N == 0:
            return []
        avgdl = bm25_index.get("avgdl", 1.0) or 1.0
        df = bm25_index.get("df", {})
        tf_index = bm25_index.get("tf", {})
        dl = bm25_index.get("dl", {})
        k1, b = BM25.k1, BM25.b

        scores: dict[str, float] = {}
        for term in query_tokens:
            if term not in tf_index:
                continue
            idf = math.log((N - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5) + 1.0)
            for doc_id, freq in tf_index[term].items():
                doc_len = dl.get(doc_id, avgdl)
                numerator = freq * (k1 + 1)
                denominator = freq + k1 * (1 - b + b * doc_len / avgdl)
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * numerator / denominator

        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return [(score_val, doc_id) for doc_id, score_val in ranked[:top_k]]


# The Citadel ships with NO workspace/domain feature vocabulary — these aliases cover only the
# Citadel's own agnostic subsystems. A workspace's real features (and their aliases/keywords) are
# LEARNED during indexing/mining and stored per-province, never hardcoded here.
FEATURE_ALIASES: dict[str, str] = {
    "data contract": "data_contract",
    "data_contract": "data_contract",
    "workspace intelligence": "workspace_intelligence",
    "workspace_intelligence": "workspace_intelligence",
    "citadel ui": "citadel_ui",
    "citadel_ui": "citadel_ui",
    "graph brain": "graph_brain",
    "graph_brain": "graph_brain",
    "brain graph": "graph_brain",
    "memory policy": "memory_policy",
    "memory_policy": "memory_policy",
    "artifact policy": "artifact_policy",
    "artifact_policy": "artifact_policy",
    "execution manifest": "execution_manifest",
    "execution_manifest": "execution_manifest",
    "scheduler": "scheduler",
}

FEATURE_KEYWORDS: dict[str, set[str]] = {
    "data_contract": {"data_contract", "datacontract", "contract"},
    "workspace_intelligence": {"workspace_intelligence", "workspace", "intelligence", "index"},
    "citadel_ui": {"citadel", "citadel_ui", "citadelui"},
    "graph_brain": {"graph_brain", "brain_graph", "brain", "graphbrain"},
    "scheduler": {"scheduler", "scheduling", "cron"},
    "memory_policy": {"memory_policy", "memorypolicy", "memory"},
    "artifact_policy": {"artifact_policy", "artifactpolicy", "artifact"},
    "execution_manifest": {"execution_manifest", "manifest"},
    "tests": {"test", "tests", "conftest", "fixture", "pytest"},
}


def _symbol_sub_tokens(symbols: list[str]) -> set[str]:
    """Break symbol names into sub-tokens for feature detection.

    Handles CamelCase (OrderProcessor -> order, processor)
    and underscore separation (compute_total_price -> compute, total, price).
    """
    out: set[str] = set()
    for s in symbols:
        sl = s.lower()
        out.add(sl)
        out.update(sl.split("_"))
        parts = re.findall(r"[A-Z][a-z]*|[a-z]+|[0-9]+", s)
        out.update(p.lower() for p in parts)
    out.discard("")
    return out


def detect_features(path: Path, repo: str, symbols: list[str], imports: list[str],
                    decorators: list[str], content_tokens: list[str]) -> list[str]:
    """Heuristic feature detection from multiple signals."""
    features: set[str] = set()
    parts_lower = [p.lower() for p in path.parts]
    path_str = str(path).lower()

    for feat, keywords in FEATURE_KEYWORDS.items():
        if any(kw in p for p in parts_lower for kw in keywords):
            features.add(feat)
        if any(kw in path_str for kw in keywords):
            features.add(feat)

    flat_tokens = set(t.lower() for t in imports + decorators + content_tokens)
    for feat, keywords in FEATURE_KEYWORDS.items():
        if any(kw in flat_tokens for kw in keywords):
            features.add(feat)

    sym_sub = _symbol_sub_tokens(symbols)
    for feat, keywords in FEATURE_KEYWORDS.items():
        if any(kw in sym_sub for kw in keywords):
            features.add(feat)

    return sorted(features)


def build_reuse_tags(file_meta: dict) -> list[str]:
    """Build reuse tags from file metadata."""
    tags: set[str] = set()
    tags.update(file_meta.get("likely_feature_area", []))
    if file_meta.get("orchestration_assets"):
        tags.add("orchestration_asset")
    if file_meta.get("schema_checks"):
        tags.add("schema_check")
    if file_meta.get("schema_models"):
        tags.add("schemaval")
    if file_meta.get("config_models"):
        tags.add("configmodel")
    if file_meta.get("distributed_usage"):
        tags.add("distributed")
    if file_meta.get("dataframe_usage"):
        tags.add("dataframe")
    if file_meta.get("query_usage"):
        tags.add("query")
    if file_meta.get("tests_related"):
        tags.add("tests")
    return sorted(tags)


def resolve_workers(cfg: dict) -> int:
    """Resolve parallel_workers from config to an int clamped to [1, 8].

    'auto' â†’ os.cpu_count() clamped to [2, 8].
    Any other value is coerced to int and clamped to [1, 8].
    Falls back to 1 (sequential) on any error.
    """
    raw = cfg.get("parallel_workers", 1)
    if raw == "auto":
        cores = os.cpu_count() or 1
        return max(2, min(cores, 8))
    try:
        return max(1, min(int(raw), 8))
    except (TypeError, ValueError):
        return 1


def sync_fts5_code_corpus(
    changed_meta: list[dict],
    deleted_ids: list[str],
    cfg: dict,
    *,
    quiet: bool = False,
) -> None:
    """Push changed/deleted file metadata into the unified FTS5 'code' corpus.

    Design:
    - Always non-fatal: if the DB or module is unavailable, logs a warning and returns.
    - Incremental: only pushes changed docs and removes deleted doc_ids.
    - Gated by cfg['fts5_sync'] (default True).
    - index_document does DELETE+INSERT per doc so re-pushing unchanged files is safe.
    """
    if not cfg.get("fts5_sync", True):
        return
    if not changed_meta and not deleted_ids:
        return

    _tools_dir = Path(__file__).resolve().parent
    try:
        if str(_tools_dir) not in sys.path:
            sys.path.insert(0, str(_tools_dir))
        from unified_query import UnifiedQueryEngine  # noqa: PLC0415
    except Exception as exc:
        _fts5_log(f"skipped â€” could not import UnifiedQueryEngine: {exc}", quiet)
        return

    try:
        engine = UnifiedQueryEngine()
    except Exception as exc:
        _fts5_log(f"skipped â€” could not open DB: {exc}", quiet)
        return

    errors = 0
    try:
        for fid in deleted_ids:
            try:
                engine.delete_document(fid)
            except Exception:
                errors += 1

        for fm in changed_meta:
            try:
                doc_id = fm.get("file_id", "")
                if not doc_id:
                    continue
                content = _fts5_build_content(fm)
                tags = _fts5_build_tags(fm)
                engine.index_document("code", doc_id, content, tags)
            except Exception:
                errors += 1
    finally:
        try:
            engine.close()
        except Exception:
            pass

    n_changed = len(changed_meta)
    n_deleted = len(deleted_ids)
    if errors:
        _fts5_log(
            f"complete with {errors} error(s) (changed={n_changed}, deleted={n_deleted})",
            quiet,
        )
    else:
        _fts5_log(f"ok (changed={n_changed}, deleted={n_deleted})", quiet)


def _fts5_log(msg: str, quiet: bool) -> None:
    if not quiet:
        print(f"  [fts5] {msg}", flush=True)


def _fts5_build_content(fm: dict) -> str:
    """Build FTS5 content string from file metadata."""
    parts: list[str] = []
    summary = fm.get("short_summary", "")
    if summary:
        parts.append(summary)
    symbols = fm.get("symbols_defined", [])
    if symbols:
        parts.append(" ".join(symbols))
    module = fm.get("module_name", "")
    if module:
        parts.append(module)
    features = fm.get("likely_feature_area", [])
    if features:
        parts.append(" ".join(features))
    rel = fm.get("relative_path", "")
    if rel:
        parts.append(rel)
    return " ".join(parts)


def _fts5_build_tags(fm: dict) -> list[str]:
    """Build FTS5 tag list from file metadata."""
    tags: list[str] = []
    repo = fm.get("repo", "")
    if repo:
        tags.append(repo)
    tags.extend(fm.get("likely_feature_area", []))
    lang = fm.get("language", "")
    if lang and lang != "unknown":
        tags.append(lang)
    for flag, tag in [
        ("orchestration_assets", "orchestration"),
        ("schema_checks", "asset_check"),
        ("schema_models", "schemaval"),
        ("config_models", "configmodel"),
        ("distributed_usage", "distributed"),
        ("dataframe_usage", "dataframe"),
        ("query_usage", "query"),
    ]:
        if fm.get(flag):
            tags.append(tag)
    return tags
