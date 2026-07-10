---
id: distributed-brain-workflow
title: Distributed Brain Workflow
type: workflow
tags: [distributed, scheduler, agents, tokens]
links: [brain-scheduler, task-queue-manager, worker-dispatcher, workload-balancer, context-router, worker-result-reducer, efficiency-auditor]
files:
  - CLAUDE.md
  - .claude/rules/distributed-brain-architecture.md

---

# Distributed Brain Workflow

Scheduler -> queue -> dispatcher -> workers -> reducer -> auditor. All agents considered; only the relevant allowlist is invoked; unrelated agents are skipped (not run micro).
