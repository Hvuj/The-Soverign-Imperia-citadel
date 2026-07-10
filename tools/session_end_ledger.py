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


def cnt(p):
    try: return len(p.read_text(encoding="utf-8",errors="ignore").splitlines())
    except Exception: return 0


write_nd("session-ledger.ndjson",{"event":"session-end","agent_runs":cnt(STATE/"agent-runs.ndjson"),"tasks":cnt(STATE/"task-ledger.ndjson"),"tool_batches":cnt(STATE/"tool-batches.ndjson")}); print("{}")
