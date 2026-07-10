# Model-Effort Outcome Log

Append-only log of model+effort choices and their outcomes.
Used by `effort-decider` to improve future model selection.
Do NOT edit past entries. Only append new rows.

## How to read this log

- **outcome**: `success` (task completed correctly), `fail` (wrong/incomplete), `overkill` (worked but cheaper model would have been fine)
- **notes**: ≤10 words explaining what happened
- Use the pattern: if model X `fail` on task_type Y ≥ 2 times → upgrade default for Y

## Entries

| date | task_type | model | effort | outcome | notes |
|------|-----------|-------|--------|---------|-------|
| 2026-06-25 | feature_change | sonnet | medium | success | commit knowledge graph, 8 files |
| 2026-06-25 | debugging | sonnet | medium | success | health errors, 3 fixes |
| 2026-06-25 | question | haiku | low | success | confirmation question, trivial |

## Patterns observed (auto-updated by effort-decider)

_None yet beyond seed entries. Will be updated as more tasks complete._

## Policy decisions derived from this log

| task_type | model | confidence | derived_from |
|-----------|-------|-----------|-------------|
| question | haiku | high | seed + rule |
| feature_change | sonnet | medium | 1 success |
| debugging | sonnet | medium | 1 success |
