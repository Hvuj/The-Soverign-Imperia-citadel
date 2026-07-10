# 04 — The Build Map

> The master map to build The Sovereign Imperia Citadel from: what works (keep), what's broken (fix),
> weak spots, redundancy, where it fails to be self-learning / self-improving / self-aware /
> self-sustaining (task 11), the improvements to add, and the sequenced roadmap. Supersedes the legacy
> `full_plan.md` and `PLAN-V2.md`. (Tasks 8, 11, 13.)
>
> Severity: **S1** = breaks a core path / correctness · **S2** = silent wrongness / weak spot ·
> **S3** = cleanup. Priority: **P0** before trusting it · **P1** high value · **P2** deferred.

---

## 1. What works — keep and build on (do NOT rewrite)

| Keep | Why it's solid | Reference |
|---|---|---|
| AST symbol index (O(1) qualname, O(log N) bisect line→symbol) + import DAG (Tarjan cycles) | Genuine, unit-tested, the zero-token backbone | [system-map/05](../system-map/05-workspace-intelligence-and-code-indexes.md) |
| `__legion__` content-addressed compile cache (PEP-552-style fact units) | Compile-once/read-many; ~100% warm-cache hits | [system-map/02](../system-map/02-python-package-src.md) |
| RAM-cache daemon (AF_UNIX→TCP Windows fallback, fail-soft LRU) | Correct, portable, fail-soft | [system-map/06](../system-map/06-daemons-and-ram-cache.md) |
| `paths.py` resolver (`CITADEL_WORKSPACE` → `.citadel/config.toml` walk-up → raise; VS Code scoping) | The one correct root resolution — make it the *only* one | [system-map/02](../system-map/02-python-package-src.md) |
| Per-turn hook pipeline + execution manifest + Stop-gate verdict | Sound conception of governed turns | [system-map/11](../system-map/11-schedulers-hook-tools-and-lints.md) |
| Local-first `/api/ask` (19 deterministic categories, bounded opt-in fallback) | The seed of the zero-token front-door (§6) | [system-map/09](../system-map/09-ui-server-and-ask-citadel.md) |
| Grounding + prompt-leak + output-schema safety trio | Real, lint-enforced | [system-map/11](../system-map/11-schedulers-hook-tools-and-lints.md) |
| Core learning triad (outcome-mine → pattern-capture → reuse/replicate) + zero-token replication | Real self-learning, wired | [system-map/08](../system-map/08-learning-and-self-improvement.md) |
| The 8 principle Orders (analyzers) + benchmark | Deterministic, tested | [system-map/07](../system-map/07-legion-engine-and-governance.md) |

## 2. What's broken — bugs & incorrect logic (fix)

> **Update 2026-07-09 — the cross-platform runtime bugs are FIXED.** The test suite went from
> 18 failing to **206 passed / 3 skipped / 0 failed** on Windows (skips are `grep`/AF_UNIX/statusline
> assets absent here; they run on macOS/Linux). All logic was preserved. Fixed: `ram_cache_daemon`
> conditional `UnixStreamServer` (+TCP fallback), `model_effort_scheduler` in-code escalation/tier/
> complexity defaults (so it works without the config file present), deferred `matplotlib` import,
> `legion_self_heal` cross-platform `bash -n` (`_bash_syntax_ok` True/False/None + posix finding paths),
> `worker_memory`/`build_sharded_brain_graph` posix paths, `legion_model_dispatcher` `cwd=tempfile.
> gettempdir()`. **Still open (not test-covered):** B3/B4 (dead governance config), B5 (unenforced budget),
> B12 (health honesty), B17 (`model_backend` `/proc` — degrades gracefully), B16 (ANSI dashboard on raw
> Windows console).


### S1 — correctness / platform (P0)

| # | Bug | Fix |
|---|---|---|
| B1 | `citadel down` crashes on Windows — `commands/_daemons.py` uses POSIX `getpgid`/`killpg`/`SIGKILL`/`ps` | cross-platform stop (`psutil` or per-PID `taskkill`/`os.kill`) |
| B2 | Anthropic CLI-fallback broken on Windows — `legion_model_dispatcher.py:147` `cwd="/tmp"` | `tempfile.gettempdir()` |
| B3 | `board-config.json` is **dead** — the Senate hardcodes thresholds, never reads its config | make `evaluate_precedence()` read the config |
| B4 | Advocacy is ignored — the board never reads `conflict-set.json`; `legion_companies_advocate.py` has no wired caller | wire it into `run_full_gate()` or delete the layer |
| B5 | Live token budget not enforced — `efficiency_gate.check_token_budget()` has no caller in the supervise loop | wire it into `_supervise()` |
| B6 | Fake gate — `verify_workflow_static.py` always prints "Status: Pass" | implement real verification or delete |
| B7 | No wall-clock deadline on `_supervise()` — a hung Legionnaire polls forever | add a deadline + kill |
| B8 | Secret denylist unproven — a real `.env` read-block on the current Claude Code version is untested | live negative test before any autonomous run |

### S2 — silent wrongness / weak spots (P1)

| # | Issue | Fix |
|---|---|---|
| B9 | Dirty-node propagation is a no-op (`brain_dirty_propagation.py` = `print("dirty nodes: 0")`) → the brain daemon rebuilds the whole index every change (scaling risk) | real changed-file→node dirty set |
| B10 | Stub graph exporters (`build_brain_graph_dot/html.py`) contradict the "interactive D3" docs | delete or make real; the real viewer is the UI server |
| B11 | Directory-brain status always 0 (`dir_brain_index/status.py` read a dead path) | repoint to `docs/brain/directories/index.json` or delete |
| B12 | `legion_health.compute_tiers` misleads (reads the last snapshot; 0/1 per bucket); six `except: pass` report corruption as "healthy" | real cumulative counts; surface parse errors |
| B13 | Three workspace-root resolutions (`CITADEL_WORKSPACE` vs `parents[1]` vs `_brain_common.ROOT`) — some tools silently target the package tree | unify on `paths.py` |
| B14 | Capsule cache never GCs — deleted/renamed nodes leave stale capsules forever | prune on rebuild |
| B15 | `up` has no rollback if `claude` isn't found (7 daemons left running) | check `which("claude")` first |
| B16 | Dashboard assumes VT100 (`\033[2J\033[H`) — garbage on a raw Windows console | detect/enable VT or plain-render fallback |
| B17 | `model_backend` Linux-only probes (`/proc/meminfo`, `/models`) → false `UNAVAILABLE` on Windows; `is_fully_operational()` only checks the embed model | cross-platform probes; check all capabilities |
| B18 | `department_router` uses unanchored substring matching (`"cd"` matches "code") | word-boundary anchoring |
| B19 | `diff_hash` in `legion_companies.py` is a hardcoded empty SHA | real content hash |

## 3. Weak spots (consolidated)

Governance-is-theater (B3/B4) · unenforced token budget (B5) · Windows-breaks (B1/B2/B16/B17) · hollow
tools (B6/B9/B10/B11) · advisory-not-gated zero-token (§6) · three root-resolvers (B13) · misleading
health (B12) · never-run-live multi-worker/autonomous path (legacy `full_plan.md §1`) · domain
vocabulary baked into code ([02 §A](02-AGNOSTIC-AUDIT.md)) · dirty seed assets ([02 §E](02-AGNOSTIC-AUDIT.md)) ·
no runtime schema validation (existence-lint only).

## 4. Redundancy (remove / consolidate)

| Redundancy | Action |
|---|---|
| `claude-start*.sh` (3) + daemon/UI/brain `*-start/stop/status.sh` (~15) largely superseded by `citadel up`/`destroy` | keep a couple as documented debug wrappers; delete the `claude-start*` trio |
| Version string in 3 places (`__init__.py`, `pyproject`, `cli.py --version`) | **fixed** — hatch now sources it from `__init__.py`; still update `cli.py` to read `__version__` ([05](05-PACKAGING-AND-INSTALL.md)) |
| `_CONFLICT_THRESHOLD = 0.70` duplicated in `legion_governance.py` + `legion_companies.py` | single constant |
| Dead code: `_slug()`, `save_miner_state()` (self-labeled legacy), `CommitGraph` ABC (no impls), `LegionUnit.features=[]`, unreachable `sed`/`awk` branch in `legion_shell.classify()` | delete |
| Duplicate seed copies of memory/UI files (working tree vs `assets/`) | one source of truth ([02 §E](02-AGNOSTIC-AUDIT.md)) |
| `.claude/state` vs `.citadel/state` pidfile straddling | document + consolidate the split |
| Print-stub tools `add_project_doc.py`, `doc_ingestion_router.py` | implement or delete |

## 5. Where it is NOT self-* (task 11 — the core gap map)

| Goal | Where it's missing | Build action | Priority |
|---|---|---|---|
| **Self-learning** | Prompt-reuse mining (`prompt_usage_miner.py`) has no dedicated hook — learns only when run manually | fire it from a PostToolBatch/SessionEnd hook | P1 |
| | Reuse is *advisory* — nothing forces a Legionnaire to consult learned patterns before exploring | exploration-budget gate (§6.1) | P1 |
| **Self-improving** | Bug→codemod promotion (`codemod_promoter.py`) — the real zero-token self-repair loop — runs only as an optional daemon, disconnected from the live loop | wire it into the Citadel Loop so a repeat bug becomes a permanent T0 codemod | **P0/P1** |
| | Skill synthesis (`skill_synthesizer.py`) + spec-gen (`spec_generator.py`) + the megacorp master loop are orphaned (megacorp-only, not in `up`/`run`) | wire into the Citadel Loop deliberately, or scope out | P1 |
| | L3–L7 verification ladder mostly orphaned (only L0/L1 likely reachable) | sequence the ladder in the live gate, or delete unused levels | P1 |
| **Self-aware** | `legion_health` reports "healthy" on corrupt state (six `except: pass`) and fakes cumulative metrics | honest health; real counters (B12) | P1 |
| | No "tokens spent vs tokens saved" telemetry — the zero-token claim is asserted, not measured | extend `telemetry-events.ndjson` + surface in the front-door | P1 |
| | The Citadel cannot *explain its own state* interactively for zero tokens | the terminal front-door (§6.2) | P0 |
| **Self-sustaining** | `citadel down` / stray-daemon cleanup break on Windows (B1) | cross-platform (B1) | P0 |
| | Governance config is dead (B3/B4) — editing config doesn't change behavior, so the Sovereign can't tune it without code | config-driven governance | P0 |
| | Transplanted-data risk — no first-run guard against trusting foreign brain/state | `citadel init` refuses to trust non-regenerated brain data | P1 |
| | Legacy narrative docs drift silently | inventory lint that regenerates counts and fails on drift ([01 §5](01-GROUND-TRUTH-AND-DISCREPANCIES.md)) | P1 |

## 6. Improvements to add

### 6.1 Zero-token enforcement (advisory → gated)

- **Exploration-budget PreToolUse hook:** a broad `Grep`/`Read` is allowed only after an index/pattern
  query, or with a logged "index miss" reason. Turns the zero-token mandate into a hard gate.
- **Enforce the run budget** (B5). **Prune caches** (B9/B14). **Instrument** tokens-spent-vs-saved.
- **Target invariant:** no model tokens on anything the indexes, ledgers, caches, codemods, or
  deterministic resolvers can answer — violable only with a logged reason.

### 6.2 The Citadel terminal front-door — "hey citadel" at zero tokens

A `citadel shell` REPL/TUI (pure stdlib) with a **deterministic intent front-door**. A greeting, a
status query, a code lookup, or a confirmation is answered at **T0 (no model call)**; only genuine
ambiguity is escalated to a Legionnaire.

```
┌ CITADEL · ONLINE · 5 daemons · health green · tokens today: 0 ┐
│ › hey citadel                                                 │
│ CITADEL: Hey.                             [T0 · 0 tokens · 2ms]│
│ › status                                                      │
│ CITADEL: 5/5 daemons up · brain 147 nodes · index fresh       │
│ › who calls compute_totals                                    │
│ CITADEL: 3 callers (from import-index)    [T0 · 0 tokens]     │
│ › redesign the caching layer                                  │
│ CITADEL: ambiguous → summoning 1 Legionnaire (opus/plan)… [T2]│
└───────────────────────────────────────────────────────────────┘
```

| Intent (all T0) | Resolver (existing seed) |
|---|---|
| wake-word / greeting (`hey citadel`, `hi`) | new tiny greeting table |
| status / health | `citadel_system_health`, `daemon_health_check`, `worker_status` |
| "what changed / who calls / where is X" | commit-index (regenerated), symbol/import indexes |
| "what worked / known pitfalls" | `what-worked.md` / `what-did-not-work.md` |
| reuse/replicate a proven change | `services/reuse` + `feature_replicator` |
| confirmations, destroy, restart | direct command dispatch |
| genuine ambiguity | summon a Legionnaire (T2) |

Reuse Ask-Citadel's local resolver + add a greeting category + a terminal renderer (extend `_theme.py`).
**P0:** REPL skeleton + greeting + status/lookup (zero-token). **P1:** escalation handoff + voice.

### 6.3 Other adds

Runtime schema validation at the boundaries that matter (manifest, tier-decision, ask-response);
head-to-head benchmark harness + trend/PDF; multi-worker + governance-veto + Windows integration tests.

## 7. The Citadel operating contract (drop into `CLAUDE.md` / the cached spine)

> **Citadel Operating Contract — self-learning · self-improving · self-aware · self-sustaining**
> 1. **Zero-token first (mandatory).** Consult indexes, ledgers, caches, patterns, and codemods before
>    spending a model token. A broad scan or model call is allowed only after a logged index/pattern
>    miss. Prefer a worker (T0) over a Legionnaire (T2) for anything deterministic tooling can do.
> 2. **Evidence or "I don't know."** No claim without evidence from live state, indexes, or a direct
>    read. Never invent results, counts, or file contents. Codebase beats memory.
> 3. **Every turn is governed.** classify → capsule → manifest → scope-guard → verdict
>    (`Pass / Needs Fix / Blocked`). The Senate may veto. The Stop-gate blocks an unverified turn.
> 4. **Learn from every outcome.** On success, capture a reusable pattern; on a repeat bug, promote the
>    fix to a permanent T0 codemod; mine Pass/Fail into memory. The next similar task must be cheaper.
> 5. **Workspace-agnostic & portable.** Every path derives from `CITADEL_WORKSPACE`/`.citadel/config.toml`;
>    every OS call works on Windows, macOS, Linux. Ship zero domain vocabulary — learn it per province.
> 6. **Self-aware.** Keep health / token-spent-vs-saved / daemon / verdict telemetry current and
>    surfaced in the front-door; a corrupt state file is an error, never a silent "healthy".
> 7. **Never leak or destroy.** No secrets/prompts/keys in output, memory, or logs. No destructive git
>    or file ops outside scope. Confirm irreversible actions.
> 8. **Config is truth.** Behavior comes from the JSON configs (Senate, schedulers, policies); code
>    reads them, so editing a config changes behavior. No hardcoded governance.
>
> *The Citadel spends model tokens only on genuine ambiguity, gets cheaper and safer every cycle, and
> can explain its own state at any moment for zero tokens.*

## 8. Sequenced build roadmap

- **P0 — trustworthy, portable, sovereign-tunable:** B1-B8 fixes; unify root resolution (B13);
  make the Senate read its config (B3/B4); enforce the run budget (B5); the terminal front-door
  **skeleton** (greeting + status + lookup, zero-token, §6.2); the BI + domain-vocabulary removal
  ([02 §A/B](02-AGNOSTIC-AUDIT.md)); scrub the seed assets ([02 §E](02-AGNOSTIC-AUDIT.md)).
- **P1 — honest & self-improving:** B9-B19; wire the codemod loop + Citadel Loop (§5); exploration
  gate + token telemetry (§6.1); the Senate/Legion/worker rename in code; escalation handoff; the
  inventory-drift lint; integration tests.
- **P2 — rich & measured:** benchmark head-to-head + trend/PDF; runtime schema validation; voice;
  regenerate the narrative docs from measured counts; delete legacy shims.

**Ship-gates.** *P0 done* = every core command runs on Windows; no fake gates; the Senate reads its
config; budgets enforced; `hey citadel`→`Hey` at 0 tokens; no domain vocabulary or foreign data ships.
*P1 done* = zero-token is gated not advisory; repeat bugs self-heal as codemods; one org vocabulary;
honest self-aware telemetry; live multi-worker test green.
