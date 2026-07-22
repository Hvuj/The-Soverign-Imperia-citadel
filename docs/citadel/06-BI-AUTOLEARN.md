# 06 — The Pandidakterion (continuous, auto-discovered, self-improving domain logic)

> **Status: BUILT.** This replaces the old removed BI code and its earlier design draft. The Cartographer
> learns any province's **domain logic** (metrics · rules · transforms · policies — not just BI KPIs),
> generates live capabilities from it, and — driven by the watch daemon + the Republic — keeps that
> understanding **100% current**: change a logic file and the cascade re-learns, regenerates, re-wires, and
> re-validates every dependent component. Governed as the **Pandidakterion**, a chartered imperial university.

## Pipeline (learn → generate → wire → cascade → govern)

```
  GRAMMAR      bi_sources.py     multi-source, agnostic evidence (code · sql · docs · config)
     │         bi_vocab.py       learn the province's OWN vocabulary (nothing shipped)
     ▼         bi_synthesize.py  assemble units + confidence + provenance (content-addressed)
  RHETORIC     bi_cartographer.py  persist .citadel/state/logic/<province>/{vocab,units,scorecard}.json
     │                             + a user-editable memory card (managed block preserves your notes)
     ▼         bi_generate.py    nodes · review skill · workflow · deterministic validator · script
  WIRE         bi_wire.py        record units into the Republic LearningStore + bus; manifest; Aerarium-gated refine
     │
     ▼         bi_cascade.py     on a logic change: re-learn → diff units → regenerate → re-wire (incremental)
  GOVERN       services/pandidakterion.py   charter monopoly · Chairs · not-self quorum → Senatus Consultum · JIT decay
```

Everything is **zero-token and deterministic** by default (a model is summoned only to refine a low-confidence
unit, and only when the **Aerarium** can afford it). Every step is guarded — nothing breaks the session.

## The Pandidakterion (charter → mechanism)

| University (Cth. 14.9.3) | Built mechanism |
|---|---|
| Charter / state monopoly | `Pandidakterion.charter_admits` — only the Cartographer + seated Chairs may write learned knowledge |
| 31 Chairs / faculty | `default_faculty()` — one Chair per discipline (metric/rule/transform/policy/term), each a **distinct** validator identity |
| Curriculum (Grammar→Rhetoric→Jurisprudence→Philosophy) | extract → synthesize → validate (gates) → not-self cross-check |
| Bilingual (Latin=law, Greek=letters) | deterministic T0 extraction vs T2 refinement (low-confidence only) |
| Salaries from the treasury (annonae) | `Aerarium` token-bucket funds refinement (`bi_wire`) |
| Declines + revivals | **JIT decay** (`decay_stale`) demotes a unit whose source changed; the cascade revives it |
| Not-self rule | a unit becomes a durable **Senatus Consultum** only via ≥2 **distinct not-self** validators (`promote_unit`) |

## The continuous "100%" loop
A logic file changes → the **incremental-brain daemon** (`_logic_cascade`) calls `bi_cascade.cascade` →
re-learn the province → **diff** units by content hash (added/removed/changed) → regenerate the affected
artifacts → re-wire into the Republic → the changed unit's Consultum **decays** (source no longer fresh) and
is re-promoted only after a fresh not-self quorum. Triggers: the watch daemon, the `logic-autolearn-sync.sh`
hook (PostToolBatch), and the git-history daemon.

## Operating
- `citadel bi learn [--province X]` — run the full pipeline on demand (primary path is automatic).
- `citadel bi status` · `citadel bi show <unit>` — inspect what was learned and its provenance.
- `citadel pandidakterion` — faculty, durable-unit count, and the governance rules.

## Guardrails
- **Agnostic:** templates carry no domain terms; two provinces learn two vocabularies (test:
  `test_two_provinces_learn_different_vocab`). No cross-province leakage (`test_templates_are_agnostic_and_isolated`).
- **No self-ingestion:** generated artifacts are marker-stamped and skipped by `ingest` (no phantom units).
- **Idempotent:** generation is byte-stable; promotion is content-addressed (no version spam).
- **Not-self:** the Cartographer cannot self-certify a durable write — a distinct family must confirm.

## Chaos drill (verification)
`tests/test_bi_command.py::test_chaos_drill_change_a_line_refreshes_and_decays`: learn → promote a unit to a
Senatus Consultum bound to its source hash → change the source line → assert the cascade re-learns + detects
the new unit + regenerates, and the stale unit's Consultum **decays**. Modules covered by
`tests/test_bi_{cartographer,generate,wire,cascade}.py` + `tests/test_pandidakterion.py` (26 tests). Every
path degrades without Ollama/keys/Redis.

## Module layout
```
tools/  bi_sources.py · bi_vocab.py · bi_synthesize.py · bi_cartographer.py · bi_generate.py · bi_wire.py · bi_cascade.py
src/citadel/services/pandidakterion.py            governance (charter · Chairs · quorum · decay)
src/citadel/commands/{bi,pandidakterion}.py       CLI
src/citadel/assets/claude_template/hooks/logic-autolearn-sync.sh    auto-connection hook
src/citadel/assets/claude_template/schemas/domain-understanding.schema.json
tools/incremental_brain_daemon.py::_logic_cascade  the watch-daemon trigger
```
