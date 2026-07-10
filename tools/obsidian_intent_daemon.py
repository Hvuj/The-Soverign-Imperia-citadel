#!/usr/bin/env python3
"""Phase 1 — Obsidian Intent Daemon

OS file-watch sensory interface for the The Sovereign Imperia Citadel framework.
Watches docs/obsidian-vault/ for .md modifications, extracts #task/active intent,
and atomically writes .claude/state/active-intent.json (status: PENDING_ORCHESTRATION).

Architecture
------------
  OS Observer thread  ──►  queue.Queue  ──►  Worker thread
  (watchdog events)         (non-blocking)    (disk / regex / JSON, sequential)

  Stdlib mtime-polling fallback activates automatically when watchdog is absent.

Usage
-----
  python tools/obsidian_intent_daemon.py            # start watch daemon (blocks)
  python tools/obsidian_intent_daemon.py --watch    # explicit --watch flag
  python tools/obsidian_intent_daemon.py --once FILE
  python tools/obsidian_intent_daemon.py --status
  python tools/obsidian_intent_daemon.py --stop
  python tools/obsidian_intent_daemon.py --test     # built-in self-tests
"""

import argparse
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path


_ROOT: Path = Path(__file__).resolve().parents[1]
_STATE: Path = _ROOT / ".claude" / "state"
_DEFAULT_VAULT: Path = _ROOT / "docs" / "obsidian-vault"
_CONFIG_FILE: Path = _ROOT / ".claude" / "daemon" / "obsidian-intent-config.json"

_ACTIVE_INTENT: Path = _STATE / "active-intent.json"
_EVENTS: Path = _STATE / "incremental-brain-events.ndjson"

_PID: Path = _STATE / "obsidian-intent-daemon.pid"
_STOP: Path = _STATE / "obsidian-intent-daemon.stop"

MAX_FILE_BYTES: int = 10_485_760
DEBOUNCE_SECONDS: float = 0.5
EXCLUSIONS: frozenset[str] = frozenset({".obsidian", ".git", ".trash", ".claude"})

_INTENT_RE = re.compile(r"(?ms)^#task/active[\s:](.*?)(?=\n\n|\n#|\Z)")
_TAG_STRIP_RE = re.compile(r"#task/active[\s:]*")


def _load_cfg() -> dict:
    """Load optional config file; return empty dict on any failure."""
    try:
        if _CONFIG_FILE.exists():
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _append_event(record: dict, events_path: Path | None = None) -> None:
    """Append a structured event to the NDJSON ledger (best-effort, never raises)."""
    path = events_path or _EVENTS
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _iso_now(), **record}, sort_keys=True) + "\n")
    except Exception:
        pass


def _is_excluded(path_str: str) -> bool:
    """§2.2 — True if any path segment matches an EXCLUSIONS token."""
    return bool(frozenset(Path(path_str).parts) & EXCLUSIONS)


def _atomic_write_json(dest: Path, data: dict) -> None:
    """§6.2 — Atomic write: stage .tmp → f.flush() → os.fsync() → os.replace()."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(dest) + ".tmp")
    try:
        payload = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(dest))
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _process_file(
    filepath: Path,
    *,
    active_intent: Path | None = None,
    events: Path | None = None,
    root: Path | None = None,
    max_bytes: int | None = None,
) -> bool:
    """Extract #task/active intent from one .md file; write active-intent.json atomically.

    Returns True if intent was extracted and written, False otherwise.
    Injectable paths (active_intent, events, root, max_bytes) enable clean testing.
    """
    intent_dest = active_intent or _ACTIVE_INTENT
    ev_path = events or _EVENTS
    project_root = root or _ROOT

    cfg = _load_cfg()
    limit = max_bytes if max_bytes is not None else int(cfg.get("max_file_bytes", MAX_FILE_BYTES))

    try:
        size = filepath.stat().st_size
    except OSError as exc:
        _append_event({"event": "intent_error", "path": str(filepath), "reason": f"stat: {exc}"}, ev_path)
        return False

    if size > limit:
        _append_event({
            "event": "intent_skipped",
            "path": str(filepath),
            "reason": f"oversized {size} > {limit}",
        }, ev_path)
        return False

    try:
        with open(filepath, encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError as exc:
        _append_event({"event": "intent_error", "path": str(filepath), "reason": str(exc)}, ev_path)
        return False

    match = _INTENT_RE.search(content)
    if not match:
        return False

    raw = _TAG_STRIP_RE.sub("", match.group(1)).strip()
    if not raw:
        return False

    try:
        source_file = str(filepath.relative_to(project_root))
    except ValueError:
        source_file = str(filepath)

    payload: dict = {
        "source_file": source_file,
        "timestamp": os.path.getmtime(str(filepath)),
        "raw_intent": raw,
        "status": "PENDING_ORCHESTRATION",
    }

    _atomic_write_json(intent_dest, payload)
    _append_event({
        "event": "intent_extracted",
        "source_file": source_file,
        "raw_intent_preview": raw[:120],
        "size_bytes": size,
    }, ev_path)
    return True


def _build_handler(
    work_q: "queue.Queue[str | None]",
    debounce: dict[str, float],
    debounce_secs: float,
):
    """Return a watchdog FileSystemEventHandler that feeds .md paths into work_q."""
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def on_any_event(self, event):  # type: ignore[override]
            if event.is_directory:
                return
            src: str = getattr(event, "src_path", "")
            if not src.endswith(".md"):
                return
            if _is_excluded(src):
                return
            now = time.perf_counter()
            if (now - debounce.get(src, 0.0)) < debounce_secs:
                return
            debounce[src] = now
            work_q.put(src)

    return _Handler()


def _worker_loop(
    work_q: "queue.Queue[str | None]",
    active_intent: Path,
    events: Path,
    root: Path,
) -> None:
    """Drain work_q sequentially — insulates OS handler from blocking I/O."""
    while True:
        try:
            item = work_q.get(timeout=1.0)
        except queue.Empty:
            continue
        if item is None:
            break
        try:
            _process_file(Path(item), active_intent=active_intent, events=events, root=root)
        except Exception as exc:
            _append_event({"event": "intent_error", "path": item, "reason": str(exc)}, events)


def _watch_watchdog(vault: Path, active_intent: Path, events: Path, root: Path) -> None:
    """§1.1 — OS-event watch loop; blocks until _STOP sentinel appears."""
    from watchdog.observers import Observer

    cfg = _load_cfg()
    debounce_secs = float(cfg.get("debounce_seconds", DEBOUNCE_SECONDS))

    work_q: queue.Queue[str | None] = queue.Queue()
    debounce: dict[str, float] = {}

    observer = Observer()
    observer.schedule(_build_handler(work_q, debounce, debounce_secs), str(vault), recursive=True)

    worker = threading.Thread(
        target=_worker_loop, args=(work_q, active_intent, events, root), daemon=True
    )
    worker.start()
    observer.start()

    try:
        while not _STOP.exists():
            time.sleep(0.25)
    finally:
        observer.stop()
        observer.join(timeout=5)
        work_q.put(None)
        worker.join(timeout=5)


def _watch_polling(vault: Path, active_intent: Path, events: Path, root: Path) -> None:
    """Mtime-polling fallback (no watchdog). Blocks until _STOP sentinel appears."""
    cfg = _load_cfg()
    poll_interval = float(cfg.get("poll_interval_seconds", 1.0))
    debounce_secs = float(cfg.get("debounce_seconds", DEBOUNCE_SECONDS))

    snap: dict[str, float] = {}
    debounce: dict[str, float] = {}

    for md in vault.rglob("*.md"):
        if not _is_excluded(str(md)):
            try:
                snap[str(md)] = md.stat().st_mtime
            except OSError:
                pass

    while not _STOP.exists():
        time.sleep(poll_interval)
        for md in list(vault.rglob("*.md")):
            s = str(md)
            if _is_excluded(s):
                continue
            try:
                mtime = md.stat().st_mtime
            except OSError:
                continue
            if mtime == snap.get(s, -1.0):
                continue
            snap[s] = mtime
            now = time.perf_counter()
            if (now - debounce.get(s, 0.0)) < debounce_secs:
                continue
            debounce[s] = now
            try:
                _process_file(md, active_intent=active_intent, events=events, root=root)
            except Exception as exc:
                _append_event({"event": "intent_error", "path": s, "reason": str(exc)}, events)


def _run_watch() -> None:
    cfg = _load_cfg()
    if not cfg.get("enabled", True):
        print("obsidian-intent-daemon: disabled in config")
        return

    vault_override = cfg.get("vault_path_override")
    vault = Path(vault_override) if vault_override else _DEFAULT_VAULT

    if not vault.exists():
        _STATE.mkdir(parents=True, exist_ok=True)
        _append_event({"event": "intent_daemon_noop", "reason": "vault absent", "vault": str(vault)})
        print(f"obsidian-intent-daemon: vault absent at {vault} — sleeping until stop sentinel")
        while not _STOP.exists():
            time.sleep(5.0)
        return

    _STATE.mkdir(parents=True, exist_ok=True)
    _PID.write_text(str(os.getpid()) + "\n")
    _STOP.unlink(missing_ok=True)
    _append_event({"event": "intent_daemon_start", "pid": os.getpid(), "vault": str(vault)})
    print(f"obsidian-intent-daemon: started pid={os.getpid()} vault={vault}")

    try:
        from watchdog.observers import Observer as _WDO  # noqa: F401
        _append_event({"event": "intent_daemon_mode", "mode": "watchdog"})
        _watch_watchdog(vault, _ACTIVE_INTENT, _EVENTS, _ROOT)
    except ImportError:
        _append_event({"event": "intent_daemon_mode", "mode": "polling_fallback"})
        print("obsidian-intent-daemon: watchdog unavailable, using stdlib polling fallback")
        _watch_polling(vault, _ACTIVE_INTENT, _EVENTS, _ROOT)
    finally:
        _append_event({"event": "intent_daemon_stop"})
        _PID.unlink(missing_ok=True)
        _STOP.unlink(missing_ok=True)


def _run_once(filepath_str: str) -> None:
    fp = Path(filepath_str).resolve()
    ok = _process_file(fp)
    print(f"{'extracted' if ok else 'no match / skipped'}: {fp}")


def _run_status() -> None:
    print("# Obsidian Intent Daemon")
    if _PID.exists():
        pid = _PID.read_text().strip()
        alive = False
        try:
            os.kill(int(pid), 0)
            alive = True
        except Exception:
            pass
        print(f"pid:     {pid}")
        print(f"running: {'yes' if alive else 'no (stale pid)'}")
    else:
        print("running: no")

    if _ACTIVE_INTENT.exists():
        try:
            data = json.loads(_ACTIVE_INTENT.read_text(encoding="utf-8"))
            print(f"status:  {data.get('status')}")
            print(f"source:  {data.get('source_file')}")
            print(f"intent:  {data.get('raw_intent', '')[:100]}")
        except Exception:
            print("active_intent: (parse error)")
    else:
        print("active_intent: none")


def _run_test() -> None:  # noqa: C901 — intentional comprehensive test
    """Built-in self-tests. Exit 0 on pass, 1 on any failure."""
    errs: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault = root / "vault"
        vault.mkdir()
        state = root / "state"
        state.mkdir()
        ai = state / "active-intent.json"
        ev = state / "events.ndjson"

        def proc(name: str, body: str, **kw) -> bool:
            md = vault / name
            md.parent.mkdir(parents=True, exist_ok=True)
            md.write_text(body, encoding="utf-8")
            return _process_file(md, active_intent=ai, events=ev, root=root, **kw)

        ok = proc("tasks/oil.md", "#task/active Add schemaval schema check for sample feature\n\nMore notes\n")
        if not ok:
            errs.append("T1: expected True (intent extracted), got False")
        if ai.exists():
            d = json.loads(ai.read_text())
            for k in ("source_file", "timestamp", "raw_intent", "status"):
                if k not in d:
                    errs.append(f"T1: missing required key {k!r} in output schema")
            if d.get("status") != "PENDING_ORCHESTRATION":
                errs.append(f"T1: status={d.get('status')!r}, want 'PENDING_ORCHESTRATION'")
            if not d.get("raw_intent"):
                errs.append("T1: raw_intent is empty")
            if (state / "active-intent.json.tmp").exists():
                errs.append("T1: leftover .tmp file — atomic write did not clean up")
        else:
            errs.append("T1: active-intent.json was not written")

        ai.unlink(missing_ok=True)
        ok = proc("tasks/notes.md", "Just plain notes without any active task tag\n")
        if ok:
            errs.append("T2: no-match file should return False")
        if ai.exists():
            errs.append("T2: active-intent.json should not be written on no-match")

        ok = proc("tasks/empty.md", "#task/active\n\n")
        if ok:
            errs.append("T3: blank intent after tag should return False")

        if MAX_FILE_BYTES != 10_485_760:
            errs.append(f"T4: MAX_FILE_BYTES={MAX_FILE_BYTES}, want 10485760")

        small = vault / "tasks" / "small.md"
        small.write_text("#task/active Check sample feature prices\n", encoding="utf-8")
        ok = _process_file(small, active_intent=ai, events=ev, root=root, max_bytes=10)
        if ok:
            errs.append("T5: file over threshold should return False")
        if ev.exists():
            events_data = [json.loads(ln) for ln in ev.read_text().splitlines() if ln.strip()]
            skipped = [e for e in events_data if e.get("event") == "intent_skipped"]
            if not skipped:
                errs.append("T5: no intent_skipped event logged for oversized file")
        else:
            errs.append("T5: events file not written")

        cases = [
            (".git/foo.md", True),
            ("docs/.obsidian/config.md", True),
            (".trash/old.md", True),
            (".claude/state/active-intent.json", True),
            ("docs/obsidian-vault/tasks/oil.md", False),
            ("tools/build_graph.py", False),
        ]
        for path_str, want_excluded in cases:
            got = _is_excluded(path_str)
            if got != want_excluded:
                errs.append(f"T6: _is_excluded({path_str!r})={got}, want {want_excluded}")

        body = "#task/active: Validate oil prices\nAcross multiple exchanges\n\nNext section"
        m = _INTENT_RE.search(body)
        if not m:
            errs.append("T7: regex did not match multi-line #task/active block")
        else:
            captured = _TAG_STRIP_RE.sub("", m.group(1)).strip()
            if "Validate oil prices" not in captured:
                errs.append(f"T7: captured text missing expected phrase: {captured!r}")
            if "Next section" in captured:
                errs.append("T7: lookahead failed — captured text past double-newline boundary")

        mid_prose = "This text mentions #task/active in the middle of a sentence"
        m2 = _INTENT_RE.search(mid_prose)
        if m2:
            errs.append(f"T8: regex matched mid-prose (should require line-start): {m2.group()!r}")

    if errs:
        for e in errs:
            print(f"  FAIL  {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  PASS  all 8 self-tests passed")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Phase 1 — Obsidian Intent Daemon: watch vault for #task/active → active-intent.json"
    )
    ap.add_argument("--watch", action="store_true", help="Start file-watch daemon (blocks; default mode)")
    ap.add_argument("--once", metavar="FILE", help="Process a single .md file and exit")
    ap.add_argument("--status", action="store_true", help="Show daemon status")
    ap.add_argument("--stop", action="store_true", help="Write stop sentinel to halt running daemon")
    ap.add_argument("--test", action="store_true", help="Run built-in self-tests and exit")
    args = ap.parse_args()

    if args.test:
        _run_test()
    elif args.stop:
        _STOP.write_text("stop\n")
        print("stop sentinel written")
    elif args.status:
        _run_status()
    elif args.once:
        _run_once(args.once)
    else:
        _run_watch()


if __name__ == "__main__":
    main()
