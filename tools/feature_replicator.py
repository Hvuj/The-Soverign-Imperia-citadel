#!/usr/bin/env python3
"""feature_replicator.py — Zero-token multi-target feature replication engine.

Captures a feature change as a parameterized template in the template registry,
then applies it deterministically across N targets with per-target parameterization,
backup, rollback, and validation. No hosted tokens required.

Template registry: .claude/brain/template-registry.json
Each template entry:
  {
    "template_id": "...",
    "description": "...",
    "source_unit": "performance",
    "placeholders": ["TARGET_MODULE", "TARGET_CLASS"],
    "patch_hunks": [{"file": "...", "find": "...", "replace": "..."}],
    "validation_cmd": "python -m pytest ...",
    "status": "active",
    "registered_at": "...",
    "applied_count": 0,
    "success_count": 0,
    "rollback_count": 0
  }

Zero-token: never calls any LLM. Build template from a captured diff.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
REGISTRY_PATH = ROOT / ".claude" / "brain" / "template-registry.json"
_registry_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {}
    try:
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_registry(reg: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class FeatureReplicator:
    """Capture and replicate feature changes across N targets."""

    def __init__(self, workspace_root: str = ".") -> None:
        self.root = Path(workspace_root).resolve()

    def register_template(self, entry: dict) -> None:
        """Write a template entry into the registry."""
        required = {
            "template_id", "description", "source_unit", "placeholders",
            "patch_hunks", "validation_cmd",
        }
        missing = required - set(entry.keys())
        if missing:
            raise ValueError(f"template entry missing required fields: {sorted(missing)}")
        entry.setdefault("status", "active")
        entry.setdefault("registered_at", _now())
        entry.setdefault("applied_count", 0)
        entry.setdefault("success_count", 0)
        entry.setdefault("rollback_count", 0)
        with _registry_lock:
            reg = _load_registry()
            reg[entry["template_id"]] = entry
            _save_registry(reg)

    def capture_from_diff(
        self,
        template_id: str,
        description: str,
        source_unit: str,
        placeholders: list[str],
        validation_cmd: str,
    ) -> dict:
        """Build a template from the current git diff. Returns the template entry."""
        result = subprocess.run(
            ["git", "diff"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        raw_diff = result.stdout
        patch_hunks: list[dict] = []
        current_file = ""
        find_lines: list[str] = []
        replace_lines: list[str] = []
        in_hunk = False

        for line in raw_diff.splitlines():
            if line.startswith("+++ b/"):
                if in_hunk and current_file:
                    patch_hunks.append({
                        "file": current_file,
                        "find": "\n".join(find_lines),
                        "replace": "\n".join(replace_lines),
                    })
                current_file = line[6:]
                find_lines, replace_lines = [], []
                in_hunk = False
            elif line.startswith("@@"):
                if in_hunk and find_lines:
                    patch_hunks.append({
                        "file": current_file,
                        "find": "\n".join(find_lines),
                        "replace": "\n".join(replace_lines),
                    })
                    find_lines, replace_lines = [], []
                in_hunk = True
            elif in_hunk:
                if line.startswith("-"):
                    find_lines.append(line[1:])
                elif line.startswith("+"):
                    replace_lines.append(line[1:])

        if in_hunk and current_file and find_lines:
            patch_hunks.append({
                "file": current_file,
                "find": "\n".join(find_lines),
                "replace": "\n".join(replace_lines),
            })

        entry = {
            "template_id": template_id,
            "description": description,
            "source_unit": source_unit,
            "placeholders": placeholders,
            "patch_hunks": patch_hunks,
            "validation_cmd": validation_cmd,
        }
        self.register_template(entry)
        return entry

    def replicate(
        self,
        template_id: str,
        targets: list[dict],
    ) -> list[dict]:
        """Apply template to each target. Returns per-target result list.

        targets: list of dicts, each must have keys matching template placeholders.
          e.g. [{"TARGET_MODULE": "client_b", "TARGET_CLASS": "ClientBProcessor"}, ...]
        """
        with _registry_lock:
            reg = _load_registry()
        template = reg.get(template_id)
        if not template:
            raise ValueError(f"template_id not found: {template_id!r}")
        if template.get("status") == "disabled":
            raise ValueError(f"template {template_id!r} is disabled")

        results: list[dict] = []
        for target_params in targets:
            result = self._apply_to_target(template, target_params)
            results.append(result)

        successes = sum(1 for r in results if r["success"])
        failures = len(results) - successes
        with _registry_lock:
            reg = _load_registry()
            entry = reg.get(template_id, {})
            entry["applied_count"] = entry.get("applied_count", 0) + len(results)
            entry["success_count"] = entry.get("success_count", 0) + successes
            entry["rollback_count"] = entry.get("rollback_count", 0) + failures
            if entry.get("rollback_count", 0) >= 3:
                entry["status"] = "disabled"
            reg[template_id] = entry
            _save_registry(reg)

        return results

    def _apply_to_target(self, template: dict, params: dict) -> dict:
        """Apply one target's parameterized patches. Backup + validate + rollback on fail."""
        placeholders = template.get("placeholders", [])
        backups: list[tuple[Path, Path]] = []
        applied_files: list[str] = []

        def _sub(text: str) -> str:
            for ph in placeholders:
                if ph in params:
                    text = text.replace(f"{{{ph}}}", params[ph])
            return text

        try:
            for hunk in template.get("patch_hunks", []):
                target_file = self.root / _sub(hunk["file"])
                if not target_file.exists():
                    continue
                backup = target_file.with_suffix(target_file.suffix + ".rep_bak")
                shutil.copy2(target_file, backup)
                backups.append((target_file, backup))

                source = target_file.read_text(encoding="utf-8")
                find_text = _sub(hunk["find"])
                replace_text = _sub(hunk["replace"])
                if find_text and find_text in source:
                    mutated = source.replace(find_text, replace_text, 1)
                    target_file.write_text(mutated, encoding="utf-8")
                    applied_files.append(str(target_file.relative_to(self.root)))

            validation_cmd = _sub(template.get("validation_cmd", "true"))
            result = subprocess.run(
                validation_cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.root,
            )
            if result.returncode != 0:
                self._rollback(backups)
                return {
                    "success": False,
                    "params": params,
                    "applied_files": applied_files,
                    "error": result.stderr[:400],
                    "rolled_back": True,
                }

            for _, bak in backups:
                bak.unlink(missing_ok=True)
            return {"success": True, "params": params, "applied_files": applied_files}

        except Exception as exc:
            self._rollback(backups)
            return {
                "success": False,
                "params": params,
                "applied_files": applied_files,
                "error": str(exc),
                "rolled_back": True,
            }

    @staticmethod
    def _rollback(backups: "list[tuple[Path, Path]]") -> None:
        for original, bak in backups:
            if bak.exists():
                shutil.copy2(bak, original)
                bak.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Feature replication engine.")
    sub = ap.add_subparsers(dest="cmd")

    cap_p = sub.add_parser("capture", help="Capture current git diff as a template")
    cap_p.add_argument("--id", required=True, dest="template_id")
    cap_p.add_argument("--desc", required=True, dest="description")
    cap_p.add_argument("--unit", default="core", dest="source_unit")
    cap_p.add_argument("--placeholders", default="", help="Comma-separated placeholder names")
    cap_p.add_argument("--validate", default="true", dest="validation_cmd")

    rep_p = sub.add_parser("replicate", help="Replicate a template to targets")
    rep_p.add_argument("--id", required=True, dest="template_id")
    rep_p.add_argument("--targets", required=True, help="JSON file or inline JSON array of param dicts")

    list_p = sub.add_parser("list", help="List registered templates")

    args = ap.parse_args()
    replicator = FeatureReplicator(str(ROOT))

    if args.cmd == "capture":
        placeholders = [p.strip() for p in args.placeholders.split(",") if p.strip()]
        entry = replicator.capture_from_diff(
            args.template_id, args.description, args.source_unit,
            placeholders, args.validation_cmd,
        )
        print(json.dumps(entry, indent=2))
    elif args.cmd == "replicate":
        if args.targets.startswith("[") or args.targets.startswith("{"):
            targets = json.loads(args.targets)
        else:
            targets = json.loads(Path(args.targets).read_text())
        if isinstance(targets, dict):
            targets = [targets]
        results = replicator.replicate(args.template_id, targets)
        print(json.dumps(results, indent=2))
        failed = [r for r in results if not r["success"]]
        if failed:
            print(f"\n{len(failed)}/{len(results)} targets FAILED", file=sys.stderr)
            sys.exit(1)
    elif args.cmd == "list":
        reg = _load_registry()
        templates = {k: v for k, v in reg.items() if not k.startswith("_") and isinstance(v, dict)}
        if not templates:
            print("No templates registered yet.")
        for tid, entry in templates.items():
            print(f"{tid} ({entry.get('status', '?')}) — {entry.get('description', '')}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
