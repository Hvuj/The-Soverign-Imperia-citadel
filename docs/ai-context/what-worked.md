# What Worked

> Proven, validated success patterns mined from outcomes. Append-only; each entry is a compact,
> reusable lesson. **Clean slate** — no prior entries.

## 2026-07-18 — `citadel init/up/down` under Windows + OneDrive (debugging saga)

- **UTF-8 for spawned child processes** (`c32102e`) — `_runner._child_env` sets `PYTHONUTF8=1` +
  `PYTHONIOENCODING=utf-8` for every daemon/tool subprocess. Windows children default to cp1252 and crashed
  printing `✓/✗/●`. Verified: `grounding_lint`/`output_schema_lint` stopped crashing. NOTE: this fixes
  CHILDREN only — the parent `citadel` process still reads files as cp1252 (see the parent-read cp1252 bug).
- **`output_schema_lint` fixes** (`a476b71`) — dropped stale `bi-understanding.schema.json` (BI removed);
  read schema JSON with `utf-8-sig` (tolerate BOM); stripped the BOM from `ask-response.schema.json`.
  `[11/14] mandatory lint` now `[✓ ✓ ✓]`.
- **realpath → abspath** (`09e7bf2`) — `_runner._tools_dir/_scripts_dir` used `Path(__file__).resolve()`
  (`os.path.realpath`), which walks every OneDrive reparse point and can block. Switched to
  `os.path.abspath` (pure string) + `functools.cache`. Got `up` past `_tools_dir`.
- **Junction-bypass + init idempotency + down** (`42206cb`, authored outside my session) — `_daemon_path`
  maps `.claude/state/...` → `.citadel/.claude/state/...` LEXICALLY (never traverses the `.claude` junction);
  `init` writes `.citadel/version` and short-circuits with "already installed (version X)" (junction left
  intact, no destructive rmtree); `down` clears stale pidfiles + machine-wide scan. All verified live.
- **Daemon-start watchdog + `_ensure_dir`** (`f15e7d7`) — a blocking `mkdir` on a dehydrated OneDrive
  placeholder RAISES NOTHING (it hangs), so `try/except` can't catch it. `start_daemon` now runs its spawn in
  a `daemon=True` thread with a 15s budget; a stalled start is skipped (returns `None`). `_ensure_dir`
  memoizes created dirs. Verified live: `up` reached `[13/14] UI server` + `[14/14]` + the `claude` launch —
  the daemon hang is gone.

**Process law learned:** a fix is only "worked" after a **clean-slate** run (delete `citadel-home` + `uv.lock`,
fresh `init`→`up`→`down`). See [[what-did-not-work]] and `bugs.md`.
