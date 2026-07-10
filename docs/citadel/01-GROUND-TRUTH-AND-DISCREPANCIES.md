# 01 — Ground Truth & Discrepancies

> Measured from the filesystem on 2026-07-09 after the clean-slate. The three legacy narrative docs
> (`Citadel.md`, `SOVEREIGN-IMPERIA-CITADEL-E2E.md`, `LIFECYCLE.md`) disagree with each other and with the code on
> nearly every count. **These numbers are authoritative; the legacy docs must be regenerated from
> them.** (Task 6.)

## 1. Code inventory (exact)

| Unit | Legacy doc claims | **Measured** | Notes |
|---|---|---|---|
| Python tools (`tools/*.py`) | 90 / 125 | **178** | 169 top-level + 9 `tools/principles/*.py` |
| Package modules (`src/citadel/**.py`) | — | **35** | excludes `__pycache__` |
| Shell scripts (`scripts/*.sh`) | 19 | **23** | several are legacy shims (see build map) |
| Test files (`tests/test_*.py`) | — | **44** | ~228 tests total |
| Health checks (`citadel_system_health.py`) | 34 | **12** (per the tool's own docstring) | legacy "34" is aspirational |
| JSON schemas (template `.claude/schemas/`) | 16 / 28 | **35** | template lives in the zip / installed pkg, not this checkout's working tree |
| Agents (template) | 63 | **63** | consistent |
| Skills (template) | 22 / 26 | **~30 dirs + 6 playbook/skill `.md`** | |
| Hooks (template) | 22 | **26** | |
| Rules (template) | 13 / 14 | **14** | |
| Brain configs (template `.claude/brain/`) | 10 / 13 | **13** | |
| Legion/governance configs (template `.claude/legion/`) | 5 | **5** | board-config, constitution, model-tiering, principle-weights, routing-rules |
| Daemons | 3 / 5 | **5 core + 3 optional + UI server** | see build map |
| Workflow scripts (JS) | 2 | **2** | |

## 2. Brain data (after clean-slate)

| Node type | Before | **After clean-slate** | Disposition |
|---|---|---|---|
| `nodes/commits/**` | 11,482 | **0** | removed (mined git history — foreign) |
| `nodes/features/**` | 3,453 | **0** | removed (learned features — foreign) |
| `nodes/agents/` | 63 | **63** | kept (system scaffolding) |
| `nodes/workflows/` | 20 | **20** | kept |
| `nodes/tools/` | 10 | **10** | kept |
| `nodes/topics/` | 17 | **11** | removed 6 learned domain topics (bi-logic, orchestration, parallel-compute, sql, dataframe-numeric, config-schema) |
| `nodes/knowledge/` | 7 | **3** | removed 4 schema-validation/orchestration domain nodes; kept grounding-policy, scaffold-integrity, workspace-intelligence-index |
| `nodes/memory/` | 10 | **9** | removed bi-logic |
| `nodes/successes/` + `failures/` | 7 | **7** | kept (system self-knowledge) |
| `nodes/code/`, `nodes/domain/`, `nodes/tests/` | 6 | **0** | removed (learned domain) |
| `nodes/units/` | 1 | **1** | kept |
| `directories/`, `graphs/`, `imports/`, `symbols/`, `workspace/repos/`, `workspace/features/` | ~150 | **0** | removed (all foreign, regenerated per province) |
| **Total `docs/brain/` files** | **15,230** | **147** | **15,083 removed** |

The remaining 147 are the Citadel's own agnostic scaffolding (agents, workflows, tool descriptions,
system successes/failures, the graph viewer HTML/JS/CSS, schema) plus reset index stubs.

## 3. Memory (`docs/ai-context/`, after clean-slate)

| Category | Before | After | Disposition |
|---|---|---|---|
| Total files | 34 | **17** | 17 removed |
| Learned content | bi-logic.md, tech-knowledge/{orchestration,schema-validation}*, feature-learning/*, incoming/*, knowledge/{bronze,silver}/*, archive/* | — | removed |
| Core memory files | active-memory, what-worked, what-did-not-work, feature-implementation-patterns, implementation-cache-index | reset to clean templates | kept, emptied |
| Agnostic policy/system | ai-agent-security-governance, memory-index, memory-update-workflow, model-effort-outcomes, model-selection-policy, system/* (5) | scrubbed of examples | kept |

## 4. Why the legacy docs drifted

1. They were hand-maintained across many sessions and never regenerated from a filesystem scan.
2. Counts were quoted from earlier snapshots (the 90→125→178 tool growth was never reflected back).
3. Aspirational claims (34 health checks, "interactive D3 graph builder") were written for intended
   behavior that the code never reached — the actual `build_brain_graph_html.py` is a counts-only stub.

## 5. The reconciliation rule for the rebuild

> Any count in any Citadel doc must be produced by a filesystem scan, never quoted from prose. A CI
> lint (`citadel_inventory_lint.py`, to build) should regenerate this table and fail if a narrative doc
> disagrees — so the docs can never silently drift again. This directly serves the Sovereign's "adjust
> all files based on real numbers and logic" requirement and makes it *self-sustaining*, not a one-time
> fix.
