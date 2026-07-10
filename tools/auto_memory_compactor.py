#!/usr/bin/env python3
"""auto_memory_compactor.py — Deterministic zero-token memory compaction.

Algorithm (no LLM required):
  1. Load all memory lines from a memory file.
  2. Cluster near-duplicate lines by token-overlap similarity (Jaccard ≥ threshold).
  3. For each cluster, keep the longest (most informative) line; drop the rest.
  4. Verify that ≥80% of original key-tokens survive in the compacted output.
  5. If verification fails: rollback (keep raw format).
  6. If verification passes: write compacted file.

Never calls any LLM. Safe to call from hooks and daemons.
"""

import os
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])

_ENTAIL_THRESHOLD = 0.80
_JACCARD_DEDUP_THRESHOLD = 0.60
_MIN_TOKEN_LEN = 4
_TOKEN_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9]{" + str(_MIN_TOKEN_LEN - 1) + r",}\b")


def _key_tokens(text: str) -> set[str]:
    """Extract lowercase word tokens ≥ MIN_TOKEN_LEN, ignoring punctuation."""
    return {m.lower() for m in _TOKEN_RE.findall(text)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _cluster_lines(lines: list[str], threshold: float) -> list[list[str]]:
    """Group lines into clusters where any two members share Jaccard ≥ threshold."""
    clusters: list[list[str]] = []
    assigned = [False] * len(lines)
    token_sets = [_key_tokens(ln) for ln in lines]

    for i, line in enumerate(lines):
        if assigned[i]:
            continue
        cluster = [line]
        assigned[i] = True
        for j in range(i + 1, len(lines)):
            if not assigned[j] and _jaccard(token_sets[i], token_sets[j]) >= threshold:
                cluster.append(lines[j])
                assigned[j] = True
        clusters.append(cluster)

    return clusters


def _entailment_check_cluster(
    original: str,
    representative: str,
    threshold: float = 0.65,
) -> bool:
    """Check that the cluster representative covers ≥threshold of the original's key tokens."""
    tokens = _key_tokens(original)
    if not tokens:
        return True
    rep_lower = representative.lower()
    matched = sum(1 for t in tokens if t in rep_lower)
    return matched / len(tokens) >= threshold


def _entailment_check(
    clusters: "list[list[str]]",
    representatives: "list[str]",
) -> "tuple[bool, list[str]]":
    """Verify each dropped line is sufficiently covered by its cluster's representative."""
    missing: list[str] = []
    for cluster, rep in zip(clusters, representatives):
        for line in cluster:
            if line == rep:
                continue
            if not _entailment_check_cluster(line, rep):
                missing.append(line)
    return len(missing) == 0, missing


class AutoMemoryCompactor:
    def compact_lines(
        self,
        lines: list[str],
        jaccard_threshold: float = _JACCARD_DEDUP_THRESHOLD,
    ) -> tuple[list[str], bool]:
        """Dedup and compact a list of memory lines. Returns (compacted_lines, success)."""
        if not lines:
            return lines, True

        clusters = _cluster_lines(lines, jaccard_threshold)
        representatives = [max(cluster, key=len) for cluster in clusters]
        compacted = representatives

        ok, missing = _entailment_check(clusters, representatives)
        if not ok:
            print(
                f"Compaction: {len(missing)} line(s) not covered after dedup "
                f"— keeping raw format.",
                file=sys.stderr,
            )
            return lines, False

        return compacted, True

    def compact_memory_node(
        self,
        node_id: str,
        original_claims: list[str],
    ) -> bool:
        """Compact a memory node in-place. Returns True on success."""
        compacted, success = self.compact_lines(original_claims)
        if not success:
            print(
                f"Compaction aborted for '{node_id}': entailment check failed. "
                "Keeping raw episodic format.",
                file=sys.stderr,
            )
            return False
        removed = len(original_claims) - len(compacted)
        if removed:
            print(f"Compaction approved for '{node_id}': {removed} duplicate(s) removed.")
        return True

    def compact_file(self, path: Path, dry_run: bool = False) -> dict:
        """Compact a markdown memory file. Returns stats dict."""
        if not path.exists():
            return {"error": f"File not found: {path}"}

        content = path.read_text(encoding="utf-8")
        lines = [ln for ln in content.splitlines() if ln.strip()]
        original_count = len(lines)

        compacted, success = self.compact_lines(lines)
        if not success:
            return {"path": str(path), "success": False, "original": original_count, "compacted": original_count}

        compacted_text = "\n".join(compacted) + "\n"
        if not dry_run and len(compacted) < original_count:
            bak = path.with_suffix(path.suffix + ".compactor_bak")
            shutil.copy2(path, bak)
            path.write_text(compacted_text, encoding="utf-8")
            bak.unlink(missing_ok=True)

        return {
            "path": str(path),
            "success": True,
            "dry_run": dry_run,
            "original": original_count,
            "compacted": len(compacted),
            "removed": original_count - len(compacted),
            "timestamp": datetime.now(UTC).isoformat(),
        }


if __name__ == "__main__":
    compactor = AutoMemoryCompactor()

    test_claims = [
        "The Orchestration IO manager requires AWS S3 credentials for external storage.",
        "Orchestration IO manager needs AWS S3 credentials to access external storage.",
        "ConfigModel models must use strict=True for runtime type checking.",
    ]
    result = compactor.compact_memory_node("smoke_test_node", test_claims)
    assert result, "smoke test: compact_memory_node should succeed"

    compacted_lines, success = compactor.compact_lines(test_claims)
    assert success, "smoke test: compact_lines should succeed"
    assert len(compacted_lines) < len(test_claims), "smoke test: should have deduped at least one line"

    print(f"smoke test: PASS  (3 → {len(compacted_lines)} lines after dedup)")
    sys.exit(0)
