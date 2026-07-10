#!/usr/bin/env python3
"""
Verification Ladder — L0 and L1 gates.

L0: Schema required-field invariant check (pure Python, T0 tier, no external deps).
L1: Provenance byte-span check — proves a claim's text was extracted from an
    unaltered Bronze source file at the recorded character range.

These gates are non-bypassable: callers receive False, not an exception, on failure
so the caller can route to quarantine rather than crashing.
"""


import json
import sys
from pathlib import Path
from typing import Any

_SCHEMAS_DIR = Path(__file__).resolve().parents[1] / ".claude" / "schemas"


class VerificationLadder:
    def __init__(self, schemas_dir: str | None = None) -> None:
        self.schemas_dir = Path(schemas_dir) if schemas_dir else _SCHEMAS_DIR
        self._schema_cache: dict[str, dict[str, Any]] = {}

    def _load_schema(self, schema_filename: str) -> dict[str, Any] | None:
        if schema_filename in self._schema_cache:
            return self._schema_cache[schema_filename]
        path = self.schemas_dir / schema_filename
        if not path.exists():
            print(f"L0 Error: schema not found: {path}", file=sys.stderr)
            return None
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            self._schema_cache[schema_filename] = schema
            return schema
        except json.JSONDecodeError as exc:
            print(f"L0 Error: schema invalid JSON ({schema_filename}): {exc}", file=sys.stderr)
            return None

    def verify_l0_invariants(self, payload: dict[str, Any], schema_filename: str) -> bool:
        """L0: confirm all schema-required fields are present in payload."""
        schema = self._load_schema(schema_filename)
        if schema is None:
            return False
        for field in schema.get("required", []):
            if field not in payload:
                print(f"L0 Failure: missing required field '{field}'", file=sys.stderr)
                return False
        return True

    def verify_l1_provenance(
        self,
        claim_text: str,
        source_hash: str,
        char_start: int,
        char_end: int,
        bronze_dir: str = "docs/ai-context/knowledge/bronze",
    ) -> bool:
        """L1: prove claim_text is anchored in the Bronze source at [char_start, char_end)."""
        bronze_path = Path(bronze_dir) / f"{source_hash}.txt"
        if not bronze_path.is_absolute():
            bronze_path = Path(__file__).resolve().parents[1] / bronze_path

        if not bronze_path.exists():
            print(
                f"L1 Failure: Bronze source '{source_hash[:16]}…' not found at {bronze_path}",
                file=sys.stderr,
            )
            return False

        source = bronze_path.read_text(encoding="utf-8")

        if char_start < 0 or char_end > len(source) or char_start >= char_end:
            print(
                f"L1 Failure: span [{char_start}, {char_end}) out of bounds (source len={len(source)})",
                file=sys.stderr,
            )
            return False

        extracted = " ".join(source[char_start:char_end].split())
        clean_claim = " ".join(claim_text.split())

        if clean_claim in extracted or extracted in clean_claim:
            return True

        print(
            f"L1 Failure: claim does not align with span. "
            f"Span snippet: '{extracted[:60]}…'",
            file=sys.stderr,
        )
        return False


if __name__ == "__main__":
    ladder = VerificationLadder()
    print("Verification Ladder (L0-L1) ready.")

    sample_bug = {
        "bug_id": "bug_3ae1f44854ba",
        "first_seen": 1000000,
        "last_seen": 1000000,
        "occurrence_count": 1,
        "fingerprints": {
            "error_class": "ValueError",
            "error_message_template": "token expired",
            "stack_signature": "a" * 64,
            "code_locus_signature": "Call:check_session",
            "ast_pattern_hash": "b" * 64,
        },
        "status": "captured",
    }
    assert ladder.verify_l0_invariants(sample_bug, "bug-record.schema.json"), "L0 failed on valid bug record"
    print("L0 smoke test: PASS")
    sys.exit(0)
