---
id: topic:claude-code-skills
title: Claude Code Skills
type: topic
tags: [topic, skill, slash-command, context-fork, dynamic-injection, frontmatter, allowed-tools, user-invocable, disable-model-invocation]
links:
  - skill-forge
  - documentation-ingestion
  - citadel-knowledge
files:
  - .claude/skills/
  - .claude/skills/skill-forge/SKILL.md
  - .claude/skills/workspace-visualize/SKILL.md
  - .claude/skills/legion-health/SKILL.md
  - .claude/skills/context-research/SKILL.md
  - .claude/skills/citadel-knowledge/SKILL.md
  - .claude/skills/settings-reference/SKILL.md
  - .claude/skills/pr-review-live/SKILL.md
  - .claude/skills/session-logger/SKILL.md
---

# Claude Code Skills

Skills extend Claude with custom /commands and auto-loaded knowledge. Each skill is a directory with `SKILL.md` as entrypoint plus optional supporting files.

When to use: skill, SKILL.md, slash command, /name, create skill, fork context, dynamic injection, allowed-tools, user-invocable, disable-model-invocation, skill frontmatter.

## Key frontmatter capabilities

| Field | Effect |
|-------|--------|
| `context: fork` + `agent:` | Run in isolated subagent |
| `` !`cmd` `` | Inject live shell output before Claude reads skill |
| `allowed-tools:` | Pre-approve tools without per-use prompts |
| `disallowed-tools:` | Remove tools while skill is active |
| `disable-model-invocation: true` | User-only invocation (side effects) |
| `user-invocable: false` | Background knowledge, Claude-only |
| `${CLAUDE_SKILL_DIR}` | Path to skill's own directory |
| `${CLAUDE_SESSION_ID}` | Current session ID |
| `${CLAUDE_EFFORT}` | Active effort level |
| `model:` / `effort:` | Override for this skill's turn |
| `paths:` | Only activate for matching file paths |
| `arguments:` | Named positional arguments ($name) |

## Skill locations
- Personal: `~/.claude/skills/<name>/SKILL.md`
- Project: `.claude/skills/<name>/SKILL.md`

## Citadel Legion skills added
skill-forge, workspace-visualize, legion-health, context-research, citadel-knowledge, settings-reference, pr-review-live, session-logger
