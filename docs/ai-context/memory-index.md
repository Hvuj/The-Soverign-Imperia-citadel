# Memory Index

Read this file first. Then read only relevant memory.

## Active run (per-worker/per-task memory)
- `.claude/state/legion-runs/current-run.json` points at the current `citadel run`.
- `.claude/state/legion-runs/<run_id>/INDEX.md` is that run's pointer file — one line
  per worker/task `.md` memory card under `.claude/state/legion-runs/<run_id>/workers/`.
  Read the run's `INDEX.md` first, then only the specific worker/task cards you need
  (same "index first, then follow pointers" convention as this file).

## Current
- `active-memory.md`

## Success patterns
- `what-worked.md`

## Failure patterns
- `what-did-not-work.md`

## Feature implementation patterns
- `feature-implementation-patterns.md`

Query first with:

```bash
python tools/feature_pattern_query.py "<task keywords>" --limit 3
```

Read only top 1-3 matching cards.

## AI agent security & governance (reference)
- `ai-agent-security-governance.md` — permission/least-privilege, data-handling (never feed
  secrets/.env/.ssh/.pem), OWASP LLM/agentic risks. Read when touching the legion permission model,
  worker spawning, credentials, or data handling.

## Workflow
- `memory-update-workflow.md`

## Archives
- `archive/`: low-frequency historical memory; do not read unless this index points there.
