#!/usr/bin/env python3
"""zombie_worker_daemon.py — runs the zero-token zombie worker on an idle interval.

Safety contract:
  never_call_claude: true
  never_edit_production_code: true
  only_writes: [.claude/state/feature-improvements/**, .claude/state/zombie-worker-daemon.{pid,stop}]

CLI: --watch | --once | --status | --stop
"""

import argparse
import json
import os
import time
from pathlib import Path

import zombie_worker

from citadel._process import pid_is_alive as process_is_alive

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
STATE = ROOT / ".claude" / "state"
PID_FILE = STATE / "zombie-worker-daemon.pid"
STOP_FILE = STATE / "zombie-worker-daemon.stop"

_POLL_INTERVAL = 300


def watch() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()) + "\n")
    STOP_FILE.unlink(missing_ok=True)
    try:
        while not STOP_FILE.exists():
            zombie_worker.run_once()
            time.sleep(_POLL_INTERVAL)
    finally:
        PID_FILE.unlink(missing_ok=True)
        STOP_FILE.unlink(missing_ok=True)


def status() -> None:
    print("# Zombie Worker Daemon")
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        try:
            alive = process_is_alive(int(pid))
        except ValueError:
            alive = False
        print(f"pid: {pid}\nrunning: {'yes' if alive else 'no'}")
    else:
        print("running: no")


def main() -> None:
    ap = argparse.ArgumentParser(description="Zombie worker daemon.")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    STATE.mkdir(parents=True, exist_ok=True)
    if args.stop:
        STOP_FILE.write_text("stop\n")
    elif args.status:
        status()
    elif args.watch:
        watch()
    else:
        result = zombie_worker.run_once()
        if not args.quiet:
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
