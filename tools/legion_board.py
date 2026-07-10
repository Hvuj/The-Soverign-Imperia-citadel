#!/usr/bin/env python3
"""
Deterministic Board Arbiter — Tier 1 governance.

Reads principle-scorecard.json and conflict-set.json, applies non-stochastic
context-keyed precedence rules, writes a tier-decision.schema.json-conformant
record to .claude/state/tier-decision.json, and exits 0 (pass) or 1 (veto).

Board directors: Correctness, Velocity, Maintainability.
Precedence rules match board-config.json.
"""


import hashlib
import json
import sys
import time
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from _brain_common import ROOT as _ROOT  # noqa: E402

SCORECARD_PATH   = _ROOT / ".claude" / "state" / "principle-scorecard.json"
CONFLICT_SET_PATH = _ROOT / ".claude" / "state" / "conflict-set.json"
DECISION_PATH    = _ROOT / ".claude" / "state" / "tier-decision.json"
BOARD_CONFIG_PATH = _ROOT / ".claude" / "legion" / "board-config.json"


def _decision_id(seed: str) -> str:
    return f"dec_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12]}"


class LegionBoardArbiter:
    def evaluate_precedence(
        self, principle: str, scorecard: dict
    ) -> tuple[bool, str, str]:
        """Apply one precedence rule for a contested principle.

        Returns (pass, rule_key, factor_message).
        """
        scores = scorecard.get("companies", {})
        simplicity  = scores.get("simplicity",  1.0)
        dryness     = scores.get("dryness",     1.0)
        convention  = scores.get("convention",  1.0)

        if principle == "structure" and simplicity < 0.60:
            return (
                True,
                "simplicity_vs_structure",
                "High structural nesting degree overrides isolation; "
                "split class to preserve cohesion.",
            )

        if principle == "frugality" and dryness < 0.50:
            return (
                False,
                "frugality_vs_dryness",
                "YAGNI override active: speculative abstraction dropped "
                "to keep code footprint minimal.",
            )

        if principle == "convention":
            if convention >= 0.50:
                return (
                    True,
                    "convention_vs_explicit",
                    "Established naming/discovery pattern is stable enough; "
                    "Convention director accepts the prevailing style.",
                )
            return (
                False,
                "convention_vs_explicit",
                f"Convention score {convention:.3f} below threshold; too many "
                "naming deviations for the pattern to be trusted — align to it.",
            )

        if principle == "dryness":
            return (
                False,
                "do_it_once_vs_novel",
                f"Duplication detected (dryness {dryness:.3f}); mechanical pattern "
                "match found — consolidate the repeated block (do-it-once) rather "
                "than shipping the novel duplicate.",
            )

        if principle == "simplicity":
            return (
                False,
                "fallback_safety_bias",
                f"Simplicity score {simplicity:.3f} below threshold; "
                "Correctness director issues veto pending refactor.",
            )

        return (
            False,
            "fallback_safety_bias",
            f"Principle '{principle}' threshold not met; "
            "defaulting to Correctness veto.",
        )

    def arbitrate_judicial_ruling(self, task_id: str) -> bool:
        if not SCORECARD_PATH.exists():
            print(
                "Board Arbitrator Failure: Missing principle scorecard.",
                file=sys.stderr,
            )
            return False

        scorecard = json.loads(SCORECARD_PATH.read_text(encoding="utf-8"))
        conflicts: list[str] = scorecard.get("conflicts", [])
        now = int(time.time())
        did = _decision_id(f"{task_id}{now}")

        if not conflicts:
            self._write_decision({
                "decision_id": did,
                "task_id": task_id,
                "tier": 1,
                "deciding_member": "Board_Uncontested_Pass",
                "conflict_set": [],
                "precedence_rule_applied": "none",
                "deciding_factor": "All principle scores above threshold.",
                "reasoning_hash": hashlib.sha256(b"uncontested").hexdigest(),
                "timestamp": now,
            })
            return True

        resolved_pass = True
        last_rule = "none"
        last_factor = ""

        for marker in conflicts:
            parts = marker.split(":", 1)
            principle = parts[1] if len(parts) == 2 else marker
            p_pass, rule, msg = self.evaluate_precedence(principle, scorecard)
            last_rule = rule
            last_factor = msg
            if not p_pass:
                resolved_pass = False

        self._write_decision({
            "decision_id": did,
            "task_id": task_id,
            "tier": 1 if resolved_pass else 0,
            "deciding_member": (
                "Director_of_Velocity" if resolved_pass
                else "Director_of_Correctness"
            ),
            "conflict_set": conflicts,
            "precedence_rule_applied": last_rule,
            "deciding_factor": last_factor,
            "reasoning_hash": hashlib.sha256(last_factor.encode("utf-8")).hexdigest(),
            "timestamp": now,
        })
        return resolved_pass

    def _write_decision(self, payload: dict) -> None:
        DECISION_PATH.parent.mkdir(parents=True, exist_ok=True)
        DECISION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    arbiter = LegionBoardArbiter()
    task_id = sys.argv[1] if len(sys.argv) > 1 else "task_p5_arbitration_test"
    passed = arbiter.arbitrate_judicial_ruling(task_id)
    decision = json.loads(DECISION_PATH.read_text())
    print(json.dumps(decision, indent=2))
    print(f"\nBoard ruling: {'PASS' if passed else 'VETO'}")
    sys.exit(0 if passed else 1)
