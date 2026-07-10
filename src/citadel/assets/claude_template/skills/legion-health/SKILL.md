---
name: legion-health
description: Show Citadel Legion system health: agent count, skill count, memory file count, brain node count, and recent git activity. Use when checking system status, diagnosing issues, getting an overview before starting work, or after a restart.
when_to_use: legion status, system health, how many agents, how many skills, brain status, memory status, system overview, citadel status
---

## System snapshot
```!
echo "=== Agents ===" && ls .claude/agents/*.md 2>/dev/null | wc -l | xargs -I{} echo "  {} agent files" && \
echo "=== Skills ===" && ls -d .claude/skills/*/ 2>/dev/null | wc -l | xargs -I{} echo "  {} skill dirs" && \
echo "=== Memory ===" && ls docs/ai-context/*.md 2>/dev/null | wc -l | xargs -I{} echo "  {} memory files" && \
echo "=== Brain nodes ===" && find docs/brain/nodes -name "*.md" 2>/dev/null | wc -l | xargs -I{} echo "  {} nodes" && \
echo "=== Hooks ===" && ls .claude/hooks/*.sh 2>/dev/null | wc -l | xargs -I{} echo "  {} hook scripts" && \
echo "=== Artifacts ===" && ls .claude/state/artifacts/current/*.md 2>/dev/null | wc -l | xargs -I{} echo "  {} current artifacts" && \
echo "=== Recent git ===" && git log --oneline -5 2>/dev/null || echo "  (no git history)"
```

## Task
Summarize the system health above in a compact table. Flag anomalies (zero counts where content is expected, missing files). If healthy, say so. If issues found, recommend the next action.
