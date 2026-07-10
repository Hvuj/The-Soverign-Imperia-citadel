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


event=sys.argv[1] if len(sys.argv)>1 else "unknown"; d=safe_input()
dec=_load("scheduler-decision.json"); task=_load("current-task.json"); sched=_load("model-effort-schedule.json")
rec={
    "event":event,
    "task_id":d.get("task_id") or d.get("id") or d.get("prompt_id") or task.get("task_id") or "unknown",
    "subagent_type":d.get("subagent_type") or d.get("agent") or "unknown",
    "session_id":d.get("session_id") or task.get("session_id"),
    "task_type":dec.get("task_type") or task.get("task_type"),
    "selected_workflow":dec.get("selected_workflow"),
    "planning_tier":sched.get("planning_tier"),
    "execution_tier":sched.get("execution_tier"),
    "review_tier":sched.get("review_tier"),
    "keys":sorted(d.keys()) if isinstance(d,dict) else [],
}
write_nd("task-ledger.ndjson",rec); print("{}")
