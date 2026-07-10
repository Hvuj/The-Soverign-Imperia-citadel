#!/usr/bin/env python3
"""efficiency_gate.py — the "efficiency company": a real, enforced budget gate.

`agent-budget-controller` / `efficiency-auditor` / `token-efficiency-auditor` are
markdown agents a Claude *reads and follows voluntarily*. This module is the
code-level backstop the CLAUDE.md caps describe (docs/graph tasks <=5 agents,
everything else <=8) applied to `citadel run`: it refuses to plan more
workers than the cap allows and, once a run is live, refuses further worker
spawns/respawns once the live token ledger (`token_ledger.py`) shows the run's
budget is exhausted. Zero model calls — this is pure arithmetic over ledgers.
"""

import argparse
import json
from dataclasses import dataclass

DEFAULT_WORKER_CAP = 8
DEFAULT_TOKEN_BUDGET = 2_000_000


@dataclass(slots=True)
class EfficiencyVerdict:
    approved: bool
    reason: str
    worker_cap: int
    token_budget: int


def check_worker_count(planned_workers: int, *, worker_cap: int = DEFAULT_WORKER_CAP) -> EfficiencyVerdict:
    """Enforce the CLAUDE.md agent-count cap on a planned run.

    docs/graph-shaped tasks use a lower cap (<=5) upstream in the caller; this
    gate just refuses to exceed whatever cap it is given, deterministically.
    """
    if planned_workers > worker_cap:
        return EfficiencyVerdict(
            approved=False,
            reason=f"planned {planned_workers} workers exceeds cap {worker_cap} "
                    "(pass a lower --max-workers, or split the task, or get explicit audit authorization)",
            worker_cap=worker_cap,
            token_budget=DEFAULT_TOKEN_BUDGET,
        )
    return EfficiencyVerdict(
        approved=True,
        reason=f"{planned_workers} workers within cap {worker_cap}",
        worker_cap=worker_cap,
        token_budget=DEFAULT_TOKEN_BUDGET,
    )


def check_token_budget(tokens_spent: int, *, token_budget: int = DEFAULT_TOKEN_BUDGET) -> EfficiencyVerdict:
    """Enforce a live per-run token budget, fed by `token_ledger.py`'s running total."""
    if tokens_spent >= token_budget:
        return EfficiencyVerdict(
            approved=False,
            reason=f"run has spent {tokens_spent} tokens, at or above budget {token_budget} "
                    "— no further worker spawns/respawns until a human raises the budget",
            worker_cap=DEFAULT_WORKER_CAP,
            token_budget=token_budget,
        )
    return EfficiencyVerdict(
        approved=True,
        reason=f"{tokens_spent}/{token_budget} tokens spent",
        worker_cap=DEFAULT_WORKER_CAP,
        token_budget=token_budget,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Efficiency-company budget gate for runs.")
    ap.add_argument("--planned-workers", type=int, default=None)
    ap.add_argument("--worker-cap", type=int, default=DEFAULT_WORKER_CAP)
    ap.add_argument("--tokens-spent", type=int, default=None)
    ap.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    args = ap.parse_args()

    if args.planned_workers is not None:
        verdict = check_worker_count(args.planned_workers, worker_cap=args.worker_cap)
    elif args.tokens_spent is not None:
        verdict = check_token_budget(args.tokens_spent, token_budget=args.token_budget)
    else:
        ap.error("pass --planned-workers or --tokens-spent")
        return

    print(json.dumps(verdict.__dict__, indent=2))
    raise SystemExit(0 if verdict.approved else 1)


if __name__ == "__main__":
    main()
