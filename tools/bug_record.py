#!/usr/bin/env python3
"""bug_record.py — the bug-record "company": zero-token bug detection, dedup, and self-heal triage.

Scans local state (no hosted-model calls) for failure signals, classifies them into a deduped
bug ledger, and — for classes that legion_self_heal can repair — drives a closed remediation loop.

Sources scanned:
  - .claude/state/self-heal.ndjson  (latest run's findings = current open init issues)
  - .claude/state/**/*.err.log      (daemon/hook stderr — tracebacks and error signatures)

Outputs:
  - .claude/state/bug-ledger.ndjson    (append-only detection + remediation events)
  - .claude/state/bug-ledger.json      (deduped rollup keyed by fingerprint, with counts + status)
  - .claude/state/restart-request.json (written only for a NEW critical detection — see below)

Critical vs non-critical (per the notify-and-schedule policy, not silent auto-restart):
  A detection whose message matches a critical signature (port bind conflict, crash-loop) is
  marked severity="critical" and — on first sighting only — writes restart-request.json with a
  human-readable reason. Nothing in this repo restarts the running session (that would kill the
  very session filing the report); the marker is a durable, visible request for the NEXT
  `citadel up` boot / for the operator to restart when convenient. Non-critical bugs are
  simply filed for the existing self-heal/manual review loop.

Err-log staleness: a `<name>.err.log` traceback is only counted as an OPEN bug if the daemon has
not cleanly restarted since — detected by comparing the log's mtime to the sibling `<name>.pid`
mtime. This stops fixed-in-code bugs (e.g. an old traceback from before an `exist_ok=True` fix)
from being reported as open forever.

Safety contract:
  never_call_claude: true
  never_edit_production_code: true   (remediation is delegated to legion_self_heal --fix only)

CLI: --scan | --triage | --status | --json
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
STATE = ROOT / ".claude" / "state"
SELF_HEAL_LOG = STATE / "self-heal.ndjson"
BUG_LEDGER = STATE / "bug-ledger.ndjson"
BUG_ROLLUP = STATE / "bug-ledger.json"
RESTART_REQUEST = STATE / "restart-request.json"
SELF_HEAL_TOOL = Path(__file__).resolve().parent / "legion_self_heal.py"

_ERR_SIGNATURES = re.compile(
    r"Traceback \(most recent call last\)|"
    r"\w*(?:Error|Exception):|"
    r"\bFAILED\b|\bfatal\b|"
    r"non-zero (?:exit|status)|No stderr output",
)
_CRITICAL_SIGNATURES = re.compile(
    r"Address already in use|Errno 48|Errno 98|"
    r"port .*(?:already|in use)|failed to bind|"
    r"OSError: \[Errno \d+\]",
    re.IGNORECASE,
)
_LOG_TAIL_LINES = 400
_MAX_ERR_DETECTIONS = 50
_SELF_HEAL_REMEDIABLE = frozenset({
    "duplicate_divergent_hook", "unguarded_git_in_hook", "malformed_json", "missing_hook_script",
})


def _classify_severity(kind: str, message: str) -> str:
    if kind == "log_error" and _CRITICAL_SIGNATURES.search(message):
        return "critical"
    return "medium" if kind == "log_error" else "high"


def _daemon_name_from_log(log: Path) -> str:
    name = log.name
    return name[: -len(".err.log")] if name.endswith(".err.log") else log.stem


def _log_is_stale(log: Path) -> bool:
    """True if the daemon has restarted cleanly since this log's last write."""
    pidfile = log.with_name(f"{_daemon_name_from_log(log)}.pid")
    if not pidfile.exists():
        return False
    try:
        return pidfile.stat().st_mtime > log.stat().st_mtime
    except OSError:
        return False


def _write_restart_request(reason: str, fingerprint: str) -> None:
    RESTART_REQUEST.parent.mkdir(parents=True, exist_ok=True)
    RESTART_REQUEST.write_text(json.dumps({
        "requested_at": _now(),
        "reason": reason,
        "fingerprint": fingerprint,
        "severity": "critical",
        "note": "Auto-detected by bug_record. Not auto-restarted (would kill the active "
                "session). Restart `citadel up` when convenient; the next boot's "
                "self-heal/health-check will clear this marker once resolved.",
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _fingerprint(kind: str, path: str, message: str) -> str:
    norm = re.sub(r"\d+", "#", f"{kind}|{path}|{message}")[:300]
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def _load_rollup() -> dict:
    try:
        return json.loads(BUG_ROLLUP.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_rollup(rollup: dict) -> None:
    BUG_ROLLUP.parent.mkdir(parents=True, exist_ok=True)
    BUG_ROLLUP.write_text(json.dumps(rollup, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_event(rec: dict) -> None:
    BUG_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    rec["ts"] = _now()
    with BUG_LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _latest_self_heal_findings() -> list[dict]:
    if not SELF_HEAL_LOG.exists():
        return []
    last = ""
    for line in SELF_HEAL_LOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last = line
    if not last:
        return []
    try:
        return json.loads(last).get("findings", [])
    except json.JSONDecodeError:
        return []


def _detect_self_heal() -> list[dict]:
    out: list[dict] = []
    for f in _latest_self_heal_findings():
        out.append({
            "kind": f.get("kind", "unknown"),
            "source": "self-heal",
            "path": f.get("path", ""),
            "severity": f.get("severity", "medium"),
            "message": f.get("detail", ""),
        })
    return out


def _detect_err_logs() -> tuple[list[dict], bool]:
    """Return (detections, capped). ``capped`` means the scan hit _MAX_ERR_DETECTIONS,
    so absence from this scan is NOT reliable evidence of resolution."""
    out: list[dict] = []
    if not STATE.exists():
        return out, False
    for log in sorted(STATE.rglob("*.err.log")):
        if _log_is_stale(log):
            continue
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines[-_LOG_TAIL_LINES:]:
            if _ERR_SIGNATURES.search(line):
                message = line.strip()[:200]
                out.append({
                    "kind": "log_error",
                    "source": "err-log",
                    "path": str(log.relative_to(ROOT)),
                    "severity": _classify_severity("log_error", message),
                    "message": message,
                })
                if len(out) >= _MAX_ERR_DETECTIONS:
                    return out, True
    return out, False


def scan_once() -> dict:
    err_detections, err_capped = _detect_err_logs()
    detections = _detect_self_heal() + err_detections
    rollup = _load_rollup()
    seen_self_heal: set[str] = set()
    seen_err_log: set[str] = set()
    new_count = 0
    now = _now()

    for d in detections:
        fp = _fingerprint(d["kind"], d["path"], d["message"])
        if d["source"] == "self-heal":
            seen_self_heal.add(fp)
        elif d["source"] == "err-log":
            seen_err_log.add(fp)
        if fp in rollup:
            rec = rollup[fp]
            rec["count"] += 1
            rec["last_seen"] = now
            if rec.get("status") == "resolved":
                rec["status"] = "open"
        else:
            rollup[fp] = {
                "fingerprint": fp, "kind": d["kind"], "source": d["source"],
                "path": d["path"], "severity": d["severity"], "sample": d["message"],
                "count": 1, "first_seen": now, "last_seen": now, "status": "open",
                "remediation": None,
            }
            new_count += 1
            _append_event({"event": "bug_detected", **rollup[fp]})
            if d["severity"] == "critical":
                _write_restart_request(d["message"], fp)
                _append_event({"event": "restart_requested", "fingerprint": fp,
                               "reason": d["message"]})

    closed = 0
    for fp, rec in rollup.items():
        stale_source = (
            (rec["source"] == "self-heal" and fp not in seen_self_heal) or
            (rec["source"] == "err-log" and not err_capped and fp not in seen_err_log)
        )
        if rec["status"] == "open" and stale_source:
            rec["status"] = "resolved"
            rec["remediation"] = "cleared"
            closed += 1
            _append_event({"event": "bug_resolved", "fingerprint": fp, "kind": rec["kind"]})
            if rec.get("severity") == "critical" and RESTART_REQUEST.exists():
                try:
                    if json.loads(RESTART_REQUEST.read_text(encoding="utf-8")).get("fingerprint") == fp:
                        RESTART_REQUEST.unlink(missing_ok=True)
                except (OSError, json.JSONDecodeError):
                    pass

    _save_rollup(rollup)
    open_count = sum(1 for r in rollup.values() if r["status"] == "open")
    return {"detections": len(detections), "new": new_count, "auto_closed": closed,
            "open": open_count, "total": len(rollup)}


def triage(threshold: int = 1) -> dict:
    rollup = _load_rollup()
    remediable = [
        r for r in rollup.values()
        if r["status"] == "open" and r["kind"] in _SELF_HEAL_REMEDIABLE and r["count"] >= threshold
    ]
    filed = [
        r["fingerprint"] for r in rollup.values()
        if r["status"] == "open" and r["kind"] not in _SELF_HEAL_REMEDIABLE
    ]
    dispatched = False
    if remediable and SELF_HEAL_TOOL.exists():
        _append_event({"event": "self_heal_dispatched",
                       "fingerprints": [r["fingerprint"] for r in remediable]})
        env = {**os.environ, "CITADEL_WORKSPACE": str(ROOT)}
        subprocess.run(
            [sys.executable, str(SELF_HEAL_TOOL), "--fix", "--quiet"],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
        )
        subprocess.run(
            [sys.executable, str(SELF_HEAL_TOOL), "--check", "--quiet"],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
        )
        dispatched = True

    result_after = scan_once() if dispatched else {"open": sum(
        1 for r in rollup.values() if r["status"] == "open")}
    return {"remediable": len(remediable), "self_heal_dispatched": dispatched,
            "filed_for_review": len(filed), "open_after": result_after["open"]}


def status() -> None:
    rollup = _load_rollup()
    open_recs = [r for r in rollup.values() if r["status"] == "open"]
    print("# Bug-Record Company")
    print(f"total records: {len(rollup)}  open: {len(open_recs)}")
    if RESTART_REQUEST.exists():
        try:
            req = json.loads(RESTART_REQUEST.read_text(encoding="utf-8"))
            print(f"  [CRITICAL] restart requested at {req.get('requested_at')}: {req.get('reason')}")
        except (OSError, json.JSONDecodeError):
            pass
    for r in sorted(open_recs, key=lambda x: -x["count"])[:10]:
        print(f"  [{r['severity']}] {r['kind']} x{r['count']} {r['path']}: {r['sample'][:70]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Bug-record company: detect, dedup, triage.")
    ap.add_argument("--scan", action="store_true", help="Scan sources and update the ledger")
    ap.add_argument("--triage", action="store_true", help="Drive self-heal for remediable bugs")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    if args.status:
        status()
        return
    result = triage() if args.triage else scan_once()

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
