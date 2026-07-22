# Bugs

> Known defects — OPEN (unfixed) and RESOLVED — for `citadel init/up/down` on Windows + OneDrive.
> Newest first. A bug moves to RESOLVED only after a **clean-slate** verification (delete `citadel-home` +
> `uv.lock`, fresh `init`→`up`→`down`, `up` reaches the `claude` launch with no traceback).

## OPEN

### BUG-1 — `citadel up` crashes: cp1252 `UnicodeDecodeError` reading `~/.claude.json`
- **Where:** `src/citadel/commands/up.py` `_ensure_workspace_trusted` — `json.loads(cfg_path.read_text())`
  reads the global `~/.claude.json` with no `encoding=`, so Windows decodes cp1252 and dies on a UTF-8 byte
  (`0x9d` at pos ~6217). The `except (json.JSONDecodeError, OSError)` does NOT catch `UnicodeDecodeError`
  (a `ValueError`), so it escapes and crashes `up` after `[14/14]`.
- **Fix (this pass):** `read_text(encoding="utf-8")` here and on every parent-hot-path JSON read
  (`up.py:70/137/466`, `git_history_miner.py:326`, `statusline.py`); broaden the `except` to `Exception`.
- **Class:** the parent `citadel` process does NOT run under `PYTHONUTF8` (that only fixed *child* daemons),
  so every bare `read_text()`/`open()` read is a latent cp1252 crash on any UTF-8 file.

### BUG-2 — SessionEnd hooks resolve to `/.claude/hooks/...` (bad absolute path)
- **Symptom:** on session end, `bash "$CLAUDE_PROJECT_DIR/.claude/hooks/session-end-*.sh"` fails
  `/.claude/hooks/…: No such file or directory` — `$CLAUDE_PROJECT_DIR` is empty/misresolved so the path
  becomes root-absolute. Non-fatal but noisy; means session-end daemon shutdown doesn't run (orphans rely on
  `citadel down`). Not fixed yet.

### BUG-3 — OneDrive intermittent filesystem stalls (mitigated, not cured)
- Any fs op resolving the `.claude` junction / a dehydrated OneDrive placeholder can block indefinitely.
  Mitigated by `_daemon_path` (junction bypass) + the `start_daemon` watchdog + `_ensure_dir`. The only cure
  is hosting the workspace OFF OneDrive (`up` now warns).

## RESOLVED
- Daemon-start HANG at `start_daemon` mkdir — `f15e7d7` watchdog + `_ensure_dir` (verified: `up` reaches
  `[14/14]`).
- `realpath` stall in `_tools_dir` — `09e7bf2` abspath + cache.
- cp1252 crash in spawned tools — `c32102e` `_child_env` PYTHONUTF8.
- `output_schema_lint` false-fail (stale BI schema + BOM) — `a476b71`.
- `citadel init` re-run destructive on the `.claude` junction + no idempotency — `42206cb` `is_junction` +
  `.citadel/version` short-circuit.
