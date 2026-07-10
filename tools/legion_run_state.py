#!/usr/bin/env python3
"""legion_run_state.py — run-scoped state root for `citadel run`.

Every `citadel run` invocation gets one run_id and one directory tree:

  .claude/state/legion-runs/<run_id>/
    ledger.ndjson         one line per worker lifecycle / gate event
    workers/<worker_id>/  per-worker/per-task memory cards (see worker_memory.py)
    gates/                governance gate artifacts captured for this run
    INDEX.md              pointer file to every worker/task memory card

`.claude/state/legion-runs/current-run.json` always points at the most recently
started run, so read-only tools (worker_status.py, the statusline) can find live
state without the caller passing --run-id explicitly.
"""

import json
import os
import time
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
STATE = ROOT / ".claude" / "state"
RUNS_DIR = STATE / "legion-runs"
CURRENT_RUN_POINTER = RUNS_DIR / "current-run.json"

_TAIL_BYTES = 512_000


def new_run_id() -> str:
    return f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def ledger_path(run_id: str) -> Path:
    return run_dir(run_id) / "ledger.ndjson"


def workers_dir(run_id: str) -> Path:
    return run_dir(run_id) / "workers"


def gates_dir(run_id: str) -> Path:
    return run_dir(run_id) / "gates"


def artifacts_dir(run_id: str) -> Path:
    return run_dir(run_id) / "artifacts"


def index_path(run_id: str) -> Path:
    return run_dir(run_id) / "INDEX.md"


def worker_log_path(run_id: str, worker_id: str, stream: str) -> Path:
    d = run_dir(run_id) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{worker_id}.{stream}.log"


def init_run(run_id: str, task: str, *, max_workers: int) -> Path:
    d = run_dir(run_id)
    workers_dir(run_id).mkdir(parents=True, exist_ok=True)
    gates_dir(run_id).mkdir(parents=True, exist_ok=True)
    index_path(run_id).write_text(
        f"# Legion run {run_id}\n\n"
        f"Task: {task}\n"
        f"Max workers: {max_workers}\n\n"
        "## Worker / task memory\n",
        encoding="utf-8",
    )
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        CURRENT_RUN_POINTER,
        json.dumps({"run_id": run_id, "task": task, "started_at": time.time()}, indent=2),
    )
    return d


def current_run_id() -> str | None:
    if not CURRENT_RUN_POINTER.exists():
        return None
    try:
        return json.loads(CURRENT_RUN_POINTER.read_text(encoding="utf-8")).get("run_id")
    except (OSError, json.JSONDecodeError):
        return None


def append_ledger(run_id: str, record: dict) -> None:
    record = {"ts": time.time(), **record}
    path = ledger_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def read_ledger(run_id: str, tail_bytes: int = _TAIL_BYTES) -> list[dict]:
    """Bounded tail-read of a run's ledger, mirroring worker_status.py's O(1) pattern."""
    path = ledger_path(run_id)
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()
            chunk = fh.read()
    except OSError:
        return []
    records = []
    for line in chunk.decode("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def append_index_line(run_id: str, line: str) -> None:
    path = index_path(run_id)
    if not path.exists():
        init_run(run_id, task="(recovered)", max_workers=0)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip("\n") + "\n")
