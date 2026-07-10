#!/usr/bin/env python3
"""
T0 Department Router — Phase 11 Megacorporate Funnel.

Reads the Phase 10 context capsule and deterministically routes the active task
to a corporate department (Backend_Dept / Frontend_Dept / Data_Dept / DevOps_Dept)
plus a list of ephemeral squads.

Capsule:  .claude/state/context-capsule.json   (written by obsidian_task_bridge.py)
Dispatch: .claude/state/department-dispatch.json
"""


import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
CAPSULE_PATH = _ROOT / ".claude" / "state" / "context-capsule.json"
ROUTING_OUT_PATH = _ROOT / ".claude" / "state" / "department-dispatch.json"


class DepartmentRouter:
    """Deterministic department routing based on capsule symbols and file paths."""

    def __init__(self) -> None:
        self.department_signatures: dict[str, list[str]] = {
            "Frontend_Dept": ["components/", "ui/", "views/", "react", "vue", "css", "html", "jsx", "tsx"],
            "Backend_Dept": ["api/", "models/", "controllers/", "auth", "db", "sql", "fastapi", "django"],
            "Data_Dept": ["etl/", "pipelines/", "orchestration", "dframe", "spark", "dbt", "warehouse"],
            "DevOps_Dept": [".github/", "docker", "k8s", "terraform", "ci", "cd", "deploy"],
        }

    def route_capsule(self) -> bool:
        """Read the context capsule and write a department dispatch payload.

        Returns True on success, False on any failure.
        """
        if not CAPSULE_PATH.exists():
            print(
                "Routing Error: context-capsule.json not found. Run Phase 10 funnel first.",
                file=sys.stderr,
            )
            return False

        try:
            capsule: dict[str, Any] = json.loads(CAPSULE_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Routing Error: failed to parse context capsule — {exc}", file=sys.stderr)
            return False

        parts: list[str] = []
        parts += capsule.get("pre_fetched_nodes", [])
        parts += capsule.get("alias_symbols", [])
        parts += capsule.get("resolved_files", [])
        parts.append(capsule.get("task_content", ""))
        search_corpus = " ".join(parts).lower()

        scores: dict[str, int] = {dept: 0 for dept in self.department_signatures}
        for dept, signatures in self.department_signatures.items():
            for sig in signatures:
                if sig.lower() in search_corpus:
                    scores[dept] += 1

        target_dept = max(scores, key=scores.get) if any(scores.values()) else "Backend_Dept"

        dispatch_payload: dict[str, Any] = {
            "source_task_file": capsule.get("source_task_file"),
            "assigned_department": target_dept,
            "department_confidence_scores": scores,
            "required_squads": self._determine_squads(target_dept, search_corpus),
            "status": "dispatched_to_tier_5",
        }

        try:
            ROUTING_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            ROUTING_OUT_PATH.write_text(json.dumps(dispatch_payload, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"Routing Error: failed to write dispatch payload — {exc}", file=sys.stderr)
            return False

        print(f"Task routed to {target_dept}. Dispatch written to {ROUTING_OUT_PATH.name}.")
        return True

    def _determine_squads(self, dept: str, corpus: str) -> list[str]:
        """Map tool requirements to ephemeral squads within the department."""
        squads: list[str] = []
        if dept == "Backend_Dept":
            squads.append("api-squad")
            if "db" in corpus or "sql" in corpus or "model" in corpus:
                squads.append("database-squad")
        elif dept == "Frontend_Dept":
            squads.append("ui-squad")
        if "test" in corpus or "validate" in corpus:
            squads.append("validation-squad")
        return squads or ["generalist-squad"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="T0 Megacorporate Department Router")
    parser.add_argument("--test", action="store_true", help="Run in isolated testing mode (ephemeral mocks)")
    args = parser.parse_args()

    if args.test:
        with tempfile.TemporaryDirectory() as _tmp:
            tmp = Path(_tmp)

            CAPSULE_PATH = tmp / "context-capsule.json"
            ROUTING_OUT_PATH = tmp / "department-dispatch.json"

            mock_capsule: dict[str, Any] = {
                "source_task_file": "Task_API_Endpoint.md",
                "task_content": "Build new user auth endpoint with login and token refresh.",
                "pre_fetched_nodes": ["Auth Rules", "API Standards"],
                "alias_symbols": ["fastapi"],
                "resolved_files": ["api/auth.py", "models/user.py"],
                "warnings": [],
                "status": "ready_for_routing",
            }
            CAPSULE_PATH.write_text(json.dumps(mock_capsule, indent=2), encoding="utf-8")

            router = DepartmentRouter()
            success = router.route_capsule()

            if success and ROUTING_OUT_PATH.exists():
                result: dict[str, Any] = json.loads(ROUTING_OUT_PATH.read_text(encoding="utf-8"))
                assert result["assigned_department"] == "Backend_Dept", (
                    f"Expected Backend_Dept, got {result['assigned_department']}"
                )
                assert "api-squad" in result["required_squads"], (
                    f"Expected api-squad in {result['required_squads']}"
                )
                print("Department Router (T0) Test Passed.")
                sys.exit(0)

        print("Department Router (T0) Test Failed.", file=sys.stderr)
        sys.exit(1)
    else:
        router = DepartmentRouter()
        sys.exit(0 if router.route_capsule() else 1)
