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
| _(none)_ | | | | | |

## Patterns observed (auto-updated by effort-decider)

_None yet. Clean slate — populated as tasks complete._

## Policy decisions derived from this log

| task_type | model | confidence | derived_from |
|-----------|-------|-----------|-------------|
| _(none)_ | | | |
