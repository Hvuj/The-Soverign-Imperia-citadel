import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(os.environ.get("CLAUDE_PROJECT_DIR",Path.cwd())).resolve(); STATE=ROOT/".claude/state"; STATE.mkdir(parents=True,exist_ok=True)


def safe_input():
    raw=sys.stdin.read()
    try: return json.loads(raw) if raw.strip() else {}
    except Exception: return {"raw":raw[:2000]}


def write_nd(name,rec):
    rec["ts"]=datetime.now(UTC).isoformat()
    with (STATE/name).open("a",encoding="utf-8") as f: f.write(json.dumps(rec,sort_keys=True)+"\n")


def _load(name):
    try: return json.loads((STATE/name).read_text(encoding="utf-8"))
    except Exception: return {}


def _resolve_model_effort(tier):
    """Resolve a scheduler tier name to {model,effort} via the scheduler (best-effort)."""
    if not tier: return (None,None)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from model_effort_scheduler import schedule_agent  # type: ignore
        r=schedule_agent(tier) or {}
        return (r.get("model"), r.get("effort"))
    except Exception:
        return (None,None)


event=sys.argv[1] if len(sys.argv)>1 else "unknown"; d=safe_input()
agent=d.get("agent_name") or d.get("subagent_type") or d.get("name") or d.get("agent_type") or "unknown"
sched=_load("model-effort-schedule.json"); task=_load("current-task.json")
tier=sched.get("execution_tier") or sched.get("planning_tier")
model,effort=_resolve_model_effort(tier)
rec={
    "event":event,
    "agent":agent,
    "session_id":d.get("session_id") or task.get("session_id"),
    "task_id":d.get("task_id") or d.get("prompt_id") or task.get("task_id"),
    "tier":tier,
    "model":model,
    "effort":effort,
    "task_type":task.get("task_type") or sched.get("task_type"),
    "keys":sorted(d.keys()) if isinstance(d,dict) else [],
}
write_nd("agent-runs.ndjson",rec); print("{}")
