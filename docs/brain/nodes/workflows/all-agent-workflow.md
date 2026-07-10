---
id: all-agent-workflow
title: All Agent Workflow
type: workflow
tags: [agents, workflow]
links: [ultra-cheap-verification, agent-budget-controller, efficiency-auditor]
files:
  - CLAUDE.md

---

# All Agent Workflow

All agents are **considered**; only a relevant allowlist is **invoked** (budget mode); unrelated agents are **skipped** with a reason. Default ≤5 invoked for docs/graph routing, hard ≤8 for all other tasks.
