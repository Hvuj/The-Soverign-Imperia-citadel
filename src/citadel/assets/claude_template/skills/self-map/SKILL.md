---
name: self-map
description: Build/refresh Citadel Legion's own persistent E2E map of every workspace repo — files/dirs/modules/symbols down to line-level logic, intra-file call edges, and verified cross-repo import edges — so the mapping is never repeated from scratch. Use before a large refactor, when asked to map/understand the whole workspace, or when logic-nodes/cross-repo-edges look stale.
when_to_use: map the workspace, self-map, build logic nodes, cross-repo edges, e2e map, understand all repos, refresh workspace intelligence
---

## What this builds

1. Per-repo file/dir/module/symbol + import indexes (`tools/symbol_index.py`, `tools/import_graph.py`) — reused as-is if already fresh.
2. Per-repo **line-level logic nodes** with intra-file call edges (`tools/build_logic_nodes.py`) — one JSON per repo under `.citadel/state/workspace-intelligence/<repo>/logic-nodes.json`.
3. **Cross-repo import edges** (`tools/build_cross_repo_edges.py`) — verified Python import edges between repos (never a name guess: only a repo's declared package name or a real on-disk module counts as "owned"), written to `docs/brain/workspace/cross-repo-edges.json`.
4. Directory-brain coverage (`tools/dir_brain_mapper.py`) across the current repo scope.

The repo scope is whatever `citadel.services.corporate.Legion.discover()` resolves — this already honors a `*.code-workspace` file if one is configured (see `.citadel/config.toml`'s `[index].code_workspace`), so self-map only covers what's actually open in the editor once that's set up.

## Run

```!
cd "${CLAUDE_PROJECT_DIR:-.}" && \
echo "=== logic nodes ===" && python3 tools/build_logic_nodes.py && \
echo "=== cross-repo edges ===" && python3 tools/build_cross_repo_edges.py && \
echo "=== symbol + import indexes (refresh if stale) ===" && python3 tools/symbol_index.py --quiet && python3 tools/import_graph.py --quiet 2>/dev/null || true
```

## Task

Summarize what changed: node counts per repo (flag any `truncated > 0`), new/changed cross-repo edges, and any repos with zero logic nodes (likely non-Python or excluded). If a repo has no Python at all, say so rather than treating it as a failure. Do not re-run this for repos whose logic-nodes.json is already fresh (mtime newer than the repo's last source change) unless the user asks for a full rebuild.
