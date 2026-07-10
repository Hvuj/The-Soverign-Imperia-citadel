#!/usr/bin/env python3
import os
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
for rel in ["CLAUDE.md",".claude/agents",".claude/rules","docs/ai-context","docs/brain/graph-index.md"]:
    p=ROOT/rel
    if p.is_file(): print(f"{rel}: {p.stat().st_size} bytes")
    elif p.is_dir():
        total=0
        for f in sorted(p.rglob("*.md")):
            s=f.stat().st_size; total+=s; print(f"{f.relative_to(ROOT)}: {s} bytes")
        print(f"{rel} total: {total} bytes")
