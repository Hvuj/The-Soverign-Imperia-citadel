"""paths.py — Workspace-root resolver for The Sovereign Imperia Citadel.

All state, index, brain, and memory paths are derived from the TARGET WORKSPACE,
never from this package's install location.

Precedence for workspace_root():
  1. CITADEL_WORKSPACE env var (set by `citadel init` or by the user)
  2. .citadel/config.toml discovered by walking up from cwd
  3. CitadelNotInitialized raised — never falls back to __file__ / site-packages.

Precedence for state_dir():
  1. CITADEL_STATE_DIR env var
  2. workspace_root() / ".citadel"
"""

import json
import os
import time
import tomllib
from pathlib import Path


class CitadelNotInitialized(RuntimeError):
    """Raised when no workspace root can be resolved."""

    def __init__(self, cwd: Path | None = None) -> None:
        cwd = cwd or Path.cwd()
        super().__init__(
            f"No Citadel workspace found for '{cwd}'.\n"
            "Run `citadel init <workspace>` first, or set CITADEL_WORKSPACE."
        )


class CitadelBootError(RuntimeError):
    """A dot-directory could not be created or verified (masterplan §11)."""


def is_unsafe_placement(path: Path) -> str | None:
    """Return why `path` is an unsafe home for Citadel state, or None if it is fine (masterplan §11.2).

    Windows/WSL 9P (`/mnt/c`) and OneDrive-synced paths corrupt dot-directories (mtime lies, cloud
    placeholders), which is the root cause of the "`.claude` is broken when clicked" bug."""
    normalized = str(path).replace("\\", "/")
    if normalized.startswith("/mnt/c/") or "/mnt/c/" in normalized:
        return "under /mnt/c (WSL 9P boundary — mtime lies and placeholders break dot-dirs)"
    if any(part.lower().startswith("onedrive") for part in path.parts):
        return "under a OneDrive-synced path (cloud placeholders corrupt dot-dirs)"
    return None


def ensure_dot_dir(path: str | Path, *, strict: bool = False) -> Path:
    """Create a dot-directory correctly (masterplan §11.3). The only sanctioned dot-dir creator.

    - Quarantines a *file* squatting on the directory's name to `<name>.broken.<ts>` (never destroyed).
    - Verifies the result is a real, writable directory via a probe round-trip.
    - `strict=True` refuses unsafe placement (/mnt/c, OneDrive); default warns via `is_unsafe_placement`
      so an existing OneDrive workspace still works while `citadel doctor` surfaces the risk.
    """
    raw = Path(path).expanduser()
    if strict:
        unsafe = is_unsafe_placement(raw)
        if unsafe:
            raise CitadelBootError(f"{raw} is unsafe: {unsafe} (masterplan §11.2)")
    resolved = raw.resolve()
    if resolved.exists() and not resolved.is_dir():
        quarantine = resolved.with_name(f"{resolved.name}.broken.{int(time.time())}")
        resolved.rename(quarantine)
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CitadelBootError(f"could not create {resolved}: {exc}") from exc
    if not resolved.is_dir():
        raise CitadelBootError(f"{resolved} exists but is not a directory after mkdir")
    probe = resolved / ".citadel-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        ok = probe.read_text(encoding="utf-8") == "ok"
    except OSError as exc:
        raise CitadelBootError(f"{resolved} failed write/read round-trip: {exc}") from exc
    finally:
        if probe.exists():
            probe.unlink()
    if not ok:
        raise CitadelBootError(f"{resolved} failed write/read round-trip")
    return resolved


def _find_config_toml(start: Path) -> Path | None:
    """Walk up from `start` looking for .citadel/config.toml."""
    for candidate in [start, *start.parents]:
        cfg = candidate / ".citadel" / "config.toml"
        if cfg.is_file():
            return cfg
    return None


def workspace_root(explicit: str | Path | None = None) -> Path:
    """Return the resolved workspace root.

    Args:
        explicit: if provided (e.g. from a CLI --workspace arg), use this and
                  export it to CITADEL_WORKSPACE so child processes inherit it.
    """
    if explicit is not None:
        p = Path(explicit).expanduser().resolve()
        os.environ["CITADEL_WORKSPACE"] = str(p)
        return p

    env = os.environ.get("CITADEL_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()

    cfg_path = _find_config_toml(Path.cwd())
    if cfg_path is not None:
        with cfg_path.open("rb") as fh:
            data = tomllib.load(fh)
        root = data.get("workspace", {}).get("root")
        if root:
            return Path(root).expanduser().resolve()
        return cfg_path.parent.parent

    raise CitadelNotInitialized()


HOME_DIR_NAME = "citadel-home"


def resolve_home(explicit: str | Path | None = None) -> Path:
    """Resolve the Citadel state home (the `citadel-home` dir `citadel init` creates).

    Used by `citadel up` and `citadel down` so they find the right workspace
    regardless of whether the command is run from the VSCode workspace root
    (the parent of `citadel-home/`) or from inside `citadel-home/` itself.

    Precedence:
      1. `explicit` (e.g. a --workspace arg) — trusted as-is, exported to
         CITADEL_WORKSPACE so child processes inherit it.
      2. CITADEL_WORKSPACE env var.
      3. <cwd>/citadel-home/.citadel/config.toml → its [workspace].root.
      4. The existing .citadel/config.toml walk-up (workspace_root()).
      5. cwd (uninitialized — caller is responsible for printing a hint).
    """
    if explicit is not None:
        p = Path(explicit).expanduser().resolve()
        os.environ["CITADEL_WORKSPACE"] = str(p)
        return p

    env = os.environ.get("CITADEL_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()

    cwd = Path.cwd()
    home_cfg = cwd / HOME_DIR_NAME / ".citadel" / "config.toml"
    if home_cfg.is_file():
        with home_cfg.open("rb") as fh:
            data = tomllib.load(fh)
        root = data.get("workspace", {}).get("root")
        if root:
            return Path(root).expanduser().resolve()
        return home_cfg.parent.parent

    try:
        return workspace_root()
    except CitadelNotInitialized:
        return cwd


def _load_config_toml(ws: Path | None = None) -> dict:
    """Load and parse .citadel/config.toml for the given workspace (empty on miss)."""
    root = ws or workspace_root()
    cfg_path = root / ".citadel" / "config.toml"
    if not cfg_path.is_file():
        return {}
    try:
        with cfg_path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _strip_jsonc_comments(text: str) -> str:
    """Strip // and /* */ comments from a JSONC string (VS Code allows both).

    Small hand-rolled state machine rather than a regex so comment markers inside
    string literals (e.g. a folder path containing "//") are left untouched.
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

    Mirrors `tools/_workspace_intel_common.py::resolve_vscode_folders` — kept as a
    dependency-free duplicate (same rationale as `_scope_from_toml` there) so
    standalone tools never need the installed package on sys.path.

    Lookup order: an explicit `code_workspace` path/hint (from `.citadel/config.toml`'s
    `[index].code_workspace`), else a single `*.code-workspace` file found directly in
    `root` or `root.parent`. Returns None (caller falls back to scan_root+glob scope)
    when no file is found, it's ambiguous (more than one candidate), or it can't be
    parsed — this must degrade gracefully, never raise.
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


def workspace_config(ws: Path | None = None) -> dict:
    """Return the drift-prone workspace/index/git scope as one authoritative dict.

    This is the Single Source of Truth for the values that used to diverge between
    .citadel/config.toml and .claude/brain/workspace-index-config.json:

        {
          "scan_root":          Path,          # dir whose children are repos
          "repo_include_globs": list[str],
          "repo_include_paths": list[Path] | None,  # set when a .code-workspace was found
          "repo_exclude_globs": list[str],
          "branches":           list[str],     # git branches to mine per repo
        }

    A `*.code-workspace` file (VS Code's multi-root workspace format) takes priority
    when present: its `folders[]` become `repo_include_paths`, scoping discovery to
    exactly what the operator's editor Explorer shows, regardless of where those
    folders live on disk. Otherwise, defaults keep the system working on a fresh
    checkout: scan_root falls back to the parent of the workspace root, globs to
    ["*"], branches to dev/main/master.
    """
    root = ws or workspace_root()
    data = _load_config_toml(root)
    index = data.get("index", {}) if isinstance(data, dict) else {}
    git = data.get("git", {}) if isinstance(data, dict) else {}
    branches = list(git.get("branches", ["dev", "main", "master"]))
    exclude_globs = list(index.get("repo_exclude_globs", []))

    vscode_folders = resolve_vscode_folders(root, index.get("code_workspace"))
    if vscode_folders:
        return {
            "scan_root": root.parent,
            "repo_include_globs": [p.name for p in vscode_folders],
            "repo_include_paths": vscode_folders,
            "repo_exclude_globs": exclude_globs,
            "branches": branches,
        }

    scan_root_raw = index.get("scan_root")
    scan_root = (
        Path(scan_root_raw).expanduser().resolve() if scan_root_raw else root.parent
    )
    return {
        "scan_root": scan_root,
        "repo_include_globs": list(index.get("repo_include_globs", ["*"])),
        "repo_include_paths": None,
        "repo_exclude_globs": exclude_globs,
        "branches": branches,
    }


_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379"


def resolve_redis_url(ws: Path | None = None, *, explicit: str | None = None) -> str | None:
    """Resolve the Redis connection URL, or None to force the pure-Python fallback.

    Precedence: explicit arg > CITADEL_REDIS_URL env > .citadel/config.toml [redis] > default localhost.
    `[redis] enabled = false` returns None on purpose (opt out of Redis). Never raises — a missing workspace
    or unparsable config falls through to the env/default, so the retrieval layer always has an answer.
    """
    if explicit:
        return explicit
    env = os.environ.get("CITADEL_REDIS_URL")
    if env:
        return env
    try:
        cfg = _load_config_toml(ws)
    except Exception:
        cfg = {}
    redis_cfg = cfg.get("redis", {}) if isinstance(cfg, dict) else {}
    if redis_cfg.get("enabled") is False:
        return None
    url = redis_cfg.get("url")
    return url if url else _DEFAULT_REDIS_URL


def set_redis_config(ws: Path | None = None, *, url: str | None = None, enabled: bool = True) -> Path:
    """Write the `[redis]` section of .citadel/config.toml, preserving every other section (targeted text
    edit — no TOML re-serialization, so existing config is never mangled). Returns the config path."""
    import re

    root = ws or workspace_root()
    cfg_path = root / ".citadel" / "config.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    text = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
    block = "[redis]\nenabled = false\n" if enabled is False else (
        "[redis]\nenabled = true\n" + (f'url = "{url}"\n' if url else "")
    )
    section = re.compile(r"(?ms)^\[redis\][ \t]*\n(?:(?!^\[).*\n?)*")
    text = section.sub(block, text) if section.search(text) else (
        (text.rstrip() + "\n\n" if text.strip() else "") + block
    )
    cfg_path.write_text(text, encoding="utf-8")
    return cfg_path


def state_dir(ws: Path | None = None) -> Path:
    """Return <workspace>/.citadel (or CITADEL_STATE_DIR override)."""
    env = os.environ.get("CITADEL_STATE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (ws or workspace_root()) / ".citadel"


def claude_dir(ws: Path | None = None) -> Path:
    """Return <workspace>/.claude — where hooks/agents/skills live."""
    return (ws or workspace_root()) / ".claude"


def ws_state_dir(ws: Path | None = None) -> Path:
    """Return <workspace>/.citadel/state/workspace-intelligence."""
    return state_dir(ws) / "state" / "workspace-intelligence"


def brain_dir(ws: Path | None = None) -> Path:
    """Return <workspace>/.claude/brain — LEGION config files."""
    return claude_dir(ws) / "brain"


def docs_brain_dir(ws: Path | None = None) -> Path:
    """Return <workspace>/docs/brain — graph nodes and generated graph files."""
    return (ws or workspace_root()) / "docs" / "brain"


def brain_search_dir(ws: Path | None = None) -> Path:
    """Return <workspace>/.citadel/state/brain-search."""
    return state_dir(ws) / "state" / "brain-search"


def index_paths(ws: Path | None = None) -> dict[str, Path]:
    """Return all workspace-intelligence index file paths keyed by name."""
    d = ws_state_dir(ws)
    return {
        "workspace":          d / "workspace-index.json",
        "repo":               d / "repo-index.json",
        "path":               d / "path-index.json",
        "file":               d / "file-index.json",
        "dir":                d / "dir-index.json",
        "module":             d / "module-index.json",
        "symbol":             d / "symbol-index.json",
        "qualified_symbol":   d / "qualified-symbol-index.json",
        "import":             d / "import-index.json",
        "reverse_import":     d / "reverse-import-index.json",
        "test":               d / "test-index.json",
        "feature":            d / "feature-index.json",
        "artifact":           d / "artifact-index.json",
        "alias":              d / "alias-index.json",
        "inverted_token":     d / "inverted-token-index.json",
        "bm25":               d / "bm25-index.json",
        "reuse_candidate":    d / "reuse-candidate-index.json",
        "graph_adjacency":    d / "graph-adjacency-index.json",
        "fingerprints":       d / "file-fingerprints.json",
        "deleted":            d / "deleted-files.json",
        "skipped":            d / "skipped-files.json",
        "build_metadata":     d / "build-metadata.json",
        "index_manifest":     d / "index-manifest.json",
        "lock":               d / "index.lock",
        "vector_dir":         d / "vector-index",
    }
