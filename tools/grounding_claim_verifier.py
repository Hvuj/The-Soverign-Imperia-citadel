#!/usr/bin/env python3
"""grounding_claim_verifier.py — Verify factual claims against evidence sources.

Local-only, no AI calls, no external APIs.
Uses keyword/token matching to classify claims as supported/unsupported.

Output matches .claude/schemas/claim-verification.schema.json.

Usage:
  python tools/grounding_claim_verifier.py --claims '["claim1", "claim2"]' --evidence /path/to/evidence/
  python tools/grounding_claim_verifier.py --claims claims.json --evidence file.md [--strict]
  echo '["claim1"]' | python tools/grounding_claim_verifier.py --stdin-claims --evidence file.md
"""

import argparse
import json
import re
import sys
from pathlib import Path


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\b\w+\b", text.lower()))


def _load_evidence_texts(evidence_path: str) -> list[tuple[str, str]]:
    """Load (path, text) pairs from a file or directory."""
    p = Path(evidence_path)
    pairs = []
    if p.is_file():
        try:
            pairs.append((str(p), p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            pass
    elif p.is_dir():
        for f in sorted(p.rglob("*")):
            if f.is_file() and f.suffix in {".md", ".txt", ".rst", ".py", ".json", ".yaml", ".yml"}:
                try:
                    pairs.append((str(f), f.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    continue
    return pairs


def classify_claim(claim: str, evidence_texts: list[tuple[str, str]]) -> dict:
    """
    Classify a claim against evidence using token overlap.

    Heuristic:
    - overlap >= 0.7 of claim tokens found in evidence → supported
    - overlap 0.4–0.69 → partially_supported
    - overlap 0.1–0.39 → unverifiable (partial signal but insufficient)
    - overlap < 0.1 → unsupported
    - If any evidence line directly contradicts common negative patterns → contradicted
    """
    claim_tokens = _tokenize(claim)
    if not claim_tokens:
        return {
            "text": claim,
            "classification": "unverifiable",
            "evidence_refs": [],
            "note": "claim could not be tokenized",
        }

    best_overlap = 0.0
    best_source = ""
    combined_evidence = ""

    for src, text in evidence_texts:
        ev_tokens = _tokenize(text)
        overlap = len(claim_tokens & ev_tokens) / len(claim_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_source = src
        combined_evidence += text.lower() + " "

    negation_words = {"not", "never", "missing", "absent", "unavailable", "disabled", "no", "none"}
    claim_lower = claim.lower()
    evidence_contradicts = False
    for sentence in re.split(r"[.!?\n]", combined_evidence):
        s_tokens = _tokenize(sentence)
        claim_overlap_in_sentence = len(claim_tokens & s_tokens) / len(claim_tokens)
        if claim_overlap_in_sentence >= 0.5 and s_tokens & negation_words:
            evidence_contradicts = True
            break

    if evidence_contradicts and best_overlap < 0.4:
        classification = "contradicted"
        note = "evidence contains negation alongside claim keywords"
    elif best_overlap >= 0.7:
        classification = "supported"
        note = f"token overlap {best_overlap:.2f} in {best_source}"
    elif best_overlap >= 0.4:
        classification = "partially_supported"
        note = f"partial token overlap {best_overlap:.2f} in {best_source}"
    elif best_overlap >= 0.1:
        classification = "unverifiable"
        note = f"weak signal ({best_overlap:.2f}) — cannot confirm from available evidence"
    else:
        classification = "unsupported"
        note = "no supporting evidence found"

    return {
        "text": claim,
        "classification": classification,
        "evidence_refs": [best_source] if best_source else [],
        "note": note,
    }


def verify_claims(
    claims: list[str],
    evidence_paths: list[str],
    strict: bool = False,
) -> dict:
    """Verify all claims against evidence. Returns claim-verification schema."""
    evidence_texts: list[tuple[str, str]] = []
    for ep in evidence_paths:
        evidence_texts.extend(_load_evidence_texts(ep))

    verified_claims = []
    unsupported_count = 0

    for claim in claims:
        result = classify_claim(claim, evidence_texts)
        verified_claims.append(result)
        if result["classification"] in ("unsupported", "contradicted"):
            unsupported_count += 1

    evidence_used = list({src for src, _ in evidence_texts})

    return {
        "enabled": True,
        "unsupported_claims_removed": unsupported_count,
        "claims": verified_claims,
        "evidence_ledger": {
            "evidence_used": evidence_used,
            "assumptions": [],
            "missing_evidence": [] if evidence_texts else ["no evidence sources loaded"],
            "validation_run": False,
            "unsupported_claims_removed": unsupported_count,
            "source_scope": ", ".join(evidence_paths) if evidence_paths else "none",
            "freshness": "local files read at runtime",
            "confidence": "high" if evidence_texts else "low",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify factual claims against evidence.")
    parser.add_argument("--claims", default=None,
                        help="JSON array of claim strings, or path to a JSON file.")
    parser.add_argument("--stdin-claims", action="store_true",
                        help="Read claims JSON from stdin.")
    parser.add_argument("--evidence", nargs="+", default=[],
                        help="Evidence file(s) or directory(ies) to verify against.")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 if any claims are unsupported or contradicted.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()

    if args.stdin_claims or (not args.claims and not sys.stdin.isatty()):
        raw = sys.stdin.read()
    elif args.claims:
        p = Path(args.claims)
        if p.is_file():
            raw = p.read_text()
        else:
            raw = args.claims
    else:
        parser.error("Provide --claims '<json_array>' or --stdin-claims.")

    try:
        claims = json.loads(raw)
        if not isinstance(claims, list):
            claims = [str(claims)]
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"Error parsing claims JSON: {exc}\n")
        sys.exit(1)

    result = verify_claims(claims, args.evidence, args.strict)
    indent = 2 if args.pretty else None
    print(json.dumps(result, indent=indent))

    if args.strict and result["unsupported_claims_removed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
