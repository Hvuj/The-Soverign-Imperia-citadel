#!/usr/bin/env python3
"""worker_memory.py — per-worker/per-task memory `.md` cards + the `.md` pointer index.

Closes a real gap: today the only per-spawn context artifact is
`.claude/state/agent-context/<agent-name>.json`, which is keyed by AGENT NAME and
overwritten on every subagent start — two workers of the same agent type clobber
each other's context, and nothing survives after the process exits. This module
gives every legion worker its own per-task `.md` card (frontmatter + body, same
shape as `learn_feature_pattern.py`'s pattern cards) plus an `INDEX.md` pointer
file, in the same "read this first, then follow the pointers" convention as
`docs/ai-context/memory-index.md`.

Layout (see legion_run_state.py):
  .claude/state/legion-runs/<run_id>/workers/<worker_id>/<task_id>.md
  .claude/state/legion-runs/<run_id>/INDEX.md   <- one line per card, pointing to it
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from _brain_common import slug  # noqa: E402
from legion_run_state import append_index_line, index_path, workers_dir  # noqa: E402


def task_id_for(worker_id: str, task: str) -> str:
    digest = hashlib.sha1(f"{worker_id}|{task}".encode()).hexdigest()[:10]
    return f"{slug(worker_id)}-{digest}"


def _already_indexed(run_id: str, task_id: str) -> bool:
    path = index_path(run_id)
    if not path.exists():
        return False
    return f"/{task_id}.md" in path.read_text(encoding="utf-8")


def _bridge_to_brain(task, model, effort, status, what_worked, what_did_not_work) -> None:
    """Best-effort: every legion worker's outcome also folds into the shared brain ledger (System 3), so
    every model that runs learns into the one brain. Never fatal to the worker."""
    try:
        from _learning_bridge import record_outcome

        success = str(status).lower() in ("pass", "passed", "ok", "success", "done", "complete")
        identity = f"{model}#{effort}" if effort else (model or "worker")
        summary = (what_worked if success else what_did_not_work) or ""
        record_outcome(task, identity, success=success,
                       category="worked" if success else "failed", summary=summary[:200])
    except Exception:
        pass


def write_task_card(
    run_id: str,
    *,
    worker_id: str,
    company_id: str,
    model: str,
    effort: str,
    tier: str,
    task: str,
    status: str,
    files_touched: list[str] | None = None,
    validation: str | None = None,
    tokens: int | None = None,
    what_worked: str | None = None,
    what_did_not_work: str | None = None,
    next_action: str | None = None,
) -> Path:
    """Write (or update) one worker's per-task memory card and index it exactly once."""
    tid = task_id_for(worker_id, task)
    worker_dir = workers_dir(run_id) / worker_id
    worker_dir.mkdir(parents=True, exist_ok=True)
    card_path = worker_dir / f"{tid}.md"

    files_block = "\n".join(f"- {f}" for f in (files_touched or [])) or "- (none yet)"
    body = f"""---
worker: {worker_id}
company: {company_id}
model: {model}
effort: {effort}
tier: {tier}
task_id: {tid}
status: {status}
tokens: {tokens if tokens is not None else "unknown"}
updated_at: {time.time()}
---

## Task
{task}

## Files touched
{files_block}

## Validation
{validation or "not run"}

## What worked
{what_worked or "(pending)"}

## What did not work
{what_did_not_work or "(pending)"}

## Next action
{next_action or "(pending)"}
"""
    card_path.write_text(body, encoding="utf-8")

    # Normalize to posix so the index line matches `_already_indexed`'s check on every OS
    # (Windows `str(Path)` uses backslashes, which broke the "index exactly once" guard).
    rel = card_path.relative_to(workers_dir(run_id).parent).as_posix()
    if not _already_indexed(run_id, tid):
        append_index_line(run_id, f"- `{rel}` — {worker_id} / {company_id} ({status})")
    _bridge_to_brain(task, model, effort, status, what_worked, what_did_not_work)
    return card_path


def read_task_card(run_id: str, worker_id: str, task: str) -> str | None:
    tid = task_id_for(worker_id, task)
    card_path = workers_dir(run_id) / worker_id / f"{tid}.md"
    if not card_path.exists():
        return None
    return card_path.read_text(encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Write/read a legion worker's per-task memory card.")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--worker-id", required=True)
    ap.add_argument("--company-id", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--effort", default="")
    ap.add_argument("--tier", default="")
    ap.add_argument("--task", required=True)
    ap.add_argument("--status", default="working")
    ap.add_argument("--read", action="store_true")
    args = ap.parse_args()

    if args.read:
        print(read_task_card(args.run_id, args.worker_id, args.task) or "{}")
        return

    path = write_task_card(
        args.run_id,
        worker_id=args.worker_id,
        company_id=args.company_id,
        model=args.model,
        effort=args.effort,
        tier=args.tier,
        task=args.task,
        status=args.status,
    )
    print(json.dumps({"card": str(path)}, indent=2))


if __name__ == "__main__":
    main()
