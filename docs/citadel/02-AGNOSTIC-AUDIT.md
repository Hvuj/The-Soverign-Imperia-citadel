# 02 â€” Agnostic Audit & Domain-Removal Map

> Every place the code is **not workspace-agnostic** â€” domain/brand/repo/person/OS assumptions baked
> into logic â€” plus the exact map for removing the BI subsystem and all domain vocabulary. (Tasks 4, 7,
> 10, code side.)
>
> **Scope note:** the *data* clean-slate is done ([03](03-CLEAN-SLATE-LOG.md)). The *code* changes below
> are **mapped, not executed** â€” per the Sovereign's "do not build yet" constraint, and because several
> are coordinated multi-file refactors (removing BI alone touches the 28 KB orchestrator) that would
> leave the tree broken if done piecemeal. Each item has a severity and a build action.

## A. Hardcoded domain vocabulary (the core agnosticism problem)

The Citadel claims to be workspace-agnostic, but domain vocabulary (airline/BI + a specific data-stack:
the orchestrator/Parallel-compute/schema validation/dataframe lib) is compiled into central logic. A truly agnostic Citadel must **learn**
this vocabulary per-province, not ship it.

| # | File:line | What's hardcoded | Fix (build action) |
|---|---|---|---|
| A-1 | `tools/_workspace_intel_common.py:511-573` | A whole alias/synonym table: `sample_feature`, `sample_rate`, `orchestration`, `schema-validation`, `distributed_store`, "currency conversion", etc. | **Biggest offender.** Move to a per-province learned alias index (`alias-index.json`, already exists) built from the mined workspace; ship an empty table. |
| A-2 | `tools/classify_prompt.py:27-43` | Task-type keyword maps hardcode `parallel-compute, dataframe, orchestration, config-model, bdd` | Make the task taxonomy config-driven (`.claude/brain/*`), learn domain keywords per province |
| A-3 | `tools/build_execution_manifest.py:122-123`, `execution_manifest_lint.py:44-45` | `orchestration-specialist`/`parallel-compute-specialist` â†’ hardcoded framework keyword lists | Load specialist keyword sets from config; specialists become optional domain adapters |
| A-4 | `tools/brain_task_scheduler.py:13-15` | domain keyword lists (`parallel-compute, dataframe, orchestration, config-model, bdd`) | config-driven |
| A-5 | `tools/build_capsule_cache.py:32` | `"orchestration": "orchestration", "parallel-compute": "parallel-compute", "sql": "sql"` topic map | config-driven / learned |
| A-6 | `tools/department_router.py:33` | `"Data_Dept": [..., "orchestration", "dataframe", "spark", "dbt", ...]` | config-driven department map |
| A-7 | `tools/dir_brain_mapper.py:58-59,106` | tags a dir "orchestration" and labels it "the orchestrator assets / pipeline definitions" | learn dir purpose from signatures, not a hardcoded framework name |
| A-8 | `tools/build_workspace_intelligence_index.py:96,471,480` | `orchestration_config`, "parallel-compute" special-casing in import handling | generalize to a pluggable framework-detector |

**Principle for the rebuild:** the Citadel ships with **zero** domain vocabulary. Domain knowledge is
learned when it maps a province (via the workspace-intelligence indexes + git mining) and stored in the
province's own brain, never in shared library code. This is what makes it genuinely agnostic *and*
self-learning at once.

## B. BI subsystem â€” removal (tasks 4 & 10) â€” âœ… EXECUTED

> **Done.** The BI code was removed as one coordinated change and verified against the test baseline
> (192 passed, 16 failed, 1 error â€” no new failures; the drop from 206 is exactly the removed BI tests).
> Removed: `tools/bi_logic_discoverer.py`, `tools/bi_understanding.py`, `tools/add_bi_logic.py`,
> `tests/test_bi_understanding.py`, `tests/test_bi_logic_discoverer.py`; the orchestrator's
> `MODE_BI_LEARN`/`_bi_learn_prompt`/`_prepare_bi_learn`/persist path/registry entry; the `citadel bi`
> CLI command and `bi-learn` mode; and the BI cases in `test_legion_modes.py`/`test_bug_regressions.py`.
> **It is being recreated properly** as the agnostic, generative **BI Cartographer** â€” see
> [06-BI-AUTOLEARN.md](06-BI-AUTOLEARN.md).
>
> The template-side BI artifacts (BI agents/rule/skill/schema/configs in the `.citadel/.claude/` template
> that ships in the wheel) remain to be removed when the curated agnostic template is committed
> ([05 Â§2](05-PACKAGING-AND-INSTALL.md)). Original removal order, for reference:

| Order | File | Action |
|---|---|---|
| 1 | `tools/bi_logic_discoverer.py` | delete (airline BI vocab at `:35-36`) |
| 2 | `tools/bi_understanding.py` | delete (imports `bi_logic_discoverer`) |
| 3 | `tools/add_bi_logic.py` | delete (delegates to discoverer) |
| 4 | `tools/legion_orchestrator.py` | remove `import bi_understanding` (`:37`), `MODE_BI_LEARN` (`:91,93`), `_bi_learn_prompt` (`:147`), `_prepare_bi_learn` (`:489`), the `persist` call (`:375`), and every `MODE_BI_LEARN` dispatch (`:178,302,565,609,648`). Reduce `--mode` to `{task, benchmark}` |
| 5 | `src/citadel/cli.py` | remove `_cmd_bi` (`:61-86`), the `bi` subparser (`:377-386`), and `bi-learn` from `--mode` choices (`:368`) |
| 6 | `tools/token_ledger.py:63` | drop the "bi-learn" mention from the comment |
| 7 | `tests/test_bi_understanding.py`, `tests/test_bi_logic_discoverer.py` | delete |
| 8 | `tests/test_legion_modes.py` | remove the 4 `bi_learn` test cases (`:22-107`) |
| 9 | `tests/test_bug_regressions.py:3,19` | remove/replace the `bi_logic_discoverer` regression (B1) |
| 10 | `tests/test_build_workspace_intelligence_index.py:62` | drop the BI mention in the docstring |
| 11 | Template (zip/installed): `.claude/agents/{bi-logic-validator,bi-doc-curator,metric-semantics-reviewer}.md`, `.claude/skills/bi-logic-review/`, `.claude/rules/bi-logic.md`, `.claude/schemas/bi-understanding.schema.json` | **reconstruct agnostic** — kept as standing agents renamed `domain-logic-validator` / `domain-doc-curator` / `semantics-reviewer` (learn per-workspace); BI-named skill/rule/schema dropped |
| 12 | Template configs: `workflow-manifest-config.json` (`bi_logic` task type + signals), `scheduler-config.json`, `memory-policy.json` (`sample_feature_join_rule`), `graph-aware-config.json` (bi aliases), `model-selection-policy` | remove BI entries |
| 13 | `tools/scheduler_lint.py:34,64` | **stop requiring `sample_feature_join_rule`** in `memory-policy.json` â€” a lint that fails without a sample-feature BI rule is the opposite of agnostic (see C-4) |

## C. Domain-specific tools & lints

| # | File | Issue | Build action |
|---|---|---|---|
| C-1 | `tools/pipeline_walker.py` | Entirely the orchestrator-specific (clientâ†’jobâ†’assetâ†’op) | Make it a pluggable "province pipeline" adapter, or move to an optional domain pack |
| C-2 | `tools/summarize_orchestration_log.py` | the orchestrator-only log summarizer | optional domain pack |
| C-3 | `tools/legion_review.py:74` | hardcoded `uv run the app` startup check | generalize to a per-province validation command from config |
| C-4 | `tools/scheduler_lint.py:34,64` | **requires** `sample_feature_join_rule` key to exist | remove; the agnostic Citadel has no sample-feature rule |
| C-5 | `tools/obsidian_intent_daemon.py:380,412` | demo/test strings use "a sample feature"/"schema-validation" | replace with neutral fixtures |
| C-6 | `tools/auto_memory_compactor.py:172-173` | the orchestrator/AWS-S3 strings in what appear to be test fixtures | neutralize |
| C-7 | `tools/bug_extractor.py:161` | `/home/user/project/models.py` fixture path | neutralize (also OS-specific) |

## D. Hardcoded machine / OS paths (agnostic + portability)

| # | File:line | Issue | Build action |
|---|---|---|---|
| D-1 | `tools/legion_model_dispatcher.py:147` | `cli_cwd = "/tmp"` â†’ `subprocess` `cwd=/tmp` crashes on Windows | `tempfile.gettempdir()` |
| D-2 | `tools/model_backend.py:142,159,442` | `/proc/meminfo`, `/models` â€” Linux-only | cross-platform probes (ctypes on Windows; `CITADEL_MODELS_DIR`) |
| D-3 | `tools/spec_generator.py:37` | `/tmp` literal | `tempfile.gettempdir()` |
| D-4 | `tools/dir_brain_hook.py:18` | `PATH_RE` matched only a macOS home-path shape | ✅ fixed: now cross-platform (Windows drive + posix home) |
| D-5 | Template `.claude/settings.local.json` (zip) | `additionalDirectories` + a hook hardcode `${CLAUDE_PROJECT_DIR}/../...` and macOS app paths | derive from `$CLAUDE_PROJECT_DIR`/`CITADEL_WORKSPACE`; ship no personal paths |
| D-6 | Template `.citadel/config.toml` (zip) | `root`/`scan_root` hardcoded to the original machine | generate at `citadel init` time |

> D-1/D-2 also appear in [../system-map/16](../system-map/16-repo-state-findings.md) as portability
> bugs; they are re-listed here because a hardcoded OS path is *also* a non-agnostic assumption.

## E. Duplicate "dirty" asset copies (ship in the wheel)

Several files exist **twice** â€” once in the working tree and once under `src/citadel/assets/`
(the seed baked into the wheel and installed by `citadel init`). Scrubbing only the working-tree copy
leaves the installed system dirty:

| Working-tree copy (cleaned) | Asset copy (still dirty) |
|---|---|
| `docs/ai-context/model-selection-policy.md` | `src/citadel/assets/ai-context/model-selection-policy.md:38,58` (orchestration/parallel-compute lines) |
| `docs/brain/workspace.{html,css,js}` | `src/citadel/assets/docs_seed/brain/workspace.{html,css,js}` (the orchestrator/schema validation badges, "a sample feature" placeholder) |

**Build action:** the seed assets are the source of truth for a fresh install â€” scrub them the same way
and add a lint (`scaffold_integrity_lint`) that fails if a seed asset contains a brand/domain token.

## F. The one file that *should* keep brand names

`tools/brand_lint.py` **intentionally** contains brand/vendor names â€” it is the guardian that detects
non-agnostic content. **Keep it**, but: (1) make its brand list configurable (the Sovereign's own
learned names may legitimately appear), and (2) point it at the seed assets (E) so it enforces
agnosticism at build time.

## G. Summary â€” what "agnostic" requires from the rebuild

1. **Ship zero domain vocabulary.** No airline/BI/the orchestrator/schema validation terms in shared library code (A, B, C).
2. **Learn domain knowledge per province**, into that province's own brain â€” never shared code.
3. **Derive every path** from `CITADEL_WORKSPACE`/`$CLAUDE_PROJECT_DIR`/`tempfile`, never a literal (D).
4. **Scrub the seed assets**, not just the working tree, and lint them (E, F).
5. **Config drives behavior**, so a province's domain is data the Citadel reads, not code it is.

This is the concrete meaning of "map out if there is any logic that is not agnostic" â€” and the fix
list that makes the Citadel installable into *any* workspace with no trace of the one it was born in.
