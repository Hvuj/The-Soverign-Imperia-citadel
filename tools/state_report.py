#!/usr/bin/env python3
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1]); STATE=ROOT/".claude/state"


def cnt(p):
    try: return len(p.read_text(encoding="utf-8",errors="ignore").splitlines())
    except Exception: return 0


print("# Claude Legion State")
for n in ["prompt-ledger.ndjson","agent-runs.ndjson","task-ledger.ndjson","tool-batches.ndjson","scope-guard.ndjson","session-ledger.ndjson"]: print(f"- {n}: {cnt(STATE/n)}")
if (STATE/"current-task.json").exists(): print("\n## Current task\n"+json.dumps(json.loads((STATE/"current-task.json").read_text()),indent=2)[:2000])
