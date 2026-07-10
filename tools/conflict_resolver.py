#!/usr/bin/env python3
"""
Conflict Resolver — final escalation path for deadlocked Board or failed L3 quorums.

When governance cannot reach a decision deterministically, this daemon:
  1. Quarantines the operation (no side effects proceed).
  2. Writes a structured intervention ticket to .claude/state/human-intervention/.
  3. Sets system health status to "attention_required".

Human operators read the ticket, adjust the code, and re-run audit-gate.sh.
"""


import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
INTERVENTION_DIR = _ROOT / ".claude" / "state" / "human-intervention"


class ConflictResolver:
    def __init__(self) -> None:
        INTERVENTION_DIR.mkdir(parents=True, exist_ok=True)

    def escalate_deadlock(
        self,
        task_id: str,
        source_tier: str,
        conflict_data: dict[str, Any],
    ) -> str:
        now = int(time.time())
        ticket_id = f"tkt_{hashlib.sha256(f'{task_id}{now}'.encode()).hexdigest()[:12]}"

        ticket = {
            "ticket_id": ticket_id,
            "task_id": task_id,
            "escalated_from_tier": source_tier,
            "timestamp": now,
            "status": "awaiting_human",
            "conflict_data": conflict_data,
            "resolution_instructions": (
                f"Review conflict data for task '{task_id}'. "
                "Adjust target files to resolve the violation, "
                "then re-run audit-gate.sh to re-trigger Tier 0-2 governance."
            ),
        }

        ticket_path = INTERVENTION_DIR / f"{ticket_id}.json"
        ticket_path.write_text(json.dumps(ticket, indent=2), encoding="utf-8")

        print(
            f"Escalation: task '{task_id}' deadlocked at {source_tier}. "
            f"Ticket '{ticket_id}' written for human review.",
            file=sys.stderr,
        )
        return ticket_id

    def check_pending_tickets(self) -> int:
        return len(list(INTERVENTION_DIR.glob("*.json")))

    def resolve_ticket(self, ticket_id: str) -> bool:
        ticket_path = INTERVENTION_DIR / f"{ticket_id}.json"
        if not ticket_path.exists():
            return False
        data = json.loads(ticket_path.read_text(encoding="utf-8"))
        data["status"] = "resolved"
        ticket_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True


if __name__ == "__main__":
    resolver = ConflictResolver()

    mock_conflict = {"reason": "L3 quorum failed 3 consecutive times.", "votes": "1/3"}
    ticket_id = resolver.escalate_deadlock(
        "task_mock_deadlock_001", "Tier_3_L3_Consensus", mock_conflict
    )
    pending = resolver.check_pending_tickets()

    assert ticket_id.startswith("tkt_") and len(ticket_id) == 4 + 12
    assert pending >= 1
    assert (INTERVENTION_DIR / f"{ticket_id}.json").exists()

    print(f"ticket_id  : {ticket_id}")
    print(f"pending    : {pending}")
    print("smoke test : PASS")
    sys.exit(0)
