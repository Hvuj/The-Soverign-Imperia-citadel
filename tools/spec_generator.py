#!/usr/bin/env python3
"""spec_generator.py — Phase 15 Verification-First Spec Generator.

Reads the Phase 10 context capsule (.claude/state/context-capsule.json) and
produces a strict architectural specification file at
.claude/state/active-spec.json before any implementation code is written.

The spec locks down constraints, filesystem edge-case risks, and the exact
verification criteria (unit-test file + method) that must pass cleanly before
task resolution is declared.

Inputs:  .claude/state/context-capsule.json  (written by obsidian_task_bridge.py)
Output:  .claude/state/active-spec.json
"""


import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CAPSULE = _ROOT / ".claude" / "state" / "context-capsule.json"
_DEFAULT_SPEC_OUT = _ROOT / ".claude" / "state" / "active-spec.json"

_CONSTRAINT_MARKERS: frozenset[str] = frozenset({"must", "shall", "constraint", "required", "MUST", "never", "always"})

_EDGE_CASE_PATTERNS: tuple[str, ...] = (
    "rmtree",
    "shutil",
    "delete",
    "unlink",
    "_ROOT",
    "/tmp",
    "tempfile",
    "cross-repo",
    "../",
    "absolute path",
)


class VerificationSpecGenerator:
    """Maps a Phase 10 context capsule to a strict architectural specification.

    The spec is written to .claude/state/active-spec.json and acts as an
    engineering gate that must be satisfied before any implementation begins.
    All paths are anchored to _ROOT (or an injectable root_dir for testing).
    """

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root = Path(root_dir) if root_dir is not None else _ROOT
        self.state_dir = self.root / ".claude" / "state"
        self.capsule_path = self.state_dir / "context-capsule.json"
        self.spec_path = self.state_dir / "active-spec.json"

    def generate_active_spec(self, capsule_path: Path) -> Path:
        """Read a context capsule and write a verified spec to active-spec.json.

        Args:
            capsule_path: Absolute path to a valid context-capsule.json.

        Returns:
            Path to the written active-spec.json.

        Raises:
            FileNotFoundError: If capsule_path does not exist.
            json.JSONDecodeError: If the capsule is not valid JSON.
        """
        capsule: dict[str, Any] = json.loads(capsule_path.read_text(encoding="utf-8"))

        task_content: str = capsule.get("task_content", "")
        created_at: str = capsule.get("created_at", "")

        spec_id = "spec-" + hashlib.sha256((task_content + created_at).encode("utf-8")).hexdigest()[:12]

        target_constraints = self._extract_constraints(task_content)
        edge_cases = self._identify_edge_cases(task_content)
        verification_criteria = self._resolve_verification_criteria(capsule)

        spec: dict[str, Any] = {
            "specification_id": spec_id,
            "target_constraints": target_constraints,
            "edge_cases_identified": edge_cases,
            "verification_criteria": verification_criteria,
        }

        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")

        print(
            f"[spec_generator] Active spec written: {self.spec_path.name} "
            f"(id={spec_id}, "
            f"constraints={len(target_constraints)}, "
            f"edge_cases={len(edge_cases)})",
            file=sys.stdout,
        )
        return self.spec_path

    def _extract_constraints(self, content: str) -> list[str]:
        """Return bullet/numbered lines and lines containing constraint markers."""
        constraints: list[str] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(("- ", "* ", "+ ")):
                constraints.append(line)
                continue
            if len(line) > 2 and line[0].isdigit() and line[1] in ".):":
                constraints.append(line)
                continue
            lower = line.lower()
            if any(m.lower() in lower for m in _CONSTRAINT_MARKERS):
                constraints.append(line)
        return constraints

    def _identify_edge_cases(self, content: str) -> list[str]:
        """Return a list of filesystem / pathing risk notes found in content."""
        found: list[str] = []
        content_lower = content.lower()
        for pattern in _EDGE_CASE_PATTERNS:
            if pattern.lower() in content_lower:
                found.append(f"Detected '{pattern}' — filesystem / pathing boundary risk")
        return found

    def _resolve_verification_criteria(self, capsule: dict[str, Any]) -> dict[str, str]:
        """Return the test file + method that must pass to verify task resolution.

        Defaults to this tool's own self-test if no test file is resolvable from
        the capsule's resolved_files.
        """
        default: dict[str, str] = {
            "test_file": "tools/spec_generator.py",
            "test_method": "_self_test",
        }
        for resolved in capsule.get("resolved_files", []):
            path_str = resolved.get("path", "") if isinstance(resolved, dict) else str(resolved)
            if "test_" in path_str or "_test" in path_str:
                return {
                    "test_file": path_str,
                    "test_method": "detected from resolved_files",
                }
        return default


def _run_self_test() -> None:
    """Isolated integration test — real state dir is never touched."""
    with tempfile.TemporaryDirectory() as tmp_root:
        tmp = Path(tmp_root)
        state_dir = tmp / ".claude" / "state"
        state_dir.mkdir(parents=True)

        mock_capsule: dict[str, Any] = {
            "created_at": "2026-06-22T12:00:00+00:00",
            "source_task_file": "docs/obsidian-vault/tasks/test-task.md",
            "task_content": (
                "# Recurring-Improvement Loop\n"
                "- Must implement VerificationSpecGenerator\n"
                "- Shall anchor all paths to _ROOT\n"
                "Constraint: use shutil only in test helpers\n"
                "1. Required: generate active-spec.json before any code\n"
            ),
            "pre_fetched_nodes": [],
            "alias_symbols": [],
            "resolved_files": [],
            "warnings": [],
            "status": "ready_for_routing",
        }
        capsule_path = state_dir / "context-capsule.json"
        capsule_path.write_text(json.dumps(mock_capsule), encoding="utf-8")

        gen = VerificationSpecGenerator(root_dir=tmp)
        spec_path = gen.generate_active_spec(capsule_path)

        assert spec_path.exists(), "active-spec.json was not created"
        spec: dict[str, Any] = json.loads(spec_path.read_text(encoding="utf-8"))

        for key in ("specification_id", "target_constraints", "edge_cases_identified", "verification_criteria"):
            assert key in spec, f"Required key '{key}' missing from spec"

        spec2_path = gen.generate_active_spec(capsule_path)
        spec2: dict[str, Any] = json.loads(spec2_path.read_text(encoding="utf-8"))
        assert spec["specification_id"] == spec2["specification_id"], "specification_id is not deterministic"

        constraints = spec["target_constraints"]
        assert any("Must implement" in c for c in constraints), "Expected 'Must implement' constraint not found"
        assert any("Shall anchor" in c for c in constraints), "Expected 'Shall anchor' constraint not found"

        edge_cases = spec["edge_cases_identified"]
        assert any("shutil" in e for e in edge_cases), "Expected 'shutil' edge case not flagged"

        vc = spec["verification_criteria"]
        assert "test_file" in vc and "test_method" in vc, "verification_criteria schema incomplete"

        assert spec_path != _DEFAULT_SPEC_OUT, "Test wrote to real .claude/state/active-spec.json!"

    print("\n✓ Phase 15 spec_generator self-test PASS.")
    print("  Verification-First Spec Generator verified in isolated temp environment.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spec_generator",
        description="Phase 15 Verification-First Spec Generator.",
    )
    parser.add_argument(
        "--capsule",
        metavar="PATH",
        default=None,
        help=("Path to the context capsule JSON (default: .claude/state/context-capsule.json)"),
    )
    parser.add_argument(
        "--test",
        action="store_true",
        default=False,
        help=("Run an isolated self-test in a temporary directory. The real state dir is never touched."),
    )
    args = parser.parse_args(argv)

    if args.test:
        _run_self_test()
        return 0

    capsule_path = Path(args.capsule) if args.capsule else _DEFAULT_CAPSULE
    if not capsule_path.exists():
        print(
            f"[spec_generator] Capsule not found: {capsule_path}",
            file=sys.stderr,
        )
        return 1

    gen = VerificationSpecGenerator()
    try:
        gen.generate_active_spec(capsule_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[spec_generator] Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
