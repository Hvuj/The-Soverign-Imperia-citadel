#!/usr/bin/env python3
"""token_ledger.py — live per-worker token/cost accounting for `citadel run`.

Reuses the pricing table in `claude_pricing.py` (same `compute_cost`/
`total_tokens` `claude_usage_cost_report.py` uses) instead of re-deriving it,
so the live per-run numbers and the offline usage-report PDF never drift
apart. Deliberately imports from that small, side-effect-free module and NOT
from `claude_usage_cost_report.py` itself — that script runs ~600 lines of
module-level code (scans `~/.claude/projects/**`, writes a PDF) with no
`if __name__ == "__main__":` guard, so importing anything from it directly
would trigger a full report generation as a side effect of import. Feeds
`worker_status.py`'s TUI (per-worker token/cost column) and
`efficiency_gate.check_token_budget` (the enforced budget backstop).

A worker spawned with `--output-format json` (see legion_orchestrator.py)
prints exactly one JSON object on exit containing a `usage` block — this
module parses that object and appends one `worker-usage` ledger record.
"""

import argparse
import json
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from claude_pricing import compute_cost, total_tokens  # noqa: E402
from legion_run_state import append_ledger, read_ledger  # noqa: E402


def parse_worker_output(raw: str) -> dict:
    """Parse a `claude --print --output-format json` worker's stdout into a usage record.

    Returns {} if the output is not a single JSON object (e.g. the worker crashed
    before printing a result) — callers treat that as zero usage, not an error.
    """
    raw = raw.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    usage = data.get("usage") or {}
    model = data.get("model") or ""
    cli_cost = data.get("total_cost_usd")
    cost = round(float(cli_cost), 6) if isinstance(cli_cost, int | float) else round(compute_cost(usage, model), 6)
    return {
        "model": model,
        "total_tokens": total_tokens(usage),
        "cost_usd": cost,
        "is_error": bool(data.get("is_error")),
        "num_turns": data.get("num_turns"),
    }


def parse_worker_result(raw: str) -> str | None:
    """Return the top-level `result` (final assistant text) from a worker's JSON output.

    `parse_worker_output` deliberately drops `result` (it only needs usage/cost, and other
    callers depend on its shape). Specialized worker modes (bi-learn/benchmark) instruct the
    worker to make its final message a JSON artifact; this captures that raw text so the
    orchestrator can persist it. Returns None if the output isn't a single JSON object.
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    result = data.get("result")
    return result if isinstance(result, str) else None


def record_worker_usage(run_id: str, worker_id: str, usage_record: dict) -> None:
    if not usage_record:
        return
    append_ledger(run_id, {"event": "worker-usage", "worker": worker_id, **usage_record})


def run_totals(run_id: str) -> dict:
    """Aggregate every `worker-usage` record for *run_id* into per-worker + run totals."""
    total_tok = 0
    total_cost = 0.0
    per_worker: dict[str, dict] = {}
    for rec in read_ledger(run_id):
        if rec.get("event") != "worker-usage":
            continue
        worker_id = rec.get("worker", "unknown")
        tok = rec.get("total_tokens", 0) or 0
        cost = rec.get("cost_usd", 0.0) or 0.0
        total_tok += tok
        total_cost += cost
        bucket = per_worker.setdefault(worker_id, {"total_tokens": 0, "cost_usd": 0.0})
        bucket["total_tokens"] += tok
        bucket["cost_usd"] = round(bucket["cost_usd"] + cost, 6)
    return {"total_tokens": total_tok, "cost_usd": round(total_cost, 6), "per_worker": per_worker}


def main() -> None:
    ap = argparse.ArgumentParser(description="Live per-worker token/cost accounting for a run.")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    totals = run_totals(args.run_id)
    if args.as_json:
        print(json.dumps(totals, indent=2))
        return
    print(f"run {args.run_id}: {totals['total_tokens']} tokens, ${totals['cost_usd']:.4f}")
    for worker_id, bucket in sorted(totals["per_worker"].items()):
        print(f"  {worker_id}: {bucket['total_tokens']} tokens, ${bucket['cost_usd']:.4f}")


if __name__ == "__main__":
    main()
