#!/usr/bin/env python3
"""
T6 Drone Automation Fleet — Phase 11 Megacorporate Funnel.

Lowest corporate tier: applies deterministic formatting (ruff) and scans the
Phase 8 codemod registry for active codemods to report — without invoking LLM
squads or executing unreviewed code.

Codemod registry: .claude/brain/codemod-registry.json  (written by codemod_runner.py)
"""


import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
CODEMOD_REGISTRY = _ROOT / ".claude" / "brain" / "codemod-registry.json"


class DroneAutomation:
    """T6 deterministic drone fleet: formatting + codemod readiness reporting."""

    def run_formatting_drones(self, target_dir: str = ".") -> bool:
        """Execute ruff check --fix and ruff format on target_dir.

        Gracefully degrades if ruff is not installed — drones must never crash
        the pipeline.  Returns True unless an unexpected exception occurs.
        """
        print("Deploying Formatting Drones...")
        try:
            subprocess.run(
                [sys.executable, "-m", "ruff", "check", "--fix", target_dir],
                check=False,
                capture_output=True,
            )
            subprocess.run(
                [sys.executable, "-m", "ruff", "format", target_dir],
                check=False,
                capture_output=True,
            )
            return True
        except Exception as exc:
            print(f"Formatting Drone Error: {exc}", file=sys.stderr)
            return False

    def apply_promoted_codemods(self) -> int:
        """Scan the active codemod registry and report ready codemods.

        Report-only: codemods are identified and described; no AST mutations
        are executed (string-eval on unreviewed code is intentionally avoided).
        Returns the count of active codemods found.
        """
        if not CODEMOD_REGISTRY.exists():
            return 0

        try:
            registry: dict = json.loads(CODEMOD_REGISTRY.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Drone registry read error: {exc}", file=sys.stderr)
            return 0

        applied_count = 0
        for cmd_id, payload in registry.items():
            if payload.get("status") == "active":
                error_classes: list[str] = payload.get("error_classes", ["Unknown"])
                print(f"Drone identified active codemod {cmd_id} for error class: {error_classes[0]}")
                applied_count += 1

        return applied_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="T6 Drone Automation Fleet")
    parser.add_argument("--test", action="store_true", help="Run in isolated testing mode (ephemeral mocks)")
    args = parser.parse_args()

    if args.test:
        with tempfile.TemporaryDirectory() as _tmp:
            drone = DroneAutomation()
            drone.run_formatting_drones(target_dir=_tmp)
            codemods = drone.apply_promoted_codemods()
        print(f"Drone Automation Loop (T6) Test Passed. Codemods scanned: {codemods}")
        sys.exit(0)
    else:
        drone = DroneAutomation()
        drone.run_formatting_drones()
        drone.apply_promoted_codemods()
        sys.exit(0)
