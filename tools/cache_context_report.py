#!/usr/bin/env python3

import os
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
WATCH = [
    "CLAUDE.md",
    ".claude/agents",
    ".claude/rules",
    "docs/ai-context",
    "docs/brain/graph-index.md",
    "docs/brain/nodes",
]

WARN_BYTES = {
    "CLAUDE.md": 16000,
    "docs/ai-context/active-memory.md": 20000,
    "docs/ai-context/what-worked.md": 40000,
    "docs/ai-context/what-did-not-work.md": 40000,
    "docs/ai-context/feature-implementation-patterns.md": 50000,
    "docs/ai-context/implementation-cache-index.md": 30000,
}


def main() -> None:
    for rel in WATCH:
        p = ROOT / rel
        if p.is_file():
            size = p.stat().st_size
            limit = WARN_BYTES.get(rel)
            status = "OK" if not limit or size <= limit else "WARN"
            print(f"{status} {rel}: {size} bytes")
        elif p.is_dir():
            total = 0
            for f in sorted(p.rglob("*.md")):
                size = f.stat().st_size
                total += size
                r = str(f.relative_to(ROOT))
                limit = WARN_BYTES.get(r)
                status = "OK" if not limit or size <= limit else "WARN"
                print(f"{status} {r}: {size} bytes")
            print(f"DIR {rel}: {total} bytes")


if __name__ == "__main__":
    main()
