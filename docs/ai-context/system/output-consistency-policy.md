# Output Consistency Policy

All Citadel API and AI outputs must be schema-valid, normalized, and consistently structured.

## Schema registry

16 JSON schemas in `.claude/schemas/`:

| Schema | Used by |
|---|---|
| ask-response.schema.json | /api/ask |
| execution-manifest.schema.json | /api/execute/* |
| provider-plan.schema.json | plan generation |
| provider-review.schema.json | co-work review |
| validation-result.schema.json | /api/execute/validate |
| learning-candidate.schema.json | /api/execute/learn |
| system-health.schema.json | /api/health |
| workspace-summary.schema.json | /api/workspace/summary |
| workspace-repo.schema.json | /api/workspace/repo |
| workspace-dir.schema.json | /api/workspace/dir |
| workspace-module.schema.json | /api/workspace/module |
| workspace-file.schema.json | /api/workspace/file |
| workspace-source-range.schema.json | /api/workspace/file/content |
| claim-verification.schema.json | claim verifier |
| quote-extraction.schema.json | quote extractor |
| provider-status.schema.json | /api/providers/status |

## Normalization rules

Use `tools/output_normalizer.py`:
1. Validate provider output against expected schema.
2. If valid: return as-is.
3. If invalid but fixable (missing optional fields): add defaults, return normalized.
4. If invalid and unfixable: return `{error: "...", schema: "...", raw_error: "..."}`.
5. Never silently drop required fields.
6. Never pass raw tracebacks to UI.

## Template registry

Prompt templates in `.claude/brain/prompt-template-registry.json`:
- 15 templates covering all Citadel response types
- Each template has: template_id, version, hash, output_schema
- Audit logs use template_id/hash only — never full template text

## Required consistency rules

- Ask Citadel skill counts must match `.claude/skills/` content
- Agent counts must match `.claude/agents/` content
- Workflow counts must match `workflow-manifest-config.json`
- Health checks must reflect actual system state
- File counts must come from workspace index, not memory

## Error format

All API errors return:
```json
{
  "error": "human-readable message",
  "code": "error_code_slug",
  "details": "optional details without stack trace"
}
```

Never: `{"traceback": "Traceback (most recent call last):..."}`

## Tools

- `tools/output_normalizer.py` — validate and normalize provider outputs
- `tools/output_schema_lint.py` — verify all schemas exist and are valid
