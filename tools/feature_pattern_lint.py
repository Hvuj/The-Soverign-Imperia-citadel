#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
PATH=ROOT/"docs/ai-context/feature-implementation-patterns.md"
required=["Tags:","Domain:","Task type:","Files:","Tests:","Problem:","Approach:","Why it worked:","Reuse next time:","Agents to escalate:","Graph links:"]
text=PATH.read_text(encoding="utf-8") if PATH.exists() else ""
cards=re.findall(r"^##\s+(.+?)\n(.*?)(?=^##\s+|\Z)", text, re.M|re.S)
ok=True
for title,body in cards:
    if title.strip().lower()=="template": continue
    for field in required:
        if field not in body:
            print(f"Missing {field} in card: {title}"); ok=False
if ok:
    print("Status: Pass"); print(f"Patterns checked: {len(cards)}")
else:
    sys.exit(1)
