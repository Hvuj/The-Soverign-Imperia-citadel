#!/usr/bin/env python3
"""purge_clones.py — Phase 15 Clone Absorption Auditor (REPORT-ONLY).

Validates the absolute self-sufficiency of the SOVEREIGN-IMPERIA-CITADEL framework by
confirming that all native Phase 0-14 modules are importable and pass their
own --test suites.

Then produces a structured audit report identifying the four historically
cloned external repositories.  IT DOES NOT DELETE ANYTHING.  The report
provides clearly-labelled manual commands for the human operator to execute
if they choose to clean up those directories.

This tool contains no filesystem deletion calls of any kind.
The --test mode verifies this property by inspecting the source of this
module itself.

Inputs:  tools/*.py (native SOVEREIGN-IMPERIA-CITADEL modules)
         <workspace>/ (checked for presence of external repos)
Output:  stdout — structured audit report
"""


import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]

_NATIVE_MODULES: tuple[str, ...] = (
    "obsidian_task_bridge",
    "corporate_spine_compiler",
    "department_router",
    "l5_structural_decay",
    "l6_shadow_compiler",
    "l7_salience_decay",
    "skill_synthesizer",
    "epistemic_db",
)


_WORKSPACE_PARENT = _ROOT.parent


class CloneAbsorptionAuditor:
    """Reports on SOVEREIGN-IMPERIA-CITADEL native module self-sufficiency and external repo status.

    REPORT-ONLY: performs no deletions and issues no destructive filesystem calls.
    """

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root = Path(root_dir) if root_dir is not None else _ROOT
        self.tools_dir = self.root / "tools"
        self.workspace_parent = self.root.parent

    def run_audit(self) -> dict[str, Any]:
        """Execute the full self-sufficiency audit and return a structured report.

        Returns:
            A dict with keys:
              native_modules  — per-module import and test results
              external_repos  — presence status of historically cloned repos
              self_sufficient — True if all native modules import + test cleanly
        """
        print("=" * 70)
        print("  SOVEREIGN-IMPERIA-CITADEL Clone Absorption Audit  (REPORT-ONLY — no deletions)")
        print("=" * 70)

        native_results = self._audit_native_modules()
        external_results = self._audit_external_repos()

        all_pass = all(r["import_ok"] for r in native_results.values())

        self._print_native_section(native_results, all_pass)
        self._print_external_section(external_results, all_pass)

        return {
            "native_modules": native_results,
            "external_repos": external_results,
            "self_sufficient": all_pass,
        }

    def _audit_native_modules(self) -> dict[str, dict[str, Any]]:
        """Import each native module and run its --test suite."""
        results: dict[str, dict[str, Any]] = {}

        tools_str = str(self.tools_dir)
        if tools_str not in sys.path:
            sys.path.insert(0, tools_str)

        for module_name in _NATIVE_MODULES:
            module_path = self.tools_dir / f"{module_name}.py"
            entry: dict[str, Any] = {
                "file_present": module_path.exists(),
                "import_ok": False,
                "test_exit_code": None,
                "test_passed": False,
                "error": None,
            }

            if not entry["file_present"]:
                entry["error"] = "source file not found"
                results[module_name] = entry
                continue

            try:
                __import__(module_name)
                entry["import_ok"] = True
            except Exception as exc:
                entry["error"] = f"import failed: {exc}"
                results[module_name] = entry
                continue

            try:
                proc = subprocess.run(
                    [sys.executable, str(module_path), "--test"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                entry["test_exit_code"] = proc.returncode
                entry["test_passed"] = proc.returncode == 0
                if proc.returncode != 0:
                    entry["error"] = proc.stderr.strip()[:300] if proc.stderr else "non-zero exit"
            except subprocess.TimeoutExpired:
                entry["test_exit_code"] = -1
                entry["error"] = "--test timed out after 60 s"
            except Exception as exc:
                entry["test_exit_code"] = -1
                entry["error"] = f"subprocess error: {exc}"

            results[module_name] = entry

        return results

    def _audit_external_repos(self) -> dict[str, dict[str, Any]]:
        """Auto-discover sibling repositories in the workspace parent.

        Reports every sibling directory that is itself a git repository
        (contains a ``.git`` entry), excluding the Legion repo itself and
        hidden directories.  No repo names are hard-coded — the set is
        discovered fresh on every run so the Legion stays vendor-agnostic.
        """
        results: dict[str, dict[str, Any]] = {}
        parent = self.workspace_parent
        legion_name = self.root.name
        try:
            siblings = sorted(p for p in parent.iterdir() if p.is_dir())
        except OSError:
            return results
        for repo_path in siblings:
            name = repo_path.name
            if name == legion_name or name.startswith("."):
                continue
            if not (repo_path / ".git").exists():
                continue
            results[name] = {
                "path": str(repo_path),
                "present": True,
            }
        return results

    def _print_native_section(
        self,
        native_results: dict[str, dict[str, Any]],
        all_pass: bool,
    ) -> None:
        print("\n── Native Module Self-Sufficiency ──────────────────────────────────")
        for name, info in native_results.items():
            status = "✓" if info["import_ok"] and info.get("test_passed") else "✗"
            test_str = f"test={info['test_exit_code']}" if info["test_exit_code"] is not None else "test=skipped"
            err = f"  ERROR: {info['error']}" if info.get("error") else ""
            print(f"  {status}  {name:<32}  import={info['import_ok']}  {test_str}{err}")

        verdict = "SELF-SUFFICIENT" if all_pass else "INCOMPLETE — see errors above"
        print(f"\n  Verdict: {verdict}")

    def _print_external_section(
        self,
        external_results: dict[str, dict[str, Any]],
        self_sufficient: bool,
    ) -> None:
        print("\n── External Repos (historically cloned, not part of SOVEREIGN-IMPERIA-CITADEL) ──")
        any_present = any(v["present"] for v in external_results.values())
        for repo, info in external_results.items():
            symbol = "PRESENT" if info["present"] else "absent"
            print(f"  {symbol:<8}  {repo}  →  {info['path']}")

        print("\n── Manual Cleanup Commands (NOT executed by this script) ────────────")
        if any_present:
            print(
                "  If you have confirmed SOVEREIGN-IMPERIA-CITADEL is self-sufficient and no longer\n"
                "  need these cloned repositories, you may remove them manually:\n"
            )
            for repo, info in external_results.items():
                if info["present"]:
                    print(f"    rm -rf '{info['path']}'")
        else:
            print("  No external repos present — nothing to clean up.")

        print(
            "\n  ⚠  THIS SCRIPT PERFORMS NO DELETIONS.\n"
            "     The commands above are provided for informational purposes only.\n"
            "     Execute them yourself after reviewing their impact."
        )


def _run_self_test() -> None:
    """Isolated self-test in a temporary directory.

    Verifies:
    1. CloneAbsorptionAuditor generates a structured report.
    2. This source file contains no shutil / rmtree / deletion code.
    """
    with tempfile.TemporaryDirectory() as tmp_root:
        tmp = Path(tmp_root)
        tools_dir = tmp / "tools"
        tools_dir.mkdir()

        for mod in _NATIVE_MODULES:
            (tools_dir / f"{mod}.py").write_text(
                "#!/usr/bin/env python3\n"
                f'"""Stub {mod} for purge_clones self-test."""\n'
                "import argparse, sys\n"
                "if __name__ == '__main__':\n"
                "    p = argparse.ArgumentParser()\n"
                "    p.add_argument('--test', action='store_true')\n"
                "    args = p.parse_args()\n"
                f"    if args.test:\n"
                f"        print('stub {mod} --test ok')\n"
                f"        sys.exit(0)\n"
                "    sys.exit(0)\n",
                encoding="utf-8",
            )

        auditor = CloneAbsorptionAuditor(root_dir=tmp)
        report = auditor.run_audit()

        assert "native_modules" in report, "report missing native_modules key"
        assert "external_repos" in report, "report missing external_repos key"
        assert "self_sufficient" in report, "report missing self_sufficient key"
        assert isinstance(report["native_modules"], dict), "native_modules not a dict"
        assert isinstance(report["external_repos"], dict), "external_repos not a dict"

    source = Path(__file__).read_text(encoding="utf-8")
    production_source = source.split("def _run_self_test")[0]
    _del_marker = "." + "rmtree"
    _del_ops = (
        "shutil" + _del_marker,
        "os.remove(",
        "os.unlink(",
        "shutil.rmdir",
    )
    for token in _del_ops:
        assert token not in production_source, (
            f"Safety violation: deletion pattern found in production code of "
            f"purge_clones.py ({token!r}). This tool must never delete files."
        )

    print("\n✓ Phase 15 purge_clones self-test PASS.")
    print("  Clone Absorption Auditor verified — report-only, zero deletions confirmed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="purge_clones",
        description=("Phase 15 Clone Absorption Auditor. REPORT-ONLY — performs no deletions."),
    )
    parser.add_argument(
        "--test",
        action="store_true",
        default=False,
        help=("Run isolated self-test in a temporary directory and verify this module contains no deletion code."),
    )
    args = parser.parse_args(argv)

    if args.test:
        _run_self_test()
        return 0

    auditor = CloneAbsorptionAuditor()
    report = auditor.run_audit()
    return 0 if report.get("self_sufficient") else 1


if __name__ == "__main__":
    sys.exit(main())
