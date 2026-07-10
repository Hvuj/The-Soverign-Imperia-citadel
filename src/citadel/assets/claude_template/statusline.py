#!/usr/bin/env python3
from __future__ import annotations
import json,subprocess,sys,os,math
from pathlib import Path
def stdin_json():
    try:
        raw=sys.stdin.read(); return json.loads(raw) if raw.strip() else {}
    except Exception: return {}
def run(c,cwd):
    try: return subprocess.check_output(c,cwd=cwd,text=True,stderr=subprocess.DEVNULL).strip()
    except Exception: return ""
def lines(p):
    try: return len(p.read_text(encoding="utf-8",errors="ignore").splitlines())
    except Exception: return 0
def color(code,text):
    return f"\033[{code}m{text}\033[0m"
def bar(pct,width=10):
    filled=max(0,min(width,int(pct*width/100)))
    empty=width-filled
    if pct>=80: bar_color="91"
    elif pct>=60: bar_color="93"
    else: bar_color="92"
    return color(bar_color,"█"*filled)+color("90","░"*empty)
def status_icon(val):
    if val=="hit": return color("92","⚡")
    elif val=="miss": return color("93","○")
    else: return "?"
def pid_alive(pidfile):
    try:
        os.kill(int(pidfile.read_text().strip()),0); return True
    except Exception: return False
DAEMON_PIDS={
    "incremental_brain_daemon":"incremental-brain-daemon.pid",
    "workspace_intelligence_daemon":"workspace-intelligence/daemon.pid",
    "outcome_miner_daemon":"outcome-miner-daemon.pid",
    "git_history_daemon":"git-history-daemon.pid",
    "ram_cache_daemon":"ram-cache-daemon.pid",
    "bug_record_daemon":"bug-record-daemon.pid",
    "zombie_worker_daemon":"zombie-worker-daemon.pid",
    "citadel_ui_server":"citadel-ui-server.pid",
}
MINING_DAEMONS={"git_history_daemon","outcome_miner_daemon","zombie_worker_daemon"}
def active_agents(p):
    try: data=p.read_bytes()
    except Exception: return 0
    if len(data)>512000: data=data[-512000:]
    open_set={}
    for line in data.decode("utf-8",errors="ignore").splitlines():
        line=line.strip()
        if not line: continue
        try: rec=json.loads(line)
        except Exception: continue
        key=(rec.get("session_id"),rec.get("task_id"))
        if key==(None,None): continue
        if rec.get("event")=="subagent-start": open_set[key]=1
        elif rec.get("event")=="subagent-stop": open_set.pop(key,None)
    return len(open_set)


def legion_mix(state):
    """Pure-file-read summary of the current `citadel run` per-worker model mix.

    Reads legion-runs/current-run.json then tail-reads that run's ledger (same bounded
    512KB seek used above), replaying worker-start/worker-respawn to each worker's current
    model. Returns "" when no run is active. Never raises — a half-written run must not
    break the statusline.
    """
    try:
        ptr=state/"legion-runs/current-run.json"
        run_id=json.loads(ptr.read_text()).get("run_id")
        if not run_id: return ""
        ledger=state/"legion-runs"/run_id/"ledger.ndjson"
        data=ledger.read_bytes()
        if len(data)>512000: data=data[-512000:]
        models={}
        for line in data.decode("utf-8",errors="ignore").splitlines():
            line=line.strip()
            if not line: continue
            try: rec=json.loads(line)
            except Exception: continue
            if rec.get("event") in ("worker-start","worker-respawn") and rec.get("worker"):
                models[rec["worker"]]=rec.get("model") or ""
        if not models: return ""
        tiers={"opus":0,"sonnet":0,"haiku":0}
        for m in models.values():
            for t in tiers:
                if t in m: tiers[t]+=1; break
        parts=[f"{t}×{n}" for t,n in tiers.items() if n]
        return f"{len(models)} workers"+(" · "+" ".join(parts) if parts else "")
    except Exception:
        return ""
d=stdin_json(); ws=d.get("workspace",{}) if isinstance(d,dict) else {}
project=Path(os.environ.get("CLAUDE_PROJECT_DIR") or ws.get("project_dir") or ws.get("current_dir") or ".").resolve()
state=project/".claude/state"
model=(d.get("model",{}) or {}).get("display_name") or (d.get("model",{}) or {}).get("name") or "Claude"
ctx=(d.get("context_window",{}) or {}).get("used_percentage") or 0
ctxs=f"{ctx:.0f}%" if isinstance(ctx,(int,float)) else "?%"
cost=(d.get("cost",{}) or {}).get("total_cost_usd") or 0
duration_ms=(d.get("cost",{}) or {}).get("total_duration_ms") or 0
mins=int(duration_ms/60000); secs=int((duration_ms%60000)/1000)
branch=run(["git","branch","--show-current"],project) or "no-git"
has_changes=bool(run(["git","status","--short"],project))
staged=run(["git","diff","--cached","--numstat"],project)
modified=run(["git","status","--short"],project)
staged_cnt=len(staged.splitlines()) if staged else 0
modified_cnt=len(modified.splitlines()) if modified else 0
task_cnt=lines(state/"task-ledger.ndjson")
daemons_alive=sum(1 for f in DAEMON_PIDS.values() if pid_alive(state/f))
daemons_mining=sum(1 for n,f in DAEMON_PIDS.items() if n in MINING_DAEMONS and pid_alive(state/f))
active_agent_cnt=active_agents(state/"agent-runs.ndjson")
dirs=0
try: dirs=len(json.loads((project/"docs/brain/directories/index.json").read_text()).get("directories",[]))
except Exception: pass
cache="hit" if (state/"current-task.json").exists() else "miss"
ui_port=os.environ.get("Citadel_UI_PORT","8765")
ui_url=f"http://localhost:{ui_port}/brain/graph.html"
ui_dot=color('92','●') if pid_alive(state/"citadel-ui-server.pid") else color('90','○')
line1=f"{color('36','◆ The Sovereign Imperia Citadel Z')} {color('97','▸')} {color('96',model)} {color('90','│')} {color('92','◈')} ctx {bar(ctx)} {ctxs}"
git_stat=color('93','●') if has_changes else color('92','●')
line2=f"{color('35','⬢')} {git_stat} {color('97',branch)} {color('90','│')} {color('91',f'±{staged_cnt}' if staged_cnt else '✓')} {color('93',f'~{modified_cnt}' if modified_cnt else '✓')}"
mining_tag=color('93',f' ⛏{daemons_mining}') if daemons_mining else ''
legion=legion_mix(state)
legion_seg=f" {color('90','│')} {color('95','⬢ legion')} {color('97',legion)}" if legion else ''
line3=f"{color('96','❯')} workers {color('97',f'{daemons_alive}/{len(DAEMON_PIDS)}')}{mining_tag} {color('90','│')} active {color('97',str(active_agent_cnt))} {color('90','│')} tasks {color('97',str(task_cnt))} {color('90','│')} cache {status_icon(cache)} {color('97',cache)} {color('90','│')} brain {color('97',str(dirs))}{legion_seg}"
line4=f"{color('92','✦')} cost {color('93',f'${cost:.2f}')} {color('90','│')} ⏱ {color('97',f'{mins}m{secs}s')} {color('90','│')} {ui_dot} UI {color('96',ui_url)}"
print(f"{line1}\n{line2}\n{line3}\n{line4}")
