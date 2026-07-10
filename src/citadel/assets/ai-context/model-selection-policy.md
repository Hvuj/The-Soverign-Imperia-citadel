# Model Selection Policy

Last updated: auto (updated by effort-decider after outcome review)

## Core rule: Haiku first

Default to **Haiku + low effort** for every task. Escalate only when:
- A specific task type listed below requires Sonnet
- Past outcomes show Haiku failed for this task type (see model-effort-outcomes.md)
- Complexity signals are present (see below)

## Model tiers

| Tier | Model | Effort | Cost index | Use when |
|------|-------|--------|-----------|----------|
| cheap | claude-haiku-4-5-20251001 | low | 1× | Routing, auditing, classification, trivial tasks |
| standard | claude-sonnet-4-6 | medium | 8× | Multi-file code, complex reasoning, domain expertise |
| strong-planning | claude-sonnet-4-6 | high | 15× | Architecture, complex domain logic, production-risk changes |
| ultracode | claude-opus-4-8 | max | 60× | Only on explicit /effort ultracode by user |

## Task → model defaults

```
question             → haiku / low
terminal_help        → haiku / low
docstring_only       → haiku / low
validation_only      → haiku / low
docs_ingestion       → haiku / low
test_creation        → haiku / medium
data_contract        → haiku / medium
graph_brain_tooling  → haiku / medium
feature_change       → sonnet / medium
bug_fix              → sonnet / medium
refactor             → sonnet / medium
debugging            → sonnet / high
```

> Task-type routing is workspace-agnostic. Framework/domain-specific task types (e.g. a data
> orchestration or query domain) are added by the domain-adapter layer once a workspace is learned,
> not hardcoded here. See the Citadel agnostic audit.

## Haiku-eligible agents (always run on Haiku regardless of task tier)

These agents do routing, auditing, classification — never need deep reasoning:
- agent-budget-controller, brain-router, brain-search-router
- cache-key-guardian, cache-performance-auditor
- context-preservation-agent, directory-access-sentinel, directory-change-detector
- efficiency-auditor, effort-decider, gitignore-safety-reviewer
- memory-optimizer, pattern-reuse-router, prompt-classifier-agent
- reuse-fast-path-agent, scope-guard, scope-guard-agent
- state-ledger, task-queue-manager, telemetry-auditor
- token-efficiency-auditor, worker-result-reducer, workload-balancer

## Sonnet-minimum agents (keep on Sonnet even for cheap tasks)

These agents need domain expertise or complex reasoning:
- domain-logic-validator, domain-doc-curator, semantics-reviewer
- performance-reviewer, distributed-compute-specialist, orchestration-specialist
- brain-scheduler, brain-daemon-agent, context-capsule-builder
- data-contract-validator, feature-implementation-learner
- graph-brain-indexer, graph-dependency-mapper, graph-maintainer
- implementation-cache-indexer, import-dependency-agent
- legion-commander, memory-curator, dataframe-specialist
- python-specialist, query-specialist, task-planner
- test-validation-runner

## Complexity escalation signals

Upgrade effort level by 1 when any of these are true:
- >3 files changed in this task
- Change touches shared infrastructure or public API
- Tests are failing or have been retried ≥2 times

Upgrade model tier by 1 when:
- Production risk, data loss, or irreversible operation
- Learned domain-metric / business-rule logic involved
- Haiku returned a known-bad pattern (see outcomes log)

## Learning

This policy is updated automatically when:
1. `effort-decider` observes a task outcome different from the prediction
2. A pattern repeats ≥3 times in `model-effort-outcomes.md`
3. User explicitly corrects the model choice

See `model-effort-outcomes.md` for the running outcome log.
