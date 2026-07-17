#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime

from _brain_common import ROOT, STATE, load_json, write_json

from citadel._process import pid_is_alive

CFG=ROOT/".claude/daemon/incremental-brain-config.json"; SNAP=STATE/"incremental-brain-snapshot.json"; PID=STATE/"incremental-brain-daemon.pid"; STOP=STATE/"incremental-brain-daemon.stop"; EVENTS=STATE/"incremental-brain-events.ndjson"; LOG=STATE/"incremental-brain-daemon.log"


def now(): return datetime.now(UTC).isoformat()
def cfg(): return load_json(CFG,{"watch_roots":[".claude","docs","tools","docs/brain/nodes/units"],"ignore_parts":[".git",".venv","__pycache__",".claude/state"],"ignore_suffixes":[".pyc",".log",".zip"],"poll_interval_seconds":4,"debounce_seconds":8})
def event(r): STATE.mkdir(parents=True,exist_ok=True); EVENTS.open("a").write(json.dumps({"ts":now(),**r},sort_keys=True)+"\n")
def log(m): STATE.mkdir(parents=True,exist_ok=True); LOG.open("a").write(f"{now()} {m}\n"); print(f"{now()} {m}",flush=True)


def ignored(p,c):
    s=str(p.relative_to(ROOT))
    return any(part and (s==part or s.startswith(part.rstrip("/")+"/") or f"/{part.strip('/')}/" in "/"+s+"/") for part in c.get("ignore_parts",[])) or p.suffix.lower() in set(c.get("ignore_suffixes",[]))


def fingerprint(c):
    out={}
    for root in c.get("watch_roots",[]):
        base=ROOT/root
        if not base.exists(): continue
        for p in sorted(base.rglob("*") if base.is_dir() else [base]):
            if p.is_file() and not ignored(p,c):
                try: st=p.stat(); out[str(p.relative_to(ROOT))]=[st.st_mtime_ns,st.st_size]
                except OSError: pass
    return out


def changed(a,b): return [k for k in sorted(set(a)|set(b)) if a.get(k)!=b.get(k)]


def sync(paths):
    if not paths: return
    structural = [p for p in paths if any(s in p for s in ["docs/brain/nodes", ".claude/agents", ".claude/brain/graph-aware-config", ".claude/brain/workflow-manifest-config", "docs/brain/nodes/units"])]
    if structural:
        subprocess.run([sys.executable,"tools/build_brain_search_index.py","--quiet"],cwd=ROOT)
    else:
        path_idx_file = STATE / "brain-search" / "path-to-nodes.json"
        try:
            path_idx = json.loads(path_idx_file.read_text()) if path_idx_file.exists() else {}
            dirty = set()
            for p in paths:
                dirty.update(path_idx.get(p, []))
            for nid in list(dirty)[:20]:
                subprocess.run([sys.executable,"tools/build_capsule_cache.py","--quiet","--node",nid],cwd=ROOT,timeout=10)
        except Exception:
            subprocess.run([sys.executable,"tools/build_brain_search_index.py","--quiet"],cwd=ROOT)
    event({"event":"sync","changed":paths[:100],"full_rebuild":bool(structural)})
    _logic_cascade(paths)


def _logic_cascade(paths):
    """Guarded: if a domain-logic file changed, re-learn/regenerate/re-wire it (Pandidakterion cascade)."""
    try:
        from bi_cascade import cascade
        report = cascade(ROOT, paths)
        if report.get("triggered"):
            event({"event": "logic-cascade", "province": report.get("province"),
                   "changed": report.get("changed"), "recorded_units": report.get("recorded_units")})
    except Exception:
        pass


def once():
    c=cfg(); old=load_json(SNAP,{}); new=fingerprint(c); paths=changed(old,new); write_json(SNAP,new); log(f"once changed={len(paths)}"); sync(paths)


def watch():
    c=cfg(); STATE.mkdir(parents=True,exist_ok=True); PID.write_text(str(os.getpid())+"\n"); STOP.unlink(missing_ok=True); snap=fingerprint(c); write_json(SNAP,snap); log(f"incremental daemon started pid={os.getpid()}")
    try:
        while not STOP.exists():
            time.sleep(float(cfg().get("poll_interval_seconds",4))); new=fingerprint(cfg()); paths=changed(snap,new)
            if paths: snap=new; write_json(SNAP,snap); sync(paths)
    finally:
        log("incremental daemon stopped"); PID.unlink(missing_ok=True); STOP.unlink(missing_ok=True)


def status():
    print("# Incremental Brain Daemon")
    if PID.exists():
        pid=PID.read_text().strip()
        try: alive=pid_is_alive(int(pid))
        except ValueError: alive=False
        print(f"pid: {pid}"); print(f"running: {'yes' if alive else 'no'}")
    else: print("running: no")


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--once",action="store_true"); ap.add_argument("--watch",action="store_true"); ap.add_argument("--status",action="store_true"); ap.add_argument("--stop",action="store_true"); args=ap.parse_args(); STATE.mkdir(parents=True,exist_ok=True)
    if args.stop: STOP.write_text("stop\n")
    elif args.status: status()
    elif args.watch: watch()
    else: once()


if __name__=="__main__": main()
