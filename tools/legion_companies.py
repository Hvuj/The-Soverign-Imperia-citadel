#!/usr/bin/env python3
"""
Legion Companies Manager — orchestrates all T0 mechanical principle checkers.

Runs all eight principle analyzers (KISS, YAGNI, SOLID, DRY, LoD/decoupling,
OOP/encapsulation, CoC/convention, Craft) concurrently over a target file,
produces a principle-scorecard.schema.json-conformant record, flags conflicts
below threshold, and persists to .claude/state/principle-scorecard.json.
"""


import concurrent.futures
import json
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from _brain_common import ROOT as _ROOT  # noqa: E402
from principles import (  # noqa: E402
    convention,
    craft,
    decoupling,
    dry,
    encapsulation,
    kiss,
    solid,
    yagni,
)

SCORECARD_PATH = _ROOT / ".claude" / "state" / "principle-scorecard.json"

_CONFLICT_THRESHOLD = 0.70


class LegionCompaniesManager:
    def evaluate_workspace_changes(self, target_file_path: str, task_id: str) -> dict:
        path = str(Path(target_file_path))

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            f_kiss          = pool.submit(kiss.analyze_file,          path)
            f_solid         = pool.submit(solid.analyze_file,         path)
            f_yagni         = pool.submit(yagni.analyze_file,         path)
            f_dry           = pool.submit(dry.analyze_file,           path)
            f_decoupling    = pool.submit(decoupling.analyze_file,    path)
            f_encapsulation = pool.submit(encapsulation.analyze_file, path)
            f_convention    = pool.submit(convention.analyze_file,    path)
            f_craft         = pool.submit(craft.analyze_file,         path)

        scores = {
            "simplicity":    round(f_kiss.result(),          4),
            "frugality":     round(f_yagni.result(),         4),
            "structure":     round(f_solid.result(),         4),
            "dryness":       round(f_dry.result(),           4),
            "decoupling":    round(f_decoupling.result(),    4),
            "encapsulation": round(f_encapsulation.result(), 4),
            "convention":    round(f_convention.result(),    4),
            "craft":         round(f_craft.result(),         4),
        }

        conflicts = [
            f"contested_threshold:{name}"
            for name, value in scores.items()
            if value < _CONFLICT_THRESHOLD
        ]

        scorecard: dict = {
            "task_id": task_id,
            "diff_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "companies": scores,
            "conflicts": conflicts,
            "board_decision_id": None,
        }

        SCORECARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCORECARD_PATH.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")

        return scorecard


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Run the 8-principle best-practices scorecard on a file.")
    ap.add_argument("--file", default="tools/model_backend.py", help="Python file to score")
    ap.add_argument("--task-id", default="task_p3_verify", help="Task id recorded in the scorecard")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    result = LegionCompaniesManager().evaluate_workspace_changes(args.file, args.task_id)
    print(json.dumps(result, indent=2) if args.as_json else json.dumps(result))


if __name__ == "__main__":
    main()
