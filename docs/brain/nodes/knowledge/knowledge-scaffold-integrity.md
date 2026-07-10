# Knowledge: Scaffold Integrity — how a scaffolded Citadel workspace breaks

**Type:** knowledge / operational
**Owner:** sovereign-imperia-citadel core (`init.py`, `up.py`, `_runner.py`)
**Validator:** `tools/scaffold_integrity_lint.py` (run automatically at end of `citadel init` and as the `scaffold_integrity` health check on every `citadel up`).

## Why this node exists

`citadel init` creates a **home workspace** (`citadel-home/`) that is NOT the source
repo. It gets a `.claude/` + `CLAUDE.md` (symlinked to `.citadel/`), plus a set of
files copied/symlinked out of the installed package. A whole class of bugs comes from
the scaffold being **incomplete** — the workspace launches, but hooks, the MCP server,
lint, or health silently fail because something the runtime references by a
workspace-relative path was never installed.

The trap: shell hooks (`$CLAUDE_PROJECT_DIR/tools/foo.py`) and `.mcp.json`
(`"args": ["tools/citadel_mcp_server.py"]`) resolve paths **relative to the workspace**,
bypassing the Python-side `_tools_dir()`/`_scripts_dir()` resolvers entirely. So a
Python `run_tool()` call can succeed while the equivalent shell hook fails, in the
same run.

## The required scaffold (what MUST exist in every workspace)

| Artifact | Installed by | Symptom if missing |
|----------|--------------|--------------------|
| `tools/` (symlink → package tools) | `init._ensure_bundled_dir_symlinks` | Hooks + `.mcp.json` fail: `python: can't open '.../tools/*.py'`; UserPromptSubmit hook **blocks every prompt** |
| `scripts/` (symlink → package scripts) | `init._ensure_bundled_dir_symlinks` | `mandatory_auto_lint` MISSING errors; start scripts unresolved |
| `.mcp.json` | `init._copy_mcp_json` | MCP server never registers; "New MCP server found" prompt never appears |
| `.claude`, `CLAUDE.md` (root symlinks) | `init._ensure_root_symlinks` | No hooks/agents/skills/config loaded |
| Executable bit on `.claude/hooks/*.sh` | `init._copy_claude_template` (chmod on `.sh`) | `mandatory_auto_lint` NOT EXECUTABLE errors → lint red |
| Seeded docs (grounding/prompt-leak/template + `knowledge-grounding-policy.md`) | `init._seed_docs` | `grounding_lint` fail; health grounding/prompt-leak layers yellow |
| `docs/brain/graph.html` / `.css` / `.js` | `init._seed_docs` (static UI assets) | Health **red**: `ui_file_graph_html/css/js missing` (these are CRITICAL) |
| Workspace trusted in `~/.claude.json` | `up._ensure_workspace_trusted` | "Ignoring N permissions.allow entries … not been trusted" — settings.local.json dropped |

## The packaging invariant (what MUST ship in the wheel)

`uv tool install .` builds a wheel via hatchling. Everything `citadel init` copies out
must be inside the wheel or init silently degrades. Guaranteed by:
- `[tool.hatch.build.targets.wheel.force-include]` → `tools`, `scripts`, `.claude`→`assets/claude_template`
- `[tool.hatch.build.targets.wheel] artifacts = ["src/citadel/assets/**"]` → `mcp.json`, `docs_seed/**`, `CLAUDE.md`, `ai-context/**`
- Assets under `src/citadel/` are package data (hatchling default), but the explicit `artifacts` entry makes it non-optional.

Validate with: `python tools/scaffold_integrity_lint.py --packaging`
(add `--wheel-root <extracted>` to check a built wheel before install).

## How to re-validate (do this after ANY change to init/up/packaging)

```
# 1. packaging complete?
python tools/scaffold_integrity_lint.py --packaging
# 2. build a fresh wheel and re-check it
uv build --wheel -o /tmp/wc && (cd /tmp/wc && unzip -oq *.whl -d ex)
python tools/scaffold_integrity_lint.py --wheel-root /tmp/wc/ex
# 3. scaffold a throwaway workspace and validate it end-to-end
citadel init /tmp/vl-smoke && python tools/scaffold_integrity_lint.py --workspace /tmp/vl-smoke/citadel-home
# 4. lint + health must be clean
CITADEL_WORKSPACE=<ws> python tools/mandatory_auto_lint.py
CITADEL_WORKSPACE=<ws> python tools/citadel_system_health.py --out /tmp/h.json  # scaffold_integrity check must be green
```

## Related fixes (2026-07-03)

Root cause of the original cluster: the wheel/editable `_tools_dir()` fix
(2026-06-25) covered Python-invoked tools but not shell hooks or `.mcp.json`. The
tools/scripts **symlink** in the workspace closes that gap for both. See also the
health-display fix (red cause was hidden behind a `[:3]` slice of yellows + a
`detail`/`details` key typo) and the parallel daemon shutdown fix
(`_daemons.terminate_many`).
