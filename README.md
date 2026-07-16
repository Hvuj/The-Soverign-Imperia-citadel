# The Sovereign Imperia Citadel

Workspace-agnostic graph-brain + multi-agent orchestration layer for Claude Code.
The **legion is the corporate**; each git repo in your workspace is a **company** it
maps, mines, and learns — so Claude Code stops being a stateless assistant and becomes
a persistent, self-improving engineering brain for your whole workspace.

## Why Citadel Legion (vs. plain Claude Code / RAG tools / agent frameworks)

| Instead of… | Citadel Legion gives you… |
|---|---|
| **Plain Claude Code** re-reading files every session with no memory | Durable cross-session memory + a queryable **code+git graph** (commit ↔ feature ↔ file ↔ **function/line**), so answers come from an index, not a re-read. |
| **RAG / embedding search** (fuzzy, per-query vector cost, drift) | Exact **O(1)/O(log N)** structures — inverted index, symbol/line index (`bisect`), import DAG with cycle detection. Deterministic, no embedding bill. |
| **Generic agent frameworks** that fan out unboundedly | Deterministic orchestration with **budget caps, scope guards, and a stop-gate** that forces a `Pass / Needs Fix / Blocked` verdict — no runaway token spend. |
| **Manual "do this same change in 8 repos"** | **Zero-token replication**: capture a proven change once, replay it across N targets in **pure Python** (validated + auto-rollback) — 0 model tokens. |

The core is pure stdlib. Everything is rooted at your workspace, never the install location.

## Install

You install one thing — **citadel** — and `citadel setup` auto-installs everything else.

```bash
# 1. Install the CLI (like pipx) — once, works on any repo
git clone <repo-url> sovereign-imperia-citadel && cd sovereign-imperia-citadel
uv tool install .            # exposes `citadel` on your PATH

# 2. Auto-install the rest: Ollama, a local model, and the Python extras
citadel setup                # then `citadel doctor` to verify readiness

# 3. Scaffold The Sovereign into any project
citadel init ~/code/my-project --branch main
```

> **Developing citadel itself?** Run commands with `uv run citadel …` from the repo (editable install, so
> `src/`/`tools/` changes are live). After changing citadel's own code, `uv tool install . --force` refreshes
> the global CLI and the baked `.claude` template used by future `citadel init`.

### Prerequisites

**`citadel setup` auto-installs these for you:**

| Auto-installed | How |
|---|---|
| **Ollama** (local, free inference) | winget (Windows) / official script (macOS/Linux) |
| A local **code** model (`qwen2.5-coder:7b`, ~4.7 GB, ~5 GB VRAM) | `ollama pull` — powers free verified coding; override with `citadel setup --model <tag>` on smaller GPUs |
| Python extras (anthropic, watchdog, PyYAML, psutil, matplotlib, pytest-xdist) | pip |
| Zero-Token retrieval + MCP (`redis`, `numpy`, `mcp`) | pip — powers dense search + the MCP bridge (optional; degrades to a pure-Python store) |
| `llama-cpp-python` (opt-in: `citadel setup --with-ml`) | pip — needs a compiler or prebuilt wheel |

**You provide these yourself (true prerequisites):**

| Prerequisite | Why |
|---|---|
| **Python ≥ 3.12** + **uv** | to install and run citadel |
| The **coding-session CLI** on your PATH | the cloud tier The Sovereign escalates to as a last resort |
| **NVIDIA driver + CUDA** (optional) | GPU-accelerated local inference; the CPU path works without it |

Run **`citadel doctor`** any time to see what is installed, what is missing, and how to fix it.

### The Zero-Token stack (Redis + MCP) — one command

The Zero-Token layer makes **read / search / answer cost 0 model tokens for any AI** (dense retrieval +
an MCP bridge). It works with **no extra setup** out of the box — the vector store falls back to a
pure-Python on-disk index and the MCP servers run as local stdio processes. For scale and native HNSW
vectors, stand up the full stack with **one prerequisite (Docker)**:

```bash
# Brings up Redis Stack (RediSearch/HNSW) + our MCP retrieval server over HTTP
docker compose -f docker/compose/docker-compose.yml up -d

# Point the workspace at it + write the compose-flavoured .mcp.json
citadel setup --mcp compose
citadel doctor            # verify: redis reachable, RediSearch, MCP servers registered
```

**Redis is configurable** — precedence is `--redis-url` > `CITADEL_REDIS_URL` env >
`.citadel/config.toml [redis]` > default `redis://127.0.0.1:6379`:

```bash
citadel setup --redis-url redis://my-redis-host:6379   # use your own Redis (writes .citadel/config.toml)
citadel setup --no-redis                               # opt out → pure-Python on-disk vector store
```

**No Docker?** Skip the compose step entirely: `citadel setup --mcp native` (the default) runs the MCP
servers as stdio subprocesses and the retrieval layer uses the on-disk store — still zero-token. See
[docker/mcp/README.md](docker/mcp/README.md) for the egress-isolation model (reads in, data-out blocked)
and digest-pinning of the open-source reference servers.

**Redis local vs cloud, and every cache layer:** see [docs/REDIS-AND-CACHING.md](docs/REDIS-AND-CACHING.md).
Bring MCP up over Docker with `citadel mcp up` (then `citadel mcp pin` / `citadel mcp status`).

## Quick start

```bash
citadel setup                                  # auto-install Ollama + model + extras (once)
citadel init ~/code/my-project --branch main   # auto-learn: index, git-mine, bootstrap memory
cd ~/code/my-project
citadel up                                     # boot the brain + daemons, launch the session
citadel do "what does the auth module do?"     # answered FREE on the local tier — zero cloud tokens
citadel down                                   # stop everything when done
```

## Commands

| Command | Description |
|---|---|
| `citadel setup [--model M] [--with-ml] [--redis-url URL] [--no-redis] [--mcp native\|compose]` | **Auto-install** Ollama + model + Python extras; configure Redis + write the `.mcp.json` flavour |
| `citadel doctor` | Report what is installed / missing / how to fix (Ollama, model, GPU, **Redis + RediSearch, MCP servers**) |
| `citadel do "<task>"` | Run a task **The Sovereign way**: free local Ollama first, escalate to the cloud only if needed |
| `citadel ask "<question>"` | Answer grounded in the local index with citations — retrieval + answer cost **0 model tokens** |
| `citadel optimize <file> [--apply]` | Optimize a file locally, **verified before trust** (your code is propose-only unless `--apply`) |
| `citadel army "<goal>"` | Decompose a goal into atomic tasks and run them on a concurrent, lease-governed local pool |
| `citadel init <workspace> [--branch BRANCH]` | Full auto-learn: scaffold, index, git-mine, bootstrap memory |
| `citadel up [--restart] [--no-ui] [--dry-run]` | Bring up the full brain and launch the session |
| `citadel down [--workspace PATH]` | Stop all Citadel daemons + UI server and clean pidfiles |
| `citadel index [--workspace PATH]` | Rebuild workspace intelligence indexes |
| `citadel mine [--workspace PATH] [--branch BRANCH]` | Mine git history of all companies × dev/main/master |
| `citadel brain [--workspace PATH]` | Rebuild brain search index |
| `citadel replicate "<task>" [--execute --targets @f.json]` | Decide/execute **zero-token** feature replication |
| `citadel companies [--list \| <file>]` | List discovered companies, or run the KISS/SOLID/YAGNI/DRY scorecard on a file |

## What happens when activated

Start sessions with `citadel up` (never `claude` directly — that bypasses the brain).
Each session boots **7 background daemons** (5 core data/brain + `bug-record` and `zombie-worker`):

1. **incremental-brain** — watches `.claude/`, `docs/`, `tools/`; rebuilds indexes on change (~4 s).
2. **workspace-intelligence** — watches source; rebuilds the O(1) code index.
3. **outcome-miner** — mines Pass/Fail verdicts from ledgers into memory every 30 s.
4. **git-history** — mines commit nodes with **line-level function linkage** (commit → the exact
   functions it changed). **Lazy**: mines only the repos you actually touched this session (from the
   tool-batch ledger), plus one daily safety sweep of the rest — not an eager all-repo poll.
5. **RAM cache** — holds hot indexes/capsules in an in-memory LRU over a unix socket, so context
   carries a small `ram_ref` **pointer** instead of the bulk payload.

### The `__legion__` compiled cache (like `__pycache__`)

Python source isn't a form the legion can read efficiently — it must re-parse `.py` with `ast`.
So the legion **compiles each file's facts once** (symbols with line spans, imports, module) into a
compact `marshal` binary unit (`.legion`), keyed by source hash exactly like a hash-based `.pyc`.
Every index (symbols, imports, workspace-intel) then reads the **unit** instead of re-parsing; a unit
recompiles only when its source hash changes. Identical files shared across repos compile once
(content-addressed dedup). On a warm cache, index builds are ~100% cache hits and near-zero re-parses.

Then, on every prompt: classify → build a graph-derived **context capsule** (only the relevant
nodes/files, not whole files) → route to the right specialist agents → enforce scope guards →
stop-gate requires a `Pass / Needs Fix / Blocked` verdict before the turn ends. Outcomes are mined
back into memory so routing improves over time.

## How it cuts cost & runs more efficiently

Concrete, measured behaviors:

- **Context capsules, not file dumps.** Instead of pasting whole files, only the top ~3 graph nodes
  + pointers are injected; prompts below the relevance threshold inject **nothing** (a cheap turn).
  A 300 s route-cache makes repeated similar prompts **O(1)** — no re-search.
- **Ask the index, not the model.** *"Which functions did ticket AIDE-3548 touch?"* is answered from
  `commit-index.json` (`function` / `sha_to_functions` maps) in **O(1)** — zero model tokens, versus
  the model reading `git log -p` and guessing.
- **Zero-token replication.** *"Apply this guard to 8 client repos"* → capture the diff once as a
  template, then `citadel replicate --execute` replays it across all 8 in pure Python with validation +
  auto-rollback. **0 model tokens** for the 8 edits, versus 8× model round-trips.
- **RAM pointers over inlined bulk.** Hot capsules/indexes live in the RAM-cache daemon; context holds
  a `ram_ref` handle (a few bytes) that hydrates on demand — smaller prompts, memory-speed reads.
- **Budgeted agents.** Unrelated agents run in **micro mode** (≤8 lines, no tool calls); domain-logic
  specialists are skipped entirely on unrelated tasks. The stop-gate blocks runaway or unvalidated turns.
- **Compile once, read many.** The `__legion__` cache means an unchanged file is never re-parsed —
  a second index build is ~100% cache hits. Mining is lazy (only touched repos) and parallel across
  repos, and the per-tool-batch brain rebuild now fires only when a brain node actually changed.

## Stop / shut down

```bash
citadel down                 # SIGTERM → 3 s grace → SIGKILL all 5 daemons + UI; clears pidfiles
citadel up --restart  # clean restart
```

## Documentation

| Doc | What it covers |
|---|---|
| [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md) | End-to-end tour: mental model, lifecycle, daemons, per-turn flow, brain graph, governance (**start here**) |
| [docs/citadel/00-OVERVIEW-AND-NAMING.md](docs/citadel/00-OVERVIEW-AND-NAMING.md) | System overview and naming |
| [docs/citadel/](docs/citadel/) | Design series `00–06`: ground truth, agnostic audit, clean-slate log, build map, packaging, auto-learn |
| CLAUDE.md (deployed by `citadel init`) | The operating contract the model follows every session |
