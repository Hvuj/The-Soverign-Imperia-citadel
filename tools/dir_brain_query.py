#!/usr/bin/env python3

import argparse
import json
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
INDEX_JSON = ROOT / "docs" / "brain" / "directories" / "index.json"


def toks(s: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9_./-]+", s) if len(t) > 1]


def score(q: list[str], text: str) -> int:
    hay = text.lower()
    return sum(hay.count(t) for t in q)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="+")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    query = " ".join(args.query)
    q = toks(query)

    if not INDEX_JSON.exists():
        print("No directory brain index found.")
        return

    data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    scored = []
    for d in data.get("directories", []):
        parts = [d.get("id",""), d.get("path",""), d.get("purpose",""), d.get("brain","")]
        brain_path = ROOT / d.get("brain", "")
        if brain_path.exists():
            parts.append(brain_path.read_text(encoding="utf-8")[:4000])
        s = score(q, "\n".join(parts))
        if s:
            scored.append((s, d))

    results = [d | {"score": s} for s, d in sorted(scored, key=lambda x: x[0], reverse=True)[:args.limit]]

    if args.json:
        print(json.dumps({"query": query, "results": results}, indent=2))
        return

    if not results:
        print("No matching directory brain.")
        return

    print("# Directory Brain Query")
    for d in results:
        print(f"- {d['id']} score={d['score']}")
        print(f"  path: {d.get('path','')}")
        print(f"  brain: {d.get('brain','')}")
        print(f"  files: {d.get('files','')}")
        print()


if __name__ == "__main__":
    main()
