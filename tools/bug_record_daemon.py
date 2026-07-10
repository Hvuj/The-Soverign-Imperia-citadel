#!/usr/bin/env python3
"""bug_record_daemon.py — Zero-token bug-record company daemon.

Periodically scans local state for failure signals (via bug_record.scan_once) and drives
self-heal remediation for repairable classes (via bug_record.triage). Never calls a hosted
model; never edits production code (remediation is delegated to legion_self_heal --fix).

Safety contract:
  never_call_claude: true
  never_edit_production_code: true
  only_writes: [.claude/state/bug-ledger.{ndjson,json},
                .claude/state/bug-record-daemon.{pid,stop},
                .claude/state/self-heal/** (via delegated legion_self_heal --fix)]

CLI: --watch | --once | --status | --stop
"""

import argparse
import json
import os
import time
from pathlib import Path

import bug_record

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
STATE = ROOT / ".claude" / "state"
PID_FILE = STATE / "bug-record-daemon.pid"
STOP_FILE = STATE / "bug-record-daemon.stop"

_POLL_INTERVAL = 45


def run_once() -> dict:
    scan = bug_record.scan_once()
    triage = bug_record.triage()
    return {"scan": scan, "triage": triage}


def watch() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()) + "\n")
    STOP_FILE.unlink(missing_ok=True)
    try:
        while not STOP_FILE.exists():
            run_once()
            time.sleep(_POLL_INTERVAL)
    finally:
        PID_FILE.unlink(missing_ok=True)
        STOP_FILE.unlink(missing_ok=True)


def status() -> None:
    print("# Bug-Record Daemon")
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        alive = False
        try:
            os.kill(int(pid), 0)
            alive = True
        except (OSError, ValueError):
            pass
        print(f"pid: {pid}")
        print(f"running: {'yes' if alive else 'no'}")
    else:
        print("running: no")
    bug_record.status()


def main() -> None:
    ap = argparse.ArgumentParser(description="Bug-record company daemon.")
    ap.add_argument("--watch", action="store_true", help="Run as a background daemon")
    ap.add_argument("--once", action="store_true", help="Scan + triage once and exit")
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
        result = run_once()
        if not args.quiet:
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
