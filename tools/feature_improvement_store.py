#!/usr/bin/env python3
"""feature_improvement_store.py — zero-token feature-improvement proposal store (The Sovereign Imperia Citadel Z).

Zombie workers and the pipeline-walker call propose() to file RICE-scored, evidence-backed
improvement proposals. Proposals live as JSON under .claude/state/feature-improvements/ (schema
`.claude/schemas/feature-improvement.schema.json`, id `fi_<12hex>`). On approval a human card is
promoted into docs/ai-context/feature-implementation-patterns.md in house style.

Safety contract: never_call_claude; only writes under .claude/state/feature-improvements/ and
(on approve) appends one card to the patterns file.

CLI: --propose (JSON on stdin) | --list [--status S] | --get ID | --approve ID | --reject ID --reason R
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from _brain_common import ROOT, STATE, slug

FI_DIR = STATE / "feature-improvements"
PATTERNS_MD = ROOT / "docs" / "ai-context" / "feature-implementation-patterns.md"
DEFAULT_APPROVE_THRESHOLD = 5.0


def _rice_score(rice: dict) -> float:
    return round(
        rice.get("reach", 0) * rice.get("impact", 0) * rice.get("confidence", 0)
        / max(0.1, rice.get("effort", 1)),
        3,
    )


def propose(title: str, source: str = "manual", **fields) -> dict:
    ts = int(time.time())
    rice = fields.get("rice") or {"reach": 1, "impact": 1, "confidence": 0.5, "effort": 1}
    nonce = time.time_ns()
    fid = "fi_" + hashlib.sha1(
        f"{title}|{fields.get('target', '')}|{nonce}".encode()).hexdigest()[:12]
    record = {
        "id": fid,
        "title": title,
        "source": source,
        "target": fields.get("target", ""),
        "scope_e2e": fields.get("scope_e2e", ""),
        "why": fields.get("why", ""),
        "how": fields.get("how", []),
        "est_time_hours": float(fields.get("est_time_hours", 0.0)),
        "expected_gain": fields.get("expected_gain", ""),
        "perf_scale_reasoning": fields.get("perf_scale_reasoning", ""),
        "pipeline_perf_recommendation": fields.get("pipeline_perf_recommendation", ""),
        "cost": float(fields.get("cost", 0.0)),
        "rice": rice,
        "rice_score": _rice_score(rice),
        "status": "proposed",
        "review_reason": None,
        "timestamp": ts,
        "evidence": fields.get("evidence", {}),
    }
    record["reasoning_hash"] = hashlib.sha256(
        json.dumps(record, sort_keys=True).encode()).hexdigest()
    FI_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = FI_DIR / f"{stamp}-{fid}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _iter_files() -> list[Path]:
    return sorted(FI_DIR.glob("*.json")) if FI_DIR.exists() else []


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_proposals(status: str | None = None) -> list[dict]:
    recs = [r for r in (_load(p) for p in _iter_files()) if r]
    if status:
        recs = [r for r in recs if r.get("status") == status]
    return sorted(recs, key=lambda r: -r.get("rice_score", 0))


def _find(fid: str) -> tuple[Path, dict] | None:
    for p in _iter_files():
        r = _load(p)
        if r and r.get("id") == fid:
            return p, r
    return None


def get(fid: str) -> dict | None:
    found = _find(fid)
    return found[1] if found else None


def _save(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def set_status(fid: str, status: str, reason: str | None = None) -> dict | None:
    found = _find(fid)
    if not found:
        return None
    path, record = found
    record["status"] = status
    if reason is not None:
        record["review_reason"] = reason
    _save(path, record)
    if status == "approved":
        _promote_card(record)
    return record


def _promote_card(record: dict) -> None:
    if not PATTERNS_MD.exists():
        return
    how = "\n".join(f"{i}. {s}" for i, s in enumerate(record.get("how", []), 1)) or "1. TBD"
    card = (
        f"\n---\n\n## {slug(record['title'])}: {record['title']}\n"
        f"Tags: [feature-improvement, {record['source']}]\n"
        f"Domain: feature-improvement\n"
        f"Task type: improvement\n"
        f"Files:\n- {record.get('target', 'TBD')}\n"
        f"Problem:\n{record.get('why', '')}\n"
        f"Approach:\n{record.get('scope_e2e', '')}\n"
        f"Performance notes:\n{record.get('perf_scale_reasoning', '')}\n"
        f"Reuse next time:\n{how}\n"
        f"Graph links:\n- [[feature-improvements]]\n"
    )
    with PATTERNS_MD.open("a", encoding="utf-8") as fh:
        fh.write(card)


def main() -> None:
    ap = argparse.ArgumentParser(description="Feature-improvement proposal store.")
    ap.add_argument("--propose", action="store_true", help="Read a proposal JSON from stdin")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--status")
    ap.add_argument("--get")
    ap.add_argument("--approve")
    ap.add_argument("--reject")
    ap.add_argument("--reason", default="")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    if args.propose:
        data = json.loads(sys.stdin.read() or "{}")
        title = data.pop("title", "untitled")
        source = data.pop("source", "manual")
        result = propose(title, source, **data)
    elif args.get:
        result = get(args.get)
    elif args.approve:
        result = set_status(args.approve, "approved")
    elif args.reject:
        result = set_status(args.reject, "rejected", args.reason)
    else:
        result = list_proposals(args.status)

    print(json.dumps(result, indent=2) if args.as_json else json.dumps(result, default=str))


if __name__ == "__main__":
    main()
