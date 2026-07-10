#!/usr/bin/env python3
"""Build a deterministic execution manifest for a given prompt.

Orchestrates all 11 deterministic schedulers and writes:
  .claude/state/execution-manifest.json   — full manifest
  .claude/state/model-effort-schedule.json — advisory tier decision
  .claude/state/scheduler-decision.json   — compact scheduler summary

History: .claude/state/execution-manifests/<ts>-<sig>.json (newest 50 kept)
"""
import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from _brain_common import (
    CONFIG,
    ROOT,
    STATE,
    load_artifact_policy,
    load_json,
    load_memory_policy,
    tokenize,
    write_json,
)

MANIFEST_CFG = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"
MANIFEST_PATH = STATE / "execution-manifest.json"
HISTORY_DIR = STATE / "execution-manifests"
MODEL_EFFORT_PATH = STATE / "model-effort-schedule.json"
SCHEDULER_DECISION_PATH = STATE / "scheduler-decision.json"


def _sig(query: str) -> str:
    """Cache-key style signature for the prompt (matches brain_context_builder._sig)."""
    t = query.lower()
    if any(x in t for x in ["fix", "error", "failed", "traceback", "bug"]):
        it = "debugging"
    elif any(x in t for x in ["add", "change", "implement", "build", "refactor"]):
        it = "implementation"
    elif any(x in t for x in ["test", "validate", "verify", "check"]):
        it = "validation"
    elif any(x in t for x in ["docs", "documentation", "learn this"]):
        it = "docs_ingestion"
    elif re.search(r'\b(bi|metric|kpi)\b', t):
        it = "bi"
    else:
        it = "question"
    toks = sorted(set(tokenize(query)))[:12]
    return f"{it}:{'|'.join(toks)}"


def _wb(keyword: str, text: str) -> bool:
    """Word-boundary safe match."""
    return bool(re.search(r'(?<![a-z0-9_])' + re.escape(keyword.lower()) + r'(?![a-z0-9_])', text))


def _has_signal(prompt: str, keywords: list[str]) -> bool:
    p = prompt.lower()
    return any(_wb(k, p) for k in keywords)


def classify_task_type(prompt: str, intent_val: str, cfg: dict) -> tuple[str, float]:
    """Classify prompt into one of 16 task types using task_type_signals."""
    signals = cfg.get("task_type_signals", {})
    p = prompt.lower()
    best_type: str | None = None
    best_score = 0.0

    for tt, sig in signals.items():
        score = 0.0
        priority = float(sig.get("priority", 1))
        for kw in sig.get("keywords", []):
            if _wb(kw, p):
                score += priority
        for pat in sig.get("patterns", []):
            try:
                if re.search(pat, p, re.IGNORECASE):
                    score += priority * 2.0
            except re.error:
                pass
        if score > best_score:
            best_score = score
            best_type = tt

    if best_type:
        return best_type, min(1.0, best_score / 10.0)

    fallback = {
        "implementation": "feature_change",
        "debugging": "debugging",
        "validation": "validation_only",
        "docs_ingestion": "docs_ingestion",
        "bi": "bi_logic",
        "question": "question",
    }
    return fallback.get(intent_val, "question"), 0.4


def _all_agents() -> list[str]:
    agents_dir = ROOT / ".claude" / "agents"
    if not agents_dir.exists():
        return []
    return sorted(p.stem for p in agents_dir.glob("*.md"))


def _resolve_conditionals(prompt: str, conditionals: list[dict]) -> list[str]:
    active = []
    p = prompt.lower()
    for cond in conditionals:
        kws = cond.get("condition_keywords", [])
        if any(_wb(k, p) for k in kws):
            active.append(cond["agent"])
    return active


# Agnostic by default: no domain/framework agents or their trigger keywords are shipped. Domain
# specialists and their gating signals are learned per workspace and would be loaded from workspace
# config here. Only the generic, always-available learner keeps a signal set.
_FORBIDDEN_DOMAIN_SIGNALS: dict[str, list[str]] = {
    "feature-implementation-learner": ["reusable", "derived feature", "validation pattern", "feature logic"],
}

_SKIP_REASON_ENUMS = frozenset({
    "unrelated_domain",
    "intent_not_matching",
    "over_budget",
    "forbidden_by_workflow",
    "explicitly_not_needed",
    "cheap_path_no_agent_needed",
})


def schedule_agents(
    prompt: str,
    wf: dict,
    brain_cfg: dict,
    intent_val: str,
) -> tuple[list[str], list[dict]]:
    """Scheduler 6: Determine required + skipped agents.

    Returns (required_agents, skipped_agents).
    """
    all_agents = _all_agents()
    required_agents: list[str] = list(wf.get("required_agents", []))
    active_conds = _resolve_conditionals(prompt, wf.get("conditional_agents", []))
    required_agents += active_conds

    for agent in wf.get("forbidden_agents_unless_explicit", []):
        sigs = _FORBIDDEN_DOMAIN_SIGNALS.get(agent, [])
        if sigs and _has_signal(prompt, sigs) and agent not in required_agents:
            required_agents.append(agent)

    seen_agents: set[str] = set()
    req_unique: list[str] = []
    for a in required_agents:
        if a not in seen_agents:
            req_unique.append(a)
            seen_agents.add(a)
    required_agents = req_unique

    forbidden_set = set(wf.get("forbidden_agents_unless_explicit", []))
    skip_rules = brain_cfg.get("agent_skip_rules", {})
    skipped_agents: list[dict] = []
    for agent in all_agents:
        if agent in seen_agents:
            continue
        reason = "explicitly_not_needed"
        if agent in forbidden_set and not _has_signal(prompt, _FORBIDDEN_DOMAIN_SIGNALS.get(agent, [])):
            reason = "forbidden_by_workflow"
        else:
            rule = skip_rules.get(agent)
            if rule:
                if intent_val in rule.get("skip_when_intent", []):
                    reason = "intent_not_matching"
                elif rule.get("skip_unless_explicit_topic") and not _has_signal(
                    prompt, rule.get("skip_unless_explicit_topic", [])
                ):
                    reason = "unrelated_domain"
        skipped_agents.append({"agent": agent, "reason": reason})

    return required_agents, skipped_agents


def schedule_skills(
    prompt: str,
    wf: dict,
    cap: dict,
    skill_contracts: dict,
) -> list[dict]:
    """Scheduler 7: Determine required skills with contracts."""
    seen_skills: set[str] = set()
    all_skills: list[str] = []
    for s in list(wf.get("required_skills", [])) + cap.get("recommended_skills", []):
        if s not in seen_skills:
            all_skills.append(s)
            seen_skills.add(s)

    required_skills = []
    for skill in all_skills:
        sc = skill_contracts.get(skill, {})
        required_skills.append({
            "skill": skill,
            "why": sc.get("why", "selected by routing"),
            "required_steps": sc.get("required_steps", []),
            "skip_conditions": sc.get("skip_conditions", []),
            "validation_expectations": sc.get("validation_expectations", []),
            "artifact_expectations": sc.get("artifact_expectations", []),
        })
    return required_skills


def schedule_artifacts(task_type: str, artifact_policy: dict | None = None) -> list[dict]:
    """Scheduler 8: Determine required + conditional artifacts from artifact-policy.json."""
    if artifact_policy is None:
        artifact_policy = load_artifact_policy()

    artifact_types = artifact_policy.get("artifact_types", {})
    art_spec = artifact_policy.get("task_type_to_artifacts", {}).get(task_type, {})

    required_artifacts = []
    for art_id in art_spec.get("required", []):
        art = artifact_types.get(art_id, {})
        fname = art.get("filename", f"{art_id}.md")
        required_artifacts.append({
            "id": art_id,
            "filename": fname,
            "path": f".claude/state/artifacts/current/{fname}",
            "required": True,
        })

    cond_conds = art_spec.get("conditional_conditions", {})
    for art_id in art_spec.get("conditional", []):
        art = artifact_types.get(art_id, {})
        fname = art.get("filename", f"{art_id}.md")
        required_artifacts.append({
            "id": art_id,
            "filename": fname,
            "path": f".claude/state/artifacts/current/{fname}",
            "required": False,
            "condition": cond_conds.get(art_id, "when applicable"),
        })

    return required_artifacts


def schedule_validations(wf: dict) -> tuple[list[str], list[str]]:
    """Scheduler 9: Determine required validations + tools."""
    return list(wf.get("required_validations", [])), list(wf.get("required_tools", []))


def schedule_memory(task_type: str, wf: dict, memory_policy_data: dict | None = None) -> str:
    """Scheduler 10: Determine memory policy for the task."""
    if memory_policy_data is None:
        memory_policy_data = load_memory_policy()

    mem_rules = memory_policy_data.get("memory_policy_rules", {})
    if task_type in set(mem_rules.get("skip_types", [])):
        return "skip"
    return wf.get("memory_policy") or mem_rules.get("default_policy", "curator_decides")


def build_manifest(prompt: str, task_type_override: str | None = None) -> dict:
    cfg = load_json(MANIFEST_CFG, {})
    brain_cfg = load_json(CONFIG, {})
    artifact_policy = load_artifact_policy()
    memory_policy_data = load_memory_policy()

    try:
        from brain_context_builder import build as build_capsule
        cap = build_capsule(prompt)
    except Exception:
        cap = {}

    intent_val = cap.get("intent", "question")

    if task_type_override:
        task_type, confidence = task_type_override, 1.0
    else:
        task_type, confidence = classify_task_type(prompt, intent_val, cfg)

    task_to_wf = cfg.get("task_type_to_workflow", {})
    workflow_id = task_to_wf.get(task_type, "question_workflow")
    wf = cfg.get("workflows", {}).get(workflow_id, {})

    required_agents, skipped_agents = schedule_agents(prompt, wf, brain_cfg, intent_val)

    skill_contracts = cfg.get("skill_contracts", {})
    required_skills = schedule_skills(prompt, wf, cap, skill_contracts)

    required_artifacts = schedule_artifacts(task_type, artifact_policy)

    required_validations, required_tools = schedule_validations(wf)

    memory_policy = schedule_memory(task_type, wf, memory_policy_data)

    try:
        from model_effort_scheduler import schedule as me_schedule
        me_sched = me_schedule(task_type, float(confidence), prompt)
    except Exception:
        me_sched = {
            "planning_tier": "standard",
            "execution_tier": "cheap",
            "review_tier": "standard",
            "planning_effort_tier": "standard",
            "execution_effort_tier": "cheap",
            "review_effort_tier": "standard",
            "cheap_execution_allowed": True,
            "plan_frozen": False,
            "escalation_policy": "no escalation policy loaded",
        }

    stop_gate = list(wf.get("stop_gate_requirements", []))
    scope_policy = {
        "no_production_code_edits": True,
        "no_nested_claude_cli": True,
        "daemon_no_claude_calls": True,
    }
    token_policy = {
        "max_agents": wf.get("max_agents", 8),
        "max_context_depth": wf.get("max_context_depth", 2),
        "capsule_chars": int(brain_cfg.get("token_budget", {}).get("prompt_capsule_chars", 8000)),
    }

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "prompt_signature": _sig(prompt),
        "intent": intent_val,
        "task_type": task_type,
        "confidence": round(float(confidence), 3),
        "selected_workflow": workflow_id,
        "selected_nodes": cap.get("selected_nodes", [])[:6],
        "context_capsules": [],
        "required_agents": required_agents,
        "skipped_agents": skipped_agents,
        "required_skills": required_skills,
        "required_tools": required_tools,
        "required_artifacts": required_artifacts,
        "required_validations": required_validations,
        "memory_policy": memory_policy,
        "planning_tier": me_sched.get("planning_tier", "standard"),
        "execution_tier": me_sched.get("execution_tier", "cheap"),
        "review_tier": me_sched.get("review_tier", "standard"),
        "planning_effort_tier": me_sched.get("planning_effort_tier", "standard"),
        "execution_effort_tier": me_sched.get("execution_effort_tier", "cheap"),
        "review_effort_tier": me_sched.get("review_effort_tier", "standard"),
        "cheap_execution_allowed": me_sched.get("cheap_execution_allowed", True),
        "plan_frozen": me_sched.get("plan_frozen", False),
        "escalation_policy": me_sched.get("escalation_policy", ""),
        "stop_gate_requirements": stop_gate,
        "scope_policy": scope_policy,
        "token_policy": token_policy,
        "known_limitations": list(wf.get("known_limitations", [])),
    }
    return manifest


def save_manifest(manifest: dict, out: str | None = None, no_history: bool = False) -> None:
    out_path = Path(out) if out else MANIFEST_PATH
    write_json(out_path, manifest)

    if not no_history:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        sig = re.sub(r"[^a-z0-9\-]", "-", manifest["prompt_signature"])[:40]
        write_json(HISTORY_DIR / f"{ts}-{sig}.json", manifest)
        files = sorted(HISTORY_DIR.glob("*.json"))
        for old in files[:max(0, len(files) - 50)]:
            try:
                old.unlink()
            except OSError:
                pass

    me_keys = [
        "planning_tier", "execution_tier", "review_tier",
        "planning_effort_tier", "execution_effort_tier", "review_effort_tier",
        "cheap_execution_allowed", "plan_frozen", "escalation_policy",
    ]
    me_sched = {k: manifest[k] for k in me_keys if k in manifest}
    me_sched["task_type"] = manifest.get("task_type", "")
    me_sched["confidence"] = manifest.get("confidence", 0.0)
    me_sched["created_at"] = manifest.get("created_at", "")
    write_json(MODEL_EFFORT_PATH, me_sched)

    sched_decision = {
        "created_at": manifest.get("created_at", ""),
        "task_type": manifest.get("task_type", ""),
        "confidence": manifest.get("confidence", 0.0),
        "selected_workflow": manifest.get("selected_workflow", ""),
        "planning_tier": manifest.get("planning_tier", ""),
        "plan_frozen": manifest.get("plan_frozen", False),
        "cheap_execution_allowed": manifest.get("cheap_execution_allowed", True),
        "required_agents_count": len(manifest.get("required_agents", [])),
        "skipped_agents_count": len(manifest.get("skipped_agents", [])),
        "required_artifact_ids": [
            a["id"] for a in manifest.get("required_artifacts", []) if a.get("required")
        ],
        "required_validations_count": len(manifest.get("required_validations", [])),
        "memory_policy": manifest.get("memory_policy", ""),
        "escalation_policy_summary": (manifest.get("escalation_policy", "") or "")[:120],
    }
    write_json(SCHEDULER_DECISION_PATH, sched_decision)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build execution manifest for a prompt.")
    ap.add_argument("prompt", nargs="*")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--hook-output", action="store_true")
    ap.add_argument("--hook-event", default="UserPromptSubmit")
    ap.add_argument("--task-type", default=None, help="Override task type classification")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    prompt = " ".join(args.prompt).strip() or "bootstrap"
    manifest = build_manifest(prompt, task_type_override=args.task_type)
    save_manifest(manifest, out=args.out, no_history=args.no_history)

    if args.hook_output:
        if manifest["task_type"] in ("question",) and not manifest.get("required_agents"):
            print(json.dumps({"hookSpecificOutput": {"hookEventName": args.hook_event, "additionalContext": ""}}))
        else:
            summary = {
                "task_type": manifest["task_type"],
                "selected_workflow": manifest["selected_workflow"],
                "required_agents": manifest["required_agents"],
                "stop_gate_requirements": manifest["stop_gate_requirements"],
            }
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": args.hook_event,
                    "additionalContext": "Execution manifest:\n" + json.dumps(summary, indent=2)[:2000],
                }
            }))
    elif args.as_json:
        print(json.dumps(manifest, indent=2))
    else:
        print(f"task_type:         {manifest['task_type']} (confidence={manifest['confidence']})")
        print(f"workflow:          {manifest['selected_workflow']}")
        print(f"planning_tier:     {manifest['planning_tier']}  execution_tier: {manifest['execution_tier']}")
        print(f"plan_frozen:       {manifest['plan_frozen']}  cheap_execution: {manifest['cheap_execution_allowed']}")
        print(f"required_agents:   {manifest['required_agents']}")
        print(f"required_artifacts:{[a['id'] for a in manifest['required_artifacts']]}")
        print(f"memory_policy:     {manifest['memory_policy']}")
        print(f"skipped_agents:    {len(manifest['skipped_agents'])}")


if __name__ == "__main__":
    main()
