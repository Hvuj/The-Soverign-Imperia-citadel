#!/usr/bin/env python3
"""
Silver Structurer — Bronze → Silver pipeline with L0/L1 gate enforcement.

Flow:
  1. Receive raw Bronze text + metadata.
  2. Build atomic-claim payloads (T1 local model in production; deterministic
     stub in Phase 2 until model_backend wires llama-cpp-python).
  3. Force payload through VerificationLadder L0 (schema) + L1 (provenance).
  4. On pass: write to docs/ai-context/knowledge/silver/<hash>.json
  5. On any gate failure: route to quarantine, never promote to Gold.
"""


import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_ladder import VerificationLadder  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
BRONZE_DIR = _REPO_ROOT / "docs" / "ai-context" / "knowledge" / "bronze"
SILVER_DIR = _REPO_ROOT / "docs" / "ai-context" / "knowledge" / "silver"
QUARANTINE_DIR = _REPO_ROOT / "docs" / "ai-context" / "knowledge" / "quarantine"

_SUMMARY_MIN = 20
_SUMMARY_MAX = 600


def _claim_id(text: str) -> str:
    digest = hashlib.sha256(text.lower().strip().encode("utf-8")).hexdigest()
    return f"clm_{digest[:8]}"


def _build_summary(source_hash: str, raw_content: str) -> str:
    snippet = raw_content[:80].strip().replace("\n", " ")
    base = f"Bronze source {source_hash[:8]}: {snippet}" if snippet else f"Bronze source {source_hash[:8]} structural baseline."
    if len(base) < _SUMMARY_MIN:
        base = base.ljust(_SUMMARY_MIN, ".")
    return base[:_SUMMARY_MAX]


class SilverStructurer:
    def __init__(self) -> None:
        self.ladder = VerificationLadder()

    def structure_bronze_record(
        self,
        source_hash: str,
        raw_content: str,
        domains: list[str],
        tags: list[str],
    ) -> tuple[str, bool]:
        """
        Ingest a Bronze record and produce a schema-valid Silver entry.

        Returns (output_path, success).  success=False means the record landed
        in quarantine — inspect the file for the failing gate detail.
        """
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        snippet = raw_content[:100].strip()
        claim_text = snippet if len(snippet) >= 5 else "Structural baseline knowledge entry."

        claim = {
            "claim_id": _claim_id(claim_text),
            "text": claim_text,
            "provenance_span": {
                "source_hash": source_hash,
                "char_start": 0,
                "char_end": len(raw_content[:100].strip()),
            },
            "confidence": "high",
        }

        silver_payload = {
            "tags": tags,
            "content_type": "note",
            "domains": domains,
            "source_hash": source_hash,
            "date_ingested": now_iso,
            "summary": _build_summary(source_hash, raw_content),
            "claims": [claim],
        }

        l0_pass = self.ladder.verify_l0_invariants(silver_payload, "silver-frontmatter.schema.json")
        l1_pass = self.ladder.verify_l1_provenance(
            claim["text"],
            source_hash,
            claim["provenance_span"]["char_start"],
            claim["provenance_span"]["char_end"],
            bronze_dir=str(BRONZE_DIR),
        )

        if l0_pass and l1_pass:
            SILVER_DIR.mkdir(parents=True, exist_ok=True)
            out = SILVER_DIR / f"{source_hash}.json"
            out.write_text(json.dumps(silver_payload, indent=2), encoding="utf-8")
            return str(out), True
        else:
            QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
            out = QUARANTINE_DIR / f"{source_hash}_failed.json"
            out.write_text(json.dumps(silver_payload, indent=2), encoding="utf-8")
            return str(out), False


if __name__ == "__main__":
    BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    dummy_hash = hashlib.sha256(b"").hexdigest()
    bronze_text = "Baseline structural knowledge text segment for verification testing."
    (BRONZE_DIR / f"{dummy_hash}.txt").write_text(bronze_text, encoding="utf-8")

    structurer = SilverStructurer()
    path, success = structurer.structure_bronze_record(
        dummy_hash, bronze_text, ["self_test"], ["v2_core"]
    )
    print(f"path    : {path}")
    print(f"success : {success}")

    if success:
        record = json.loads(Path(path).read_text())
        assert record["source_hash"] == dummy_hash
        assert len(record["claims"]) >= 1
        assert record["claims"][0]["claim_id"].startswith("clm_")
        print("smoke test: PASS")
        sys.exit(0)
    else:
        print("smoke test: FAIL (record quarantined — check L0/L1 output above)")
        sys.exit(1)
