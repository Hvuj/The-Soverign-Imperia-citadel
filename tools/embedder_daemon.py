#!/usr/bin/env python3
"""embedder_daemon.py — the learning Z-worker (Phase Z1): embed changed files into the vector store.

Mirrors incremental_brain_daemon.py's fingerprint→changed→sync watch loop, but the sync step embeds
changed files (zero cloud tokens, local GPU) via the retrieval EmbedderWorker and writes a live stats
file that `citadel workers` reads. Skips files whose index is still fresh (Z0 JIT contract) and no-ops
when the embedding engine is offline, so it is cheap on a quiet tree.
"""

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
_SRC = _TOOLS.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from citadel._process import pid_is_alive as process_is_alive  # noqa: E402
from citadel.services.retrieval.worker import EmbedderWorker  # noqa: E402

_WS = Path(os.environ.get("CITADEL_WORKSPACE", ".")).resolve()
_STATE = _WS / ".claude" / "state"
_PID = _STATE / "embedder-daemon.pid"
_STOP = _STATE / "embedder-daemon.stop"
_SNAP = _STATE / "embedder-snapshot.json"
_LOG = _STATE / "embedder-daemon.log"

_WATCH_ROOTS = ["src", "tools", "docs", "scripts"]
_IGNORE_PARTS = {".git", ".venv", "__pycache__", "node_modules", ".claude", "state", ".mypy_cache", ".pytest_cache"}
_POLL_SECONDS = 6.0


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _log(msg: str) -> None:
    _STATE.mkdir(parents=True, exist_ok=True)
    with _LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {msg}\n")
    print(f"{_now()} {msg}", flush=True)


def _ignored(path: Path) -> bool:
    return bool(set(path.parts) & _IGNORE_PARTS)


def _fingerprint() -> dict:
    out: dict[str, list[int]] = {}
    roots = [_WS / r for r in _WATCH_ROOTS] or [_WS]
    for base in roots:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not _ignored(p):
                try:
                    st = p.stat()
                    out[str(p.relative_to(_WS)).replace("\\", "/")] = [st.st_mtime_ns, st.st_size]
                except OSError:
                    pass
    return out


def _load_snapshot() -> dict:
    try:
        return json.loads(_SNAP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_snapshot(snap: dict) -> None:
    _STATE.mkdir(parents=True, exist_ok=True)
    _SNAP.write_text(json.dumps(snap), encoding="utf-8")


def _diff(old: dict, new: dict) -> tuple[list[str], list[str]]:
    changed = [k for k in new if old.get(k) != new[k]]
    deleted = [k for k in old if k not in new]
    return changed, deleted


def _worker() -> EmbedderWorker:
    return EmbedderWorker.for_workspace(_WS)


def once() -> None:
    worker = _worker()
    old = _load_snapshot()
    new = _fingerprint()
    changed, deleted = _diff(old, new)
    n = worker.sync([_WS / c for c in changed], deleted)
    _save_snapshot(new)
    _log(f"once changed={len(changed)} deleted={len(deleted)} indexed={n}")


def watch() -> None:
    _STATE.mkdir(parents=True, exist_ok=True)
    _PID.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    _STOP.unlink(missing_ok=True)
    worker = _worker()
    snap = _fingerprint()
    _save_snapshot(snap)
    worker.sweep(_WATCH_ROOTS)
    _log(f"embedder daemon started pid={os.getpid()} model={worker.embed_model} backend={worker.store.backend_name}")
    try:
        while not _STOP.exists():
            time.sleep(_POLL_SECONDS)
            new = _fingerprint()
            changed, deleted = _diff(snap, new)
            if changed or deleted:
                snap = new
                _save_snapshot(snap)
                worker.sync([_WS / c for c in changed], deleted)
    finally:
        _log("embedder daemon stopped")
        _PID.unlink(missing_ok=True)
        _STOP.unlink(missing_ok=True)


def status() -> None:
    print("# Embedder Z-Worker")
    if _PID.exists():
        pid = _PID.read_text().strip()
        try:
            alive = process_is_alive(int(pid))
        except ValueError:
            alive = False
        print(f"pid: {pid}")
        print(f"running: {'yes' if alive else 'no'}")
    else:
        print("running: no")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="embedder_daemon")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--stop", action="store_true")
    args = ap.parse_args(argv)
    _STATE.mkdir(parents=True, exist_ok=True)
    if args.stop:
        _STOP.write_text("stop\n", encoding="utf-8")
    elif args.status:
        status()
    elif args.watch:
        watch()
    else:
        once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
