#!/usr/bin/env python3
"""legion_review.py — deterministic review gate + implementation-plan generator (The Sovereign Imperia Citadel Z).

Legion "reviews" feature-improvement proposals with a deterministic gate (RICE ≥ threshold, not a
duplicate of an already-approved title). Approved proposals get a detailed implementation-plan
artifact with an end-to-end validation checklist (commands, not auto-run). Rejected proposals record
a reason. Zero-token; no hosted-model calls.

CLI: --review ID [--threshold T] | --review-all [--threshold T] | --json
"""

import argparse
import json
from pathlib import Path

import feature_improvement_store as store
from _brain_common import STATE

FI_DIR = STATE / "feature-improvements"


def _approved_titles() -> set[str]:
    return {r["title"] for r in store.list_proposals()
            if r.get("status") in ("approved", "implemented")}


def review(fid: str, threshold: float = store.DEFAULT_APPROVE_THRESHOLD) -> dict | None:
    rec = store.get(fid)
    if not rec:
        return None
    if rec.get("status") != "proposed":
        return rec
    if rec["title"] in _approved_titles():
        return store.set_status(fid, "rejected", "duplicate of an already-approved proposal")
    if rec.get("rice_score", 0) < threshold:
        return store.set_status(
            fid, "rejected", f"RICE {rec.get('rice_score')} < threshold {threshold}")
    approved = store.set_status(fid, "approved")
    _generate_plan(approved)
    return approved


def _generate_plan(rec: dict) -> Path:
    how = "\n".join(f"{i}. {s}" for i, s in enumerate(rec.get("how", []), 1)) or "1. TBD"
    body = f"""# Implementation Plan — {rec['title']}

- id: {rec['id']}
- source: {rec['source']}
- target: {rec.get('target', '')}
- RICE: {rec.get('rice')} → score {rec.get('rice_score')}

## Why
{rec.get('why', '')}

## Scope (end to end)
{rec.get('scope_e2e', '')}

## Steps (smallest detail)
{how}

## Expected gain
{rec.get('expected_gain', '')}

## Performance / scale reasoning
{rec.get('perf_scale_reasoning', '')}

## Scale prediction (required — .claude/schemas/scale-prediction.schema.json)
Before implementing: predict {{rows, bytes, qps}} at steady state, pick the
structure/algorithm that fits it, and write the rationale + reconsider-if threshold.
See `.citadel/.claude/rules/code-style.md` § Scale-prediction checklist.

## E2E validation checklist (run before merge — commands, not auto-run)
- [ ] Scale-prediction artifact recorded (schema above) before implementation started
- [ ] `uv run orchestration dev` starts clean (capture startup logs for import/ConfigModel errors)
- [ ] Dummy-data edge-case matrix: empty, single-row, null-heavy, max-partition, malformed
- [ ] Behavior-driven tests (pytest-bdd/bdd) cover the changed behavior
- [ ] Stress + load test on a bounded sample; capture wall-clock + memory
- [ ] Smart %-diff check: compare N% sample output pre/post; assert diff within tolerance
- [ ] `uv add <tool>` any needed test/profiling tooling; record it
- [ ] `ruff check` + `uv run pytest -x` green; `best_practices_lint` + `brand_lint` clean
"""
    plan_path = FI_DIR / f"{rec['id']}-plan.md"
    FI_DIR.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(body, encoding="utf-8")
    return plan_path


def review_all(threshold: float = store.DEFAULT_APPROVE_THRESHOLD) -> dict:
    results = {"approved": [], "rejected": []}
    for rec in store.list_proposals("proposed"):
        out = review(rec["id"], threshold)
        if out and out.get("status") == "approved":
            results["approved"].append(out["id"])
        elif out:
            results["rejected"].append(out["id"])
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="Legion review gate + plan generator.")
    ap.add_argument("--review")
    ap.add_argument("--review-all", action="store_true")
    ap.add_argument("--threshold", type=float, default=store.DEFAULT_APPROVE_THRESHOLD)
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    result = review(args.review, args.threshold) if args.review else review_all(args.threshold)
    print(json.dumps(result, indent=2) if args.as_json else json.dumps(result, default=str))


if __name__ == "__main__":
    main()
