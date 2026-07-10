# Feature implementation learning

## Goal

Learn compact reusable implementation patterns after successful validated feature work so future similar tasks need fewer file reads, fewer searches, and fewer failed attempts.

## Before implementation

Run `pattern-reuse-router` for code/runtime/BI/data/performance work.

Query:

```bash
python tools/feature_pattern_query.py "<task keywords>" --limit 3
```

Read only top 1-3 matching pattern cards.

## After successful implementation

Run `feature-implementation-learner` when:
- code/runtime behavior changed
- data/BI/performance logic changed
- a repeated failure was resolved
- a durable validation pattern was found
- a reusable implementation shortcut was discovered

Do not run deep learning for workflow-only verification.

## Storage

Primary:
- `docs/ai-context/feature-implementation-patterns.md`

Optional graph node:
- `docs/brain/nodes/successes/<pattern-id>.md`
- `docs/brain/nodes/failures/<pattern-id>.md`

## Token rules

- never save raw transcript
- never save large diffs
- keep pattern cards compact
- tags/files/tests must be searchable
- archive old/rare patterns if the file grows too large
