---
name: settings-reference
description: Claude Code settings.json reference for permissions, sandbox, plugins, skill visibility, and configuration options. Claude loads automatically when asked about settings, permissions, configuration, or hooks.
user-invocable: false
when_to_use: settings, permissions, deny, allow, sandbox, hooks, plugin, skillOverrides, env, defaultMode, availableModels, companyAnnouncements, footerLinksRegexes, configuration, managed settings, disableBundledSkills
---

# Claude Code Settings Reference

## Settings precedence (highest → lowest)
1. **Managed** (MDM / server / file) — cannot be overridden by any lower scope
2. **CLI flags** / `--settings <file>`
3. **Local project** `.claude/settings.local.json`
4. **Shared project** `.claude/settings.json`
5. **User** `~/.claude/settings.json`

Array settings **merge** across scopes (exception: `fallbackModel` and `availableModels` do not merge).

## Key settings

| Key | Effect |
|-----|--------|
| `permissions.allow/ask/deny` | Tool permission rules |
| `permissions.defaultMode` | `default` / `acceptEdits` / `plan` / `auto` / `bypassPermissions` |
| `env` | Environment variables injected every session |
| `model` | Default model override |
| `effortLevel` | Persist effort: `low` / `medium` / `high` / `xhigh` |
| `availableModels` | Restrict which models users can select |
| `skillOverrides` | Per-skill: `on` / `name-only` / `user-invocable-only` / `off` |
| `disableBundledSkills` | Remove bundled skills (code-review, debug, loop, etc.) |
| `disableSkillShellExecution` | Block `!`cmd`` in skills from user/project sources |
| `autoCompactEnabled` | Auto-compact when context approaches limit |
| `sandbox.enabled` | Isolate bash from filesystem and network |
| `sandbox.network.allowedDomains` | Network allowlist for sandboxed commands |
| `hooks` | Lifecycle automation (PreToolCall, PostToolCall, Stop, etc.) |
| `companyAnnouncements` | Startup messages shown to all users |
| `footerLinksRegexes` | Turn IDs in output into clickable footer badges |
| `strictPluginOnlyCustomization` | Lock skills/agents/hooks/mcp to plugin sources only |
| `agent` | Run main thread as a named subagent |

## Permission rule syntax
```
Bash(npm run *)           # prefix match on command
Read(./.env)              # exact file path
WebFetch(domain:*.com)    # domain wildcard
Skill(deploy *)           # skill name prefix
mcp__github__get_*        # MCP tool glob
```
Deny rules are checked first, then ask, then allow. First match wins.

## Skill visibility (`skillOverrides`)
```json
{
  "skillOverrides": {
    "legacy-context": "name-only",
    "deploy": "off"
  }
}
```
`on` → full description in context; `name-only` → name only (saves budget); `user-invocable-only` → hidden from Claude; `off` → hidden everywhere.

## Sandbox example
```json
{
  "sandbox": {
    "enabled": true,
    "filesystem": { "allowWrite": ["/tmp/build", "~/.kube"] },
    "network": { "allowedDomains": ["github.com", "*.npmjs.org"] }
  }
}
```
