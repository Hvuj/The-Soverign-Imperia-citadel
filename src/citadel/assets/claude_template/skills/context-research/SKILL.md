---
name: context-research
description: Deep codebase research in an isolated read-only context. Use for thorough exploration of unfamiliar code, mapping how a feature works end-to-end, or understanding dependency chains before starting implementation.
context: fork
agent: Explore
when_to_use: research, explore, how does X work, trace, dependency, map feature, understand code, deep dive
argument-hint: [topic or question]
---

Research the following thoroughly: $ARGUMENTS

## Instructions

1. Use Glob to find relevant files by pattern.
2. Use Grep to locate definitions, usages, and references across the codebase.
3. Read the most relevant files — prioritize entry points, core logic, and tests.
4. Trace one dependency hop where it reveals important context.
5. Return a structured report:

**Key files** — path and one-line role for each  
**How it works** — data flow or call chain, 3–6 steps  
**Edge cases and gotchas** — surprising behavior, implicit invariants  
**Starting points for changes** — which file to edit first and why
