# 06 — The BI Cartographer (Agnostic, Auto-Connected, Generative BI Auto-Learning)

> Design for the **recreated** BI capability. The old BI code (airline-hardcoded, shallow, orphaned)
> has been fully removed; this is its agnostic, self-connecting, *generative* replacement — a subsystem
> that learns a province's business-intelligence logic from many sources and then **auto-creates**
> skills, workflows, tools, scripts, artifacts, memory files, and brain nodes from what it learned, and
> wires them into the live system with no manual step.
>
> **Status: design (buildable).** This is a major new subsystem; per the session's "map the big pieces,
> then build" pattern it is specified here first. A first-increment build path is in §9.

## 1. What it must be (vs. the old BI code)

| Old BI (removed) | The BI Cartographer (this design) |
|---|---|
| Hardcoded airline vocab (`fare/rpk/ask/load_factor`) | **Agnostic** — learns the domain vocabulary from the province itself |
| Shallow (SQL `GROUP BY` + Python aggregations only) | **Multi-source**: docs, README, API docstrings, git commit history, prompts, code, SQL, config, "other" |
| **Orphaned** — a manual `citadel bi learn` command | **Auto-connected** — fires from init, the git-history daemon, prompt hooks, and the Citadel Loop |
| Wrote one `bi-understanding.json` | **Generative** — creates brain nodes, memory `.md`, skills, workflows, tools, scripts, artifacts, and updates indexes/aliases |
| Static | **Self-updating** — re-learns incrementally on change; keeps generated artifacts fresh |

**Name:** the **Cartographer** — a Citadel order that maps each province's business logic terrain.

## 2. Pipeline (learn → synthesize → generate → wire)

```
        MULTI-SOURCE INGEST (T0, zero-token, deterministic)
   docs · README · API docstrings · git commits · prompt ledger · code · SQL · config
                              │
                              ▼
        VOCABULARY LEARNING (agnostic — no shipped terms)
   derive domain nouns/metrics from the corpus → .citadel/state/bi/<province>/vocab.json
                              │
                              ▼
        PER-METRIC SYNTHESIS (T0 pre-pass; T2 only for low-confidence refinement)
   assemble {name, formula, grain, filters, date_window, joins/cardinality, nulls,
             rounding, expected_output, evidence[], confidence} per metric
                              │
                              ▼
        GENERATION (turn knowledge into capabilities — the new part)
   nodes · memory.md · skills · workflows · tools · scripts · artifacts · index updates
                              │
                              ▼
        AUTO-WIRE + SELF-UPDATE
   register generated artifacts · update manifest/routing · re-learn on change
```

## 3. Sources (multi-source ingestion, all T0)

| Source | Extractor | What it yields |
|---|---|---|
| Docs / README | markdown parse | metric glossaries, KPI tables, prose definitions |
| API docstrings | `ast` docstring scan (reuses `services/index/symbols`) | metric/formula language attached to functions |
| Git commit history | the commit index (`commit-index.json`, line→function) | which commits define/changed a metric, and why (message) |
| Prompt ledger | mine `prompt-ledger.ndjson` | which metrics the Sovereign actually asks about (salience) |
| Code | `ast` scan | aggregations (`groupby/sum/mean/ratio`), metric-defining functions |
| SQL | sqlparse-style walk | `GROUP BY` (grain), `JOIN…ON` (cardinality), `WHERE` (filters), window/date functions |
| Config / catalogs | YAML/JSON/TOML parse | declared metrics, dashboards, semantic layers |
| "Other" | notebooks, dashboard configs | cells and panels that compute metrics |

Each yields **evidence records** `{metric, dimension, value, source_path, line, weight}` — the atoms
synthesis assembles.

## 4. Agnostic vocabulary learning (the core fix)

Instead of a shipped `_BI_TERMS`, the Cartographer **learns** each province's vocabulary:
- Frequent domain nouns co-occurring with aggregations in code.
- Glossary/KPI terms named in docs/README.
- Terms in metric-defining commit messages.
- Metric names the Sovereign uses in prompts.

Stored per-province at `.citadel/state/bi/<province>/vocab.json`. Nothing airline/domain-specific ships;
two different provinces learn two different vocabularies. This is what makes it genuinely workspace-agnostic.

## 5. Generation — what it auto-creates (per province, from learned metrics)

| Target | Path | Content |
|---|---|---|
| **Brain nodes** | `docs/brain/nodes/domain/bi/<province>/<metric>.md` + `topic:bi-<province>.md` | one node per metric (frontmatter: formula, grain, evidence, confidence, `links:`) |
| **Memory** | `docs/ai-context/bi/<province>.md` | human-readable, **user-editable**, marker-delimited managed block (preserves the Sovereign's notes on re-learn) |
| **Skill** | `.claude/skills/bi-review-<province>/SKILL.md` | a generated review procedure that checks a change against the learned metrics (formula/grain/filter/date-window/cardinality/nulls/rounding) |
| **Workflow** | `docs/brain/nodes/workflows/bi-validation-<province>.md` | wires the metric checks into the execution manifest for BI-touching tasks |
| **Tool** | `tools/generated/bi_validate_<province>.py` | deterministic (T0) validator: check a metric's formula/grain against sample/dummy data |
| **Script** | `scripts/bi-<province>-check.sh` | thin wrapper to run the validator |
| **Artifact** | `.citadel/state/bi/<province>/{metrics.json, scorecard.json}` | schema-conforming understanding + a confidence scorecard |
| **Index/alias updates** | workspace-intelligence `feature-index`, `alias-index` | register metric→file/symbol links and learned metric aliases (routing) |

Generation is **template-driven and agnostic** — the templates carry no domain terms; they are filled
per-province from the learned metrics. A generated artifact is regenerated (not hand-edited) so it stays
in sync; the memory `.md` is the one place user edits are preserved.

## 6. Auto-connection (never orphaned)

| Trigger | Action |
|---|---|
| `citadel init` | run the Cartographer as part of the initial mining sweep of each province |
| **git-history daemon** | on a commit touching a metric-defining file (via line→function map), re-learn that metric incrementally + regenerate its artifacts |
| **UserPromptSubmit hook** | when a prompt mentions a learned metric, inject that metric's node into the context capsule (routing) |
| **PostToolBatch / Citadel Loop** | after a validated BI-touching change, refresh the metric + regenerate |
| **Stop-gate (manifest)** | BI-touching tasks require the generated `bi-review-<province>` skill to have run |
| **incremental-brain daemon** | picks up generated nodes so they become live routing targets |

New hook: `.claude/hooks/bi-autolearn-sync.sh` (PostToolBatch + a git-change branch). The Cartographer
runs as a **worker** (zero-token) by default; a Legionnaire (T2) is summoned only to refine a metric
whose confidence is low — and that refinement is captured so it is never re-derived.

## 7. How this fulfils the four self-* goals

- **Self-learning** — learns BI from the province's own docs/code/git/prompts, no hardcoding.
- **Self-improving** — *generates new capabilities* (skills/tools/workflows/scripts) from what it learned:
  the Citadel literally grows new abilities as it understands a province. This is the strongest
  self-improvement in the system.
- **Self-aware** — every metric carries confidence + provenance; the scorecard tells the Sovereign what
  the Citadel knows and how well, for zero tokens.
- **Self-sustaining** — re-learns on change, regenerates stale artifacts, stays agnostic and isolated
  per province.

## 8. Module layout (to build)

```
tools/
├── bi_cartographer.py     # orchestrates learn → synthesize → generate → wire (agnostic)
├── bi_sources.py          # the 8 multi-source extractors → evidence records
├── bi_vocab.py            # agnostic per-province vocabulary learning
├── bi_synthesize.py       # per-metric assembly + confidence scoring
├── bi_generate.py         # emits nodes/memory/skills/workflows/tools/scripts/artifacts
├── bi_wire.py             # registers generated artifacts, updates indexes/manifest routing
└── generated/             # generated per-province validators (git-tracked, regenerated)
.claude/hooks/bi-autolearn-sync.sh   # PostToolBatch + git-change trigger
.claude/schemas/bi-understanding.schema.json  # agnostic, regenerated
.citadel/state/bi/<province>/{vocab,metrics,scorecard}.json
docs/brain/nodes/domain/bi/<province>/*.md
docs/ai-context/bi/<province>.md
```

CLI surface (re-introduced, agnostic): `citadel bi learn [--province X]`, `citadel bi status`,
`citadel bi show <metric>` — but the primary path is **automatic** (init + daemon + hooks), not the CLI.

## 9. Build increments (so it can land safely)

1. **P0 — agnostic multi-source discoverer + per-province synthesis** (`bi_sources`, `bi_vocab`,
   `bi_synthesize`, `bi_cartographer`) writing `metrics.json` + `scorecard.json` + the memory `.md`.
   Zero-token, agnostic, tested against a synthetic province. *(Replaces the old removed code, done right.)*
2. **P1 — generation** (`bi_generate`): brain nodes + skill + workflow + validator tool + script from the
   learned metrics, template-driven.
3. **P1 — auto-wire** (`bi_wire` + the hook): connect to init, the git-history daemon, the prompt hook,
   and the Stop-gate. This is what makes it *auto* and never orphaned.
4. **P2 — refinement loop**: summon a Legionnaire only for low-confidence metrics; capture the result;
   validate metrics against sample data to *earn* confidence rather than assume it.

## 10. Guardrails

- **Agnostic lint:** `brand_lint` runs over generated artifacts — no cross-province term leakage, no
  shipped domain vocabulary.
- **Per-province isolation:** each province's BI lives under its own `bi/<province>/` namespace; nothing
  is global.
- **Zero-token first:** deterministic extraction/generation is the default; a model is the exception,
  and its output is captured so it is spent once, not repeatedly.
- **User edits win:** the memory `.md` managed-block convention preserves the Sovereign's corrections
  across re-learns (`source: user` pins a metric).

> This design is the concrete answer to "recreate the ability to auto-learn and map BI, connect it auto
> to the system, and have it generate skills/workflows/tools/scripts/artifacts/memory/nodes." Ready to
> build starting from §9 increment 1 on your go.
