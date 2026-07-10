#!/usr/bin/env python3
"""
L5 Structural Decay Gate — Phase 12 Extended Epistemic Engine.

Reads the active principle scorecard and compares per-principle scores against
a deterministic 0.85 baseline. If any structural score decays by more than the
5% tolerance budget, the gate mathematically vetoes the proposed change.

Scorecard: .claude/state/principle-scorecard.json
"""


import argparse
import json
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from _brain_common import ROOT as _ROOT  # noqa: E402

SCORECARD_PATH = _ROOT / ".claude" / "state" / "principle-scorecard.json"

_STRUCTURAL_PRINCIPLES = ("simplicity", "structure", "frugality", "dryness")


class StructuralDecayGate:
    """Deterministic L5 gate: veto commits that degrade structural quality."""

    def __init__(self, tolerance_budget: float = 0.05) -> None:
        self.tolerance_budget = tolerance_budget

    def evaluate_decay(
        self,
        baseline_scores: dict[str, float],
        proposed_scores: dict[str, float],
    ) -> tuple[bool, str]:
        """Compare per-principle scores; return (passed, reason).

        For each structural principle, drift = baseline − proposed.
        If drift exceeds the tolerance budget, return (False, reason).
        """
        for principle in _STRUCTURAL_PRINCIPLES:
            baseline = baseline_scores.get(principle, 1.0)
            proposed = proposed_scores.get(principle, 1.0)

            drift = baseline - proposed

            if drift > self.tolerance_budget:
                reason = (
                    f"L5 Decay Veto: '{principle}' degraded by {drift:.2f}"
                    f" (Budget: {self.tolerance_budget:.2f})."
                )
                print(reason, file=sys.stderr)
                return False, reason

        print(
            "L5 Structural Decay Pass: Proposed changes are within acceptable complexity budgets.",
            file=sys.stdout,
        )
        return True, "passed"

    def run_gate(self) -> bool:
        """Read the active scorecard and compare against the deterministic baseline.

        Returns True (pass) or False (veto).
        """
        if not SCORECARD_PATH.exists():
            print("L5 Gate Skipped: No active principle scorecard.", file=sys.stdout)
            return True

        try:
            scorecard: dict[str, Any] = json.loads(SCORECARD_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"L5 Gate Error: Could not read scorecard — {exc}", file=sys.stderr)
            return False

        proposed: dict[str, float] = scorecard.get("companies", {})
        baseline: dict[str, float] = {k: 0.85 for k in proposed}

        passed, _ = self.evaluate_decay(baseline, proposed)
        return passed


def main() -> None:
    parser = argparse.ArgumentParser(description="L5 Structural Decay Gate")
    parser.add_argument("--test", action="store_true", help="Run in isolated testing mode")
    args = parser.parse_args()

    if args.test:
        gate = StructuralDecayGate(tolerance_budget=0.05)

        pass_1, _ = gate.evaluate_decay({"simplicity": 0.90}, {"simplicity": 0.88})
        pass_2, _ = gate.evaluate_decay({"simplicity": 0.90}, {"simplicity": 0.70})

        if pass_1 and not pass_2:
            print("L5 Structural Decay Gate (T0) Test Passed.")
            sys.exit(0)
        else:
            print("L5 Structural Decay Gate (T0) Test Failed.", file=sys.stderr)
            sys.exit(1)
    else:
        sys.exit(0 if StructuralDecayGate().run_gate() else 1)


if __name__ == "__main__":
    main()
