# Memory — `citadel init/up/down` on Windows + OneDrive (debugging index)

> Scannable index of the debugging saga. Detail lives in `what-worked.md`, `what-did-not-work.md`, `bugs.md`.

## The situation
The sandbox (`C:\Users\Hvuj\OneDrive\Desktop\sandbox-workspace`) runs Citadel from a **local editable
install** of `../the-source-repo` (`[tool.uv.sources] … { path = "../the-source-repo", editable = true }`), so the-source-repo/src edits are
live — no push/sync loop. The Desktop is Known-Folder-Moved **into OneDrive**, and `.claude` is a **junction**
to `.citadel/.claude`. That combination makes every unguarded filesystem or text-encoding operation a latent
failure.

## The through-line: two root causes, many symptoms
1. **OneDrive/junction filesystem stalls** — `realpath`, `mkdir`, `open` on reparse points / cloud
   placeholders can block. Fixed op-by-op: abspath (not realpath), `_daemon_path` junction bypass,
   `start_daemon` watchdog, `_ensure_dir` memoization.
2. **cp1252 text decoding** — Windows defaults file I/O to cp1252. Fixed for *child* daemons via
   `PYTHONUTF8` in `_child_env`; the *parent* `citadel` process still needs explicit `encoding="utf-8"` on
   every read (BUG-1, in progress).

## Two process laws (paid for in wasted cycles)
1. **Clean-slate testing.** Before verifying any fix: `rm -rf sandbox-workspace/citadel-home
   sandbox-workspace/uv.lock` → `uv sync` → `citadel init` → `citadel up` → `citadel down`. A stale
   already-initialized workspace hides bugs that a fresh `init` exposes.
2. **No "fixed" without a full clean run.** `citadel up` must reach `Launching: claude.exe …` with **zero
   traceback** (non-TTY `claude` "Input must be provided…" is expected and fine), and `down` must leave 0
   daemons. Only then is it fixed.

## Commit trail (branch `TSIC-0001-citadel`)
`c32102e` child UTF-8 · `a476b71` output_schema_lint+BOM · `449214b` Pandidakterion · `09e7bf2`
realpath→abspath · `42206cb` junction-bypass + init idempotency + down (authored outside my session) ·
`f15e7d7` daemon watchdog. **Open:** BUG-1 (parent cp1252). See `bugs.md`.
