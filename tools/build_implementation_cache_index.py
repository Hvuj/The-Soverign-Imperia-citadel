#!/usr/bin/env python3
"""build_implementation_cache_index.py — Real implementation cache indexer.

Scans feature-implementation-patterns.md and the workspace intelligence index
to build a searchable cache that reuse_fast_path.py can query at O(1) per lookup.

Output:
  .claude/state/implementation-cache-index.json  (machine-readable, keyed by pattern id)
  docs/ai-context/implementation-cache-index.md  (human-readable summary)
"""

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
PATTERNS_MD = ROOT / "docs" / "ai-context" / "feature-implementation-patterns.md"
CACHE_INDEX_JSON = ROOT / ".claude" / "state" / "implementation-cache-index.json"
CACHE_INDEX_MD = ROOT / "docs" / "ai-context" / "implementation-cache-index.md"

CARD_RE = re.compile(r"^##\s+(.+?)\n(.*?)(?=^##\s+|\Z)", re.M | re.S)
TAG_RE = re.compile(r"Tags:\s*\[([^\]]*)\]")
DOMAIN_RE = re.compile(r"^Domain:\s*(.+)$", re.M)
FILES_RE = re.compile(r"^Files:\n((?:- .+\n?)+)", re.M)
TESTS_RE = re.compile(r"^Tests:\n((?:- .+\n?)+)", re.M)
APPROACH_RE = re.compile(r"^Approach:\n(.+?)(?=^[A-Z]|\Z)", re.M | re.S)
PITFALLS_RE = re.compile(r"^Pitfalls avoided:\n((?:- .+\n?)+)", re.M)
AGENTS_RE = re.compile(r"^Agents to escalate:\n((?:- .+\n?)+)", re.M)


def _list_items(block: str) -> list[str]:
    return [ln.lstrip("- ").strip() for ln in block.strip().splitlines() if ln.strip() and ln.strip() != "-"]


def _parse_card(title: str, body: str) -> dict:
    card_id = title.split(":", 1)[0].strip()
    tags = _list_items(TAG_RE.search(body).group(1)) if TAG_RE.search(body) else []
    domain_m = DOMAIN_RE.search(body)
    domain = domain_m.group(1).strip() if domain_m else "unknown"
    files_m = FILES_RE.search(body)
    files = _list_items(files_m.group(1)) if files_m else []
    tests_m = TESTS_RE.search(body)
    tests = _list_items(tests_m.group(1)) if tests_m else []
    approach_m = APPROACH_RE.search(body)
    approach = approach_m.group(1).strip()[:300] if approach_m else ""
    pitfalls_m = PITFALLS_RE.search(body)
    pitfalls = _list_items(pitfalls_m.group(1)) if pitfalls_m else []
    agents_m = AGENTS_RE.search(body)
    agents = _list_items(agents_m.group(1)) if agents_m else []

    all_text = " ".join([title, domain, " ".join(tags), " ".join(files),
                         approach, " ".join(pitfalls)])
    tokens = sorted({t.lower() for t in re.findall(r"[a-z0-9_][a-z0-9_]{2,}", all_text.lower())})

    return {
        "id": card_id,
        "title": title.strip(),
        "tags": tags,
        "domain": domain,
        "files": files,
        "tests": tests,
        "approach": approach,
        "pitfalls": pitfalls,
        "agents": agents,
        "tokens": tokens[:60],
    }


def build(quiet: bool = False) -> dict:
    cards: dict[str, dict] = {}

    if PATTERNS_MD.exists():
        text = PATTERNS_MD.read_text(encoding="utf-8")
        for title, body in CARD_RE.findall(text):
            title = title.strip()
            if title.lower() in ("template", "feature implementation patterns"):
                continue
            try:
                card = _parse_card(title, body)
                cards[card["id"]] = card
            except Exception:
                pass

    payload = {
        "built_at": datetime.now(UTC).isoformat(),
        "card_count": len(cards),
        "files": cards,
    }

    CACHE_INDEX_JSON.parent.mkdir(parents=True, exist_ok=True)
    CACHE_INDEX_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    CACHE_INDEX_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Implementation Cache Index",
        f"\nBuilt: {payload['built_at']}  |  Cards: {len(cards)}\n",
    ]
    for cid, card in sorted(cards.items()):
        lines.append(f"## {cid}: {card['title']}")
        lines.append(f"Domain: {card['domain']}  Tags: {', '.join(card['tags'])}")
        if card["files"]:
            lines.append("Files: " + ", ".join(card["files"][:4]))
        lines.append("")
    CACHE_INDEX_MD.write_text("\n".join(lines), encoding="utf-8")

    if not quiet:
        print(f"implementation cache built: {len(cards)} cards → {CACHE_INDEX_JSON}")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()
    result = build(quiet=args.quiet)
    if args.as_json:
        print(json.dumps({"card_count": result["card_count"], "built_at": result["built_at"]}))


if __name__ == "__main__":
    main()
