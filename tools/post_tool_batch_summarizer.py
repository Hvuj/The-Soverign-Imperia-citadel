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


d=safe_input(); txt=json.dumps(d,ensure_ascii=False); write_nd("tool-batches.ndjson",{"event":"post-tool-batch","size_chars":len(txt),"keys":sorted(d.keys()) if isinstance(d,dict) else [],"preview":txt[:800]}); print("{}")
