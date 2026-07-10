#!/usr/bin/env python3
"""Scheduler layer lint.

Validates:
  1. Required scheduler config files exist and parse as valid JSON with required keys.
  2. model-effort-schedule.json has the 9 tier keys and no forbidden values.
  3. scheduler-decision.json exists and is consistent with execution-manifest.json.
  4. No forbidden /model or /effort commands in tool/hook output paths.
  5. Tiers are from the valid enum (not concrete model IDs).
  6. Policy sections are single-sourced (no active artifact/memory policy duplicates
     in workflow-manifest-config.json).
"""

import json
import re
import sys
from pathlib import Path

from _brain_common import ROOT, STATE, load_json

BRAIN_DIR = ROOT / ".claude" / "brain"
HOOKS_DIR = ROOT / ".claude" / "hooks"

_REQUIRED_CONFIGS: dict[str, list[str]] = {
    "model-effort-config.json":   ["valid_tiers", "task_type_tiers", "escalation_policy"],
    "scheduler-config.json":      ["scheduler_hierarchy", "caps"],
    "artifact-policy.json":       ["artifact_types", "task_type_to_artifacts"],
    "memory-policy.json":         ["memory_policy_rules"],
    "workflow-manifest-config.json": ["workflows", "task_type_to_workflow", "skill_contracts"],
}

_POLICY_CANONICAL: dict[str, list[str]] = {
    "artifact-policy.json": ["artifact_types", "task_type_to_artifacts"],
    "memory-policy.json":   ["memory_policy_rules"],
}
_MANIFEST_CFG = "workflow-manifest-config.json"

_FORBIDDEN_TIER_VALUES = re.compile(
    r'claude[-_]opus|claude[-_]sonnet|claude[-_]haiku|'
    r'/effort\s+(low|medium|high|xhigh|max)|'
    r'/model\s+\w',
    re.IGNORECASE,
)

_FORBIDDEN_EMIT_PY = re.compile(
    r'print\s*\(.*?(?:/model\s+\w|/effort\s+(?:low|medium|high|xhigh|max))',
    re.IGNORECASE,
)
_FORBIDDEN_EMIT_SH = re.compile(
    r'echo\s+.*?(?:/model\s+\w|/effort\s+(?:low|medium|high|xhigh|max))',
    re.IGNORECASE,
)

VALID_TIERS = frozenset({"cheap", "standard", "strong-planning", "ultracode-escalation-allowed"})
TIER_KEYS = [
    "planning_tier", "execution_tier", "review_tier",
    "planning_effort_tier", "execution_effort_tier", "review_effort_tier",
]


def _has_section(data: object, key: str) -> bool:
    """Return True if *key* is a JSON key at top level or one level deep.

    The one-level search is needed because some rules live under a nested section
    (e.g. ``domain_join_rules``) inside a policy file rather than at the root.
    """
    if not isinstance(data, dict):
        return False
    if key in data:
        return True
    return any(isinstance(v, dict) and key in v for v in data.values())


def _classify_section(section: str, manifest: object, canon: object) -> str:
    """Classify a policy section relative to its canonical file and the manifest.

    Returns:
        ``"duplicate"``  — section is active in BOTH places (hard error).
        ``"fallback"``   — section exists only in the manifest (backwards-compat
                           read-only fallback; should be migrated, but not a hard
                           failure on its own).
        ``"ok"``         — section lives only in the canonical file or neither.
    """
    in_manifest = isinstance(manifest, dict) and section in manifest
    in_canonical = _has_section(canon, section)
    if in_manifest and in_canonical:
        return "duplicate"
    if in_manifest:
        return "fallback"
    return "ok"


def _lint_policy_single_source(errors: list[str], warnings: list[str]) -> None:
    """Fail if any policy section is active in both its canonical file and the manifest.

    Missing / unparseable files are silently skipped here — _lint_configs already
    handles those conditions so we avoid double-reporting.
    """
    manifest = load_json(BRAIN_DIR / _MANIFEST_CFG, None)

    for canon_fname, sections in _POLICY_CANONICAL.items():
        canon = load_json(BRAIN_DIR / canon_fname, None)
        for section in sections:
            verdict = _classify_section(section, manifest, canon)
            if verdict == "duplicate":
                errors.append(
                    f"Policy section {section!r} is active in BOTH "
                    f".claude/brain/{canon_fname} and {_MANIFEST_CFG}; "
                    f"single-source it in {canon_fname} and remove the duplicate "
                    f"from {_MANIFEST_CFG}."
                )
            elif verdict == "fallback":
                warnings.append(
                    f"WARN: Policy section {section!r} lives only in {_MANIFEST_CFG} "
                    f"(read-only backwards-compat fallback). "
                    f"Migrate it to .claude/brain/{canon_fname}."
                )


def _lint_configs(errors: list[str], warnings: list[str]) -> None:
    for fname, required_keys in _REQUIRED_CONFIGS.items():
        fpath = BRAIN_DIR / fname
        if not fpath.exists():
            errors.append(f"MISSING config: .claude/brain/{fname}")
            continue
        try:
            data = json.loads(fpath.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"JSON parse error in {fname}: {e}")
            continue
        for k in required_keys:
            if k not in data:
                errors.append(f"{fname} missing required key: {k!r}")


def _lint_model_effort_schedule(errors: list[str], warnings: list[str]) -> None:
    sched_path = STATE / "model-effort-schedule.json"
    if not sched_path.exists():
        warnings.append("WARN: model-effort-schedule.json not yet generated (run build_execution_manifest.py)")
        return
    try:
        sched = json.loads(sched_path.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"JSON parse error in model-effort-schedule.json: {e}")
        return

    for key in TIER_KEYS:
        if key not in sched:
            errors.append(f"model-effort-schedule.json missing tier key: {key!r}")
            continue
        val = str(sched[key])
        if _FORBIDDEN_TIER_VALUES.search(val):
            errors.append(
                f"model-effort-schedule.json tier {key!r} contains forbidden value: {val!r}"
            )
        if val not in VALID_TIERS:
            errors.append(
                f"model-effort-schedule.json tier {key!r} has invalid value {val!r}. "
                f"Must be one of: {sorted(VALID_TIERS)}"
            )

    esc = sched.get("escalation_policy", "")
    if _FORBIDDEN_TIER_VALUES.search(esc):
        errors.append(
            f"model-effort-schedule.json escalation_policy contains forbidden command: {esc[:80]!r}"
        )


def _lint_scheduler_decision(errors: list[str], warnings: list[str]) -> None:
    dec_path = STATE / "scheduler-decision.json"
    manifest_path = STATE / "execution-manifest.json"

    if not dec_path.exists():
        warnings.append("WARN: scheduler-decision.json not yet generated (run build_execution_manifest.py)")
        return
    if not manifest_path.exists():
        warnings.append("WARN: execution-manifest.json not found — cannot cross-check scheduler-decision")
        return

    try:
        dec = json.loads(dec_path.read_text())
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"JSON parse error in scheduler state files: {e}")
        return

    for key in ["task_type", "selected_workflow", "plan_frozen", "cheap_execution_allowed"]:
        if dec.get(key) != manifest.get(key):
            errors.append(
                f"scheduler-decision.json {key!r} ({dec.get(key)!r}) "
                f"disagrees with execution-manifest.json ({manifest.get(key)!r})"
            )


def _lint_forbidden_emit(errors: list[str], warnings: list[str]) -> None:
    """Grep tools/ and .claude/hooks/ for forbidden emitted /model or /effort commands."""
    tool_files = list((ROOT / "tools").glob("*.py"))
    hook_files = list(HOOKS_DIR.glob("*.sh")) if HOOKS_DIR.exists() else []

    this_file = Path(__file__).resolve()

    for py_file in tool_files:
        if py_file.resolve() == this_file:
            continue
        try:
            text = py_file.read_text()
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if _FORBIDDEN_EMIT_PY.search(line):
                errors.append(
                    f"Forbidden /model or /effort emit in {py_file.name}:{i}: {line.strip()[:80]}"
                )

    for sh_file in hook_files:
        try:
            text = sh_file.read_text()
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _FORBIDDEN_EMIT_SH.search(line):
                errors.append(
                    f"Forbidden /model or /effort emit in hooks/{sh_file.name}:{i}: {line.strip()[:80]}"
                )


def lint() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    _lint_configs(errors, warnings)
    _lint_policy_single_source(errors, warnings)
    _lint_model_effort_schedule(errors, warnings)
    _lint_scheduler_decision(errors, warnings)
    _lint_forbidden_emit(errors, warnings)
    return errors, warnings


def main() -> None:
    errors, warnings = lint()
    for w in warnings:
        print(w)
    for e in errors:
        print(f"ERROR: {e}")
    if errors:
        print(f"Status: Fail ({len(errors)} error(s), {len(warnings)} warning(s))")
        sys.exit(1)
    else:
        print(f"Status: Pass ({len(warnings)} warning(s))")


if __name__ == "__main__":
    main()
