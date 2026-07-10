#!/usr/bin/env python3
"""
Legion Companies Advocate — T1 advocacy orchestrator.

Reads the principle-scorecard from Phase 3, identifies contested principles,
and dispatches parallel T1 local inference jobs to generate architectural
arguments. Outputs a conflict-set.json for the Tier 1 Board.
"""


import concurrent.futures
import json
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from model_backend import execute_t1_local_mock  # noqa: E402

_ROOT = _TOOLS_DIR.parent
SCORECARD_PATH = _ROOT / ".claude" / "state" / "principle-scorecard.json"
CONFLICT_SET_PATH = _ROOT / ".claude" / "state" / "conflict-set.json"
SKILLS_DIR = _ROOT / ".claude" / "skills"

_PLAYBOOK_MAP: dict[str, str] = {
    "simplicity":    "kiss-playbook.md",
    "frugality":     "yagni-playbook.md",
    "structure":     "solid-playbook.md",
    "dryness":       "dry-playbook.md",
    "decoupling":    "solid-playbook.md",
    "encapsulation": "solid-playbook.md",
    "convention":    "kiss-playbook.md",
    "craft":         "dry-playbook.md",
}


class LegionCompaniesAdvocate:
    def run_advocacy_for_principle(self, principle: str, task_id: str) -> dict:
        skill_file = SKILLS_DIR / _PLAYBOOK_MAP.get(principle, "solid-playbook.md")
        skill_guidance = skill_file.read_text(encoding="utf-8") if skill_file.exists() else ""
        prompt = (
            f"Task: {task_id}. "
            f"Defend the code through the lens of {principle}. "
            f"Guidelines:\n{skill_guidance}"
        )
        t1 = execute_t1_local_mock(prompt, "company_advocacy_arguments")
        return {
            "company": principle,
            "argument": (
                f"Advocate Insight: {t1['mock_response']} "
                f"— Protect code against {principle} violations."
            ),
            "tier_used": t1["tier_used"],
        }

    def deliberate_contested_changes(self) -> dict:
        if not SCORECARD_PATH.exists():
            return {"status": "error", "message": "No active principle scorecard found."}

        scorecard = json.loads(SCORECARD_PATH.read_text(encoding="utf-8"))
        task_id = scorecard["task_id"]

        contested = [
            conflict.split(":", 1)[1]
            for conflict in scorecard.get("conflicts", [])
            if conflict.startswith("contested_threshold:")
        ]

        if not contested:
            result: dict = {
                "task_id": task_id,
                "is_contested": False,
                "arguments": [],
            }
            CONFLICT_SET_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFLICT_SET_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
            return result

        arguments: list[dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(contested)) as pool:
            future_map = {
                pool.submit(self.run_advocacy_for_principle, p, task_id): p
                for p in contested
            }
            for future in concurrent.futures.as_completed(future_map):
                principle = future_map[future]
                try:
                    arguments.append(future.result())
                except Exception as exc:
                    arguments.append({
                        "company": principle,
                        "argument": f"Advocacy fault: {exc}",
                        "tier_used": "error",
                    })

        result = {
            "task_id": task_id,
            "is_contested": True,
            "arguments": arguments,
        }
        CONFLICT_SET_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFLICT_SET_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


if __name__ == "__main__":
    advocate = LegionCompaniesAdvocate()
    res = advocate.deliberate_contested_changes()
    print(json.dumps({"phase_4_advocacy_resolution": res}, indent=2))
    assert CONFLICT_SET_PATH.exists(), "conflict-set.json not written"
    print("smoke test: PASS")
    sys.exit(0)
