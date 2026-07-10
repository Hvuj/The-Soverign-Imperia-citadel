# 03 â€” Clean-Slate Log

> Exactly what was removed to reach a clean, agnostic slate, what remains, and how to verify.
> (Tasks 1, 2, 3, 4-data, 5, 10.) Executed 2026-07-09. **All removed data is preserved in
> `sovereign-imperia-citadel 2.zip`** (the pre-cleanup snapshot) â€” nothing is unrecoverable.

## What was removed (data)

### Brain (`docs/brain/`) â€” 15,230 â†’ 147 files (âˆ’15,083)

| Removed | Count | Reason |
|---|---|---|
| `nodes/commits/**` | 11,482 | mined git history of the original workspace (task 1) |
| `nodes/features/**` | 3,453 | learned features of foreign repos (task 10) |
| `nodes/code/`, `nodes/tests/`, `nodes/domain/` | 6 | learned domain nodes (sample-feature, sample-rate, distributed-store, bi-logic, â€¦) |
| `directories/**` + `nodes/directories/**` | ~34 | directory maps of `${HOME}/â€¦/acme-core` (tasks 2, 3) |
| `graphs/**` | 31 | per-repo brain shards for `acme-*`, `svc-*`, `external`, etc. (task 3) |
| `imports/**`, `symbols/**` | 6 | code indexes of foreign repos |
| `workspace/repos/**`, `workspace/features/**` | ~57 | summaries of ~32 foreign repos |
| 6 domain topic nodes | 6 | bi-logic, orchestration, parallel-compute, sql, dataframe-numeric, config-schema (task 4, 10) |
| 4 domain knowledge nodes | 4 | schema-validation/orchestration (task 10) |
| built graph artifacts | 7 | `graph.json` (1.2 MB), `graph.dot`, `graph.svg`, `graph-shard-index.json`, `repos-graph.json`, `system-status.json`, `graph.html.bak` â€” stale over deleted data |

### Memory (`docs/ai-context/`) â€” 34 â†’ 17 files (âˆ’17)

| Removed | Reason |
|---|---|
| `bi-logic.md` | all BI logic (tasks 4, 10) |
| `tech-knowledge/{orchestration,orchestration-schema-validation,orchestration-asset-checks-schema-validation,schema-validation-patterns,schema-validation-complete-guide}.md` | learned domain knowledge |
| `feature-learning/**`, `incoming/**` (schema-validation staging), `knowledge/{bronze,silver}/**` | learned/staged domain data |
| `archive/**` (3 files) | archived learned outcomes |

### Reset to clean agnostic templates (kept, emptied)

`active-memory.md`, `what-worked.md`, `what-did-not-work.md`, `feature-implementation-patterns.md`,
`implementation-cache-index.md`, `docs/brain/graph-index.md`, `docs/brain/workspace/index.md`,
`model-effort-outcomes.md` (entries cleared).

### Scrubbed of foreign examples (kept)

`docs/ai-context/system/workspace-intelligence-index.md` ("acme repo" â†’ "repo"; sample-feature/schema-validation
query examples â†’ generic), `docs/ai-context/model-selection-policy.md` (BI task type + BI agents +
"BI logic" references removed), `docs/ai-context/memory-index.md` (bi-logic section removed).

## What remains (the agnostic Citadel scaffolding)

- `docs/brain/nodes/`: 63 agents, 20 workflows, 10 tool-descriptions, 11 system topics, 3 system
  knowledge nodes, 9 memory-structure nodes, 7 system successes/failures, 1 unit â€” **all agnostic,
  about the Citadel's own operation, not any workspace.**
- `docs/brain/`: the graph viewer (`graph.html/js/css`, `workspace.*`, `*.html`), `graph.schema.json`,
  reset index stubs.
- `docs/ai-context/`: the 5 empty core memory files + agnostic policy/system docs (grounding,
  output-consistency, prompt-leak, prompt-template-registry, security-governance, memory-index/workflow,
  model-effort/selection policy).

## What was NOT removed this turn (mapped for the build phase instead)

- **BI *code*** (`bi_logic_discoverer.py`, `bi_understanding.py`, `add_bi_logic.py`, the orchestrator
  BI mode, the `citadel bi` CLI) â€” a coordinated refactor; see [02 Â§B](02-AGNOSTIC-AUDIT.md).
- **Domain vocabulary in code** (alias table, classifier keyword maps) â€” see [02 Â§A](02-AGNOSTIC-AUDIT.md).
- **Seed asset copies** under `src/citadel/assets/` â€” see [02 Â§E](02-AGNOSTIC-AUDIT.md).
- **The legacy template** in the zip (`.citadel/.claude/`) with its BI agents/rules/schemas and
  `${HOME}` paths â€” regenerated/scrubbed at build time; see [02 Â§D5/D6, Â§B11-13](02-AGNOSTIC-AUDIT.md).

## Verification

```powershell
# Brain + memory are clean of foreign repo/person/domain data-tokens:
#   (remaining hits are in CODE and in the legacy system-map, both mapped in 02/04)
rg -i "<any prior brand / repo / person / client tokens>" docs/brain docs/ai-context
# â†’ only agnostic UI code (workspace.js field names) remains; no data.
```

After the build phase completes [02](02-AGNOSTIC-AUDIT.md) and a fresh `citadel init` on a real workspace,
the Citadel regenerates its brain from that workspace alone â€” no trace of any prior one.
