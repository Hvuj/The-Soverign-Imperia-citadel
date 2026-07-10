#!/usr/bin/env python3
"""Validate the execution manifest against schema and workflow config."""
import argparse
import json
import sys
from pathlib import Path

from _brain_common import ROOT, STATE, load_artifact_policy, load_json

MANIFEST_CFG = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"
MANIFEST_PATH = STATE / "execution-manifest.json"

REQUIRED_KEYS = {
    "created_at", "prompt_signature", "intent", "task_type", "confidence",
    "selected_workflow", "selected_nodes", "context_capsules",
    "required_agents", "skipped_agents", "required_skills", "required_tools",
    "required_artifacts", "required_validations", "memory_policy",
    "stop_gate_requirements", "scope_policy", "token_policy", "known_limitations",
    "planning_tier", "execution_tier", "review_tier",
    "planning_effort_tier", "execution_effort_tier", "review_effort_tier",
    "cheap_execution_allowed", "plan_frozen", "escalation_policy",
}

VALID_TIERS = frozenset({"cheap", "standard", "strong-planning", "ultracode-escalation-allowed"})
TIER_KEYS = [
    "planning_tier", "execution_tier", "review_tier",
    "planning_effort_tier", "execution_effort_tier", "review_effort_tier",
]
_FORBIDDEN_MODEL_PATTERN = __import__("re").compile(
    r'claude[-_]opus|claude[-_]sonnet|claude[-_]haiku|/model\s+\w|/effort\s+(low|medium|high|xhigh|max)',
    __import__("re").IGNORECASE,
)
_TRIVIAL_CHEAP_ONLY = frozenset({"terminal_help", "question", "docstring_only"})

VALID_SKIP_REASONS = frozenset({
    "unrelated_domain", "intent_not_matching", "over_budget",
    "forbidden_by_workflow", "explicitly_not_needed",
})

# Agnostic: no shipped domain gate-agents. Domain specialists + their gate keywords are learned
# per workspace. Only the generic learner keeps a signal set.
_GATE_AGENTS = {
    "feature-implementation-learner": ["reusable", "derived feature", "feature logic"],
}

_TRIVIAL_TYPES = frozenset({"terminal_help", "question", "docstring_only"})


def _has_signal(prompt_sig: str, keywords: list[str]) -> bool:
    import re
    p = prompt_sig.lower()
    return any(
        re.search(r'(?<![a-z0-9_])' + re.escape(k.lower()) + r'(?![a-z0-9_])', p)
        for k in keywords
    )


def lint(manifest_path: Path = MANIFEST_PATH) -> list[str]:
    errors: list[str] = []

    if not manifest_path.exists():
        return [f"MISSING manifest file: {manifest_path}"]

    try:
        m = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        return [f"JSON parse error: {e}"]

    cfg = load_json(MANIFEST_CFG, {})
    task_types = set(cfg.get("task_types", []))
    workflows = cfg.get("workflows", {})
    art_policy = load_artifact_policy()
    artifact_types = set(art_policy.get("artifact_types", {}).keys())

    missing_keys = REQUIRED_KEYS - set(m.keys())
    for k in sorted(missing_keys):
        errors.append(f"MISSING key: {k}")

    if missing_keys:
        return errors

    if not isinstance(m["required_agents"], list):
        errors.append("required_agents must be a list")
    if not isinstance(m["skipped_agents"], list):
        errors.append("skipped_agents must be a list")
    if not isinstance(m["required_artifacts"], list):
        errors.append("required_artifacts must be a list")
    if not isinstance(m["confidence"], (int, float)):
        errors.append("confidence must be numeric")

    tt = m.get("task_type", "")
    if task_types and tt not in task_types:
        errors.append(f"Unknown task_type: {tt!r}")

    wf_id = m.get("selected_workflow", "")
    wf = workflows.get(wf_id)
    if workflows and wf is None:
        errors.append(f"Unknown selected_workflow: {wf_id!r}")

    if wf:
        wf_allowed = set(wf.get("required_agents", []))
        for ca in wf.get("conditional_agents", []):
            wf_allowed.add(ca["agent"])
        wf_optional = set(wf.get("optional_agents", []))
        for agent in m.get("required_agents", []):
            if agent not in wf_allowed and agent not in wf_optional:
                if agent in _GATE_AGENTS:
                    sigs = _GATE_AGENTS[agent]
                    if not _has_signal(m.get("prompt_signature", ""), sigs):
                        errors.append(
                            f"Gated agent {agent!r} in required_agents without explicit domain signal"
                        )

    if wf:
        forbidden = set(wf.get("forbidden_agents_unless_explicit", []))
        prompt_sig = m.get("prompt_signature", "")
        for agent in m.get("required_agents", []):
            if agent in forbidden:
                sigs = _GATE_AGENTS.get(agent, [])
                if not _has_signal(prompt_sig, sigs):
                    errors.append(
                        f"Forbidden agent {agent!r} present without explicit domain signal"
                    )

    for entry in m.get("skipped_agents", []):
        if not isinstance(entry, dict):
            errors.append(f"skipped_agents entry not a dict: {entry!r}")
            continue
        reason = entry.get("reason", "")
        if reason not in VALID_SKIP_REASONS:
            errors.append(f"Invalid skip reason {reason!r} for agent {entry.get('agent')!r}")

    for art in m.get("required_artifacts", []):
        if not isinstance(art, dict):
            errors.append(f"required_artifacts entry not a dict: {art!r}")
            continue
        art_id = art.get("id", "")
        if artifact_types and art_id not in artifact_types:
            errors.append(f"Unknown artifact id: {art_id!r}")

    if tt in _TRIVIAL_TYPES:
        req_arts = [a for a in m.get("required_artifacts", []) if a.get("required")]
        if req_arts:
            errors.append(f"Trivial task_type {tt!r} must not have required artifacts: {[a['id'] for a in req_arts]}")
        for agent in m.get("required_agents", []):
            if agent == "feature-implementation-learner":
                errors.append(f"Trivial task_type {tt!r} must not invoke feature-implementation-learner")
        if m.get("memory_policy") not in ("skip", ""):
            errors.append(f"Trivial task_type {tt!r} should have memory_policy=skip, got {m.get('memory_policy')!r}")

    for key in TIER_KEYS:
        val = m.get(key)
        if val is None:
            continue
        val_str = str(val)
        if _FORBIDDEN_MODEL_PATTERN.search(val_str):
            errors.append(f"Tier {key!r} contains forbidden model/effort value: {val_str!r}")
        if val_str not in VALID_TIERS:
            errors.append(
                f"Tier {key!r} has invalid value {val_str!r}. "
                f"Must be one of: {sorted(VALID_TIERS)}"
            )

    if tt in _TRIVIAL_CHEAP_ONLY:
        for key in TIER_KEYS:
            if m.get(key, "cheap") != "cheap":
                errors.append(
                    f"Trivial task_type {tt!r} should use 'cheap' for {key!r}, "
                    f"got {m.get(key)!r}"
                )
        if not m.get("plan_frozen", True):
            errors.append(f"Trivial task_type {tt!r} should have plan_frozen=true")

    esc = m.get("escalation_policy", "") or ""
    if _FORBIDDEN_MODEL_PATTERN.search(esc):
        errors.append(f"escalation_policy contains forbidden command: {esc[:80]!r}")

    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description="Lint the execution manifest.")
    ap.add_argument("--manifest", default=None)
    args = ap.parse_args()

    path = Path(args.manifest) if args.manifest else MANIFEST_PATH
    errors = lint(path)

    if errors:
        print(f"Status: Fail ({len(errors)} error(s))")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("Status: Pass")
        m = json.loads(path.read_text())
        print(f"  task_type={m.get('task_type')}  workflow={m.get('selected_workflow')}  confidence={m.get('confidence')}")


if __name__ == "__main__":
    main()
