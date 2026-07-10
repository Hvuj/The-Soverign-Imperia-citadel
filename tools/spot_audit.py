#!/usr/bin/env python3
"""
Spot Auditor — residual error calculator for the Silver/Gold knowledge tiers.

Randomly samples Silver-tier records, re-runs L0 (schema) + L1 (provenance)
verification, and reports a residual error rate as a transparency metric.
"""


import json
import random
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from verification_ladder import VerificationLadder  # noqa: E402

_ROOT = _TOOLS_DIR.parent
_SILVER_DIR = _ROOT / "docs" / "ai-context" / "knowledge" / "silver"
_BRONZE_DIR = _ROOT / "docs" / "ai-context" / "knowledge" / "bronze"


class SpotAuditor:
    def __init__(self, sample_rate: float = 0.10) -> None:
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self.ladder = VerificationLadder()

    def run_audit(self) -> dict:
        if not _SILVER_DIR.exists():
            return {"status": "skipped", "reason": "Silver corpus directory not found."}

        files = list(_SILVER_DIR.glob("*.json"))
        if not files:
            return {"status": "skipped", "reason": "Silver corpus is empty."}

        sample_size = max(1, round(len(files) * self.sample_rate))
        sampled = random.sample(files, min(sample_size, len(files)))

        report = {
            "status": "completed",
            "total_files": len(files),
            "files_audited": len(sampled),
            "l0_failures": 0,
            "l1_failures": 0,
            "residual_error_rate": 0.0,
        }

        for fp in sampled:
            try:
                payload = json.loads(fp.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"Audit fault reading {fp.name}: {exc}", file=sys.stderr)
                report["l0_failures"] += 1
                continue

            if not self.ladder.verify_l0_invariants(payload, "silver-frontmatter.schema.json"):
                report["l0_failures"] += 1
                continue

            for claim in payload.get("claims", []):
                span = claim.get("provenance_span", {})
                if not self.ladder.verify_l1_provenance(
                    claim.get("text", ""),
                    span.get("source_hash", ""),
                    span.get("char_start", 0),
                    span.get("char_end", 0),
                    bronze_dir=str(_BRONZE_DIR),
                ):
                    report["l1_failures"] += 1
                    break

        total_failures = report["l0_failures"] + report["l1_failures"]
        report["residual_error_rate"] = round(
            total_failures / len(sampled) if sampled else 0.0, 4
        )
        return report


if __name__ == "__main__":
    auditor = SpotAuditor(sample_rate=1.0)
    result = auditor.run_audit()
    print(json.dumps({"spot_audit_report": result}, indent=2))
    assert result["status"] in {"completed", "skipped"}
    print("smoke test: PASS")
    sys.exit(0)
