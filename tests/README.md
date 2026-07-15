# The Sovereign — Test Suite

## Running the tests

```bash
uv run pytest                 # full suite, parallel by default (-n auto), ~30s
uv run pytest tests/test_policy.py -o addopts="-ra"   # one file, serial (override the -n auto default)
uv run pytest -m serial       # only the parallel-unsafe tests
```

Configuration lives in `pyproject.toml` (`[tool.pytest.ini_options]`):
- **`-n auto --dist loadscope`** — parallel across all CPU cores; `loadscope` keeps each module's tests on
  one worker, so tests that share module-level state don't collide.
- **`serial` marker** — for parallel-unsafe tests (shared sockets/ports/fixed state files). Mark with
  `@pytest.mark.serial`.
- Live/hardware tests **auto-skip** when their dependency is absent, so the suite is green on any host.

Baseline: **~548 passed, 3 skipped** (the skips are legitimate: AF_UNIX socket + `grep` on Windows, and a
missing statusline asset in this checkout).

## The Sovereign execution + cache stack (the current focus)

| Test file | Covers |
|---|---|
| `test_ram_cache.py` | SIEVE (default) + LRU eviction, byte budget, entry cap, socket round-trip |
| `test_memoize.py` | Universal free memoization — compute-once, zero-recompute, disk persistence |
| `test_execute.py` | Cloud executor + `ResourceArbitrator` (token/rate budget) + `orchestrate` seam |
| `test_local_execute.py` | HRA GPU/VRAM budgeting, engine swap, Ollama HTTP, sequencer, self-heal ladder |
| `test_model_backend.py` | Cross-platform hardware detection — RAM/GPU probes, tier ladder, spec selection |
| `test_policy.py` | Local-first routing by intent + `LocalConfidence` self-learning |
| `test_sovereign.py` | `SovereignRunner` — classify → local-first → escalate to the Sonnet tier |
| `test_setup.py` | `citadel setup`/`doctor` detection helpers (no install side effects) |
| `test_ollama_live.py` | **Live** Ollama generation on the GPU — auto-skips when no server/model |
| `test_codebase_smoke.py` | **Every** `tools/`+`src/` file compiles and every `citadel` module imports |
| `test_cli.py` | CLI parser for every subcommand (init/up/down/run/do/setup/doctor/…) |

## The brain, legion, and workspace subsystems

Grouped by area (each file's docstring states its scope):
- **Brain / graph / reuse:** `test_brain_context_builder_reuse`, `test_reuse`, `test_import_graph`,
  `test_symbol_index`, `test_sharded_brain_graph`, `test_build_workspace_intelligence_index`,
  `test_prompt_usage_miner`, `test_feature_improvement_store`, `test_lazy_load`.
- **Legion / workers / governance:** `test_legion_*`, `test_worker_*`, `test_zombie_worker`,
  `test_efficiency_gate`, `test_principles_extended`, `test_best_practices_benchmark`,
  `test_repo_style_profiler`, `test_daemon_health_check`.
- **State / memory / recovery:** `test_self_heal`, `test_failure_recovery`, `test_session_snapshotter`,
  `test_token_ledger`, `test_bug_record`, `test_bug_regressions`, `test_git_history`.
- **Runtime / misc:** `test_up_dryrun`, `test_theme`, `test_scope_guard`, `test_mcp_server`,
  `test_cost_report_import_safe`, `test_statusline_legion`.

## Conventions

- Prefer injected fakes over real services (see `FakeEngine`/`Recorder`/`Scripted` in the execute tests) so
  the suite is deterministic and offline; add a **live** counterpart guarded by `skipif` for real hardware.
- No inline narration comments in test code (see `.claude/rules/code-style.md`) — names and structure carry
  the intent.
