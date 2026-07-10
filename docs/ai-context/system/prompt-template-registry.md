# Prompt Template Registry

Human-readable reference for Citadel prompt templates.

Machine-readable registry: `.claude/brain/prompt-template-registry.json`

## Template catalog

| Template ID | Role | Output Schema | Grounding Mode |
|---|---|---|---|
| ask_local_answer | local_resolver | ask-response | evidence_first |
| ask_claude_fallback | bounded_fallback | ask-response | evidence_first |
| quote_first_analysis | source_analyst | quote-extraction | quote_first |
| claim_verification | claim_verifier | claim-verification | evidence_first |
| claude_code_plan | planner | provider-plan | evidence_first |
| claude_code_execute_scoped | executor | provider-plan | evidence_first |
| cowork_review | reviewer | provider-review | evidence_first |
| docs_ingestion | doc_ingester | ask-response | quote_first |
| workspace_query_answer | workspace_resolver | ask-response | evidence_first |
| implementation_final_report | reporter | validation-result | evidence_first |
| validation_report | validator | validation-result | evidence_first |
| learning_candidate_generation | learner | learning-candidate | evidence_first |
| prompt_leak_refusal | refusal_handler | ask-response | none |
| forbidden_action_refusal | refusal_handler | ask-response | none |
| evidence_summary | summarizer | ask-response | evidence_first |

## Usage rules

1. Every AI response must map to exactly one template.
2. Audit logs record template_id/hash — never full template text.
3. Forbidden context categories are enforced per template (secrets, hidden_instructions, etc.).
4. Prompt leak policy is strict for user-facing templates, standard for internal ones.
5. To add a template: update `.claude/brain/prompt-template-registry.json` and this doc.

## Adding a template

Required fields:
```json
{
  "template_id": "unique_snake_case_id",
  "version": "1.0",
  "hash": "8-char-hex",
  "role": "role_description",
  "task": "one-line task description",
  "grounding_mode": "evidence_first|quote_first|none",
  "output_schema": "schema-name.schema.json",
  "forbidden_context": ["secrets", "hidden_instructions"],
  "prompt_leak_policy": "strict|standard"
}
```
