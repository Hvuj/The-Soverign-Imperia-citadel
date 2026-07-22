# What Did Not Work

> Known failure patterns and pitfalls mined from outcomes. Append-only; each entry is a compact
> warning so a mistake is never repeated. **Clean slate** — no prior entries.

## 2026-07-18 — process failures while fixing `citadel up` (learn from these)

- **Claimed "fixed" without a clean-slate run.** Verified fixes against an *already-initialized* workspace
  with good state, then declared success. A **fresh** `citadel init` → `up` immediately surfaced the next
  bug (the cp1252 crash in `_ensure_workspace_trusted`). RULE: never say "fixed" until a fresh
  `rm -rf citadel-home uv.lock` → `uv sync` → `init` → `up` (reaches the `claude` launch, no traceback) →
  `down` passes.
- **Whack-a-mole on one root cause.** OneDrive + Windows makes *every* unguarded filesystem/encoding op a
  latent failure. Fixing one (realpath) just moved the hang to the next (`mkdir`); fixing that moved the
  crash to the next unguarded *read* (`~/.claude.json` cp1252). Fix the CLASS, not the instance: audit ALL
  `read_text()`/`open()` for missing `encoding="utf-8"`, and guard ALL daemon fs ops, in one pass.
- **Assumed `realpath` was a consistent hang.** It's intermittent (OneDrive hydration state) — fast when
  files are hydrated (~0.17ms), blocks when dehydrated. Timing it once "proved" it was fine and misled the
  diagnosis. For OneDrive, assume any fs op CAN block; use watchdogs/timeouts, not micro-benchmarks.
- **Slow verification loop.** Editing the-source-repo → `git push` → `uv sync` from git → test was slow and couldn't
  reproduce `up` end-to-end. FIX: point the sandbox at a **local editable install**
  (`[tool.uv.sources] sovereign-imperia-citadel = { path = "../the-source-repo", editable = true }`) so edits are live;
  run the real CLI in the activated venv. (`citadel up` execs interactive `claude` at the end — in a
  non-TTY terminal that errors "Input must be provided…"; that's expected, the boot phase already finished.)
- **`except (json.JSONDecodeError, OSError)` didn't catch `UnicodeDecodeError`** — it's a `ValueError`
  subclass, so a "best-effort, never raises" block still crashed. When a block promises "never raises",
  catch `Exception` (or at least `ValueError`).
