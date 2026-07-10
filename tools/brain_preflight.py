#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime

from _brain_common import ROOT, STATE, write_json

ap=argparse.ArgumentParser(); ap.add_argument("--bootstrap",action="store_true"); ap.add_argument("--full",action="store_true"); ap.add_argument("--hook-output",action="store_true"); args=ap.parse_args()
results=[]
for cmd in [[sys.executable,"tools/build_brain_search_index.py","--quiet"],[sys.executable,"tools/brain_context_builder.py","bootstrap","--mode","bootstrap","--out",".claude/state/bootstrap-context.json"]]:
    p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True); results.append({"cmd":cmd,"returncode":p.returncode,"output":(p.stdout+p.stderr)[:800]})

manifest_cfg_path = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"
manifest_meta = {}
try:
    if manifest_cfg_path.exists():
        import json as _json
        _cfg = _json.loads(manifest_cfg_path.read_text())
        manifest_meta = {
            "manifest_config_present": True,
            "manifest_config_version": _cfg.get("version"),
            "task_types": _cfg.get("task_types", []),
            "workflow_count": len(_cfg.get("workflows", {})),
        }
    else:
        manifest_meta = {"manifest_config_present": False}
except Exception:
    manifest_meta = {"manifest_config_present": False, "error": "parse_error"}

report={"ts":datetime.now(UTC).isoformat(),"results":results,"manifest_meta":manifest_meta}
write_json(STATE/"brain-preflight-report.json",report)
print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Brain preflight complete."}} if args.hook_output else report, indent=None if args.hook_output else 2))
