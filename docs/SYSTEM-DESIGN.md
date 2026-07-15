# The Sovereign Imperia Citadel — System Design

> A workspace-agnostic **graph-brain + multi-agent orchestration layer** that wraps a coding
> session, does as much work as possible **for free on local hardware**, and governs every
> irreversible act through a Roman-Republic-inspired **control plane**. The CLI is `citadel`;
> the system speaks to the operator as **The Sovereign**.

This document is the authoritative description of the *current, built* design — every subsystem named
here exists in `src/citadel/` and is covered by the test suite (**659 passing, 3 platform-skipped**).
Where a capability is a primitive that is built-and-tested but not yet wired into every live call path,
it is marked **[adoption pending]** — those are integration steps, not missing designs.

---

## Table of contents

1. [Design goals & principles](#1-design-goals--principles)
2. [System-level architecture](#2-system-level-architecture)
3. [The Read Spine — index correctness](#3-the-read-spine--index-correctness)
4. [The Shields — context custody](#4-the-shields--context-custody)
5. [The execution model — local-first & self-learning](#5-the-execution-model--local-first--self-learning)
6. [The Blades — safe writes, verdicts, condemned set](#6-the-blades--safe-writes-verdicts-condemned-set)
7. [The Law — the control plane](#7-the-law--the-control-plane)
8. [The Empire — the command hierarchy](#8-the-empire--the-command-hierarchy)
9. [The Auxilia — multi-model trust & citizenship](#9-the-auxilia--multi-model-trust--citizenship)
10. [Directives, gates & chaos drills](#10-directives-gates--chaos-drills)
11. [The Ground — dot-dir contract & term-lint](#11-the-ground--dot-dir-contract--term-lint)
12. [CLI surface & operator flow](#12-cli-surface--operator-flow)
13. [State & data layout](#13-state--data-layout)
14. [Testing & verification](#14-testing--verification)
15. [Naming, taxonomy & the Legion](#15-naming-taxonomy--the-legion)
16. [Roadmap status](#16-roadmap-status)

---

## 1. Design goals & principles

| # | Principle | How it shows up |
|---|-----------|-----------------|
| **P1** | **Local-first, zero-token by default.** Cheap work runs free on the local tier; the cloud is the last resort. | `services/execute/policy.py`, `sovereign.py`, Ollama tier |
| **P2** | **Self-learning.** The system learns which work it can do locally and keeps more of it free over time. | `LocalConfidence`, `TrustLedger` |
| **P3** | **Verify before you trust.** A local "pass" means *the work was checked*, never "text was generated." | sandbox-verify-before-write (`coding.py`) |
| **P4** | **No power without a lease.** Every grant of authority carries a TTL; nothing is authorized forever. | `authority/lease.py`, `empire.Dictator` |
| **P5** | **Two gates on the axe.** No irreversible act proceeds on a single validator's say-so. | `authority/intercessio.py` |
| **P6** | **Reversible by construction.** Every mutation carries a content-addressed pre-image and a verdict record. | `authority/../execute/verdict.py`, `coding.py` |
| **P7** | **Agnostic.** No workspace-specific vocabulary, frameworks, or paths are hard-coded; they are *discovered*. | framework-signals discovery, agnostic agents |
| **P8** | **Enhance, don't rewrite.** New primitives sit *beside* the working system behind stable seams. | the `Executor` ABC, `services/authority/` package |

The unifying metaphor is the **Roman Republic**: authority is explicit, delegated by attenuation, bounded
by leases, checked by veto, and even the highest office is stripped of its most dangerous power inside the
protected core (the *pomerium*).

---

## 2. System-level architecture

```
                          ┌──────────────────────────────────────────────┐
   operator ── "citadel …"│                 The Sovereign                 │
                          │        (voice + CLI front, cli.py)            │
                          └───────────────┬──────────────────────────────┘
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        │                                 │                                 │
  ┌─────▼──────┐                   ┌───────▼────────┐                 ┌──────▼───────┐
  │ READ SPINE │                   │  EXECUTION     │                 │  CONTROL     │
  │ (index)    │                   │  (do the work) │                 │  PLANE (Law) │
  ├────────────┤                   ├────────────────┤                 ├──────────────┤
  │ oracle     │  membership,      │ policy.route   │  local-first    │ fasces       │ capability
  │ JIT hash   │  freshness,       │ sovereign_run  │  free Ollama →  │ pomerium     │ zones
  │ degree-1   │  zero-IO prune    │ LocalCoding    │  cloud escalate │ lease        │ TTL
  └─────┬──────┘                   │ Cloud(Claude)  │                 │ verdict      │ blades
        │                          └───────┬────────┘                 │ intercessio  │ dual-gate
  ┌─────▼──────┐                           │                          │ tribune      │ veto
  │  SHIELDS   │  count-first,     ┌────────▼───────┐                  │ trust/auxilia│ citizenship
  │  (custos)  │  splice, redact   │  THE BLADES    │  sandbox→verify  │ empire       │ hierarchy
  └────────────┘                   │  pre-image +   │  →write-back     └──────────────┘
                                   │  verdict       │
                                   └────────────────┘
        │                                                                     │
  ┌─────▼─────────────────────────────────────────────────────────────────────▼─────┐
  │   THE GROUND: dot-dir contract (paths.py) · term-lint · doctor · daemons · brain  │
  └───────────────────────────────────────────────────────────────────────────────────┘
```

Everything above the Ground is a **service** under `src/citadel/services/`. The four pillars — Read Spine,
Shields, Execution, Control Plane — are independent packages joined only by small, testable seams.

---

## 3. The Read Spine — index correctness

**Module:** `tools/citadel_oracle.py` · **Gates:** G1, G2, G3

Before any cached knowledge is served, the Read Spine answers two questions in O(1): *"does this symbol
even exist?"* and *"is what I cached still true?"*

- **`MembershipOracle`** — an L0 exact key set (**zero false-positive by construction**) plus an L1
  mutable `adds`/`tombstones` delta. `absent(key)` is the **Zero-IO pruning gate**: a definite-absence
  answer halts a search before it touches the disk. (A perfect-hash/fingerprint memory optimization —
  CMPH/BBHash — is deferred; the exact set already delivers the correctness win.)
- **`content_hash(path)`** — xxHash64 when available, else a truncated BLAKE2b. Content-based, **never
  mtime**, so a branch switch that rewrites a file with the same timestamp is still caught.
- **`is_fresh(path, cached_hash)`** — the **JIT validation** (directive D3): re-hash the file before
  serving any cached brain/symbol node; a miss triggers a single-file re-index. Catches staleness 100% of
  the time under a branch-switch storm.
- **`degree_one(adjacency, node, k)`** — caps graph traversal to depth 1 with a total count, so an impact
  query can never fan out into an O(N) walk (directive D5).

**[adoption pending]** wiring `is_fresh` into *every* cached-read serve path (the oracle and hashing are
standalone-tested; adoption into brain-search dispatch is incremental).

---

## 4. The Shields — context custody

**Module:** `tools/citadel_custos.py` · **Gate:** G4

The Shields (*Custodiae*) stand between tool output and the model's context window. Nothing enters context
uncounted.

- **`counts(text)`** — line + byte counts: the mandatory **count-first preamble** (`rg -c` philosophy).
- **`splice(text, max_bytes)`** — byte-bounded serving → `(body, served, total)`, so a 2 GB log never
  detonates the context budget.
- **`redact(text)`** — masks secrets before they can be logged or cached: `sk-*`, `ghp_`/`github_pat`,
  `AKIA*`, `xox*`, `PRIVATE KEY` blocks, `Bearer` tokens, and `.env` `KEY=value` pairs (keeps the key,
  masks the value).
- **`guard_output(...)`** — the composite: **always** emits a `preamble`, then splices, then redacts. This
  is the enforcement point for G4.

---

## 5. The execution model — local-first & self-learning

**Modules:** `services/execute/{policy,sovereign,executor,coding,cloud,local/}.py`

The execution model is the beating heart of P1/P2/P3. The flow for `citadel do "<task>"`:

```
classify_intent(prompt)  →  policy.route(intent, complexity, risk, confidence)
        │                              │
        │                     ┌────────┴─────────┐
        │                 tier=local          tier=cloud
        │                 (free, Ollama)      (escalate)
        ▼                     │                   │
 sovereign_run:  try LocalExecutor / LocalCodingExecutor  ──fail──▶  CloudClaudeExecutor (Sonnet/Opus)
        │                     │                                          │
        └──────── record outcome → LocalConfidence (JSONL) ─────────────┘
                              (self-learning knob)
```

- **`policy.route(intent, complexity, high_risk, local_confidence)`** — cheap intents (question, search,
  simple_function, check, docstring-only, validation-only, docs-ingestion, lookup, terminal-help) run
  **local & free**; `architecture`/`migration`/`security`/`cross_repo`, high-risk, high-complexity, or a
  learned-low-confidence intent go straight to cloud.
- **`LocalConfidence`** — a per-intent success rate learned from recorded outcomes and persisted as JSONL.
  Repeated local failure drops confidence below 0.5 → `route` escalates that intent; recovery earns it back.
  This is the self-improving loop: as the local tier proves itself, more work stays free.
- **`LocalExecutor` (Ollama)** — `qwen2.5-coder:7b` by default (Q&A can use the tiny `qwen2.5:0.5b`).
  Runs 100% on GPU when one is auto-detected (`model_backend` via `nvidia-smi`/torch; RTX-class cards
  auto-use all layers). CPU/RAM-aware fallback via the local `HardwareResourceArbitrator`.
- **`CloudClaudeExecutor`** — the escalation tier, wrapping the `claude --print --model` CLI with a
  stable-prefix-first layout for prompt caching. Behind the scenes it is Claude; to the operator the system
  only ever speaks as **The Sovereign**.
- **`sovereign_run`** — the composition: try free local first, escalate on failure, record the outcome to
  confidence. The `Executor` ABC + `orchestrate()` means Fake/Local/Cloud executors all pass the identical
  code path (swap-tested).

### Verified local coding (P3)

`LocalCodingExecutor` (`coding.py`) is what makes a local "pass" trustworthy:

1. Ask the local model for the **complete new content** of the target file(s) (multi-file via
   `### FILE: <path>` fenced blocks, restricted to declared targets).
2. Apply to an **isolated sandbox copy** (`shutil.copytree`, ignoring `.git`/`.venv`/caches).
3. Run a deterministic **`verify(sandbox) → (ok, detail)`** (default: `ast.parse` every target `.py`; or a
   custom command whose exit code is the verdict — zero tokens).
4. **Write back to the real workspace only if verify passes** — all-or-nothing across all files. An
   unverified change never touches the repo.

This is **live-proven**: `citadel do "Set A to 1 in a.py and B to 2 in b.py" --file a.py --file b.py`
applied and verified two files with **zero cloud tokens** on the local GPU.

---

## 6. The Blades — safe writes, verdicts, condemned set

**Module:** `services/execute/verdict.py` · **Gate:** G5

Every mutation is reversible and judged.

- **`artifact_hash(content)`** — BLAKE2b-16 content digest, the key for both the verdict ledger and the
  condemned set.
- **`VerdictLedger(root)`** — `record(hash, status)` writes `PASS | FAIL | CAPITAL` to `verdicts.jsonl`.
- **Condemned set** — a `CAPITAL` verdict adds the content hash to a permanent condemned set: **O(1)
  reject** of the identical content on every future submission (it can never be re-proposed), persisted
  across reloads.
- **`backup(path)`** — a **content-addressed pre-image** written to `<root>/pre-images/<digest>` *before*
  any overwrite. Identical content dedups to one blob (a hundred backups of an unchanged file cost one).

Wired into `LocalCodingExecutor`: before applying, any generated file whose hash is condemned is
**blocked**; on verify-fail a `FAIL` is recorded; on a verified write-back the pre-image is backed up and a
`PASS` recorded. → **100% of mutations carry a pre-image + a verdict (G5).**

---

## 7. The Law — the control plane

**Package:** `src/citadel/services/authority/` · **Gates:** G6, G7

The control plane is the constitutional core. Authority is a `uint64` **capability mask** carried in a
signed token; where and when it may be used is bounded by zones and leases; irreversible acts require a
second, uncorrelated vote; and certain processes can never be touched.

### 7.1 Fasces — signed capability tokens (`fasces.py`)

A `uint64` mask: the low bits are **rods** (reversible mutate-class — `WRITE_FILE`, `APPLY_PATCH`,
`RESTART_SVC`, `INDEX_WRITE`, `CACHE_EVICT`, `FORMAT`); the high 16 bits are the **axe**
(`AXE_CLASS = 0xFFFF_0000_0000_0000` — `DELETE_PATH`, `DROP_TABLE`, `FORCE_PUSH`, `KILL_PID`,
`LEASE_REVOKE`, `CONDEMN`).

- **`sign_token(...)` / `verify_token(...)`** — HMAC-SHA256 over the canonical
  `{imperium|rank|mask|lease|zone|expiry}`. Alter any field and the binding breaks — the token is
  tamper-evident.
- **`permitted(required, token, *, in_domi, key, now)`** — **O(1)**: reject if expired, verify the
  signature when a key is supplied, strip the axe inside the pomerium (`mask & ~AXE_CLASS if in_domi`),
  then a single `(required & effective) == required`.
- **`attenuate(parent, requested) = parent & requested`** — delegation can only *drop* bits.

### 7.2 Pomerium — filesystem zones (`pomerium.py`)

`Pomerium(domi_prefixes, militiae_prefixes)` classifies a path by longest-prefix match into **DOMI** (the
protected city — `.git/`, `main`, protected state) or **MILITIAE** (the field — `/tmp`, sandboxes,
worktrees). Inside DOMI the axe is removed for *every* rank. `/mnt/c` and OneDrive paths are always DOMI
(the WSL wall); unknown paths fail safe to DOMI.

### 7.3 Leases — no grant is forever (`lease.py`)

`LeaseReaper` holds a min-heap keyed by expiry: O(1) `is_valid`, O(log L) `grant`, O(1) `next_expiry`
peek. Nothing polls — `reap(now)` returns everything expired or revoked so the caller runs the enforcement
(*Coercitionis*) ladder.

### 7.4 Lex Curiata — signed activation manifests (`lex_curiata.py`) → G6

A manifest on disk holds **zero authority until ratified**. `validate_manifest` rejects: a missing lease
TTL (D1), a missing/empty province clause, a **wildcard province** (`/**`, `/`, `**`, `/*` = god-mode
scope), and a floating `:latest` image (D6). `sign_manifest` is an HMAC over the canonical body;
`is_ratified` = *schema-valid AND signature matches*. **The signature is the activation** — a tampered
field fails `compare_digest`.

### 7.5 Intercessio — the dual-gate (`intercessio.py`) → G7

`dual_gate(gates)` approves an axe-class act **only when ≥2 PASS verdicts come from *different* model
families**. A second Claude instance shares Claude's blind spots — it is not an independent gate. Returns
`(approved, reason)`.

### 7.6 Tribune — sacrosanct veto (`tribune.py`)

`SacrosanctRegistry.may_kill(pid)` returns `False` for a protected PID (the stop-gate watchdog, the
operator's control channel) **and records the refused attempt** as a constitutional violation. The Tribune
holds no imperium of its own — it can only block, never command.

---

## 8. The Empire — the command hierarchy

**Module:** `services/authority/empire.py`

The command hierarchy rests entirely on the primitives above (enhance, don't rewrite).

- **`Imperium`** — a holder of authority: `(imperium_id, rank, mask, pomerium, lease_id)`.
  `permits(required, path)` is the O(1) effective-mask check (axe stripped inside the pomerium for every
  rank). `delegate(...)` is **attenuation-only** — a Legatus receives `parent & requested`, so no legate
  can out-rank its appointer, and its effective mask is precomputed (a later check is one AND, not a walk
  up the chain).
- **`imperium_maius(...)`** — the root supervisor, holding every rod and axe (`IMPERIUM_MAIUS`).
- **`Dictator`** — an extraordinary imperium: a broad mask on a **short auto-expiring lease**. `is_in_command`
  is just `reaper.is_valid` — when the reaper collects the lease, the dictatorship simply ends (absolute
  power, but only until it expires). Carries a pre-named **MagisterEquitum**.
- **`hand_to_magister()`** — the **hot standby**: the MagisterEquitum assumes the *same* imperium (same
  mask, same lease), re-titled, with **no fresh grant ceremony** — command survives the principal falling.

The chain is: **Imperium Maius → Legati (attenuated) → the Legion workforce → Z-Workers / Auxilia.**

**[adoption pending]** refactoring the live services onto the `Imperium` base class, plus the *provocatio*
human-appeal pause and `citadel halt <imperium>` wiring (the primitives are built + tested; adoption is
incremental, as with prior phases).

---

## 9. The Auxilia — multi-model trust & citizenship

**Modules:** `services/authority/trust.py`, `auxilia.py`

The Auxilia are validators from a *different* model family — the ingredient that makes Intercessio's
dual-gate meaningful.

- **`GeminiFunditor(validate)`** — emits a `Gate(family="gemini", passed=…)` that composes directly with
  `dual_gate`. The judgement is injected, so it is exercised in tests and chaos drills without a live API
  and swapped for a real Gemini call in production without touching control-plane logic.
- **`TrustLedger(threshold)`** — generalizes the per-intent `LocalConfidence` into **per-component
  monotonic trust counters**:
  - a clean **rod-class** `PASS` extends a component's clean streak;
  - reaching the threshold makes it a **citizen** — trusted to gate rod-class work *solo* (the second gate
    is dropped for reversible acts only);
  - **axe-class is ALWAYS dual-gated**, regardless of trust (`requires_dual_gate(axe=True)` is always
    `True`) and axe verdicts never build trust;
  - a single **`CAPITAL`** revokes citizenship **permanently** — demote-instantly; trust is expensive to
    earn and cheap to lose (proven by the reward-hack chaos drill: 10 more `PASS` cannot buy it back).

---

## 10. Directives, gates & chaos drills

The design is verified against seven **directives** (invariants) and seven **gates** (acceptance checks).

| Directive | Statement | Enforced by |
|-----------|-----------|-------------|
| D1 | No power without a lease (TTL). | `lease.py`, `lex_curiata` |
| D3 | No cached read without content verification (JIT). | `citadel_oracle.is_fresh` |
| D4 | No single validator on an irreversible act. | `intercessio.dual_gate` |
| D5 | No O(N) on the hot path. | `degree_one`, O(1) `permitted` |
| D6 | No floating `:latest`; pin by digest. | `lex_curiata.validate_manifest` |

| Gate | Check | Status |
|------|-------|--------|
| G1 | Warm resolve < 1 ms | ✅ (10k warm lookups < 1 ms each) |
| G2 | Zero false positives | ✅ (exact set by construction) |
| G3 | JIT catches staleness 100% | ✅ (branch-switch storm) |
| G4 | No output enters context without a count preamble | ✅ (`guard_output`) |
| G5 | Every mutation carries a pre-image + verdict | ✅ (coding path) |
| G6 | No TTL-less / province-less / wildcard / `:latest` manifest ratifies | ✅ |
| G7 | No axe op with < 2 uncorrelated gates | ✅ |

**Chaos drills (all passing):** god-manifest rejected pre-signature; lease-overrun ladder reaps the
expired grant; reward-hack `CAPITAL` permanently revokes citizenship; tampered manifest not ratified;
Legatus cannot escalate beyond its parent; the pomerium strips the axe even from Maius.

---

## 11. The Ground — dot-dir contract & term-lint

**Modules:** `src/citadel/paths.py`, `tools/term_lint.py`, `commands/setup.py`

- **Dot-dir contract** — `ensure_dot_dir(path, *, strict=False)` **quarantines a squatting FILE** to
  `<name>.broken.<ts>` (the exact fix for "`.claude` is broken when clicked"), then probes a write/read
  round-trip. `is_unsafe_placement(path)` flags `/mnt/c` + OneDrive; enforcement is opt-in (`strict`) so
  the current OneDrive-hosted workspace still works while `doctor` *warns* about the risk.
- **Term-lint** — bans the dead brands `swarm`/`VIREN` outside `docs/history/` and `docs/citadel/`.
  Generated caches and the runtime `.claude/` instance are exempt (its settings embed absolute workspace
  paths that may incidentally contain the folder name). `LEGION` is intentionally *not* banned — see §15.
- **Doctor** — `citadel doctor` reports python deps, engine CLI, Ollama install/server/model, GPU, and the
  §11.2 placement check; `--repair` runs `ensure_dot_dir`.

---

## 12. CLI surface & operator flow

`citadel <command>` (from `src/citadel/cli.py`; the system self-identifies as **The Sovereign**):

| Command | Purpose |
|---------|---------|
| `init` | Initialize a workspace (full auto-learn); installs the `.claude` template. |
| `up` / `down` | Bring the Citadel online / offline (brain + daemons + UI, launch the session). |
| `do "<task>" [--file … --verify …]` | **Local-first** task execution (free Ollama → cloud escalation). |
| `run [--local-first]` | The Legion orchestrator run path. |
| `setup` / `doctor` | Auto-install everything / report what is installed / missing / how to fix. |
| `index` / `brain` / `mine` | Rebuild intelligence indexes / brain search index / git-history miner. |
| `workers` | Live daemon + subagent status. |
| `benchmark` | Deterministic best-practices score (SOLID/KISS/PEP8). |
| `replicate` / `companies` | Workspace replication / multi-province utilities. |

**Typical first run:** `uv tool install .` → `citadel setup` (installs Ollama + model + deps) →
`citadel init <ws>` → `citadel up`. Thereafter `citadel do "…"` does verified work locally for free,
escalating to the cloud only when it must.

---

## 13. State & data layout

```
<workspace>/
  .claude/                     runtime instance (settings, permissions) — generated, git-ignored
  citadel-home/.citadel/       state root (junction on Windows, symlink on POSIX)
    state/                      ledgers, pidfiles, local-confidence.jsonl
    verdicts.jsonl             the verdict ledger
    pre-images/<digest>        content-addressed mutation backups
  docs/brain/                  the graph brain (nodes: agents, workflows, tools, memory, rules, topics)
src/citadel/                   the package (services/, commands/, cli.py, paths.py)
src/citadel/assets/claude_template/   the shipped agnostic .claude template (~380 files, 61 agents)
tools/                         standalone tools (citadel_oracle.py, citadel_custos.py, term_lint.py, …)
tests/                         the suite
```

State is content-addressed where it matters (pre-images, compile cache), append-only JSONL where it is a
log (verdicts, confidence), and never holds secrets (redaction runs before anything is written).

---

## 14. Testing & verification

- **Command:** `$env:PYTHONPATH='src'; python -m pytest -q -n auto --dist loadscope`
  (pytest-xdist parallel; a `serial` marker exists for the few order-sensitive tests).
- **Current:** **659 passed, 3 skipped** (skips are platform-gated: AF_UNIX socket, `grep`, a statusline
  template asset not in this checkout). Live Ollama tests run when a server + model are present and skip
  otherwise.
- **Full-codebase smoke:** `tests/test_codebase_smoke.py` `py_compile`s every `tools/` + `src/` file and
  imports every `citadel` module — so a crash anywhere in the tree is caught, not just in tested paths.
- The control plane has dedicated suites: `test_authority`, `test_law`, `test_trust`, `test_empire`,
  `test_verdict`, `test_citadel_oracle`, `test_citadel_custos`, `test_dot_dir_contract`, `test_term_lint`.

---

## 15. Naming, taxonomy & the Legion

The system is **The Sovereign Imperia Citadel**. The command hierarchy is Roman:
**Imperium Maius → Legati → the Legion → Z-Workers / Auxilia**, governed by the Law (fasces, pomerium,
leases, Intercessio, Tribune, Lex Curiata).

The internal `legion_*` modules (`legion_orchestrator.py`, etc.) are **kept by deliberate decision** — a
*Legion* is the Roman army a commander directs, so the term is thematically correct and sits naturally
below the Empire hierarchy. A full `legion_* → Imperia` file rename was evaluated and **declined**: it is
~180 files of hard-to-reverse churn for zero functional gain, and would break the build the instant the
lint flipped. Term-lint therefore bans only the *dead* brands `swarm`/`VIREN`; `LEGION` remains a valid
internal term. (If a rename is ever wanted it is a clean isolated pass + a one-line lint change.)

To the operator, the system always speaks as **The Sovereign** — the underlying models (Claude, Ollama,
Gemini) are internal implementation detail, never surfaced in the voice.

---

## 16. Roadmap status

The Master-Plan roadmap ran as seven resumable phases; **all are complete**:

| Phase | Name | Delivered |
|-------|------|-----------|
| 0 | The Purge & the Ground | dot-dir contract, term-lint, doctor |
| 1 | The Read Spine | membership oracle, JIT hash, degree-1 (G1–G3) |
| 2 | The Shields | count-first / splice / redact (G4) |
| 3 | The Blades | verdict ledger + condemned set + pre-image (G5) |
| 4 | The Law | fasces, pomerium, leases, Lex Curiata, Intercessio, Tribune (G6, G7) |
| 5 | The Auxilia | trust/citizenship + GeminiFunditor uncorrelated gate |
| 6 | The Empire | Imperium/Legati/Dictator/MagisterEquitum command hierarchy |

**Remaining work is adoption, not design:** wiring the built-and-tested primitives (JIT freshness on every
serve path, the `Imperium` base class under the live services, *provocatio* + `citadel halt`, a real Gemini
validator, TrustLedger on the live verdict path) into every runtime call path — the same
"primitives-first, adoption-incremental" pattern used throughout. The architecture described above is
whole and verified.

---

*The Sovereign Imperia Citadel — designed to do the work for free, prove it before it trusts it, and never
wield the axe without the Republic's consent.*
