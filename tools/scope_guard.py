#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_ROOT_SCRIPTS_RE = re.compile(r'(?:^|[\s"\'(])\.?/scripts(?:/|\b)')

ROOT=Path(os.environ.get("CLAUDE_PROJECT_DIR",Path.cwd())).resolve(); STATE=ROOT/".claude/state"; STATE.mkdir(parents=True,exist_ok=True)
PAT=[(r"\bgit\s+rm\s+-r\s+--cached\s+\.","Blocks full-index untracking. Use explicit root-only paths."),(r"\bgit\s+rm\s+-r\s+\.","Blocks recursive git rm on current directory."),(r"\brm\s+-rf\s+/","Blocks rm -rf on absolute root."),(r"\brm\s+-rf\s+\.","Blocks rm -rf on current directory."),(r"\bgit\s+reset\s+--hard\b","Blocks git reset --hard unless explicitly allowed."),(r"\bsudo\s+rm\b","Blocks sudo rm.")]


def inp():
    raw=sys.stdin.read()
    try: return json.loads(raw) if raw.strip() else {}
    except Exception: return {"raw":raw}


def log(dec,reason):
    with (STATE/"scope-guard.ndjson").open("a",encoding="utf-8") as f: f.write(json.dumps({"ts":datetime.now(UTC).isoformat(),"decision":dec,"reason":reason},sort_keys=True)+"\n")


def deny(reason):
    log("deny",reason); print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":reason}}))


def allow(): log("allow",""); print("{}")


def discovered_scripts_paths():
    p=STATE/"workspace-discovery.json"
    try: data=json.loads(p.read_text(encoding="utf-8"))
    except Exception: return []
    names=[]
    for proj in data.get("projects",[]):
        rp=proj.get("root_path")
        if rp: names.append(f"{Path(rp).name}/scripts")
    return names


d=inp(); text=json.dumps(d,ensure_ascii=False)
if "git reset --hard" in text and os.environ.get("CLAUDE_SCOPE_GUARD_ALLOW_RESET")=="1": allow(); raise SystemExit
for pat,why in PAT:
    if re.search(pat,text): deny(why); raise SystemExit
if re.search(r"\bgit\s+rm\b.*\bscripts\b",text) and not _ROOT_SCRIPTS_RE.search(text) and not any(p in text for p in discovered_scripts_paths()): deny("Ambiguous scripts path. Use root-only /scripts or explicit production path."); raise SystemExit
allow()
