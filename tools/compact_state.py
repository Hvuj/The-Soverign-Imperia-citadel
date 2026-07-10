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


import subprocess

mode=sys.argv[1] if len(sys.argv)>1 else "pre"


def tail(p,n=20):
    try: return p.read_text(encoding="utf-8",errors="ignore").splitlines()[-n:]
    except Exception: return []


def git_status():
    try: return subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True,stderr=subprocess.DEVNULL)[:3000]
    except Exception: return ""


if mode=="pre":
    data={"current_task":json.loads((STATE/"current-task.json").read_text()) if (STATE/"current-task.json").exists() else None,"agent_runs_tail":tail(STATE/"agent-runs.ndjson"),"task_ledger_tail":tail(STATE/"task-ledger.ndjson"),"git_status_short":git_status()}
    (STATE/"compact-state.json").write_text(json.dumps(data,indent=2,sort_keys=True)+"\n")
else: write_nd("compact-restore-ledger.ndjson",{"restored":(STATE/"compact-state.json").exists()})
print("{}")
