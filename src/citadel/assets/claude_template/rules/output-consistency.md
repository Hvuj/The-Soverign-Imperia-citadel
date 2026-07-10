# Output Consistency Rules

All Citadel API responses and AI outputs must be schema-valid and consistent.

## Schema validation

- All `/api/*` endpoints return schema-valid JSON per `.claude/schemas/`.
- Provider outputs are validated before use.
- If provider output is invalid: retry once (if safe), then return structured error.
- Never return raw Python tracebacks in UI or API responses.
- Use `tools/output_normalizer.py` to validate and normalize provider outputs.

## Required fields

All Ask Citadel responses must include:
- `source` (local | local_plus_claude | claude_fallback | unavailable)
- `confidence` (high | medium | low)
- `evidence` (array, may be empty)
- `claim_verification.enabled`
- `claim_verification.unsupported_claims_removed`

## Template usage

Responses are generated from templates registered in `.claude/brain/prompt-template-registry.json`.

Template rules:
- Each response type maps to one template.
- Templates define: role, task, output schema, grounding mode, forbidden context.
- Do not embed hidden instructions in provider context without template tracking.
- Templates have version + hash. Audit logs record template_id/hash only, never full content.

## XML-like sections for structured outputs

Use XML-like section markers for multi-part responses:
```
<answer>...</answer>
<evidence>...</evidence>
<assumptions>...</assumptions>
<warnings>...</warnings>
```

## Provider output normalization

When a provider returns output:
1. Validate against the expected schema.
2. If valid: return as-is.
3. If invalid but close: normalize (add missing optional fields with defaults).
4. If still invalid: return `{error: "Provider output did not match schema", schema: "<schema_name>"}`.
5. Never silently drop required fields.

## Structured outputs

Use structured output mode if the provider supports it.
Do not rely on prefill to enforce output format for newer models.
Use explicit output schemas in provider context.

## Consistency rules

- Skill count answers must match `.claude/skills/` directory contents.
- Agent count answers must match `.claude/agents/` directory contents.
- Workflow count answers must match `workflow-manifest-config.json`.
- Do not invent counts. If local source disagrees with memory, prefer local source.
- If sources disagree, report the mismatch instead of guessing.
