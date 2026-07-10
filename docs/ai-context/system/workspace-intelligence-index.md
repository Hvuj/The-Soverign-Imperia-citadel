# Workspace Intelligence Index

## Purpose

The workspace intelligence layer provides O(1) exact lookup and near-instant
precomputed retrieval for every included repo, directory, module, file,
symbol, import, test, feature, artifact, and reusable pattern.

**Key truth:** Exact lookups are O(1); semantic/reuse retrieval is precomputed
and near-instant using inverted/BM25/optional-local-vector indexes.

## Config

`.claude/brain/workspace-index-config.json`

## Output location

`.claude/state/workspace-intelligence/` — all machine indexes (JSON)
`docs/brain/workspace/` — human-readable summaries

## Tools

| Tool | Purpose |
|------|---------|
| `tools/build_workspace_intelligence_index.py` | Build / incremental-update all indexes |
| `tools/workspace_intelligence_query.py` | Query indexes (O(1) exact + BM25/inverted reuse) |
| `tools/workspace_intelligence_lint.py` | Security + correctness lint |
| `tools/workspace_intelligence_daemon.py` | Optional file-watch daemon |
| `tools/_workspace_intel_common.py` | Shared helpers (atomic writes, BM25, lock, config) |

## Security constraints

- Never indexes sensitive files (`.env`, `*.pem`, `*.key`, credentials, etc.)
- Never stores private key headers in any index
- Never calls external APIs
- Never imports or executes project code (text + AST only)
- All writes atomic via temp-file → fsync → rename

## Query examples

```bash
python tools/workspace_intelligence_query.py summary --pretty
python tools/workspace_intelligence_query.py repos --pretty
python tools/workspace_intelligence_query.py reuse "<feature keywords>" --pretty
python tools/workspace_intelligence_query.py feature <feature_id> --pretty
python tools/workspace_intelligence_query.py search "<query>" --pretty
```
