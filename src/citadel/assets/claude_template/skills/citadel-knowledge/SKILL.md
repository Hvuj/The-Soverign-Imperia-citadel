---
name: citadel-knowledge
description: Background knowledge about Citadel Legion architecture, agents, memory, brain, skills, and hooks. Claude loads automatically when working on the orchestration system itself.
user-invocable: false
when_to_use: citadel, legion, brain, agent, memory, skill, hook, workflow, up, graph, capsule, preflight, audit-gate, orchestration
---

# Citadel Legion — Architecture Reference

**Purpose:** AI orchestration layer on top of Claude Code. Coordinates agents, brain graph, memory, skills, and hooks into a managed workflow system.

## Core components

| Component | Location | Purpose |
|-----------|----------|---------|
| Brain graph | `docs/brain/` | Routing index; nodes describe topics, agents, files |
| Agents | `.claude/agents/*.md` | Specialized subagents invoked by name |
| Skills | `.claude/skills/*/SKILL.md` | Slash commands and auto-loaded capabilities |
| Memory | `docs/ai-context/` | Durable context across sessions |
| Hooks | `.claude/hooks/` | Lifecycle automation |
| State | `.claude/state/` | Artifacts, sessions, human-intervention queue |

## Memory files
- `active-memory.md` — current goals and in-progress work
- `what-worked.md` — validated patterns
- `what-did-not-work.md` — known pitfalls
- `feature-implementation-patterns.md` — reusable shortcuts

## Brain query
```bash
python tools/brain_query.py "<topic>" --limit 3
```

## Start/stop
```bash
citadel up            # start
citadel down                 # stop
citadel up --restart  # clean restart
```
Never invoke `claude` directly — bypasses preflight and daemon.

## Audit gate (stop hook)
Every session stop runs `.claude/hooks/audit-gate.sh`. Requires:
- `.claude/state/artifacts/current/file-map.md`
- `.claude/state/artifacts/current/feature-contract.md`
- Required agents from execution manifest

## Agent ledger pattern
task-planner → token-efficiency-auditor → effort-decider → domain agents → efficiency-auditor (last).
Domain-logic gate: only invoke domain-logic-validator / query-specialist when prompt explicitly touches workspace-specific domain logic or queries.
