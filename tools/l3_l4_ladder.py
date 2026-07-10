#!/usr/bin/env python3
"""
High-Stakes Verification Ladder — L3 and L4 gates.

L3: Consensus quorum — requires ceil(2k/3) positive votes from k independent
    agent extractions before merging a core architectural claim.

L4: Canary regression — runs golden Q&A pairs through the unified query engine
    and vetoes if any known answer drops below its min_match_score threshold.
"""


import json
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
CANARY_REGISTRY = _ROOT / ".claude" / "state" / "canary-registry.json"


class HighStakesVerificationLadder:
    def evaluate_l3_quorum(self, agent_votes: list[bool]) -> tuple[bool, str]:
        """L3: strict ⌈2k/3⌉ quorum over k independent agent votes."""
        k = len(agent_votes)
        if k == 0:
            return False, "0/0"

        required = math.ceil((2 * k) / 3)
        positive = sum(1 for v in agent_votes if v is True)
        quorum_str = f"{positive}/{k}"

        if positive >= required:
            return True, quorum_str

        print(
            f"L3 Failure: quorum not reached. Got {quorum_str}, needed {required}/{k}.",
            file=sys.stderr,
        )
        return False, quorum_str

    def run_l4_canary_suite(
        self,
        search_callback: Callable[[str, int], list[dict[str, Any]]],
    ) -> bool:
        """L4: run all registered canary Q&A pairs through the query engine."""
        if not CANARY_REGISTRY.exists():
            return True

        try:
            registry = json.loads(CANARY_REGISTRY.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"L4 Fault: cannot read canary registry: {exc}", file=sys.stderr)
            return False

        canaries = registry.get("canaries", [])
        if not canaries:
            return True

        passed_all = True
        for canary in canaries:
            canary_id = canary.get("canary_id", "unknown")
            question = canary.get("question", "")
            expected_keys: list[str] = canary.get("expected_answer_keys", [])
            min_score: float = canary.get("min_match_score", 0.0)

            results = search_callback(question, 5)

            found = 0
            for res in results:
                hl = res.get("highlight", "").lower()
                for key in expected_keys:
                    if key.lower() in hl:
                        found += 1

            match_ratio = found / len(expected_keys) if expected_keys else 1.0

            if match_ratio < min_score:
                print(
                    f"L4 Failure: canary '{canary_id}' regressed. "
                    f"match_ratio={match_ratio:.3f} < min={min_score}",
                    file=sys.stderr,
                )
                passed_all = False

        return passed_all


if __name__ == "__main__":
    ladder = HighStakesVerificationLadder()

    cases = [
        ([True, True, False],        True,  "2/3"),
        ([True, False, False],       False, "1/3"),
        ([True, True, True, False],  True,  "3/4"),
        ([False, False, False],      False, "0/3"),
        ([],                          False, "0/0"),
    ]
    for votes, expect_pass, expect_q in cases:
        got_pass, got_q = ladder.evaluate_l3_quorum(votes)
        assert got_pass == expect_pass, f"votes={votes}: expected pass={expect_pass}, got {got_pass}"
        assert got_q == expect_q, f"votes={votes}: expected quorum={expect_q!r}, got {got_q!r}"
        print(f"  votes={votes!s:<30} → pass={got_pass}, quorum={got_q}")

    assert ladder.run_l4_canary_suite(lambda q, n: []), "L4 bootstrap should pass"

    print("L3/L4 smoke test: PASS")
    sys.exit(0)
