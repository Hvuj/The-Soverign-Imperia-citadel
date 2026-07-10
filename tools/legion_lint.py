#!/usr/bin/env python3
import os
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1]); agents=list((ROOT/".claude/agents").glob("*.md")); skills=list((ROOT/".claude/skills").glob("*/SKILL.md"))
print(f"agents: {len(agents)}"); print(f"skills: {len(skills)}")
if len(agents)<20: raise SystemExit("Blocked: expected at least 20 agents")
print("Status: Pass")
