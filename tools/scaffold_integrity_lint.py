#!/usr/bin/env python3
"""scaffold_integrity_lint.py — Validate that a Citadel workspace is 100% scaffolded.

This is the guardrail for a whole class of "scaffolded workspace is missing X" bugs
(see docs/brain/nodes/knowledge/knowledge-scaffold-integrity.md). Shell hooks and
.mcp.json reference paths like `$CLAUDE_PROJECT_DIR/tools/foo.py` and
`tools/citadel_mcp_server.py` that bypass the Python-side `_tools_dir()` resolver, so
they only work if the scaffold physically installed everything. This lint asserts it.

Two modes:
  (default)     Validate the scaffolded WORKSPACE (CITADEL_WORKSPACE or --workspace):
                tools/ + scripts/ symlinks resolve, .mcp.json present & valid,
                seeded docs present, brain-graph UI files present, hooks executable,
                root symlinks (.claude, CLAUDE.md) resolve.
  --packaging   Validate the INSTALLED PACKAGE (or a --wheel-root) ships every asset
                `citadel init` copies out — catches a wheel that dropped assets before
                any workspace is even created.

Exit 0 = all pass, 1 = one or more failures.
"""

import argparse
import json
import os
from pathlib import Path

SEEDED_DOCS = (
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

REQUIRED_TOOLS = (
    "session_end_ledger.py",
    "classify_prompt.py",
    "brain_preflight.py",
    "citadel_mcp_server.py",
)

REQUIRED_SCRIPTS = ("claude-start-smart.sh",)


def _check(name: str, ok: bool, message: str) -> dict:
    return {"name": name, "status": "pass" if ok else "fail", "message": message}


def check_workspace(root: Path) -> list[dict]:
    checks: list[dict] = []

    tools = root / "tools"
    if not tools.is_dir():
        checks.append(_check("tools_dir", False, f"{tools} missing/unresolved (symlink broken?)"))
    else:
        missing = [t for t in REQUIRED_TOOLS if not (tools / t).exists()]
        checks.append(_check("tools_dir", not missing,
                             "tools/ resolves with required tools" if not missing
                             else f"tools/ present but missing: {missing}"))

    scripts = root / "scripts"
    if not scripts.is_dir():
        checks.append(_check("scripts_dir", False, f"{scripts} missing/unresolved (symlink broken?)"))
    else:
        missing = [s for s in REQUIRED_SCRIPTS if not (scripts / s).exists()]
        checks.append(_check("scripts_dir", not missing,
                             "scripts/ resolves with required scripts" if not missing
                             else f"scripts/ present but missing: {missing}"))

    mcp = root / ".mcp.json"
    if not mcp.exists():
        checks.append(_check("mcp_json", False, ".mcp.json missing (MCP server won't register)"))
    else:
        try:
            data = json.loads(mcp.read_text())
            servers = data.get("mcpServers", {})
            ok = "sovereign-imperia-citadel" in servers
            checks.append(_check("mcp_json", ok,
                                 ".mcp.json registers sovereign-imperia-citadel" if ok
                                 else ".mcp.json present but no sovereign-imperia-citadel server entry"))
        except (json.JSONDecodeError, OSError) as exc:
            checks.append(_check("mcp_json", False, f".mcp.json invalid: {exc}"))

    for name in (".claude", "CLAUDE.md"):
        p = root / name
        checks.append(_check(f"link_{name}", p.exists(),
                             f"{name} resolves" if p.exists() else f"{name} missing/broken"))

    docs = root / "docs"
    missing_docs = [d for d in SEEDED_DOCS if not (docs / d).exists()]
    checks.append(_check("seeded_docs", not missing_docs,
                         f"all {len(SEEDED_DOCS)} seeded docs present" if not missing_docs
                         else f"missing seeded docs: {missing_docs}"))

    hooks_dir = root / ".claude" / "hooks"
    if hooks_dir.is_dir():
        non_exec = [p.name for p in sorted(hooks_dir.glob("*.sh")) if not os.access(p, os.X_OK)]
        checks.append(_check("hooks_executable", not non_exec,
                             "all hook .sh files executable" if not non_exec
                             else f"non-executable hooks: {non_exec}"))
    else:
        checks.append(_check("hooks_executable", False, f"{hooks_dir} missing"))

    return checks


def _resolve_packaging_layout(wheel_root: Path | None):
    """Return (assets, claude_template, tools, scripts, layout_label), or an Exception
    if the package can't be located.

    Handles all three layouts:
      • --wheel-root <extracted>: everything under citadel/ (force-include applied)
      • installed wheel:          importlib pkg has tools/ + assets/claude_template/
      • editable/src install:     force-included dirs are NOT under the package — they
                                  live at the repo root (tools/, scripts/, .claude/),
                                  mirroring _tools_dir()'s dual-path resolution.
    """
    if wheel_root is not None:
        base = wheel_root / "citadel"
        assets = base / "assets"
        return assets, assets / "claude_template", base / "tools", base / "scripts", "wheel-root"
    try:
        import importlib.resources as ir
        pkg = Path(str(ir.files("citadel")))
    except Exception as exc:
        return exc
    assets = pkg / "assets"
    if (pkg / "tools").is_dir():
        return assets, assets / "claude_template", pkg / "tools", pkg / "scripts", "installed-wheel"
    repo = pkg.parents[1]
    return assets, repo / ".claude", repo / "tools", repo / "scripts", "editable"


def check_packaging(wheel_root: Path | None) -> list[dict]:
    """Verify the package (wheel, installed, or editable) carries every asset
    `citadel init` copies into a workspace."""
    resolved = _resolve_packaging_layout(wheel_root)
    if not isinstance(resolved, tuple):
        return [_check("package_import", False, f"cannot locate citadel package: {resolved}")]
    assets, claude_template, tools, scripts, layout = resolved

    checks: list[dict] = [_check("packaging_layout", True, f"layout: {layout}")]
    required_assets = ["CLAUDE.md", "mcp.json", *(f"docs_seed/{d}" for d in SEEDED_DOCS)]
    missing = [a for a in required_assets if not (assets / a).exists()]
    checks.append(_check("packaged_assets", not missing,
                         f"all {len(required_assets)} required assets present" if not missing
                         else f"missing assets: {missing}"))
    checks.append(_check("packaged_claude_template", claude_template.is_dir(),
                         f"claude template present ({claude_template.name})" if claude_template.is_dir()
                         else f"claude template missing: {claude_template}"))

    tmissing = [t for t in REQUIRED_TOOLS if not (tools / t).exists()]
    checks.append(_check("packaged_tools", not tmissing,
                         "required tools present" if not tmissing else f"missing tools: {tmissing}"))
    smissing = [s for s in REQUIRED_SCRIPTS if not (scripts / s).exists()]
    checks.append(_check("packaged_scripts", not smissing,
                         "required scripts present" if not smissing else f"missing scripts: {smissing}"))
    return checks


def run(root: Path, *, packaging: bool, wheel_root: Path | None) -> list[dict]:
    return check_packaging(wheel_root) if packaging else check_workspace(root)


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a Citadel workspace/package is fully scaffolded.")
    ap.add_argument("--workspace", help="Workspace root (default: $CITADEL_WORKSPACE or cwd).")
    ap.add_argument("--packaging", action="store_true", help="Validate the installed package instead of a workspace.")
    ap.add_argument("--wheel-root", help="Extracted wheel dir to validate (implies --packaging).")
    ap.add_argument("--json", action="store_true", help="Emit JSON.")
    args = ap.parse_args()

    wheel_root = Path(args.wheel_root).expanduser().resolve() if args.wheel_root else None
    packaging = args.packaging or wheel_root is not None
    root = Path(args.workspace or os.environ.get("CITADEL_WORKSPACE") or Path.cwd()).expanduser().resolve()

    checks = run(root, packaging=packaging, wheel_root=wheel_root)
    failed = sum(1 for c in checks if c["status"] == "fail")
    overall = "pass" if failed == 0 else "fail"
    mode = "packaging" if packaging else f"workspace {root}"

    if args.json:
        print(json.dumps({"mode": mode, "status": overall, "checks": checks}, indent=2))
    else:
        print(f"scaffold_integrity ({mode}): {overall.upper()} "
              f"({len(checks) - failed} pass, {failed} fail)")
        for c in checks:
            icon = "✓" if c["status"] == "pass" else "✗"
            print(f"  [{icon}] {c['name']}: {c['message']}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
