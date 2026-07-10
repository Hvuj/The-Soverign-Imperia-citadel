---
id: knowledge-grounding-policy
type: knowledge
title: Citadel Grounding Policy
tags: [grounding, evidence, hallucination-reduction, claim-verification, quote-first]
domain: citadel-infrastructure
---

# Citadel Grounding Policy

Evidence-first policy for all Citadel AI outputs.

## Summary

No claim without evidence. Uncertainty preferred over invention. Quote-first for source analysis.

## Key files

- `.claude/rules/grounding.md` — grounding rules (loaded by agent context)
- `docs/ai-context/system/grounding-policy.md` — full policy document
- `tools/grounding_quote_extractor.py` — extract quotes from source
- `tools/grounding_claim_verifier.py` — verify claims against evidence
- `tools/grounding_lint.py` — verify grounding infrastructure

## Evidence ledger

Every non-trivial answer includes:
- evidence_used
- assumptions
- missing_evidence
- validation_run (bool)
- unsupported_claims_removed (int)
- source_scope
- confidence (high|medium|low)

## Required phrases

- "I do not have enough information to confidently assess this."
- "No relevant quotes found."
- "This is an assumption, not a verified fact."

## Linked nodes

- knowledge-output-consistency-policy
- knowledge-prompt-leak-policy
- tool-grounding-quote-extractor
- tool-grounding-claim-verifier
