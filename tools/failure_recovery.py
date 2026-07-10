#!/usr/bin/env python3
"""failure_recovery.py — deterministic respawn/escalation policy for legion workers.

Backs the `failure-recovery-agent` contract: classify a stopped/blocked legion
worker and decide whether to respawn it, and at what model+effort tier. Workers
never escalate themselves — only `legion_orchestrator.py` acts on this decision,
so "a legion worker only schedules; it never modifies its own model/effort."

Escalation ladder mirrors `model_effort_scheduler.py`'s `escalation_tiers`:
  cheap -> standard -> strong-planning -> ultracode
Bounded to MAX_ESCALATIONS per worker so a broken task cannot escalate forever.
Zero model calls: this is pure deterministic policy over exit codes/verdicts.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from model_effort_scheduler import next_tier, schedule_agent  # noqa: E402

MAX_ESCALATIONS = 2
RETRYABLE_EXIT_CODES = frozenset({1, 124, 137})


@dataclass(slots=True)
class EscalationDecision:
    should_respawn: bool
    tier: str
    model: str
    effort: str
    reason: str


def decide(
    *,
    tier: str,
    exit_code: int | None,
    blocked_verdict: bool = False,
    escalations_used: int = 0,
) -> EscalationDecision:
    """Decide whether a worker that just stopped should respawn, and at what tier.

    A worker that exits 0 with no blocked verdict is left alone. A worker that
    exits with a retryable code, or whose validation verdict was Blocked, is
    escalated one tier up (cheap -> standard -> strong-planning -> ultracode)
    and respawned — unless it has already used its escalation budget, in which
    case it is left failed for a human to inspect (the delta from
    `worker_memory.py`'s per-task card is exactly the artifact to inspect).
    """
    failed = blocked_verdict or (exit_code is not None and exit_code in RETRYABLE_EXIT_CODES)

    if not failed:
        current = schedule_agent(tier)
        return EscalationDecision(
            should_respawn=False,
            tier=tier,
            model=current["model"],
            effort=current["effort"],
            reason="worker completed cleanly",
        )

    if escalations_used >= MAX_ESCALATIONS:
        current = schedule_agent(tier)
        return EscalationDecision(
            should_respawn=False,
            tier=tier,
            model=current["model"],
            effort=current["effort"],
            reason=f"escalation budget exhausted ({escalations_used}/{MAX_ESCALATIONS})",
        )

    escalated_tier = next_tier(tier)
    escalated = schedule_agent(escalated_tier)
    trigger = "blocked verdict" if blocked_verdict else f"exit code {exit_code}"
    return EscalationDecision(
        should_respawn=escalated_tier != tier,
        tier=escalated_tier,
        model=escalated["model"],
        effort=escalated["effort"],
        reason=f"{trigger} — escalating {tier!r} -> {escalated_tier!r}",
    )


def main() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Decide legion worker respawn/escalation.")
    ap.add_argument("--tier", default="cheap")
    ap.add_argument("--exit-code", type=int, default=None)
    ap.add_argument("--blocked", action="store_true")
    ap.add_argument("--escalations-used", type=int, default=0)
    args = ap.parse_args()

    decision = decide(
        tier=args.tier,
        exit_code=args.exit_code,
        blocked_verdict=args.blocked,
        escalations_used=args.escalations_used,
    )
    print(json.dumps(decision.__dict__, indent=2))


if __name__ == "__main__":
    main()
