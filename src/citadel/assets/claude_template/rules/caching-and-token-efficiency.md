# Caching And Token Efficiency

Use graph search, implementation cache, and context capsules before broad scans.

Start through `scripts/claude-start-smart.sh`. Manual search and run-once sync are debug-only.

## Workflow performance patterns (`.claude/workflows/*.workflow.js`)

The JS workflow runtime exposes **no Node APIs** (no `child_process`/`require`/`process`). Four rules
for fast, cheap fan-out — see `legion-specialists.workflow.js` / `legion-companies.workflow.js` for the
reference implementation (`mapLimit`, `TIER`, `agentTiered`):

1. **Bound the fan-out.** Never `parallel(items.map(...))` unbounded — one sub-agent per item invites
   provider throttling and linear cost. Keep using the runtime's `parallel()` (it does the real
   concurrent scheduling), but feed it **bounded batches** via `boundedParallel(items, MAX_PARALLEL,
   makeThunk)` (cap ~4–8) rather than a bare `Promise.all` pool. Each sub-agent pays a cold context +
   fresh cache prefix, so keep batches small and always end a fan-out with a single **reduce** agent
   that writes a compact summary — don't return raw per-agent output.
2. **Offload heavy lifting to Python via an `agent()` Bash call**, not `child_process`. Have the agent run
   the tool with a cross-platform launcher (`python` then `python3`) and return only a **condensed**
   result (last line / small JSON), never raw stdout. A nonzero exit → a `FAILED` sentinel the workflow
   branches on. Prefer the existing zero-token tools (`explore_map.py`, `feature_pattern_query.py`,
   `reuse_fast_path.py`) before any model reasoning.
3. **Isolate context, don't `/reset`.** `/reset` throws away the 5-min prompt cache; `/compact` mid-run is
   guarded by `cache-performance-auditor`. Give each sub-agent a shared, cache-stable prefix + a minimal
   task capsule sized by `graph-aware-config.json` `token_budget`. Isolate at **task** granularity, not
   per-function (per-function multiplies the cached-prefix cost).
4. **Tune model/effort per `agent()` call**, never session-wide mid-run (session effort is fixed at
   launch). Pick from the `TIER` map (never a hardcoded model id): cheap/haiku for mechanical sub-agents,
   standard/strong for reasoning. On a null/`FAILED` result, `agentTiered` retries once one tier up — a
   valid `passed:false` verdict is a real finding, not a failure, and is not retried.
