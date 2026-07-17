#!/usr/bin/env python3
"""outcome_miner_daemon.py — Zero-token outcome miner daemon.

Polls task-ledger.ndjson and agent-run-ledger.ndjson for completed tasks.
Extracts Pass / Blocked / Needs Fix signals and appends compact entries to:
  docs/ai-context/what-worked.md
  docs/ai-context/what-did-not-work.md

Safety contract:
  never_call_claude: true
  never_edit_production_code: true
  only_writes: [docs/ai-context/what-worked.md, docs/ai-context/what-did-not-work.md,
                .claude/state/outcome-miner-*.{pid,stop,events.ndjson}]
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
STATE = ROOT / ".claude" / "state"
WHAT_WORKED = ROOT / "docs" / "ai-context" / "what-worked.md"
WHAT_FAILED = ROOT / "docs" / "ai-context" / "what-did-not-work.md"
TASK_LEDGER = STATE / "task-ledger.ndjson"
AGENT_LEDGER = STATE / "agent-run-ledger.ndjson"
CURSOR_FILE = STATE / "outcome-miner-cursor.json"
PID_FILE = STATE / "outcome-miner-daemon.pid"
STOP_FILE = STATE / "outcome-miner-daemon.stop"
EVENTS_FILE = STATE / "outcome-miner-events.ndjson"

_POLL_INTERVAL = 30
_MAX_ENTRY_CHARS = 400
_MAX_ENTRIES_PER_RUN = 5


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _log(msg: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    line = f"{_now()} {msg}\n"
    with (STATE / "outcome-miner-daemon.log").open("a") as f:
        f.write(line)
    print(line, end="", flush=True)


def _event(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with EVENTS_FILE.open("a") as f:
        f.write(json.dumps({"ts": _now(), **data}, sort_keys=True) + "\n")


def _load_cursor() -> dict:
    try:
        return json.loads(CURSOR_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"task_ledger_lines": 0, "agent_ledger_lines": 0}


def _save_cursor(cursor: dict) -> None:
    CURSOR_FILE.write_text(json.dumps(cursor, indent=2) + "\n")


def _read_new_lines(path: Path, from_line: int) -> "tuple[list[str], int]":
    """Read lines from `from_line` onward. Returns (new_lines, new_line_count)."""
    if not path.exists():
        return [], from_line
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[from_line:], len(lines)


def _extract_outcomes(lines: list[str]) -> "tuple[list[str], list[str]]":
    """Extract worked/failed snippets from ledger lines. Returns (worked, failed)."""
    worked: list[str] = []
    failed: list[str] = []
    for raw in lines:
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        verdict = str(rec.get("verdict", rec.get("status", ""))).lower()
        task_type = str(rec.get("task_type", rec.get("event", "")))
        agent = str(rec.get("agent_id", rec.get("agent", "")))
        summary = str(rec.get("summary", rec.get("result", rec.get("output", ""))))[:200]
        ts = str(rec.get("ts", rec.get("created_at", _now())))[:19]

        if not verdict:
            continue

        tag = f"{task_type}/{agent}".strip("/") or "unknown"
        snippet = f"## Auto-mined {ts} ({tag})\n{summary[:_MAX_ENTRY_CHARS]}\n"

        if any(v in verdict for v in ["pass", "success", "completed"]):
            worked.append(snippet)
        elif any(v in verdict for v in ["blocked", "fail", "needs fix", "error"]):
            failed.append(snippet)

    return worked, failed


def _append_if_new(path: Path, entry: str, header: str) -> bool:
    """Append entry to path if it isn't already there. Returns True if appended."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"# {header}\n\n", encoding="utf-8")
    existing = path.read_text(encoding="utf-8")
    key = entry[:80].strip()
    if key in existing:
        return False
    with path.open("a", encoding="utf-8") as f:
        f.write("\n" + entry)
    return True


def _bridge_record(entry: str, *, success: bool, category: str) -> None:
    """Best-effort: fold a mined outcome into the shared brain ledger (never fatal to the daemon)."""
    try:
        from _learning_bridge import record_outcome

        record_outcome(entry[:200], "outcome-miner", success=success, category=category, summary=entry[:200])
    except Exception:
        pass


def mine_once() -> dict:
    cursor = _load_cursor()
    task_lines, new_task_count = _read_new_lines(TASK_LEDGER, cursor["task_ledger_lines"])
    agent_lines, new_agent_count = _read_new_lines(AGENT_LEDGER, cursor["agent_ledger_lines"])

    all_worked: list[str] = []
    all_failed: list[str] = []
    for lines in (task_lines, agent_lines):
        w, f = _extract_outcomes(lines)
        all_worked.extend(w)
        all_failed.extend(f)

    written_worked = written_failed = 0
    for entry in all_worked[:_MAX_ENTRIES_PER_RUN]:
        if _append_if_new(WHAT_WORKED, entry, "What Worked"):
            written_worked += 1
            _bridge_record(entry, success=True, category="worked")
    for entry in all_failed[:_MAX_ENTRIES_PER_RUN]:
        if _append_if_new(WHAT_FAILED, entry, "What Did Not Work"):
            written_failed += 1
            _bridge_record(entry, success=False, category="failed")

    cursor["task_ledger_lines"] = new_task_count
    cursor["agent_ledger_lines"] = new_agent_count
    _save_cursor(cursor)

    result = {
        "new_task_lines": len(task_lines),
        "new_agent_lines": len(agent_lines),
        "written_worked": written_worked,
        "written_failed": written_failed,
    }
    _event({"event": "mine_once", **result})
    return result


def watch() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()) + "\n")
    STOP_FILE.unlink(missing_ok=True)
    _log(f"outcome miner daemon started pid={os.getpid()}")
    try:
        while not STOP_FILE.exists():
            result = mine_once()
            if result["written_worked"] or result["written_failed"]:
                _log(
                    f"mined: +{result['written_worked']} worked, "
                    f"+{result['written_failed']} failed"
                )
            time.sleep(_POLL_INTERVAL)
    finally:
        _log("outcome miner daemon stopped")
        PID_FILE.unlink(missing_ok=True)
        STOP_FILE.unlink(missing_ok=True)


def status() -> None:
    print("# Outcome Miner Daemon")
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        alive = False
        try:
            os.kill(int(pid), 0)
            alive = True
        except Exception:
            pass
        print(f"pid: {pid}")
        print(f"running: {'yes' if alive else 'no'}")
    else:
        print("running: no")
    if CURSOR_FILE.exists():
        try:
            cur = json.loads(CURSOR_FILE.read_text())
            print(f"task_ledger_lines_processed: {cur.get('task_ledger_lines', 0)}")
            print(f"agent_ledger_lines_processed: {cur.get('agent_ledger_lines', 0)}")
        except Exception:
            pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Outcome miner daemon.")
    ap.add_argument("--watch", action="store_true", help="Run as a background daemon")
    ap.add_argument("--once", action="store_true", help="Mine once and exit")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--stop", action="store_true")
    args = ap.parse_args()

    STATE.mkdir(parents=True, exist_ok=True)
    if args.stop:
        STOP_FILE.write_text("stop\n")
    elif args.status:
        status()
    elif args.watch:
        watch()
    else:
        result = mine_once()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
