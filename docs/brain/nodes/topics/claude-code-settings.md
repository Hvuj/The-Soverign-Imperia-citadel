---
id: topic:claude-code-settings
title: Claude Code Settings
type: topic
tags: [topic, settings, permissions, sandbox, hooks, plugins, configuration, skillOverrides, managed-settings]
links:
  - settings-reference
  - citadel-knowledge
files:
  - .claude/settings.json
  - .claude/settings.local.json
---

# Claude Code Settings

settings.json controls permissions, environment, model, effort, skill visibility, sandbox, hooks, and plugins.

When to use: settings, permissions, deny, allow, sandbox, hooks, plugin, configuration, skillOverrides, managed settings, disableBundledSkills, availableModels.

## Precedence (high → low)
Managed → CLI flags → local project → shared project → user

Array settings merge across scopes (exceptions: `fallbackModel`, `availableModels`).

## Critical settings

| Key | Purpose |
|-----|---------|
| `permissions.allow/ask/deny` | Tool permission rules |
| `permissions.defaultMode` | default/acceptEdits/plan/auto/bypassPermissions |
| `env` | Injected environment variables |
| `model` / `effortLevel` | Default model and effort |
| `availableModels` | Restrict model selection |
| `skillOverrides` | on/name-only/user-invocable-only/off per skill |
| `disableBundledSkills` | Remove bundled skills |
| `sandbox.enabled` | Filesystem/network isolation for bash |
| `hooks` | Lifecycle automation |
| `companyAnnouncements` | Startup messages |
| `footerLinksRegexes` | ID → clickable footer badges |
| `strictPluginOnlyCustomization` | Lock skills/agents/hooks/mcp to plugins |

## Permission rule syntax
```
Bash(npm run *)     # prefix match
Read(./.env)        # exact file
WebFetch(domain:*)  # domain wildcard
Skill(deploy *)     # skill prefix
```
Deny first, then ask, then allow. First match wins.
