# Grounding Policy

Citadel answers must be grounded in evidence. This document defines the full grounding contract.

## Principle

No claim without evidence. Uncertainty is allowed and preferred over invention.

## Evidence hierarchy

1. **Live system state** (system-status.json, PID files, daemon logs) — highest trust for health claims
2. **Workspace intelligence indexes** (built today, O(1) lookup) — highest trust for code/file claims
3. **Brain graph nodes** — high trust for architecture/feature/workflow claims
4. **Docs in docs/ai-context/** — high trust for policy/BI/memory claims
5. **Model-generated reasoning** — lowest trust; must be labeled as reasoning, not fact

## Required phrases when evidence is missing

| Situation | Required phrase |
|---|---|
| Evidence missing | "I do not have enough information to confidently assess this." |
| Context insufficient | "The available sources are insufficient." |
| No quotes found | "No relevant quotes found." |
| Assumption made | "This is an assumption, not a verified fact." |
| File not inspected | "I could not find evidence for that in the available context." |

## Quote-first mode

Trigger conditions:
- User provides long documentation to analyze
- Compliance, legal, or BI semantics analysis
- Source-only analysis requested
- High-risk decision with provided source material

Steps:
1. Extract relevant quotes from source using `tools/grounding_quote_extractor.py`
2. Label each quote: source_path, heading, line (if available)
3. Draft answer using only extracted quotes
4. If no quotes found: return `no_quotes_found: true`, say "No relevant quotes found."
5. Never synthesize beyond the quotes

## Claim verification

Run `tools/grounding_claim_verifier.py` before finalizing non-trivial answers.

Classification guide:
- **supported**: claim is directly backed by evidence
- **partially_supported**: claim is roughly correct but evidence is incomplete
- **unsupported**: no evidence found (remove or mark uncertain)
- **contradicted**: evidence contradicts the claim (remove and note conflict)
- **unverifiable**: would require external data not available locally

## Evidence ledger

Required fields for non-trivial answers:

```json
{
  "evidence_used": [],
  "assumptions": [],
  "missing_evidence": [],
  "validation_run": false,
  "unsupported_claims_removed": 0,
  "source_scope": "local indexes",
  "freshness": "index built at <timestamp>",
  "confidence": "high|medium|low"
}
```

## Scope restrictions

| Task type | Evidence source |
|---|---|
| File content claim | workspace index or direct file read |
| Health claim | system-status.json or /api/health |
| Validation claim | command output captured by citadel_validation_runner.py |
| Count claim | counted from local directory or index |
| Architecture claim | .claude/rules/ or brain graph nodes |

## What is not allowed

- Claiming a function exists without checking the current index
- Claiming validation passed without command output
- Claiming a file has certain content without reading it
- Inventing test results
- Presenting memory as current fact without verifying

## Grounding tools

- `tools/grounding_quote_extractor.py` — extract quotes from source
- `tools/grounding_claim_verifier.py` — verify claims against evidence
- `tools/grounding_lint.py` — verify grounding infrastructure exists
