---
id: knowledge:workspace-intelligence-index
title: Workspace Intelligence Index
type: knowledge
tags: [knowledge, workspace, intelligence, index, reuse, bm25, incremental, python, feature-detection]
links:
  - topic:workspace_intelligence
  - topic:graph_brain
files:
  - docs/ai-context/system/workspace-intelligence-index.md
  - tools/build_workspace_intelligence_index.py
  - tools/workspace_intelligence_query.py
  - tools/_workspace_intel_common.py
---

# Workspace Intelligence Index

Production-grade Python-only workspace indexing layer for all indexed repos (provinces).

## What it does
Precomputes durable machine-readable indexes of every repo, directory, module,
file, symbol, import, test, feature, artifact, and reusable pattern so
Citadel/Claude never re-explores the workspace from scratch.

## Key truth
Exact lookups are O(1); semantic/reuse retrieval is precomputed and near-instant
using inverted/BM25/optional-local-vector indexes.

## Tools
- `tools/build_workspace_intelligence_index.py` — incremental builder (9-phase)
- `tools/workspace_intelligence_query.py` — query tool (exact + BM25)
- `tools/workspace_intelligence_lint.py` — security + correctness lint
- `tools/workspace_intelligence_daemon.py` — optional file-watch daemon
- `tools/_workspace_intel_common.py` — atomic writes, BM25, lock, config

## Config
`.claude/brain/workspace-index-config.json`

## Indexes
`.claude/state/workspace-intelligence/*.json` — 24 machine indexes

## Citadel integration
`/api/ask` handles: workspace, repo, file, module, symbol, feature, reuse,
tests, dependency, artifact questions from local indexes (zero model tokens).

## Security
Never indexes `.env`, `*.pem`, `*.key`, credentials, private key headers.
All writes atomic. No external APIs. No project code import/execution.
