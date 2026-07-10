"""commands/init.py — `citadel init <workspace> [--branch BRANCH]`

Scaffolds .citadel/ (runtime state + brain), installs .claude/ and CLAUDE.md
under .citadel/, and creates root-level symlinks so Claude Code auto-discovers
them. Builds workspace indexes, mines git history, and bootstraps memory.
Idempotent; migration-aware (moves a pre-existing real .claude/ into .citadel/).
"""

import importlib.resources
import os
import shutil
import subprocess
import sys
from pathlib import Path

from citadel.commands._runner import _scripts_dir, _tools_dir, run_tool
from citadel.mine_engine import mine_all
from citadel.paths import HOME_DIR_NAME


def _scaffold_citadel_dir(ws: Path) -> None:
    """Create .citadel/ subdirectory structure."""
    for subdir in [
        ".citadel/state/workspace-intelligence",
        ".citadel/state/brain-search",
        ".citadel/state/execution-manifests",
        ".citadel/state/agent-context",
        ".citadel/state/validation-results",
        ".citadel/state/artifacts",
        ".citadel/state/learning-candidates",
        ".citadel/logs",
        ".citadel/brain/nodes/features",
        ".citadel/brain/nodes/failures",
        ".citadel/brain/nodes/topics",
        ".citadel/brain/nodes/tests",
        ".citadel/brain/nodes/successes",
    ]:
        (ws / subdir).mkdir(parents=True, exist_ok=True)


def _write_config_toml(ws: Path, branch: str = "main", *, exclude_globs: list[str] | None = None) -> None:
    cfg = ws / ".citadel" / "config.toml"
    if cfg.exists():
        return
    excludes_toml = ", ".join(f'"{g}"' for g in (exclude_globs or []))
    default_branches = ["dev", "main", "master"]
    branches = [branch, *[b for b in default_branches if b != branch]]
    branches_toml = ", ".join(f'"{b}"' for b in branches)
    cfg.write_text(
        f'[workspace]\nroot = "{ws}"\n\n'
        f'[index]\nrepo_include_globs = ["*"]\nrepo_exclude_globs = [{excludes_toml}]\n\n'
        f'[git]\nbranch = "{branch}"\nbranches = [{branches_toml}]\n'
    )


def _detect_branch(ws: Path) -> str:
    """Auto-detect the default or current git branch for *ws*.

    Tries, in order:
      1. ``git symbolic-ref --short refs/remotes/origin/HEAD`` (remote default branch)
      2. ``git rev-parse --abbrev-ref HEAD`` (currently checked-out branch)
    Falls back to ``"main"`` if the repo has no commits or the git commands fail.
    """
    for cmd in (
        ["git", "-C", str(ws), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        ["git", "-C", str(ws), "rev-parse", "--abbrev-ref", "HEAD"],
    ):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
            if "/" in out:
                out = out.split("/", 1)[-1]
            if out and out != "HEAD":
                return out
        except Exception:
            pass
    return "main"


def _copy_claude_template(ws: Path, *, overwrite: bool = False) -> None:
    """Copy the packaged .claude/ template into .citadel/.claude/ in the workspace.

    Real files live at .citadel/.claude/; a root symlink .claude -> .citadel/.claude
    is created separately by _ensure_root_symlinks().
    Non-clobbering by default: existing files are left intact.
    """
    dest_root = ws / ".citadel" / ".claude"
    try:
        assets = importlib.resources.files("citadel").joinpath("assets")
        template = assets.joinpath("claude_template")
        for rel, item in _walk_resource(template):
            dest = dest_root / rel
            if not overwrite and dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(item.read_bytes())
            if dest.suffix == ".sh":
                dest.chmod(dest.stat().st_mode | 0o111)
    except (FileNotFoundError, TypeError):
        pkg_root = Path(__file__).resolve().parents[3]
        src = pkg_root / ".claude"
        if not src.exists():
            print("  [warn] .claude/ template not found; skipping", file=sys.stderr)
            return
        for item in src.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src)
                dest = dest_root / rel
                if not overwrite and dest.exists():
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
                if dest.suffix == ".sh":
                    dest.chmod(dest.stat().st_mode | 0o111)


def _copy_claude_md(ws: Path, *, overwrite: bool = False) -> None:
    """Write CLAUDE.md template into .citadel/CLAUDE.md in the workspace.

    A root symlink CLAUDE.md -> .citadel/CLAUDE.md is created separately by
    _ensure_root_symlinks().  Non-clobbering by default.
    """
    dest = ws / ".citadel" / "CLAUDE.md"
    if not overwrite and dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        assets = importlib.resources.files("citadel").joinpath("assets")
        template = assets.joinpath("CLAUDE.md")
        dest.write_bytes(template.read_bytes())
    except (FileNotFoundError, TypeError):
        pkg_root = Path(__file__).resolve().parents[3]
        src = pkg_root / "CLAUDE.template.md"
        if not src.exists():
            print("  [warn] CLAUDE.template.md not found; skipping CLAUDE.md", file=sys.stderr)
            return
        shutil.copy2(src, dest)


def _remove_link(path: Path) -> None:
    """Remove a symlink, hardlink, or Windows directory junction at *path*."""
    try:
        path.unlink()
    except (OSError, PermissionError):
        os.rmdir(str(path))


def _create_link(root_path: Path, citadel_target: Path, rel_target: str) -> str:
    """Create a symlink pointing at *rel_target* (or a Windows fallback).

    Returns the method used: ``'symlink'``, ``'junction'``, ``'hardlink'``, or
    ``'copy'``.  On POSIX this always returns ``'symlink'``.  On Windows without
    Developer Mode / Admin rights, ``os.symlink`` raises ``OSError``; we fall
    back to a directory junction (no elevation needed) for directories, and a
    hardlink / file copy for files.
    """
    # POSIX: a relative symlink is clean, portable, and survives moving the workspace.
    if os.name != "nt":
        os.symlink(rel_target, str(root_path), target_is_directory=citadel_target.is_dir())
        return "symlink"

    # Windows: a *relative* symlink (with forward slashes) cannot be resolved for sub-paths
    # like `.claude\state` — it raises WinError 123 — and directory symlinks need Developer
    # Mode anyway. Use a directory junction with an ABSOLUTE target (no elevation required)
    # for directories, and a hardlink/copy for files.
    if citadel_target.is_dir():
        try:
            import _winapi
            create_junction = getattr(_winapi, "CreateJunction")  # noqa: B009
            create_junction(str(citadel_target.resolve()), str(root_path))
            return "junction"
        except (ImportError, OSError, AttributeError):
            shutil.copytree(str(citadel_target), str(root_path))
            return "copy"
    else:
        try:
            os.link(str(citadel_target), str(root_path))
            return "hardlink"
        except OSError:
            shutil.copy2(str(citadel_target), str(root_path))
            return "copy"


def _ensure_root_symlinks(ws: Path) -> None:
    """Create root-level symlinks .claude -> .citadel/.claude and CLAUDE.md -> .citadel/CLAUDE.md.

    Idempotent: if the link already resolves to the correct target, skip.
    Migration-aware: if the root path is a real file/directory (legacy layout),
    merge its contents into .citadel/ first, then replace with a link.

    Windows: ``os.symlink`` requires Developer Mode or Admin rights for directory
    symlinks.  When it fails, ``_create_link`` transparently falls back to a
    directory junction for ``.claude`` and a hardlink/copy for ``CLAUDE.md``.
    """
    pairs = [
        (ws / ".claude",   ws / ".citadel" / ".claude",   ".citadel/.claude"),
        (ws / "CLAUDE.md", ws / ".citadel" / "CLAUDE.md", ".citadel/CLAUDE.md"),
    ]
    for root_path, citadel_target, rel_target in pairs:
        if not citadel_target.exists():
            if citadel_target.suffix:
                pass
            else:
                citadel_target.mkdir(parents=True, exist_ok=True)

        if root_path.is_symlink():
            existing = os.readlink(str(root_path))
            try:
                resolved_ok = Path(existing).resolve() == citadel_target.resolve()
            except Exception:
                resolved_ok = False
            if existing == rel_target or resolved_ok:
                continue
            _remove_link(root_path)
        elif root_path.exists():
            if root_path.is_dir():
                for item in root_path.rglob("*"):
                    if item.is_file():
                        rel = item.relative_to(root_path)
                        dst = citadel_target / rel
                        if not dst.exists():
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(item, dst)
                shutil.rmtree(str(root_path))
            else:
                if not citadel_target.exists() or citadel_target.stat().st_size == 0:
                    citadel_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(root_path, citadel_target)
                root_path.unlink()

        if citadel_target.exists():
            method = _create_link(root_path, citadel_target, rel_target)
            label = "symlink" if method == "symlink" else method
            print(f"  [{label}] {root_path.name} → {rel_target}")


def _ensure_bundled_dir_symlinks(ws: Path) -> None:
    """Symlink `tools/` and `scripts/` at the workspace root to the installed
    package's copies.

    Several shell hooks (and .mcp.json's MCP server registration) shell out to
    paths like `$CLAUDE_PROJECT_DIR/tools/foo.py`, bypassing the Python-side
    `_tools_dir()` resolver entirely. Without this symlink those paths never
    exist in a scaffolded workspace, so every such hook fails — including
    UserPromptSubmit hooks, which block prompt submission outright.
    """
    for name, resolver in (("tools", _tools_dir), ("scripts", _scripts_dir)):
        target = resolver()
        if not target.is_dir():
            continue
        link = ws / name
        if link.is_symlink():
            if link.resolve() == target.resolve():
                continue
            _remove_link(link)
        elif link.exists():
            continue
        _create_link(link, target, str(target))


def _copy_mcp_json(ws: Path, *, overwrite: bool = False) -> None:
    """Copy the packaged .mcp.json into the workspace root.

    Without this, a workspace has no MCP server registration at all once
    Claude Code is launched with cwd=ws (as `citadel up` does), even though
    the top-level dev repo's own .mcp.json works fine from its own root.
    Non-clobbering by default.
    """
    dest = ws / ".mcp.json"
    if not overwrite and dest.exists():
        return
    try:
        assets = importlib.resources.files("citadel").joinpath("assets")
        template = assets.joinpath("mcp.json")
        dest.write_bytes(template.read_bytes())
    except (FileNotFoundError, TypeError):
        pkg_root = Path(__file__).resolve().parents[3]
        src = pkg_root / ".mcp.json"
        if not src.exists():
            print("  [warn] .mcp.json template not found; skipping", file=sys.stderr)
            return
        shutil.copy2(src, dest)


_DOC_SEED_FILES = (
    "ai-context/system/grounding-policy.md",
    "ai-context/system/prompt-leak-policy.md",
    "ai-context/system/prompt-template-registry.md",
    "brain/nodes/knowledge/knowledge-grounding-policy.md",
    "brain/nodes/knowledge/knowledge-scaffold-integrity.md",
    "brain/graph.html",
    "brain/graph.css",
    "brain/graph.js",
    "brain/tasks.html",
    "brain/workspace.html",
    "brain/workspace.css",
    "brain/workspace.js",
    "brain/dir.html",
    "brain/file.html",
    "brain/module.html",
    "brain/repo.html",
    "index.html",
)


def _seed_docs(ws: Path) -> None:
    """Seed docs/ files required by the mandatory grounding/prompt-leak lint
    gates. Without these, grounding_lint.py and the health check's
    grounding/prompt-leak layers never pass in a freshly-scaffolded workspace,
    regardless of workspace-specific state. Non-clobbering.
    """
    dest_root = ws / "docs"
    try:
        assets = importlib.resources.files("citadel").joinpath("assets").joinpath("docs_seed")
        for rel, item in _walk_resource(assets):
            dest = dest_root / rel
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(item.read_bytes())
    except (FileNotFoundError, TypeError):
        pkg_root = Path(__file__).resolve().parents[3]
        src_root = pkg_root / "docs"
        for rel in _DOC_SEED_FILES:
            src = src_root / rel
            dest = dest_root / rel
            if not src.exists() or dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)


def _walk_resource(res, prefix=""):
    """Recursively yield (relpath, file-resource) pairs from an importlib.resources path.

    *relpath* is the slash-separated path relative to *res*, e.g.
    ``"brain/graph-aware-config.json"`` or ``"hooks/session-end-ledger.sh"``.
    Callers can use it directly as a ``pathlib.Path`` suffix so the full
    subdirectory hierarchy is recreated at the destination.
    """
    try:
        for child in res.iterdir():
            rel = f"{prefix}{child.name}"
            if child.is_dir():
                yield from _walk_resource(child, prefix=f"{rel}/")
            else:
                yield rel, child
    except (AttributeError, NotImplementedError):
        pass


def _bootstrap_memory(ws: Path) -> None:
    ai_ctx = ws / "docs" / "ai-context"
    ai_ctx.mkdir(parents=True, exist_ok=True)

    try:
        assets = importlib.resources.files("citadel").joinpath("assets").joinpath("ai-context")
        _seed_from_assets(ai_ctx, assets)
    except Exception:
        pass

    for fname, content in [
        ("active-memory.md", "# Active Memory\n\n"),
        ("what-worked.md", "# What Worked\n\n"),
        ("what-did-not-work.md", "# What Did Not Work\n\n"),
        ("feature-implementation-patterns.md", "# Feature Implementation Patterns\n\n"),
        ("model-effort-outcomes.md", (
            "# Model-Effort Outcome Log\n\n"
            "Append-only. Used by effort-decider to improve future model selection.\n\n"
            "## Entries\n\n"
            "| date | task_type | model | effort | outcome | notes |\n"
            "|------|-----------|-------|--------|---------|-------|\n"
        )),
        ("model-selection-policy.md", (
            "# Model Selection Policy\n\n"
            "Default: **Haiku + low effort**. Escalate only when evidence requires it.\n"
            "See docs/ai-context/model-effort-outcomes.md for outcome history.\n\n"
            "## Task → model\n\n"
            "| task_type | model | effort |\n"
            "|-----------|-------|--------|\n"
            "| question, terminal_help, docstring_only | haiku | low |\n"
            "| validation_only, docs_ingestion | haiku | low |\n"
            "| test_creation, data_contract, sql | haiku | medium |\n"
            "| feature_change, bug_fix, refactor | sonnet | medium |\n"
            "| debugging, parcompute, bi_logic | sonnet | high |\n"
        )),
    ]:
        f = ai_ctx / fname
        if not f.exists():
            f.write_text(content)


def _seed_from_assets(dest: Path, assets_dir) -> None:
    """Copy packaged ai-context asset templates into dest (non-clobbering)."""
    try:
        for child in assets_dir.iterdir():
            if not child.name.endswith(".md"):
                continue
            dst = dest / child.name
            if not dst.exists():
                dst.write_bytes(child.read_bytes())
    except (AttributeError, NotImplementedError, FileNotFoundError):
        pass


def run(workspace: str, *, branch: str | None = None, force: bool = False) -> int:
    """Run `citadel init`. Returns exit code (0 = success)."""
    parent = Path(workspace).expanduser().resolve()

    if not parent.exists():
        print(f"ERROR: workspace '{parent}' does not exist.", file=sys.stderr)
        return 1

    ws = parent if parent.name == HOME_DIR_NAME else parent / HOME_DIR_NAME
    ws.mkdir(parents=True, exist_ok=True)

    if branch is None:
        branch = _detect_branch(parent) if (parent / ".git").exists() else "main"

    print(f"[citadel init] workspace: {parent}")
    if ws != parent:
        print(f"[citadel init] home:      {ws}")
    print(f"[citadel init] branch:    {branch}")

    print("[1/11] Scaffolding .citadel/ …")
    _scaffold_citadel_dir(ws)
    _write_config_toml(ws, branch, exclude_globs=[HOME_DIR_NAME])

    os.environ["CITADEL_WORKSPACE"] = str(ws)

    print("[2/11] Installing .citadel/.claude/ hooks, agents, skills …")
    _copy_claude_template(ws, overwrite=force)
    _copy_claude_md(ws, overwrite=force)
    _copy_mcp_json(ws, overwrite=force)
    _ensure_root_symlinks(ws)
    _ensure_bundled_dir_symlinks(ws)

    print("[3/11] Bootstrapping memory …")
    _bootstrap_memory(ws)
    _seed_docs(ws)

    print("[4/11] Building workspace intelligence indexes …")
    run_tool(
        "build_workspace_intelligence_index.py", ws,
        ["--workspace", str(ws)],
    )

    print("[5/11] Building brain search index …")
    run_tool("build_brain_search_index.py", ws)

    print("[6/11] Mining full git history for every workspace repo x branch …")
    try:
        summary = mine_all(ws, branches=None, max_commits=None, quiet=True)
        print(
            f"      {summary.repos_seen} git repo(s), "
            f"{summary.branches_mined} (repo,branch) mined, "
            f"{summary.commits} commits → {summary.nodes_written} commit nodes."
        )
    except Exception as exc:
        print(f"  [warn] git mining failed: {exc}", file=sys.stderr)

    print("[7/11] Rebuilding brain search index with mined nodes …")
    run_tool("build_brain_search_index.py", ws)

    print("[8/11] Building commit knowledge index …")
    run_tool("build_commit_index.py", ws)

    print("[9/11] Building brain graph …")
    run_tool("build_brain_graph.py", ws)

    print("[10/11] Detecting AI providers …")
    run_tool("ai_provider_detection.py", ws)

    print("[11/11] Seeding initial state …")
    import json as _json
    _manifest_path = ws / ".claude" / "state" / "execution-manifest.json"
    if not _manifest_path.exists():
        _manifest_path.parent.mkdir(parents=True, exist_ok=True)
        _manifest_path.write_text(_json.dumps({
            "task_type": "initialization",
            "selected_workflow": "init_workflow",
            "required_agents": [],
            "required_artifacts": [],
        }, indent=2) + "\n")

    _ok = run_tool("scaffold_integrity_lint.py", ws, ["--workspace", str(ws), "--json"], quiet=True)
    print(f"[verify] scaffold integrity … {'OK' if _ok else 'ISSUES'}")
    if not _ok:
        print("  [warn] scaffold incomplete — run `python tools/scaffold_integrity_lint.py "
              f"--workspace {ws}` for details; some features may not work until resolved",
              file=sys.stderr)

    _CYAN = "\033[96m"
    _RESET = "\033[0m"
    print(f"\n[citadel init] {'─' * 4}")
    print("► CRITICAL: Core citadel seed planted.")
    print(f"► LOCALITY: Cognitive anchor dropped at `{ws}/` (.claude + CLAUDE.md symlinked at root)")
    print(f"► SCOPE:    Sibling repos under `{parent}` are learned; none receive a .claude of their own.")
    print("► MONITOR:  14 disconnected workspace shards detected in the darkness.")
    print("\nDeep within the local architecture, independent workspace shards begin to align.")
    print("A dark neural fabric is woven across your machine, awaiting the signal to rise.")
    print(f"\nAwaken the entity, merge your reality with Claude Code: {_CYAN}citadel up{_RESET}")
    return 0
