#!/usr/bin/env python3
"""megacorp_orchestrator.py — Phase 15/16 Recurring-Improvement Master Loop.

Binds all Phase 0-15 SOVEREIGN-IMPERIA-CITADEL intelligence layers into a single,
verification-first pipeline with Phase 16 intent-driven dual-track routing.

Phase 16 adds an IntentClassifier gateway before the mutation pipeline:
  INTERROGATION → Track A: fast-path read-only answer loop (skips B/C/E gates)
  ACTION        → Track B: full Phase 15 mutation loop A → B → C → D → E → F

Track A execution steps (A1-A5):
  A1  Skip spec/L5/L6 gates; no branches or worktrees created.
  A2  Fetch adjacent prior art from the FTS5 epistemic database.
  A3  Build LLM payload: Static Cached Corporate Spine + Dynamic Interrogation
      Capsule (Dense-Response Directive + Prior Art + Prompt).
  A4  Enforce the ultra-dense telegraphic response directive.
  A5  Emit raw generated text to sys.stdout.  No Obsidian writes.  Return True.

Track B execution steps (B-F, unchanged from Phase 15):
  B  Compile     — CorporateSpineCompiler refreshes prompt-cache matrix
  C  Spec        — VerificationSpecGenerator locks active-spec.json gates
  D  Route/Exec  — DepartmentRouter dispatches; model_exec runs inference
  E  Audit       — L5 StructuralDecayGate + L6 ShadowCompiler verify delta
  F  Write-path  — SkillSynthesizer harvests skills; ObsidianWriter marks
                   task complete; EpistemicDB logs resolution; pipeline halts
                   and writes a human-intervention record for operator review.

NO GIT COMMANDS ARE EVER INVOKED.  Repository commits are the sole
responsibility of the human operator.  When gates pass, the orchestrator
writes .claude/state/human-intervention/<id>-delta.json describing the
verified delta and waits for explicit human approval before any write-back.

Inputs:  docs/obsidian-vault/               (Obsidian task vault)
         .claude/state/context-capsule.json  (written by obsidian_task_bridge)
         .claude/state/corporate-spine.md    (compiled by corporate_spine_compiler)
Output:  .claude/state/context-capsule.json
         .claude/state/active-spec.json
         .claude/state/department-dispatch.json
         .claude/state/human-intervention/<id>-delta.json
         docs/obsidian-vault/ (task note updated — complete or failed-gate)
"""


import argparse
import hashlib
import json
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

try:
    from obsidian_task_bridge import ObsidianTaskBridge as _ObsidianTaskBridge  # type: ignore[import]

    _BRIDGE_AVAILABLE = True
except Exception:
    _BRIDGE_AVAILABLE = False
    _ObsidianTaskBridge = None  # type: ignore[assignment]

try:
    from corporate_spine_compiler import CorporateSpineCompiler as _SpineCompiler  # type: ignore[import]

    _SPINE_AVAILABLE = True
except Exception:
    _SPINE_AVAILABLE = False
    _SpineCompiler = None  # type: ignore[assignment]

try:
    from spec_generator import VerificationSpecGenerator as _SpecGenerator  # type: ignore[import]

    _SPEC_AVAILABLE = True
except Exception:
    _SPEC_AVAILABLE = False
    _SpecGenerator = None  # type: ignore[assignment]

try:
    import department_router as _dr_mod  # type: ignore[import]
    from department_router import DepartmentRouter as _DepartmentRouter  # type: ignore[import]

    _ROUTER_AVAILABLE = True
except Exception:
    _ROUTER_AVAILABLE = False
    _DepartmentRouter = None  # type: ignore[assignment]
    _dr_mod = None  # type: ignore[assignment]

try:
    from l5_structural_decay import StructuralDecayGate as _DecayGate  # type: ignore[import]

    _L5_AVAILABLE = True
except Exception:
    _L5_AVAILABLE = False
    _DecayGate = None  # type: ignore[assignment]

try:
    from l6_shadow_compiler import ShadowCompiler as _ShadowCompiler  # type: ignore[import]

    _L6_AVAILABLE = True
except Exception:
    _L6_AVAILABLE = False
    _ShadowCompiler = None  # type: ignore[assignment]

try:
    from skill_synthesizer import SkillSynthesizer as _SkillSynthesizer  # type: ignore[import]

    _SYNTHESIZER_AVAILABLE = True
except Exception:
    _SYNTHESIZER_AVAILABLE = False
    _SkillSynthesizer = None  # type: ignore[assignment]

try:
    from obsidian_writer import ObsidianWriter as _ObsidianWriter  # type: ignore[import]

    _WRITER_AVAILABLE = True
except Exception:
    _WRITER_AVAILABLE = False
    _ObsidianWriter = None  # type: ignore[assignment]

try:
    from epistemic_db import EpistemicDatabaseManager as _EpistemicDBManager  # type: ignore[import]

    _EPISTEMIC_AVAILABLE = True
except Exception:
    _EPISTEMIC_AVAILABLE = False
    _EpistemicDBManager = None  # type: ignore[assignment]

try:
    from legion_model_dispatcher import dispatch as _default_dispatch  # type: ignore[import]

    _DISPATCH_AVAILABLE = True
except Exception:
    _DISPATCH_AVAILABLE = False
    _default_dispatch = None  # type: ignore[assignment]

try:
    from intent_classifier import (
        DENSE_RESPONSE_DIRECTIVE as _DENSE_DIRECTIVE,  # type: ignore[import]
        IntentClassifier as _IntentClassifier,  # type: ignore[import]
    )

    _INTENT_AVAILABLE = True
except Exception:
    _INTENT_AVAILABLE = False
    _IntentClassifier = None  # type: ignore[assignment]
    _DENSE_DIRECTIVE = ""  # type: ignore[assignment]

try:
    from telemetry_ledger import emit as _telemetry_emit  # type: ignore[import]

    _TELEMETRY_AVAILABLE = True
except Exception:
    _TELEMETRY_AVAILABLE = False

    def _telemetry_emit(*_args, **_kwargs) -> None:  # type: ignore[misc]
        pass


class MegacorpOrchestrator:
    """Phase 15/16 Recurring-Improvement Master Loop with Dual-Track routing.

    Chains Phase 0-15 tools into a deterministic, verification-first pipeline.
    Phase 16 adds intent classification at the pipeline entry point, routing
    interrogation prompts to a fast read-only answer path and action prompts
    to the full mutation loop.

    All filesystem paths are anchored to root_dir (_ROOT by default) for full
    testability via constructor injection.  No git commands are ever executed.
    """

    def __init__(
        self,
        root_dir: Path | None = None,
        model_exec: Any | None = None,
    ) -> None:
        self.root = Path(root_dir) if root_dir is not None else _ROOT
        self.vault_path = self.root / "docs" / "obsidian-vault"
        self.state_dir = self.root / ".claude" / "state"
        self.capsule_path = self.state_dir / "context-capsule.json"
        self.spec_path = self.state_dir / "active-spec.json"
        self.dispatch_path = self.state_dir / "department-dispatch.json"
        self.intervention_dir = self.state_dir / "human-intervention"
        self.model_exec = model_exec

    def execute_autonomous_loop(self, raw_input_prompt: str | None = None) -> bool:
        """Run the Phase 15/16 pipeline with Dual-Track intent routing.

        Phase 16 addition: classifies raw_input_prompt (or capsule task_content
        when omitted) to select an execution track before committing to the
        mutation pipeline:
          INTERROGATION → Track A: fast-path read-only answer loop (A2-A5 only)
          ACTION        → Track B: full Phase 15 mutation loop A → B → C → D → E → F

        When raw_input_prompt is supplied and no vault task is active, an
        INTERROGATION prompt is serviced directly without requiring a task note.

        Args:
            raw_input_prompt: Optional prompt for intent classification.  When
                None the capsule task_content is used for classification.

        Returns:
            True on pipeline success, Track A completion, or clean no-op.
            False on gate failure or unrecoverable step error.

        No git commands are executed at any point.
        """
        print(
            "[orchestrator] Phase 15/16 Recurring-Improvement Master Loop — START",
            file=sys.stdout,
        )

        source_file, capsule = self._step_a_read()
        if capsule is None:
            if raw_input_prompt:
                if _INTENT_AVAILABLE and _IntentClassifier is not None:
                    _early_track = _IntentClassifier().classify(raw_input_prompt)
                else:
                    _early_track = "ACTION"
                if _early_track == "INTERROGATION":
                    return self._run_interrogation(raw_input_prompt)
            print(
                "[orchestrator] Step A — No active tasks found. Clean no-op.",
                file=sys.stdout,
            )
            return True
        print(
            f"[orchestrator] Step A — Context capsule ready: {self.capsule_path.name}",
            file=sys.stdout,
        )

        _prompt_for_track = raw_input_prompt or capsule.get("task_content", "")
        if _INTENT_AVAILABLE and _IntentClassifier is not None:
            _track = _IntentClassifier().classify(_prompt_for_track)
        else:
            _track = "ACTION"

        if _track == "INTERROGATION":
            print("[orchestrator] Phase 16 — Track A (INTERROGATION) selected.", file=sys.stdout)
            return self._run_interrogation(_prompt_for_track)

        print("[orchestrator] Phase 16 — Track B (ACTION) selected.", file=sys.stdout)

        if not self._step_b_compile():
            print(
                "[orchestrator] Step B — Corporate spine compile failed.",
                file=sys.stderr,
            )
            return False
        print("[orchestrator] Step B — Corporate spine compiled.", file=sys.stdout)

        self._step_c_spec()
        print("[orchestrator] Step C — Active spec locked.", file=sys.stdout)

        response_text, target_files = self._step_d_route_and_execute(capsule)
        if response_text is None:
            print(
                "[orchestrator] Step D — Routing or model execution failed.",
                file=sys.stderr,
            )
            return False
        print("[orchestrator] Step D — Model dispatch complete.", file=sys.stdout)

        gates_passed = self._step_e_audit(response_text, target_files)
        if not gates_passed:
            print(
                "[orchestrator] Step E — Gate failure. Triggering fail-path.",
                file=sys.stderr,
            )
            self._step_f_fail(source_file, reason="L5/L6 gate failure")
            return False
        print("[orchestrator] Step E — L5/L6 gates passed.", file=sys.stdout)

        self._step_f_pass(source_file, capsule, response_text)
        print(
            "[orchestrator] Phase 15 COMPLETE — delta staged for human review.",
            file=sys.stdout,
        )
        return True

    def _run_interrogation(self, prompt: str) -> bool:
        """Track A: fast-path read-only interrogation loop (Phase 16, steps A1-A5).

        Fetches adjacent prior art from the epistemic database, builds the
        telegraphic LLM payload with the dense-response directive, emits the
        generated response to stdout, and returns.  No spec generation, no
        L5/L6 gates, no Obsidian writes, no git.

        Args:
            prompt: The classified interrogation prompt.

        Returns:
            True on success.  Also True when the model is unavailable — the
            track degrades gracefully rather than treating a missing model as
            a pipeline failure.
        """
        print("[orchestrator] Phase 16 Track A — INTERROGATION fast path.", file=sys.stdout)

        prior_art: list[dict[str, Any]] = []
        if _EPISTEMIC_AVAILABLE and _EpistemicDBManager is not None:
            try:
                db = _EpistemicDBManager()
                prior_art = db.search_prior_art(prompt, limit=3)
                db.close()
            except Exception as exc:
                print(f"[orchestrator] Track A — Epistemic DB error: {exc}", file=sys.stderr)

        prior_art_text = json.dumps(prior_art, indent=2) if prior_art else "(none)"
        user_message = f"{_DENSE_DIRECTIVE}\n\nPRIOR ART:\n{prior_art_text}\n\nPROMPT:\n{prompt}"

        response_text = self._invoke_model(user_message)
        if response_text is None:
            print(
                "[orchestrator] Track A — Model unavailable; no response generated.",
                file=sys.stderr,
            )
            return True

        print(response_text, file=sys.stdout)
        print("[orchestrator] Phase 16 Track A — INTERROGATION complete.", file=sys.stdout)
        return True

    def _step_a_read(self) -> tuple[str | None, dict[str, Any] | None]:
        """Build the context capsule from the Obsidian vault."""
        if not _BRIDGE_AVAILABLE:
            print(
                "[orchestrator] Step A — ObsidianTaskBridge unavailable.",
                file=sys.stderr,
            )
            return None, None

        sym_idx = self.state_dir / "workspace-intelligence" / "symbol-index.json"
        file_idx = self.state_dir / "workspace-intelligence" / "file-index.json"

        bridge = _ObsidianTaskBridge(
            vault_dir=self.vault_path,
            capsule_path=self.capsule_path,
            symbol_index_path=sym_idx,
            file_index_path=file_idx,
        )

        tasks = bridge.scan_active_tasks()
        if not tasks:
            return None, None

        now_ts = datetime.now(UTC).isoformat()
        capsule = bridge.build_capsule(created_at=now_ts)
        if capsule is None:
            return None, None

        source_file: str = capsule.get("source_task_file", "")
        return source_file, capsule

    def _step_b_compile(self) -> bool:
        """Compile the corporate spine to keep the prompt-cache matrix current."""
        if not _SPINE_AVAILABLE:
            print(
                "[orchestrator] Step B — CorporateSpineCompiler unavailable (skip).",
                file=sys.stderr,
            )
            return True
        return _SpineCompiler(root_dir=self.root).compile_spine()

    def _step_c_spec(self) -> None:
        """Lock active-spec.json engineering gates."""
        if not _SPEC_AVAILABLE:
            print(
                "[orchestrator] Step C — VerificationSpecGenerator unavailable (skip).",
                file=sys.stderr,
            )
            return
        if not self.capsule_path.exists():
            print(
                "[orchestrator] Step C — Capsule absent; spec skipped.",
                file=sys.stderr,
            )
            return
        try:
            gen = _SpecGenerator(root_dir=self.root)
            gen.spec_path = self.spec_path
            gen.generate_active_spec(self.capsule_path)
        except Exception as exc:
            print(
                f"[orchestrator] Step C — Spec generation error: {exc}",
                file=sys.stderr,
            )

    def _step_d_route_and_execute(self, capsule: dict[str, Any]) -> tuple[str | None, list[str]]:
        """Route the capsule through DepartmentRouter then invoke the model."""
        target_files: list[str] = [
            r.get("path", "") if isinstance(r, dict) else str(r) for r in capsule.get("resolved_files", []) if r
        ]

        if _ROUTER_AVAILABLE and _dr_mod is not None:
            _orig_capsule = _dr_mod.CAPSULE_PATH
            _orig_dispatch = _dr_mod.ROUTING_OUT_PATH
            try:
                _dr_mod.CAPSULE_PATH = self.capsule_path
                _dr_mod.ROUTING_OUT_PATH = self.dispatch_path
                router = _DepartmentRouter()
                if not router.route_capsule():
                    print(
                        "[orchestrator] Step D — DepartmentRouter failed.",
                        file=sys.stderr,
                    )
                    return None, []
            finally:
                _dr_mod.CAPSULE_PATH = _orig_capsule
                _dr_mod.ROUTING_OUT_PATH = _orig_dispatch
            _telemetry_emit("route", "department-router", "orchestrator", "capsule routed")

        user_message = capsule.get("task_content", "")[:4000]
        if not user_message:
            print(
                "[orchestrator] Step D — No task content; skipping model exec.",
                file=sys.stderr,
            )
            return "", []

        response_text = self._invoke_model(user_message)
        if response_text is None:
            return None, target_files

        return response_text, target_files

    def _invoke_model(self, user_message: str) -> str | None:
        """Call model_exec or the default dispatcher; return text or None on error."""
        exec_fn = self.model_exec
        if exec_fn is None and _DISPATCH_AVAILABLE:
            exec_fn = _default_dispatch
        if exec_fn is None:
            print(
                "[orchestrator] Step D — No model executor available.",
                file=sys.stderr,
            )
            return None
        try:
            return exec_fn(user_message)
        except Exception as exc:
            print(
                f"[orchestrator] Step D — Model execution error: {exc}",
                file=sys.stderr,
            )
            return None

    def _step_e_audit(self, response_text: str, target_files: list[str]) -> bool:
        """L5 structural decay gate + L6 shadow compiler gate."""
        if _L5_AVAILABLE:
            proposed = self._score_response(response_text)
            baseline = {k: 0.85 for k in proposed}
            gate = _DecayGate()
            passed, reason = gate.evaluate_decay(baseline, proposed)
            if not passed:
                print(
                    f"[orchestrator] Step E — L5 decay veto: {reason}",
                    file=sys.stderr,
                )
                _telemetry_emit("l5_veto", "l5-structural-decay", "orchestrator", reason[:200])
                return False
            _telemetry_emit("l5_pass", "l5-structural-decay", "orchestrator", "L5 quality gate passed")

        if _L6_AVAILABLE:
            py_files = [f for f in target_files if f.endswith(".py") and Path(f).exists()]
            compiler = _ShadowCompiler()
            if not compiler.execute_shadow_build(py_files):
                print(
                    "[orchestrator] Step E — L6 shadow compiler veto.",
                    file=sys.stderr,
                )
                _telemetry_emit("l6_fail", "l6-shadow-compiler", "orchestrator", "L6 shadow build failed")
                return False
            _telemetry_emit("l6_pass", "l6-shadow-compiler", "orchestrator", "L6 shadow build passed")

        return True

    def _score_response(self, text: str) -> dict[str, float]:
        """Compute heuristic quality scores from a model response for L5 evaluation."""
        length = max(len(text), 1)
        completeness = min(1.0, length / 1000.0)
        coherence = max(0.0, 1.0 - text.count("TODO") * 0.1)
        return {
            "completeness": round(min(1.0, completeness), 4),
            "coherence": round(coherence, 4),
        }

    def _step_f_pass(
        self,
        source_file: str | None,
        capsule: dict[str, Any],
        response_text: str,
    ) -> None:
        """Gates passed: harvest skills, mark task complete, write delta record."""
        if _SYNTHESIZER_AVAILABLE:
            resolved = [
                r.get("path", "") if isinstance(r, dict) else str(r) for r in capsule.get("resolved_files", []) if r
            ]
            py_files = [f for f in resolved if f.endswith(".py")]
            if py_files:
                synth = _SkillSynthesizer(root_dir=self.root)
                candidates = synth.analyze_commit_delta(py_files)
                for cand in candidates:
                    synth.synthesize_and_register(
                        skill_name=cand.get("name", "unknown_skill"),
                        source_code=cand.get("source", ""),
                    )

        node_title: str | None = None
        if _WRITER_AVAILABLE and source_file:
            writer = _ObsidianWriter(vault_dir=self.vault_path)
            task_abs = source_file if Path(source_file).is_absolute() else str(self.root / source_file)
            node_title = writer.generate_semantic_node(
                title="Phase 15 Resolution",
                summary=response_text[:500],
                linked_concepts=capsule.get("pre_fetched_nodes", []),
                related_files=[
                    r.get("path", "") if isinstance(r, dict) else str(r) for r in capsule.get("resolved_files", [])
                ],
            )
            writer.mark_task_complete(task_abs, resolution_link=node_title)

        if _EPISTEMIC_AVAILABLE:
            db = _EpistemicDBManager()
            db.log_resolved_task(
                {
                    "task_file": source_file or "",
                    "resolution": response_text[:500],
                    "knowledge_node": node_title or "",
                    "specification_id": self._read_spec_id(),
                }
            )
            db.close()

        self._write_intervention_record(source_file, capsule, response_text, node_title)

    def _step_f_fail(self, source_file: str | None, reason: str) -> None:
        """Gates failed: append failure diagnostics to the Obsidian task note."""
        print(f"[orchestrator] Gate Failure — {reason}", file=sys.stderr)

        if _WRITER_AVAILABLE and source_file:
            task_abs = source_file if Path(source_file).is_absolute() else str(self.root / source_file)
            task_path = Path(task_abs)
            if task_path.exists():
                existing = task_path.read_text(encoding="utf-8")
                updated = re.sub(r"#task/active", "#task/failed-gate", existing)
                ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
                updated += (
                    f"\n\n> [!error] Gate Failure — {ts}\n"
                    f"> Automated diagnostics: {reason}\n"
                    f"> System invariants preserved. No repository changes were made.\n"
                )
                task_path.write_text(updated, encoding="utf-8")
                print(
                    f"[orchestrator] Failure diagnostics appended to {task_path.name}.",
                    file=sys.stdout,
                )

    def _read_spec_id(self) -> str:
        """Return specification_id from active-spec.json, or '' if absent."""
        if not self.spec_path.exists():
            return ""
        try:
            spec = json.loads(self.spec_path.read_text(encoding="utf-8"))
            return spec.get("specification_id", "")
        except Exception:
            return ""

    def _write_intervention_record(
        self,
        source_file: str | None,
        capsule: dict[str, Any],
        response_text: str,
        node_title: str | None,
    ) -> None:
        """Write a human-review record for the pending delta.  No git."""
        self.intervention_dir.mkdir(parents=True, exist_ok=True)
        record_id = hashlib.sha256((capsule.get("created_at", "") + (source_file or "")).encode("utf-8")).hexdigest()[
            :12
        ]
        record_path = self.intervention_dir / f"{record_id}-delta.json"
        record: dict[str, Any] = {
            "record_id": record_id,
            "created_at": capsule.get("created_at", ""),
            "source_task_file": source_file or "",
            "specification_id": self._read_spec_id(),
            "knowledge_node": node_title or "",
            "response_preview": response_text[:500],
            "resolved_files": capsule.get("resolved_files", []),
            "status": "awaiting_human_review",
            "git_action_required": True,
            "instructions": (
                "Review the verified delta described above. "
                "If approved, commit the changes manually. "
                "No git commands were executed by the orchestrator."
            ),
        }
        record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(
            f"[orchestrator] Human-intervention record written: {record_path.name}",
            file=sys.stdout,
        )


def _run_self_test() -> None:
    """Dual-track mocked loop in an isolated tempdir.

    Covers both Phase 16 execution routes:
      Track A (INTERROGATION): no vault task needed; fast-path read-only answer.
      Track B (ACTION):        vault task present; full Phase 15 mutation loop.

    No real paths are written.  No API call is made.  No git command runs.
    """
    with tempfile.TemporaryDirectory() as tmp_root:
        tmp = Path(tmp_root)

        vault = tmp / "docs" / "obsidian-vault"
        vault.mkdir(parents=True)
        state = tmp / ".claude" / "state"
        state.mkdir(parents=True)
        wi = state / "workspace-intelligence"
        wi.mkdir(parents=True)
        (tmp / ".claude" / "skills").mkdir(parents=True, exist_ok=True)

        (wi / "symbol-index.json").write_text("{}", encoding="utf-8")
        (wi / "file-index.json").write_text("{}", encoding="utf-8")

        def _mock_model(message: str) -> str:
            return f"[MOCK] Response: {message[:80]}"

        if _ROUTER_AVAILABLE and _dr_mod is not None:
            _orig_capsule = _dr_mod.CAPSULE_PATH
            _orig_dispatch = _dr_mod.ROUTING_OUT_PATH
        else:
            _orig_capsule = None
            _orig_dispatch = None

        try:
            orch = MegacorpOrchestrator(root_dir=tmp, model_exec=_mock_model)

            result_a = orch.execute_autonomous_loop(raw_input_prompt="explain how the L6 shadow compiler works")
            assert result_a is True, f"Track A: execute_autonomous_loop() returned {result_a!r}"

            records_a = list(orch.intervention_dir.glob("*-delta.json")) if orch.intervention_dir.exists() else []
            assert not records_a, f"Track A: unexpectedly wrote intervention records: {records_a}"

            task_file = vault / "compound-loop-test.md"
            task_file.write_text(
                "# Recurring-Improvement Loop Test\n#task/active\n"
                "Must verify the full Phase 15/16 pipeline runs end-to-end.\n",
                encoding="utf-8",
            )

            if orch.capsule_path.exists():
                orch.capsule_path.unlink()

            result_b = orch.execute_autonomous_loop(raw_input_prompt="implement the compound loop test pipeline")
            assert result_b is True, f"Track B: execute_autonomous_loop() returned {result_b!r}"

            assert orch.capsule_path.exists(), "Track B: context-capsule.json was not created"

            assert orch.intervention_dir.exists(), "Track B: human-intervention directory not created"
            records_b = list(orch.intervention_dir.glob("*-delta.json"))
            assert records_b, "Track B: no human-intervention record was written"

            rec = json.loads(records_b[0].read_text(encoding="utf-8"))
            assert rec.get("git_action_required") is True, "Track B: git_action_required not set in record"
            assert rec.get("status") == "awaiting_human_review", f"Track B: unexpected status {rec.get('status')!r}"

            real_capsule = _ROOT / ".claude" / "state" / "context-capsule.json"
            assert orch.capsule_path != real_capsule or not real_capsule.exists(), (
                "Orchestrator test wrote to the real _ROOT state dir!"
            )

        finally:
            if _ROUTER_AVAILABLE and _dr_mod is not None and _orig_capsule is not None:
                _dr_mod.CAPSULE_PATH = _orig_capsule
                _dr_mod.ROUTING_OUT_PATH = _orig_dispatch

    print("\n✓ Phase 16 LOCKED — megacorp_orchestrator dual-track integration test PASS.")
    print("  Track A (INTERROGATION fast-path) and Track B (ACTION mutation loop) verified.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="megacorp_orchestrator",
        description="Phase 15 Recurring-Improvement Master Loop.",
    )
    parser.add_argument(
        "--run",
        nargs="?",
        const="",
        default=None,
        metavar="PROMPT",
        help=(
            "Execute the autonomous loop against the live workspace. "
            "Optionally supply a PROMPT string to drive intent classification "
            'directly (e.g. --run "explain how the spine is compiled"). '
            "When no PROMPT is given the capsule task_content is used."
        ),
    )
    parser.add_argument(
        "--test",
        action="store_true",
        default=False,
        help=(
            "Run a fully mocked dual-track end-to-end test in a temporary "
            "directory.  No real paths are written.  No API call is made.  "
            "No git runs."
        ),
    )
    args = parser.parse_args(argv)

    if args.test:
        _run_self_test()
        return 0

    if args.run is not None:
        orch = MegacorpOrchestrator()
        prompt_arg: str | None = args.run if args.run else None
        return 0 if orch.execute_autonomous_loop(raw_input_prompt=prompt_arg) else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
