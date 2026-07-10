#!/usr/bin/env python3
"""verdict_ledger.py — capture the turn's verdict and JOIN it to its causes.

The verdict (Pass / Needs Fix / Blocked) is produced at the Stop gate but was
never written back to any ledger — so nothing could learn *which* agents,
model, effort, or skills produced a good or bad outcome.  This tool closes that
edge.  It is invoked by the `verdict-capture.sh` Stop hook, ordered BEFORE
`audit-gate.sh`, and:

  1. reads the verdict via manifest_status.check(),
  2. joins the current turn's state (task_type, tiers) + the agent roster from
     agent-runs.ndjson,
  3. appends a verdict-linked `task-completed` record to task-ledger.ndjson,
  4. appends an append-only agent-outcome.ndjson correlation (one row per
     contributing agent → verdict) — NDJSON is never mutated in place.

It is intentionally defensive: any failure is swallowed so the Stop hook never
breaks the session.  It writes data only; it changes no behavior and never
weakens the audit gate.
"""
import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    from _brain_common import STATE, load_json
except Exception:  # pragma: no cover - fallback when run standalone
    import os
    _ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path.cwd())).resolve()
    STATE = _ROOT / ".claude" / "state"
    def load_json(path, default):
        try: return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception: return default


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw and raw.strip() else {}
    except Exception:
        return {}


def _verdict() -> dict:
    """Get the verdict + manifest satisfaction from manifest_status."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from manifest_status import check  # type: ignore
        return check() or {}
    except Exception:
        return {}


def _agent_roster(session_id: str | None) -> list[dict]:
    """Unique contributing agents for this session from agent-runs.ndjson."""
    path = STATE / "agent-runs.ndjson"
    roster: dict[str, dict] = {}
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines:
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("event") not in ("subagent-start", "subagent-stop"):
            continue
        if session_id and e.get("session_id") and e.get("session_id") != session_id:
            continue
        agent = e.get("agent") or "unknown"
        roster[agent] = {
            "agent": agent,
            "model": e.get("model"),
            "effort": e.get("effort"),
            "tier": e.get("tier"),
        }
    return list(roster.values())


def build_record(stdin: dict) -> dict:
    v = _verdict()
    task = load_json(STATE / "current-task.json", {})
    dec = load_json(STATE / "scheduler-decision.json", {})
    sched = load_json(STATE / "model-effort-schedule.json", {})
    session_id = stdin.get("session_id") or task.get("session_id")
    contributions = _agent_roster(session_id)
    verdict = v.get("verdict_hint", "unknown")
    return {
        "event": "task-completed",
        "session_id": session_id,
        "task_id": stdin.get("prompt_id") or task.get("task_id") or "unknown",
        "task_type": v.get("task_type") or dec.get("task_type") or task.get("task_type"),
        "selected_workflow": v.get("workflow") or dec.get("selected_workflow"),
        "verdict": verdict,
        "unmet_count": len(v.get("unmet_requirements", [])),
        "planning_tier": sched.get("planning_tier"),
        "execution_tier": sched.get("execution_tier"),
        "review_tier": sched.get("review_tier"),
        "agent_contributions": contributions,
        "skills_used": task.get("recommended_skills") or [],
        "trivial": bool(v.get("trivial")),
    }


def capture(stdin: dict) -> dict:
    rec = build_record(stdin)
    rec["ts"] = _now()
    try:
        with (STATE / "task-ledger.ndjson").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    except Exception:
        pass
    try:
        with (STATE / "agent-outcome.ndjson").open("a", encoding="utf-8") as f:
            for c in rec.get("agent_contributions", []):
                f.write(json.dumps({
                    "ts": rec["ts"],
                    "session_id": rec["session_id"],
                    "task_id": rec["task_id"],
                    "task_type": rec["task_type"],
                    "agent": c.get("agent"),
                    "model": c.get("model"),
                    "effort": c.get("effort"),
                    "tier": c.get("tier"),
                    "verdict": rec["verdict"],
                }, sort_keys=True) + "\n")
    except Exception:
        pass
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Capture verdict and join to causes.")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args(argv)
    if args.test:
        rec = build_record({})
        assert "verdict" in rec and "agent_contributions" in rec
        print("verdict_ledger --test PASS")
        return 0
    capture(_read_stdin())
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
