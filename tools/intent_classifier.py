#!/usr/bin/env python3
"""
Intent Classifier — Phase 16: The Intent-Driven Dual-Track Matrix.

Classifies an incoming user prompt into one of two execution tracks:
  INTERROGATION — read-only fast path (questions, audits, lookups, explanations)
  ACTION        — full mutation loop (build, fix, refactor, implement, ...)

Classification uses heuristic regular expressions anchored to the leading
token(s) of the prompt.  Word-boundary anchoring prevents substring leaks
(e.g. "combine" falsely matching "build" inside it) — lesson from the
brain_search alias-scan fix (see docs/ai-context/what-worked.md).

When intent is ambiguous the fallback is always INTERROGATION to protect the
repository from accidental file mutations.

Output: string literal "INTERROGATION" or "ACTION"
"""


import argparse
import json
import re
import sys


DENSE_RESPONSE_DIRECTIVE: str = (
    "ANSWER TELEGRAPHIC. NO PREAMBLE. DENSE FACTS ONLY. "
    "CITE FILE:LINE FOR ALL CODE CLAIMS. "
    "DO NOT REPEAT QUESTION. STOP WHEN DONE."
)


class IntentClassifier:
    """Heuristic intent router for the Phase 16 Dual-Track Matrix.

    Classifies a prompt string as INTERROGATION (read-only fast path) or
    ACTION (full mutation pipeline).  Patterns are anchored to the leading
    token to prevent substring leaks.
    """

    def __init__(self) -> None:
        interrogation_kw = r"how|why|what|where|explain|audit|find|list|check|analyze"
        self.interrogation_patterns: list[re.Pattern[str]] = [
            re.compile(rf"^\s*(?:{interrogation_kw})\b", re.IGNORECASE),
        ]

        action_kw = r"build|create|fix|refactor|add|delete|run|modify|implement"
        self.action_patterns: list[re.Pattern[str]] = [
            re.compile(rf"^\s*(?:{action_kw})\b", re.IGNORECASE),
        ]

    def classify(self, user_input: str) -> str:
        """Classify user_input as INTERROGATION or ACTION.

        Args:
            user_input: Raw prompt string from the caller.

        Returns:
            "INTERROGATION" for read-only / lookup intent, or when ambiguous.
            "ACTION" for mutation / implementation intent.
        """
        text = (user_input or "").strip()

        if "?" in text:
            return "INTERROGATION"

        for pat in self.interrogation_patterns:
            if pat.match(text):
                return "INTERROGATION"

        for pat in self.action_patterns:
            if pat.match(text):
                return "ACTION"

        return "INTERROGATION"


if __name__ == "__main__":
    _parser = argparse.ArgumentParser(
        description="SOVEREIGN-IMPERIA-CITADEL Intent Classifier — Phase 16: The Intent-Driven Dual-Track Matrix"
    )
    _parser.add_argument(
        "--classify",
        metavar="PROMPT",
        help="Classify a single prompt string and print the resulting track.",
    )
    _parser.add_argument(
        "--test",
        action="store_true",
        default=False,
        help="Run isolated self-test assertions and exit 0 on pass.",
    )
    _args = _parser.parse_args()

    if _args.test:
        _classifier = IntentClassifier()

        _cases: list[tuple[str, str]] = [
            ("Explain how the L6 compiler works", "INTERROGATION"),
            ("Fix the bug in model_backend.py", "ACTION"),
            ("What is the corporate spine?", "INTERROGATION"),
            ("refactor the dispatcher", "ACTION"),
            ("something vague with no keyword", "INTERROGATION"),
            ("how does epistemic_db handle FTS5?", "INTERROGATION"),
            ("build the new skill synthesizer", "ACTION"),
            ("where is the capsule written?", "INTERROGATION"),
            ("implement the dual-track matrix", "ACTION"),
            ("audit the corporate spine schemas", "INTERROGATION"),
            ("delete stale obsidian notes", "ACTION"),
            ("check vault task count", "INTERROGATION"),
            ("add the Phase 16 branch", "ACTION"),
            ("list all active tasks", "INTERROGATION"),
            ("modify the schema validator", "ACTION"),
        ]

        _failures: list[str] = []
        for _prompt, _expected in _cases:
            _got = _classifier.classify(_prompt)
            if _got != _expected:
                _failures.append(f"  FAIL: {_prompt!r} → {_got!r}  (expected {_expected!r})")

        if _failures:
            print("IntentClassifier --test FAILED:")
            for _f in _failures:
                print(_f)
            sys.exit(1)

        _report = {
            "test": "IntentClassifier --test",
            "cases_run": len(_cases),
            "result": "PASS",
            "DENSE_RESPONSE_DIRECTIVE_len": len(DENSE_RESPONSE_DIRECTIVE),
        }
        print(json.dumps(_report, indent=2))
        print("IntentClassifier --test passed.")
        sys.exit(0)

    if _args.classify:
        _result = IntentClassifier().classify(_args.classify)
        print(_result)
        sys.exit(0)

    _parser.print_help()
    sys.exit(1)
