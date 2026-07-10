#!/usr/bin/env python3
"""Advisory model/effort tier scheduler.

Determines planning/execution/review tiers for a given prompt + task_type.
Tiers are ADVISORY ONLY. The harness always runs opusplan + CLAUDE_CODE_EFFORT_LEVEL=auto.
Never emits /model or /effort commands. Only documents when /effort ultracode is justified.

Output: .claude/state/model-effort-schedule.json
"""
import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from _brain_common import ROOT, STATE, load_json, write_json

_CONFIG_PATH = ROOT / ".claude" / "brain" / "model-effort-config.json"
_SCHEDULE_PATH = STATE / "model-effort-schedule.json"

VALID_TIERS = frozenset({"cheap", "standard", "strong-planning", "ultracode-escalation-allowed"})

# The escalation ladder and per-tier model map are system invariants (documented in this module's
# and failure_recovery.py's docstrings), so they have code defaults and work even when the workspace
# config file is absent. A present config's keys override/extend these; missing keys fall back here.
_DEFAULT_ESCALATION_TIERS: dict[str, str] = {
    "cheap": "standard",
    "standard": "strong-planning",
    "strong-planning": "ultracode",
    "ultracode": "ultracode",  # ceiling maps to itself
}
_DEFAULT_PER_AGENT_TIERS: dict[str, dict] = {
    "cheap": {"model": "claude-haiku-4-5-20251001", "effort": "low"},
    "standard": {"model": "claude-sonnet-4-6", "effort": "medium"},
    "strong-planning": {"model": "claude-sonnet-4-6", "effort": "high"},
    "ultracode": {"model": "claude-opus-4-8", "effort": "max"},
}
# Agnostic default complexity signal words (workspace config can extend/override these).
_DEFAULT_COMPLEXITY_KEYWORDS: dict[str, list[str]] = {
    "high": ["refactor", "architecture", "architect", "migrate", "migration", "redesign",
             "rewrite", "distributed", "concurrency", "pipeline", "entire", "security",
             "cross-repo", "orchestration", "breaking"],
    "medium": ["implement", "feature", "integrate", "endpoint", "validate", "optimize",
               "debug", "reproduce"],
}

_TRIVIAL_TYPES = frozenset({"terminal_help", "question", "docstring_only"})
_CHEAP_ONLY_TYPES = frozenset({"terminal_help", "question", "docstring_only", "docs_ingestion"})


def _load_cfg() -> dict:
    cfg = load_json(_CONFIG_PATH, {})
    return cfg


def complexity(prompt: str, confidence: float, task_type: str, cfg: dict | None = None) -> str:
    """Classify prompt complexity as 'low', 'medium', or 'high'.

    Used to decide whether to upgrade planning tier from standard → strong-planning.
    """
    if cfg is None:
        cfg = _load_cfg()
    p = prompt.lower()
    ckw: dict = cfg.get("complexity_keywords", {})
    high_kws: list[str] = ckw.get("high", _DEFAULT_COMPLEXITY_KEYWORDS["high"])
    medium_kws: list[str] = ckw.get("medium", _DEFAULT_COMPLEXITY_KEYWORDS["medium"])

    def _wb(kw: str) -> bool:
        return bool(re.search(r'(?<![a-z0-9_])' + re.escape(kw.lower()) + r'(?![a-z0-9_])', p))

    if confidence < 0.5:
        return "high"
    if any(_wb(k) for k in high_kws):
        return "high"
    if any(_wb(k) for k in medium_kws):
        return "medium"
    if confidence >= 0.8:
        return "low"
    return "medium"


def schedule(task_type: str, confidence: float, prompt: str) -> dict:
    """Return advisory tier schedule for the given task.

    Keys in the returned dict:
      planning_tier, execution_tier, review_tier,
      planning_effort_tier, execution_effort_tier, review_effort_tier,
      cheap_execution_allowed, plan_frozen, escalation_policy
    """
    cfg = _load_cfg()
    task_tiers: dict = cfg.get("task_type_tiers", {})
    defaults: dict = cfg.get("default_tiers", {})
    escalation_policy: dict = cfg.get("escalation_policy", {})

    base = dict(task_tiers.get(task_type, defaults))

    cplx = complexity(prompt, confidence, task_type, cfg)
    overrides: dict = cfg.get("complexity_overrides", {})
    if cplx == "high" and base.get("planning") == "standard":
        base["planning"] = overrides.get("high_upgrades_planning_to", "strong-planning")
        base["plan_frozen"] = False

    triggers = escalation_policy.get("allowed_triggers", [])
    esc_note = "ultracode escalation allowed only for: " + "; ".join(triggers) if triggers else "no escalation policy configured"

    return {
        "planning_tier": base.get("planning", "standard"),
        "execution_tier": base.get("execution", "cheap"),
        "review_tier": base.get("review", "standard"),
        "planning_effort_tier": base.get("planning_effort", "standard"),
        "execution_effort_tier": base.get("execution_effort", "cheap"),
        "review_effort_tier": base.get("review_effort", "standard"),
        "cheap_execution_allowed": bool(base.get("cheap_execution_allowed", True)),
        "plan_frozen": bool(base.get("plan_frozen", False)),
        "escalation_policy": esc_note,
        "complexity": cplx,
        "task_type": task_type,
        "confidence": round(float(confidence), 3),
    }


def schedule_agent(tier: str, cfg: dict | None = None) -> dict:
    """Return concrete (model, effort) for a subagent spawned at the given tier.

    These are per-agent spawn recommendations. They never affect the main-loop
    model/effort (which stays on opusplan+auto to preserve the prompt cache).
    On stall/fail, use escalation_tiers to get the next tier, then call schedule_agent again.
    """
    if cfg is None:
        cfg = _load_cfg()
    per_agent: dict = {**_DEFAULT_PER_AGENT_TIERS, **cfg.get("per_agent_tiers", {})}
    entry = per_agent.get(tier, per_agent.get("standard", {}))
    escalation: dict = {**_DEFAULT_ESCALATION_TIERS, **cfg.get("escalation_tiers", {})}
    return {
        "tier": tier,
        "model": entry.get("model", "claude-sonnet-4-6"),
        "effort": entry.get("effort", "medium"),
        "next_tier_on_fail": escalation.get(tier, "ultracode"),
    }


def next_tier(tier: str, cfg: dict | None = None) -> str:
    """Return the next escalation tier for *tier* (unchanged once already at the ceiling).

    Public wrapper around `escalation_tiers` so callers outside this module (e.g.
    `failure_recovery.py`, deciding whether/how to respawn a stalled legion worker)
    don't need to reach into the private `_load_cfg()` config loader.
    """
    if cfg is None:
        cfg = _load_cfg()
    escalation: dict = {**_DEFAULT_ESCALATION_TIERS, **cfg.get("escalation_tiers", {})}
    return escalation.get(tier, tier)


def save_schedule(sched: dict, out: Path | None = None) -> None:
    out = out or _SCHEDULE_PATH
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        **sched,
    }
    write_json(out, payload)


def main() -> None:
    ap = argparse.ArgumentParser(description="Advisory model/effort tier scheduler.")
    ap.add_argument("prompt", nargs="*", help="Prompt text to schedule")
    ap.add_argument("--task-type", default=None, help="Override task type")
    ap.add_argument("--confidence", type=float, default=0.6, help="Routing confidence (0-1)")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--out", default=None, help="Override output path")
    args = ap.parse_args()

    prompt = " ".join(args.prompt).strip() or "bootstrap"
    task_type = args.task_type or "question"
    confidence = args.confidence

    sched = schedule(task_type, confidence, prompt)
    out_path = Path(args.out) if args.out else None
    save_schedule(sched, out_path)

    if args.as_json:
        print(json.dumps({"created_at": datetime.now(UTC).isoformat(), **sched}, indent=2))
    else:
        print(f"task_type:             {sched['task_type']}")
        print(f"complexity:            {sched['complexity']}")
        print(f"plan_frozen:           {sched['plan_frozen']}")
        print(f"cheap_execution:       {sched['cheap_execution_allowed']}")
        print(f"planning_tier:         {sched['planning_tier']}")
        print(f"execution_tier:        {sched['execution_tier']}")
        print(f"review_tier:           {sched['review_tier']}")
        print(f"planning_effort_tier:  {sched['planning_effort_tier']}")
        print(f"execution_effort_tier: {sched['execution_effort_tier']}")
        print(f"review_effort_tier:    {sched['review_effort_tier']}")
        print(f"escalation_policy:     {sched['escalation_policy'][:80]}...")


if __name__ == "__main__":
    main()
