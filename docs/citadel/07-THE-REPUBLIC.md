# 07 — The Republic

A brain-centered, Imperia + Senate governance layer over the Citadel. Every model (local Ollama, Groq,
NVIDIA, Claude) connects to one shared **graph brain** to learn and to read all services/logic/files;
governance is an **Imperium per model-family** under a formal **Senate**. Everything is decoupled behind
interfaces and O(1)/sublinear on the hot path, with a pure-Python/in-memory fallback for every component.

Code lives under `src/citadel/services/{brain,imperium,senate,consensus}/`. Tests:
`tests/test_{identity,brain_bus,brain_access,learning,brain_injection,imperium,senate,scu}.py`.

## Systems

| # | System | Module | Core patterns | Hot-path cost |
|---|---|---|---|---|
| 0 | **Brain** (nervous system) | `brain/access.py`, `brain/bus.py` | Facade · Repository · CQRS · Event Sourcing · Content-Addressed Storage | prune **O(1)** → HNSW **O(log N)** → graph **O(1)** |
| 1 | **Identity & not-self** | `consensus/identity.py` | Value Object · Specification | O(k) distinct-witness set |
| 2 | **Imperia** (per family) | `imperium/registry.py`, `imperium/rails.py` | Registry · Composite · Capability-security · Chain of Responsibility | rails **O(L)**, fasces **O(1)** |
| 3 | **Learning ledger** | `brain/learning.py` | Event Sourcing · CQRS · CRDT-idempotent | MinHash+LSH recall **O(1)** |
| 4 | **Brain-for-all** | `brain/injection.py` | Facade · Strategy · Decorator (redaction) · Adapter | cascade + greedy pack |
| 5 | **Senate** | `senate/*.py` | State Machine · Observer · leader-lease · Circuit Breaker · Bulkhead | O(1) keyed consulta |
| 6 | **Decoupling fabric** | `brain/bus.py`, `senate/scu.py` | Pub/Sub · consumer groups · DLQ · idempotent consumers | O(1) |

## The one correctness rule (System 1)

Validation keys on **model identity = (vendor, family, model_id, effort)**, not vendor family. A model may
**not** validate its exact self, but a *different configuration of the same family is a valid independent
validator*: `opus-4.8-low` validates `opus-4.8-medium`; `sonnet-5` validates `sonnet-4.6`; `haiku` validates
`sonnet` — but nothing validates its exact self. A candidate/promotion needs a **distinct-witness quorum**:
≥N validators whose identities are pairwise distinct and ≠ the author's. Enforced in
`ConsensusEngine._aggregate`, `authority.intercessio.dual_gate`, and every `CursusHonorum` rung.

## Learning loop (System 3)

Every executor, wrapped by `LearningExecutor`, **recalls before generating** (prior lessons for similar
tasks injected as context) and **records after** (pass/fail folds into a per-signature EWMA success-rate; a
failure leaves a content-addressed, deduped lesson). Recall is fuzzy + O(1): the intent's normalized token
set → **MinHash** signature → **LSH bands**, so *similar* intents recall each other's lessons without a scan.
Stale lessons retire lazily (time-decay TTL).

## Brain-for-all (System 4)

`attach_brain(member, brain, store=…)` composes redacted context injection + the learning decorator onto any
`Executor`. The boundary is a Strategy: **local** members get the full capsule; **cloud** members get it
through a redaction Decorator — secrets masked (`sk-…`/`ghp_…`/bearer/private-key/`KEY=value`) and any chunk
referencing sensitive material (`.env`, private keys, `**/private/**`, `[PRIVATE]`) **dropped entirely**.

## The Senate (System 5) — weak spots → fixes

| Roman weak spot | Systemic risk | Fix |
|---|---|---|
| Princeps speaks first (single priority) | bias / SPOF | `Princeps` sets baseline only; motions need a distinct-identity **quorum** |
| Lifetime seats never expire | stale knowledge | **JIT decay** — a Consultum whose sources fail `is_fresh` is demoted on read (`senate/decay.py`) |
| Consuls unchecked | runaway authority | **lease + fencing token (fasces)** + Tribune veto + Intercessio dual-gate |
| SCU = unrestricted | catastrophic misuse | **Circuit Breaker → Dictator on an auto-expiring TTL lease** + sacrosanct allowlist + audit (bulkheaded) |
| Cursus self-promotion | model rubber-stamps itself | **not-self distinct-identity quorum** mandatory at every rung |
| Aerarium unbounded spend | credit exhaustion | **token-bucket** caps + refill (`senate/aerarium.py`) |
| Foreign envoys trusted | exfiltration / injection | egress allowlist + **redaction-before-send** + deny-list (`senate/foreign.py`) |
| Absolute laws crash downstream | brittle global rules | Consulta are **weighted configs**, reconciled + **appealable (provocatio)**, not hard laws |

## Cursus Honorum (promotion)

`proposed → quaestor → aedile → praetor → consul`. Each rung is a gate needing a deterministic check **and**
a not-self distinct-identity quorum. Reaching **consul** enacts a **Senatus Consultum** — a content-addressed,
versioned, weighted config broadcast on the bus (repeal = tombstone; appeal = provocatio).

## SCU (emergency)

`SenatusConsultumUltimum` trips only after **systemic** failure (a `CircuitBreaker` threshold), appoints a
`Dictator` on a **short TTL lease** (the reaper auto-expires it), pre-names a `MagisterEquitum` standby, and
**never condemns a Tribune-sacrosanct process** (bulkhead). Every declaration/condemnation/stand-down is
audited.

## Operating

- `citadel senate` — read-only status (systems 0-6, brain/learning/bus backends).
- `citadel consensus <task>` — multi-model consensus under the not-self identity rule.
- Redis present → hot tier (Streams bus, RediSearch HNSW, O(1) hashes); absent → in-memory fallback, same
  contract.

## Chaos drill (verification)

1. **SCU** — feed `threshold` failures; assert `should_declare()`, `declare()` grants a Dictator, and it
   `is_active()` == False past the TTL (auto-expiry). Confirm a sacrosanct PID survives `may_condemn`.
2. **DLQ** — publish a poison event; `fail()` it `max_deliveries` times; assert it lands on `<topic>:dlq`
   and the group drains (no head-of-line block).
3. **JIT decay** — enact a Consultum with sources; flip `is_fresh`→False; `sweep()` demotes it.
4. **Not-self** — a proposal whose only validators are its exact self never leaves `proposed`.

All four are covered by the P5/P6 test suites; every path degrades gracefully without Redis/keys/Ollama.
