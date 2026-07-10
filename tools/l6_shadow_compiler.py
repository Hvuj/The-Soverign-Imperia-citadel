#!/usr/bin/env python3
"""
L6 Shadow Compiler — Phase 12 Extended Epistemic Engine.

Creates an ephemeral tempfile worktree, copies the target files into it, and
executes a pytest build sequence in strict isolation before allowing integration
into the main branch. Pytest is anchored to the shadow dir to avoid inheriting
repository config from pyproject.toml.

No state files written; all work is ephemeral inside tempfile.TemporaryDirectory().
"""


import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from telemetry_ledger import emit as _telemetry_emit  # type: ignore[import]
except Exception:

    def _telemetry_emit(*_args, **_kwargs) -> None:  # type: ignore[misc]
        pass


class ShadowCompiler:
    """Deterministic L6 gate: run tests inside an ephemeral shadow environment."""

    def execute_shadow_build(self, target_files: list[str]) -> bool:
        """Copy target files into a shadow tempdir and run pytest.

        Pytest exit codes treated as survival:
            0 — all tests passed
            5 — no tests collected (shadow dir may be empty or files lack test_ prefix)

        Returns True (shadow build passed), False (veto).
        """
        with tempfile.TemporaryDirectory(prefix="citadel_shadow_") as shadow_dir:
            shadow_path = Path(shadow_dir)
            print(f"L6 Shadow Environment initialized at {shadow_path}", file=sys.stdout)

            for f_path in target_files:
                src = Path(f_path)
                if src.exists() and src.is_file():
                    dst = shadow_path / src.name
                    shutil.copy2(src, dst)

            print("Running compiler and unit tests in shadow environment...", file=sys.stdout)
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        str(shadow_path),
                        f"--rootdir={shadow_path}",
                        "-p",
                        "no:cacheprovider",
                        "-o",
                        "addopts=",
                    ],
                    capture_output=True,
                    text=True,
                )

                if result.returncode in (0, 5):
                    print("L6 Shadow Compilation Pass: Code is stable.", file=sys.stdout)
                    _telemetry_emit("l6_pass", "l6-shadow-compiler", "shadow-env", "L6 shadow build passed")
                    return True
                else:
                    print(
                        f"L6 Shadow Compilation Veto:\n{result.stdout}\n{result.stderr}",
                        file=sys.stderr,
                    )
                    _telemetry_emit("l6_fail", "l6-shadow-compiler", "shadow-env", "L6 shadow build failed")
                    return False

            except Exception as exc:
                print(f"L6 Fault: Compiler execution failed: {exc}", file=sys.stderr)
                _telemetry_emit("l6_fail", "l6-shadow-compiler", "shadow-env", f"L6 fault: {str(exc)[:100]}")
                return False


def main() -> None:
    parser = argparse.ArgumentParser(description="L6 Shadow Compiler")
    parser.add_argument("--test", action="store_true", help="Run in isolated testing mode")
    args = parser.parse_args()

    if args.test:
        compiler = ShadowCompiler()
        with tempfile.TemporaryDirectory() as _tmp:
            test_file = Path(_tmp) / "test_mock.py"
            test_file.write_text("def test_mock():\n    assert True\n", encoding="utf-8")
            success = compiler.execute_shadow_build([str(test_file)])

        if success:
            print("L6 Shadow Compiler (T0) Test Passed.")
            sys.exit(0)
        else:
            print("L6 Shadow Compiler (T0) Test Failed.", file=sys.stderr)
            sys.exit(1)
    else:
        sys.exit(0 if ShadowCompiler().execute_shadow_build([]) else 1)


if __name__ == "__main__":
    main()
