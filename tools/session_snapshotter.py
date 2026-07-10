#!/usr/bin/env python3
"""session_snapshotter.py — mid-session full-context save (never lose context on /compact).

Runs on PostToolBatch (and can be called on an interval). The batch payload already carries
`session_id` + `transcript_path`, so we persist a durable copy of the live transcript plus a
lightweight turn index under `.claude/state/session-context/<session_id>/`. These are RAW session
artifacts kept out of the bounded/redacted routing-capsule path, so the full conversation is
recoverable even after `/compact` trims the in-context window.

Snapshots are deduped by size and rotated (keep last K) so firing every batch is cheap.

Safety contract: never_call_claude, never_edit_production_code. Only writes under
`.claude/state/session-context/`.

CLI:
  (no args, stdin=hook payload) : snapshot from the PostToolBatch payload; prints "{}"
  --status                      : summarize known sessions
  --restore --session <id>      : print the latest snapshot path + manifest for a session
"""

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path


def _root() -> Path:
    for env in ("CITADEL_WORKSPACE", "CLAUDE_PROJECT_DIR"):
        v = os.environ.get(env)
        if v:
            return Path(v).expanduser().resolve()
    return Path.cwd()


ROOT = _root()
SESS_DIR = ROOT / ".claude" / "state" / "session-context"

_SNAPSHOT_MIN_DELTA_BYTES = 4096
_KEEP_SNAPSHOTS = 5


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_stdin() -> dict:
    raw = sys.stdin.read()
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


def snapshot(payload: dict) -> dict:
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    if not session_id:
        return {"skipped": "no session_id"}

    sdir = SESS_DIR / str(session_id)
    snaps = sdir / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)

    turn_line = {"ts": _now(), "size_chars": len(json.dumps(payload, ensure_ascii=False)),
                 "keys": sorted(payload.keys())}
    with (sdir / "turn-index.ndjson").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(turn_line, sort_keys=True) + "\n")

    copied = None
    tpath = Path(transcript_path).expanduser() if transcript_path else None
    if tpath and tpath.is_file():
        existing = sorted(snaps.glob("*.jsonl"))
        last = existing[-1] if existing else None
        cur_size = tpath.stat().st_size
        grew = last is None or abs(cur_size - last.stat().st_size) >= _SNAPSHOT_MIN_DELTA_BYTES
        if grew:
            stamp = _now().replace(":", "").replace("-", "").replace(".", "")
            dest = snaps / f"{stamp}.jsonl"
            shutil.copy2(tpath, dest)
            copied = dest.name
            for old in sorted(snaps.glob("*.jsonl"))[:-_KEEP_SNAPSHOTS]:
                old.unlink(missing_ok=True)

    manifest = {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "last_batch_ts": turn_line["ts"],
        "batches": _count_lines(sdir / "turn-index.ndjson"),
        "snapshots": sorted(p.name for p in snaps.glob("*.jsonl")),
        "last_snapshot": copied,
    }
    (sdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"session_id": session_id, "snapshotted": copied, "batches": manifest["batches"]}


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())


def restore(session_id: str) -> dict | None:
    manifest_path = SESS_DIR / session_id / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snaps = SESS_DIR / session_id / "snapshots"
    latest = sorted(snaps.glob("*.jsonl"))[-1] if any(snaps.glob("*.jsonl")) else None
    return {"manifest": manifest,
            "latest_snapshot": str(latest.relative_to(ROOT)) if latest else None}


def status() -> None:
    if not SESS_DIR.exists():
        print("session-snapshotter: no sessions recorded")
        return
    sessions = [d for d in SESS_DIR.iterdir() if d.is_dir()]
    print(f"session-snapshotter: {len(sessions)} session(s)")
    for d in sorted(sessions):
        n = len(list((d / "snapshots").glob("*.jsonl"))) if (d / "snapshots").exists() else 0
        print(f"  {d.name}: {n} snapshot(s)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Mid-session full-context snapshotter.")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--session", metavar="ID")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    if args.status:
        status()
        return
    if args.restore:
        result = restore(args.session) if args.session else None
        print(json.dumps(result, indent=2) if args.as_json else (result or "no such session"))
        return

    result = snapshot(_safe_stdin())
    print(json.dumps(result) if args.as_json else "{}")


if __name__ == "__main__":
    main()
