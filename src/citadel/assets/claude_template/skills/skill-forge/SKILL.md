---
name: skill-forge
description: Create a new Claude Code skill for Citadel Legion with correct structure, frontmatter, and best practices. Use when asked to build a skill, add a /command, or extend the system with a new capability.
argument-hint: [skill-name] [purpose]
arguments: [name, purpose]
context: fork
agent: Explore
---

Create a new skill at `.claude/skills/$name/` for this purpose: $purpose

## Step 1 — Discover existing patterns
Read 3–4 existing skills from `.claude/skills/*/SKILL.md` to understand project conventions before writing anything.

## Step 2 — Choose frontmatter
Pick the correct frontmatter for this skill type:

| Purpose | Frontmatter to add |
|---------|-------------------|
| Knowledge/reference only | `user-invocable: false` |
| User-only task (has side effects) | `disable-model-invocation: true` |
| Deep research in isolation | `context: fork` + `agent: Explore` |
| Needs shell tool grants | `allowed-tools: Bash(...)` |
| Background loop, no questions | `disallowed-tools: AskUserQuestion` |
| Python-file-specific | `paths: ["**/*.py"]` |
| Needs model override | `model: opus` |
| Needs effort override | `effort: high` |

Always add `description:` — this is how Claude decides when to auto-load the skill.
Add `when_to_use:` for additional trigger keywords beyond the description.
Add `argument-hint:` to show users what arguments the skill expects.

## Step 3 — Create the skill
Create `.claude/skills/$name/SKILL.md`:
```yaml
---
name: $name
description: <what it does and when Claude should use it — key use case first>
# add relevant frontmatter fields from Step 2
---
```

Follow with concise instructions. Keep SKILL.md under 500 lines. If large reference material is needed, put it in a sibling file and link to it from SKILL.md. If a supporting script is needed, create `.claude/skills/$name/scripts/<file>` and reference it with `${CLAUDE_SKILL_DIR}/scripts/<file>`.

## Step 4 — Report
Output:
- Skill path created
- Frontmatter fields chosen and why
- Trigger phrase that will auto-activate it
- How to invoke it directly (`/$name`)
