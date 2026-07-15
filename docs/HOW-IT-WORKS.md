# How the Sovereign Imperia Citadel Works

A single end-to-end tour of the system: what it is, what each command does, what boots, and what
happens on every prompt. For the operating contract the model itself follows, see the deployed
`CLAUDE.md`; for design rationale and history see `docs/citadel/00–06`.

## Mental model

The Citadel is a **workspace-agnostic graph-brain + multi-agent orchestration layer that wraps Claude
Code**. It ships with **zero domain knowledge** and learns each workspace over time. The internal
metaphor: the **legion is the corporate**, and each git repo under your workspace is a **company** it
maps, mines, and learns — so Claude Code stops being a stateless assistant and becomes a persistent,
self-improving engineering brain for the whole workspace.

Everything is rooted at **your workspace**, never the install location. The core is pure stdlib.

## Lifecycle

```
citadel init <workspace>   # scaffold + auto-learn (once per workspace)
citadel up                 # boot the brain + daemons, launch Claude Code
  … per-turn flow …        # every prompt is classified, routed, gated
citadel down               # stop daemons + UI, clean pidfiles
```

| Command | What it does |
|---|---|
| `citadel init <workspace> [--branch B]` | Scaffold `.citadel/.claude` + `CLAUDE.md`, then index, git-mine, and bootstrap memory |
| `citadel up [--restart] [--no-ui] [--effort L]` | Bring up the full brain and launch Claude Code |
| `citadel down [--workspace P]` | SIGTERM → 3 s grace → SIGKILL all daemons + UI; clear pidfiles |
| `citadel index` / `mine` / `brain` | Rebuild the intelligence indexes / mine git history / rebuild the brain search index |
| `citadel replicate "<task>" [--execute]` | Zero-token feature replication across N repos (pure Python, validated, auto-rollback) |
| `citadel companies [--list | <file>]` | List discovered companies, or run the KISS/SOLID/YAGNI/DRY scorecard |

## What `init` scaffolds

`init` writes the curated `.claude/` template and the operating contract into the workspace:
`<ws>/.citadel/CLAUDE.md` with a root `CLAUDE.md` symlink, and `<ws>/.citadel/.claude/` (agents, skills,
hooks, rules, schemas, brain configs, workflows) linked as `<ws>/.claude`. It then runs the auto-learn
pass — index the repos, mine git history, bootstrap memory — so the brain is warm before the first
prompt. On a fresh install the brain indexes are intentionally **empty** (`docs/brain/graph-index.md`,
`docs/brain/workspace/index.md` show a clean slate) and fill in as the system learns the workspace.

## What `up` boots

Start sessions with `citadel up` (never `claude` directly — that bypasses the brain). Each session boots
**7 background daemons** — 5 core data/brain daemons plus 2 auxiliary:

1. **incremental-brain** — watches `.claude/`, `docs/`, `tools/`; rebuilds indexes on change (~4 s).
2. **workspace-intelligence** — watches source; rebuilds the O(1) code index.
3. **outcome-miner** — mines Pass/Fail verdicts from ledgers into memory every 30 s.
4. **git-history** — mines commit nodes with line-level function linkage (commit → exact functions it
   changed); lazy (only touched repos this session) plus one daily safety sweep.
5. **RAM cache** — holds hot indexes/capsules in an in-memory byte-budgeted LRU, so context carries a
   small `ram_ref` pointer instead of the bulk payload.
6. **bug-record** — maintains the deduped bug ledger.
7. **zombie-worker** — reaps dead/stale worker processes.

### The `__legion__` compiled cache

Rather than re-parsing `.py` with `ast` on every index build, the legion compiles each file's facts once
(symbols with line spans, imports, module) into a compact binary unit keyed by source hash — like a
hash-based `.pyc`. Every index reads the unit instead of re-parsing; a unit recompiles only when its
source hash changes, and identical files across repos compile once. Warm-cache builds are near-100 %
cache hits.

## Per-turn flow

On every prompt:

1. **Classify** the prompt (intent, unit, complexity).
2. **Build a context capsule** — only the top few relevant graph nodes/pointers, not whole files.
   Prompts below the relevance threshold inject nothing (a cheap turn); a 300 s route-cache makes repeat
   prompts O(1).
3. **Route to the right agents** — an allowlist of the relevant specialists, each under a budget mode.
4. **Enforce scope guards** — no out-of-scope edits, no unsafe deletes.
5. **Stop-gate** — the turn cannot end without a `Pass / Needs Fix / Blocked` verdict.
6. **Mine outcomes** back into memory so routing improves over time.

## The brain graph

The brain is a queryable graph of nodes under `docs/brain/nodes/**` — **agents**, **workflows**,
**tools**, **topics**, **memory**, plus recorded **successes/failures**. `docs/brain/graph-index.md` is
the lightweight id → file routing index; `tools/brain_query.py` and the brain-search nodes provide
search. The interactive `docs/brain/graph.html` is UI-only. On a clean slate these are empty and grow as
the workspace is learned.

## Governance (from `CLAUDE.md`)

- **Budget modes** — `micro` (cheap applicability check, no tools), `standard` (focused review), `deep`
  (full review for correctness/production risk).
- **Agent caps** — ≤5 for docs/graph tasks, ≤8 otherwise; `agent-budget-controller` runs first,
  `efficiency-auditor` last.
- **Domain-logic gate** — domain-logic/semantics/query specialists run ONLY when the prompt explicitly
  touches workspace-specific domain logic, metrics, or queries (learned per workspace, never assumed).
- **Validation gate** — non-trivial code/config/workflow changes must run `test-validation-runner`.
- **Memory workflow** — `memory-curator` decides what to persist; `memory-optimizer` dedupes/compacts.

## Agnostic learning

The Citadel carries no framework-specific vocabulary. Two layers of discovery, at different maturity:

- **Live today:** `workspace_discoverer.py` walks the workspace with no hardcoded paths, detects
  languages/frameworks by content, and writes `.claude/state/workspace-discovery.json`. The specialist
  workflow reads that and dispatches one generic specialist per discovered framework — fully agnostic
  and auto.
- **Reader wired, populator not yet built:** `build_workspace_intelligence_index.py` records raw
  decorators/imports and categorizes them (orchestration assets, schema models, dataframe/query usage)
  only from `.claude/brain/framework-signals.json`. That file ships **empty and nothing writes it yet**,
  so this categorization is currently **inert** — it stays empty until a learning step is built to
  populate it. This is deliberate (no tech-specific rules are baked in) but means the fine-grained
  categorization is a planned capability, not a working one.

## The Sovereign — voice, and local-first free execution

The system speaks to you as **The Sovereign**; the model underneath is invisible plumbing. When it
answers, it never names the engine.

Execution is **local-first and free**. `citadel do "<task>"` classifies the request and routes it:
questions, search, simple functions, and checks run on the **local Ollama tier (CPU/RAM/GPU) at zero
tokens**; only genuinely complex or high-risk work escalates to the cloud (Sonnet) as a last resort. Each
outcome is recorded to a per-intent **confidence** (`LocalConfidence`) — a repeatedly-failing intent
escalates, a recovering one returns to free — so the local tier takes on more over time. The moving parts
live in `src/citadel/services/execute/` (`policy.py`, `sovereign.py`, `local/`), all behind the same
`Executor` seam.

GPU use is automatic: hardware detection (`tools/model_backend.py` → `detect_hardware`, with an
`nvidia-smi` fallback) picks the tier and offload; the HRA budgets VRAM before dispatch.

## Setup, doctor, and the VSCode extension

- **`citadel setup`** auto-installs Ollama, a small local model, and the Python extras — you only install
  citadel. **`citadel doctor`** reports what is installed / missing / how to fix (Ollama, model, GPU,
  extras, the escalation CLI).
- **VSCode:** opening a `citadel init`'d workspace makes the coding extension auto-load the Citadel context
  — the root `CLAUDE.md` and `.claude/settings.json` (hooks + statusline) are read automatically. Run
  `citadel up` in an integrated terminal to boot the daemons for the session.

## Running the tests

`uv run pytest` runs the full suite in parallel (`-n auto`) in ~30s; live/hardware tests auto-skip when
absent. See `tests/README.md` for the map of what each area covers.
