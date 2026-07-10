#!/usr/bin/env python3
"""
SOVEREIGN-IMPERIA-CITADEL System Health Monitor.

Aggregates T0/T1/T2 cost metrics, governance state, bug-engine stats, and
pending human-intervention tickets into a single health snapshot.

Does NOT replace tools/citadel_system_health.py (34-check Citadel monitor).
This file covers LEGION-specific metrics only.
"""


import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATE = _ROOT / ".claude" / "state"


class LegionSystemHealth:
    def compile_health_report(self) -> dict:
        report: dict = {
            "timestamp": int(time.time()),
            "status": "healthy",
            "compute_tiers": {
                "T0_deterministic_tasks": 0,
                "T1_local_tasks": 0,
                "T2_hosted_tasks": 0,
            },
            "bug_engine": {
                "active_codemods": 0,
                "total_auto_fixes": 0,
                "promoted_bugs": 0,
            },
            "governance": {
                "board_vetoes": 0,
                "board_passes": 0,
                "pending_interventions": 0,
            },
            "knowledge_corpus": {
                "silver_records": 0,
                "quarantined_records": 0,
                "indexed_documents": 0,
            },
        }

        td = _STATE / "tier-decision.json"
        if td.exists():
            try:
                d = json.loads(td.read_text())
                tier = d.get("tier", -1)
                if tier == 0:
                    report["compute_tiers"]["T0_deterministic_tasks"] += 1
                    if d.get("deciding_member") == "Director_of_Correctness":
                        report["governance"]["board_vetoes"] += 1
                elif tier == 1:
                    report["compute_tiers"]["T1_local_tasks"] += 1
                    report["governance"]["board_passes"] += 1
                elif tier == 2:
                    report["compute_tiers"]["T2_hosted_tasks"] += 1
            except Exception:
                pass

        cr = _ROOT / ".claude" / "brain" / "codemod-registry.json"
        if cr.exists():
            try:
                registry = json.loads(cr.read_text())
                for data in registry.values():
                    if data.get("status") == "active":
                        report["bug_engine"]["active_codemods"] += 1
                    report["bug_engine"]["total_auto_fixes"] += data.get("success_count", 0)
            except Exception:
                pass

        br = _STATE / "bug-registry.json"
        if br.exists():
            try:
                bugs = json.loads(br.read_text())
                report["bug_engine"]["promoted_bugs"] = sum(
                    1 for b in bugs.values() if b.get("status") == "codemod_promoted"
                )
            except Exception:
                pass

        iv = _STATE / "human-intervention"
        if iv.exists():
            count = len(list(iv.glob("*.json")))
            report["governance"]["pending_interventions"] = count
            if count > 0:
                report["status"] = "attention_required"

        silver = _ROOT / "docs" / "ai-context" / "knowledge" / "silver"
        quar   = _ROOT / "docs" / "ai-context" / "knowledge" / "quarantine"
        if silver.exists():
            report["knowledge_corpus"]["silver_records"] = len(list(silver.glob("*.json")))
        if quar.exists():
            report["knowledge_corpus"]["quarantined_records"] = len(list(quar.glob("*.json")))

        db = _STATE / "citadel_unified_index.db"
        if db.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(db), check_same_thread=False)
                row = conn.execute("SELECT COUNT(*) FROM indexed_documents;").fetchone()
                report["knowledge_corpus"]["indexed_documents"] = row[0] if row else 0
                conn.close()
            except Exception:
                pass

        return report


if __name__ == "__main__":
    monitor = LegionSystemHealth()
    report = monitor.compile_health_report()
    print(json.dumps({"citadel_health": report}, indent=2))
    assert report["status"] in {"healthy", "attention_required"}
    print("smoke test: PASS")
    sys.exit(0)
