#!/usr/bin/env python3
"""legion_governance.py — wires the dormant board/companies/L5/L6 governance stack
into the live legion_orchestrator pipeline instead of leaving it disconnected.

Plan company:  legion_review.py's RICE gate (via feature_improvement_store)
               approves the run PLAN before any worker is spawned.
Companies:     legion_companies.py + tools/principles/* mechanically score each
               worker's changed files (KISS/SOLID/YAGNI/DRY — zero tokens).
Board:         legion_board.py resolves contested principles and writes
               tier-decision.json — the SAME file the live `audit-gate.sh` Stop
               hook already reads (previously always absent, so its veto branch
               was dead code — see also the _ROOT path-resolution fix applied
               to legion_companies.py/legion_board.py so this file lands where
               CLAUDE_PROJECT_DIR/audit-gate.sh actually looks for it).
Validation:    l5_structural_decay.py (structural drift) + l6_shadow_compiler.py
               (sandboxed pytest) gate the merge.

All of this is deterministic/mechanical — no model calls — matching the
"zero-token-first" mandate: governance should never be the expensive part of a
run.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import feature_improvement_store as fi_store  # noqa: E402
import legion_review  # noqa: E402
from l5_structural_decay import StructuralDecayGate  # noqa: E402
from l6_shadow_compiler import ShadowCompiler  # noqa: E402
from legion_board import DECISION_PATH, LegionBoardArbiter  # noqa: E402
from legion_companies import SCORECARD_PATH, LegionCompaniesManager  # noqa: E402

_CONFLICT_THRESHOLD = 0.70

LEGION_PLAN_DEFAULT_THRESHOLD = 1.0
"""Distinct from fi_store.DEFAULT_APPROVE_THRESHOLD (5.0): that default is
calibrated for feature-improvement proposals, whose `reach` values are
typically tens. A run's `reach` is its (small: 1-8) worker count, so
reusing the 5.0 threshold verbatim would reject every plan by construction —
this is the threshold actually calibrated for this domain."""


@dataclass(slots=True)
class GateResult:
    approved: bool
    reason: str
    detail: dict = field(default_factory=dict)


def plan_gate(
    task: str, num_workers: int, *,
    impact: float = 3.0, confidence: float = 0.7, threshold: float = LEGION_PLAN_DEFAULT_THRESHOLD,
) -> GateResult:
    """The "plan company": run the legion-run plan itself through the RICE gate
    before any worker is spawned. `reach` scales with worker count (breadth of
    the run); `effort` is the fixed cost of running the orchestrator once — it
    does NOT scale with worker count, since per-worker cost is separately
    capped by `efficiency_gate.check_worker_count`. A plan with low confidence
    or low impact is mechanically rejected, not just advised against in prose.
    """
    rice = {"reach": max(1, num_workers), "impact": impact, "confidence": confidence, "effort": 1}
    proposal = fi_store.propose(
        title=f"run: {task[:80]}",
        source="legion_orchestrator",
        target="legion-run",
        scope_e2e=task,
        why="parallel run plan approval",
        rice=rice,
    )
    reviewed = legion_review.review(proposal["id"], threshold)
    if not reviewed:
        return GateResult(approved=False, reason="plan review failed to run", detail={})
    approved = reviewed.get("status") == "approved"
    reason = reviewed.get("review_reason") or "approved"
    return GateResult(approved=approved, reason=reason, detail=reviewed)


def score_companies(changed_files: list[str], task_id: str) -> dict:
    """Run the mechanical KISS/SOLID/YAGNI/DRY scorecard over changed files.

    Multiple files are aggregated by keeping the worst (lowest) score per
    principle — one badly-structured file should not be diluted by many clean
    ones when deciding whether the board should contest anything.
    """
    if not changed_files:
        scorecard = {
            "task_id": task_id,
            "diff_hash": "no_changes",
            "companies": dict.fromkeys(
                ["simplicity", "frugality", "structure", "dryness",
                 "decoupling", "encapsulation", "convention", "craft"], 1.0,
            ),
            "conflicts": [],
            "board_decision_id": None,
        }
        SCORECARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCORECARD_PATH.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
        return scorecard

    manager = LegionCompaniesManager()
    aggregate: dict[str, float] | None = None
    for f in changed_files:
        scores = manager.evaluate_workspace_changes(f, task_id)["companies"]
        aggregate = dict(scores) if aggregate is None else {k: min(aggregate[k], scores[k]) for k in aggregate}

    conflicts = [f"contested_threshold:{name}" for name, value in aggregate.items() if value < _CONFLICT_THRESHOLD]
    scorecard = {
        "task_id": task_id,
        "diff_hash": "aggregate",
        "companies": aggregate,
        "conflicts": conflicts,
        "board_decision_id": None,
    }
    SCORECARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCORECARD_PATH.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
    return scorecard


def board_ruling(task_id: str) -> GateResult:
    """Run the board arbiter. Writes tier-decision.json, feeding the live audit-gate.sh veto branch."""
    passed = LegionBoardArbiter().arbitrate_judicial_ruling(task_id)
    decision = json.loads(DECISION_PATH.read_text(encoding="utf-8")) if DECISION_PATH.exists() else {}
    return GateResult(approved=passed, reason=decision.get("deciding_factor", "no scorecard"), detail=decision)


def validation_gates(changed_files: list[str]) -> GateResult:
    """L5 structural-decay veto, then L6 sandboxed-pytest veto (cheapest check first)."""
    if not StructuralDecayGate().run_gate():
        return GateResult(approved=False, reason="L5 structural decay veto")

    py_files = [f for f in changed_files if f.endswith(".py") and Path(f).exists()]
    if py_files and not ShadowCompiler().execute_shadow_build(py_files):
        return GateResult(approved=False, reason="L6 shadow-compiler veto (sandboxed pytest failed)")

    return GateResult(approved=True, reason="L5 + L6 passed")


def run_full_gate(task_id: str, changed_files: list[str]) -> GateResult:
    """Companies score -> board rules -> L5/L6 validate. Run once per worker at completion."""
    score_companies(changed_files, task_id)
    ruling = board_ruling(task_id)
    if not ruling.approved:
        return GateResult(approved=False, reason=f"board veto: {ruling.reason}", detail=ruling.detail)

    validated = validation_gates(changed_files)
    if not validated.approved:
        return GateResult(approved=False, reason=validated.reason, detail=validated.detail)

    return GateResult(approved=True, reason="companies + board + L5/L6 all passed")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the legion governance pipeline standalone.")
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument("--stage", choices=["plan", "full"], default="full")
    ap.add_argument("--task", default="")
    ap.add_argument("--num-workers", type=int, default=1)
    ap.add_argument("--impact", type=float, default=3.0)
    ap.add_argument("--confidence", type=float, default=0.7)
    ap.add_argument("--threshold", type=float, default=LEGION_PLAN_DEFAULT_THRESHOLD)
    args = ap.parse_args()

    if args.stage == "plan":
        result = plan_gate(
            args.task, args.num_workers, impact=args.impact, confidence=args.confidence, threshold=args.threshold,
        )
    else:
        result = run_full_gate(args.task_id, args.files)

    print("GATE_RESULT:" + json.dumps({"approved": result.approved, "reason": result.reason}))
    raise SystemExit(0 if result.approved else 1)


if __name__ == "__main__":
    main()
