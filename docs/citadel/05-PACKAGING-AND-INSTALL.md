# 05 â€” Packaging & Install (uv + hatch)

> How the Citadel should be versioned, built into a wheel, and installed â€” mapped, not built (per the
> Sovereign's "do not build yet"). Backend is **hatchling**; the dev/build/install flow is **uv**. The
> one config change already applied this turn is hatch-managed versioning (Â§1). (Task 12.)

> âœ… **Update 2026-07-10 â€” EXECUTED & verified.** The packaging is now real and working. The `.claude`
> template is a committed, agnostic 380-file directory at `src/citadel/assets/claude_template/`; the
> broken `.citadel/.claude/` force-include is gone; `uv build --wheel` produces
> `sovereign_imperia_citadel-0.1.0-py3-none-any.whl` containing the 380 template files (61 agents) + 175
> tools; and `citadel init` installs it into a workspace end-to-end on Windows (exit 0, 433 files,
> `.claude` junction resolves). Activation is now **`citadel up` / `citadel down`** (see [00](00-OVERVIEW-AND-NAMING.md)).
> Two Windows bugs were fixed to get init working: UTF-8 stdout in `cli.main()`, and an absolute
> directory **junction** for `.claude` on Windows (a relative forward-slash symlink raised WinError 123).

## 1. Version management â€” hatch owns it (APPLIED)

The version is now a **single source of truth** read by hatch:

```toml
[project]
name = "sovereign-imperia-citadel"
dynamic = ["version"]          # no static version literal

[tool.hatch.version]
path = "src/citadel/__init__.py"   # reads __version__ = "0.1.0"
```

- Bump the version in **one place** â€” `src/citadel/__init__.py::__version__`. Hatch stamps the
  wheel/sdist from it. This fixes the old triplication (the literal in `pyproject`, `__init__.py`, and
  `cli.py`).
- **Remaining (build step):** `cli.py`'s `--version` action still hardcodes `"%(prog)s 0.1.0"` â€” change
  it to import `__version__` so the CLI and the wheel can never disagree.
- **Optional upgrade:** for date/commit-derived versions later, switch to
  `hatch-vcs` (`[tool.hatch.version] source = "vcs"`) once the workspace is a git repo â€” deferred; the
  file-path source is correct and dependency-free for now.

## 2. The critical packaging bug (must fix before any real install)

The wheel is meant to bake the `.claude/` template so `citadel init` can copy it into a scaffolded
workspace. But:

```toml
[tool.hatch.build.targets.wheel.force-include]
".citadel/.claude/" = "citadel/assets/claude_template/"
```

âš ï¸ **`.citadel/.claude/` does not exist as a real directory in this checkout** â€” it was a macOS symlink,
lost in transfer. Building a wheel here bakes an **empty** `claude_template/`, so a fresh
`citadel init` installs **zero** agents/skills/hooks/rules/schemas. This is the single highest-priority
packaging defect.

**Fix (build phase):** make the template a **real, curated directory in the repo** â€” e.g.
`src/citadel/assets/claude_template/` committed directly (not a symlink, not a force-include from a
symlinked path). The `citadel init` scaffolder then copies from the installed package's own assets, which
always exist. The curated template must be the **agnostic, BI-free, path-free** version (per
[02 Â§B/D/E](02-AGNOSTIC-AUDIT.md)) â€” not the `${HOME}` copy in the zip.

## 3. Wheel contents (what must ship)

The installed package must be fully self-contained (the CLI runs standalone tools as subprocesses):

```
citadel/                     (from src/citadel/, packages=[...])
â”œâ”€â”€ cli.py, paths.py, __init__.py
â”œâ”€â”€ commands/, services/          (index/compile/cache/reuse/corporate)
â”œâ”€â”€ tools/                        (force-include tools/ â†’ 178 standalone tools)
â”œâ”€â”€ scripts/                      (force-include scripts/ â†’ shell helpers; optional post-cleanup)
â””â”€â”€ assets/
    â”œâ”€â”€ claude_template/          (the curated .claude/ â€” agents/skills/hooks/rules/schemas/brain/legion/workflows)
    â”œâ”€â”€ docs_seed/                (graph viewer + seed brain nodes â€” scrubbed, Â§02 E)
    â”œâ”€â”€ ai-context/               (seed memory templates â€” scrubbed)
    â”œâ”€â”€ CLAUDE.md, mcp.json
```

Current `pyproject` wiring (correct except the template source in Â§2):

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/citadel"]
artifacts = ["src/citadel/assets/**"]

[tool.hatch.build.targets.wheel.force-include]
"tools/"   = "citadel/tools/"
"scripts/" = "citadel/scripts/"
# ".citadel/.claude/" â†’ replace with a real committed assets/claude_template/ (see Â§2)
```

**Build-phase action:** add a `scaffold_integrity_lint.py --packaging` check that fails the build if
`assets/claude_template/` is empty, contains a brand/domain token, or contains an absolute machine path.

## 4. Dependency model (APPLIED, correct)

Core is **pure stdlib** â€” extras pull third-party libs only when a feature needs them:

```toml
dependencies = []                              # core = stdlib only
[project.optional-dependencies]
ai       = ["anthropic>=0.116.0"]              # Legionnaire model calls / Q&A fallback
daemons  = ["watchdog>=6.0.0"]                 # file-watch (else polling fallback)
reports  = ["matplotlib>=3.11.0"]              # cost report PDFs
obsidian = ["PyYAML>=6.0.3", "watchdog>=6.0.0"]
all      = [ ...the union... ]
```

Every third-party import in the code is deferred/tool-local (verified), so the stdlib core genuinely
imports and runs without any extra installed.

## 5. Install & dev flow

```bash
# Install the CLI globally (like pipx) â€” from the built/cloned repo:
uv tool install .                      # exposes `citadel` on PATH
uv tool install ".[all]"               # with every optional feature

# Develop the Citadel itself (editable â€” src/ and tools/ changes are live):
uv run citadel <cmd>                     # uses the editable install, no reinstall
uv tool install . --force              # refresh the global CLI + baked template after code changes

# Scaffold + run on any workspace:
citadel init ~/code/my-project --branch main
cd ~/code/my-project && citadel up
citadel down
```

**Build & verify a wheel:**

```bash
uv build                               # hatchling builds sdist + wheel; version from __init__.py
# verify the template shipped (this is the Â§2 bug guard):
python -c "import citadel, pathlib; \
  t=pathlib.Path(citadel.__file__).parent/'assets'/'claude_template'; \
  print('template files:', sum(1 for _ in t.rglob('*')) if t.exists() else 'MISSING')"
```

## 6. Rename impact on packaging (Citadel identity)

When the code rename lands ([00 Â§2](00-OVERVIEW-AND-NAMING.md)):

- **Distribution name:** `sovereign-imperia-citadel` â†’ `sovereign-imperia-citadel` (PyPI/`[project].name`).
- **Import package:** `citadel` â†’ `imperia` (or `citadel`) â€” a large mechanical rename across
  ~178 tools + 35 modules + tests + the `[tool.hatch.version] path` + `packages=[â€¦]` + the
  `force-include` targets + the `[project.scripts]` entry point.
- **CLI entry point:** keep `citadel` as an alias for one release for muscle memory, add the new command
  name (e.g. `citadel` / `imp`). `[project.scripts]` supports both:
  ```toml
  [project.scripts]
  citadel = "imperia.cli:main"
  citadel   = "imperia.cli:main"   # deprecated alias, one release
  ```
- **Sequence:** rename is a single coordinated commit (an automated codemod over the import graph),
  done as a **build step** â€” not this turn. Until then the package stays `citadel` and only the
  *docs* carry the new name.

## 7. Packaging checklist (for the build phase)

- [ ] Commit a real, curated, agnostic `src/citadel/assets/claude_template/` (Â§2).
- [ ] `cli.py --version` reads `__version__` (Â§1).
- [ ] `scaffold_integrity_lint.py --packaging` fails on empty/dirty template (Â§3).
- [ ] Seed assets scrubbed of domain/brand/absolute-machine-path tokens ([02 Â§E](02-AGNOSTIC-AUDIT.md)).
- [ ] `uv build` produces a wheel whose `citadel init` scaffolds a non-empty `.claude/` on a clean machine.
- [ ] `uv tool install .` on Windows + macOS + Linux; `citadel up`/`destroy` run on all three (needs B1).
- [ ] Decide the `scripts/*.sh` fate (ship as debug helpers, or drop â€” the CLI is the portable path).
