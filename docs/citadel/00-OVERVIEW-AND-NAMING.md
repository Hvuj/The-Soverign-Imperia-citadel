# The Sovereign Imperia Citadel â€” Overview & Naming

> **This is the authoritative, forward-looking, workspace-agnostic build documentation.**
> The system is being rebuilt from a clean slate: all mined commits, learned features, learned
> topics, business-intelligence logic, and every trace of prior workspaces/repos have been removed
> (see [03-CLEAN-SLATE-LOG.md](03-CLEAN-SLATE-LOG.md)). The former name "The Sovereign Imperia Citadel" is retired.
>
> The prior technical as-built map lives in [`../system-map/`](../system-map/00-INDEX.md) and is kept
> only as a **legacy engineering reference** (it documents the pre-cleanup system, including what was
> removed and why). Where the two disagree, **this directory wins**.

---

## 1. What it is

**The Sovereign Imperia Citadel** is a workspace-agnostic operating layer that wraps Claude Code and
turns it from a stateless assistant into a persistent, self-governing, self-improving engineering brain
for an entire workspace. It installs once as a CLI, is pointed at any git workspace, and from then on
every session runs inside the Citadel's brain, daemons, governance, and safety gates.

Its single design law is unchanged and is the reason it exists:

```
Spend model tokens ONLY on genuine ambiguity.
Everything answerable from an index, ledger, cache, or deterministic analyzer
is answered that way â€” for zero tokens.
```

Everything below is a naming and architecture map. The Citadel is **not** a rewrite from nothing â€” it
keeps the genuinely strong substrate (AST code indexes, the compiled-fact cache, the RAM cache, the
hook pipeline, the local-first Q&A, the replication engine) and rebuilds the parts that were theater,
hollow, non-portable, or workspace-specific ([04-BUILD-MAP.md](04-BUILD-MAP.md)).

## 2. The naming model (replaces "Citadel / corporate / companies / board")

The old vocabulary was inconsistent ("Citadel", "corporate", "companies", "megacorp", "board of
directors"). The Citadel uses one coherent imperial metaphor, top to bottom:

| Old term | New term | Meaning |
|---|---|---|
| The Sovereign Imperia Citadel / "the corporate" | **The Sovereign Imperia Citadel** (or **the Citadel**) | The whole system â€” the sovereign city-state that governs the workspace |
| The operator / user | **The Sovereign** | The human authority the Citadel answers to |
| Board of 3 Directors | **The Senate** | Deterministic governance body; senators arbitrate precedence and hold veto power |
| Principle "companies" (KISS/YAGNI/â€¦) | **Orders** (of the Legion) | The 8 deterministic principle analyzers â€” disciplined orders that score every change |
| Workspace repos ("companies") | **Provinces** (the Imperia) | The territories the Citadel maps, mines, and governs â€” one per repo |
| The legion (single interactive Claude) / `run` workers | **The LEGION** | The executing force. It is **not** the whole system â€” it is the Citadel's workforce |
| `zombie_worker` / deterministic workers | **workers** (Zero-token legionnaires) | The default force: pure-Python, zero-token workers that do all deterministic work |
| model workers (`claude -p`) | **Legionnaires** | T2 model workers, summoned only for genuine ambiguity |
| megacorp master loop | **The Citadel Loop** | The continuous self-improvement cycle, wired into the live session |

> **The LEGION is not the Citadel.** The Citadel is the sovereign whole (brain + Senate + Legion +
> the Sovereign's interface). The LEGION is specifically its **workforce** â€” the workers (zero-token,
> default) and the Legionnaires (model-backed, exception). This resolves the old ambiguity where
> "legion" meant both the whole system and its workers.

## 3. How it works (target architecture)

```
                          THE SOVEREIGN (the human)
                                   â”‚  speaks to
                                   â–¼
                        THE CITADEL â€” interactive front-door
                    ("hey citadel" â†’ answered at zero tokens; Â§see 04 Â§Terminal)
                                   â”‚
        â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
        â–¼                          â–¼                           â–¼
   THE SENATE               THE LEGION                    THE BRAIN
  (governance, T0)     (the workforce)                 (memory + indexes)
  Â· Orders score       Â· workerS (T0, default):       Â· agnostic graph
    every change         index, mine, compile,           Â· O(1) code indexes
  Â· Senate arbitrates    replicate, codemod,             Â· compiled-fact cache
    (reads its config)   benchmark, answer trivia         Â· RAM cache
  Â· tier decision:     Â· LEGIONNAIRES (T2, exception):    Â· learned patterns
    T0 / T1 / T2         summoned only for ambiguity        (regenerated per
  Â· veto power           a worker cannot resolve          province)
        â”‚                          â”‚                           â”‚
        â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                   â”‚
                          THE CITADEL LOOP
        (every cycle: outcomes â†’ patterns â†’ codemods â†’ skills â†’ brain,
         so the Citadel is cheaper and safer the next time)
```

**Execution tiers (unchanged in spirit, renamed for clarity):**

| Tier | Cost | Who | For |
|---|---|---|---|
| **T0** | zero tokens | workers + the Senate's Orders | facts, lookups, scoring, replication, codemods, trivia |
| **T1** | local compute | optional local model backend | scoring/classification/drafting when a local model exists |
| **T2** | model tokens | Legionnaires (Claude) | genuine ambiguity, novel code, judgment |

The whole point of the rebuild is to push work **down** to T0 and make that the enforced default, not
an advisory preference ([04-BUILD-MAP.md](04-BUILD-MAP.md) Â§Zero-token enforcement).

## 4. What "self-*" must mean (the four goals, made concrete)

The Sovereign's requirement is a system that is genuinely self-learning, self-improving, self-aware,
and self-sustaining. Today only the first is real. [04-BUILD-MAP.md](04-BUILD-MAP.md) Â§Self-* gaps maps
every place each is missing. In brief:

- **Self-learning** â€” accumulates proven patterns, outcomes, and reuse templates, read back into future
  turns. *Mostly real; the loops are wired.*
- **Self-improving** â€” turns a repeat problem into a permanent zero-token fix (codemod promotion) and
  synthesizes new skills. *Built but disconnected from the live loop â€” the biggest gap.*
- **Self-aware** â€” maintains an accurate model of its own health, token spend/savings, and governance
  state, and can explain it at any moment for zero tokens. *Substrate exists; not surfaced or honest
  (health defaults to "healthy" on corruption).*
- **Self-sustaining** â€” runs, heals, and stays workspace-agnostic and portable across OSes without
  hand-holding. *Partially â€” several core paths break on Windows and several configs are dead.*

## 5. Document set (read in order)

| # | File | Covers |
|---|---|---|
| 00 | [00-OVERVIEW-AND-NAMING.md](00-OVERVIEW-AND-NAMING.md) | This â€” identity, naming, target architecture |
| 01 | [01-GROUND-TRUTH-AND-DISCREPANCIES.md](01-GROUND-TRUTH-AND-DISCREPANCIES.md) | Real, measured numbers; every doc discrepancy reconciled |
| 02 | [02-AGNOSTIC-AUDIT.md](02-AGNOSTIC-AUDIT.md) | Every non-agnostic piece of logic in code (file:line) + the BI/domain removal map |
| 03 | [03-CLEAN-SLATE-LOG.md](03-CLEAN-SLATE-LOG.md) | Exactly what data was removed, what remains, verification |
| 04 | [04-BUILD-MAP.md](04-BUILD-MAP.md) | Works / doesn't-work / bugs / weak spots / redundancy / improvements + self-* gaps + roadmap |
| 05 | [05-PACKAGING-AND-INSTALL.md](05-PACKAGING-AND-INSTALL.md) | Hatch-managed version + wheel + install design |
| 06 | [06-BI-AUTOLEARN.md](06-BI-AUTOLEARN.md) | The BI Cartographer â€” agnostic, auto-connected, generative BI auto-learning (design) |

**Legacy:** [`../system-map/`](../system-map/00-INDEX.md) â€” pre-cleanup as-built technical reference (17
chapters). Useful for deep per-file detail; superseded by this directory for anything forward-looking.

## Execution status (what has actually been done vs designed)

| Change | State |
|---|---|
| Data clean-slate (commits/features/repos/acme/BI-data/learned nodes removed; memory reset) | **EXECUTED** â€” [03](03-CLEAN-SLATE-LOG.md) |
| BI **code** removal (bi tools, orchestrator BI mode, `bi` CLI, BI tests) | **EXECUTED** â€” verified against test baseline (192 passed, no new failures) |
| **Rename** everything `citadel`â†’`citadel` (package, CLI, env vars, `.citadel/` dir, tool files, branding) | **EXECUTED** â€” package `citadel`, CLI `citadel`, dist `sovereign-imperia-citadel`; verified at baseline |
| Hatch-managed dynamic version | **EXECUTED** â€” [05](05-PACKAGING-AND-INSTALL.md) |
| Agnostic-audit code fixes (domain vocabulary in `_workspace_intel_common` etc.) | **MAPPED** â€” [02](02-AGNOSTIC-AUDIT.md) Â§A |
| BI Cartographer (generative auto-learn) | **DESIGNED** â€” [06](06-BI-AUTOLEARN.md), ready to build |
| Bug fixes, self-* wiring, terminal front-door, packaging template fix | **MAPPED** â€” [04](04-BUILD-MAP.md) |

> Env var is now `CITADEL_WORKSPACE`, state dir `.citadel/`, home dir `citadel-home`. Tests run with
> `PYTHONPATH=src` importing the `citadel` package. The transplanted `.venv` (macOS layout) is unusable
> on Windows and is not the test path.
