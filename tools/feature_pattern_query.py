#!/usr/bin/env python3
import argparse
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
PATTERNS=ROOT/"docs/ai-context/feature-implementation-patterns.md"
CARD=re.compile(r"^##\s+(.+?)\n(.*?)(?=^##\s+|\Z)", re.M|re.S)


def toks(s): return [t.lower() for t in re.findall(r"[A-Za-z0-9_./-]+",s) if len(t)>1]


p=argparse.ArgumentParser(); p.add_argument("query"); p.add_argument("--limit",type=int,default=3); a=p.parse_args()
if not PATTERNS.exists():
    print("No feature pattern memory found."); raise SystemExit
text=PATTERNS.read_text(encoding="utf-8"); qs=toks(a.query); scored=[]
for title,body in CARD.findall(text):
    hay=(title+"\n"+body).lower(); score=sum(hay.count(t) for t in qs)
    if score: scored.append((score,title.strip(),body.strip()))
if not scored:
    print("No matching feature implementation patterns."); raise SystemExit
keep=("Tags:","Domain:","Task type:","Files:","Tests:","Problem:","Approach:","Reuse next time:","Agents to escalate:","Graph links:")
for score,title,body in sorted(scored,key=lambda x:x[0],reverse=True)[:a.limit]:
    compact=[]; cap=0
    for line in [l.rstrip() for l in body.splitlines()]:
        if line.startswith(keep):
            compact.append(line); cap=3
        elif cap>0 and (line.startswith("- ") or re.match(r"^\d+\.", line) or line.strip()):
            compact.append(line); cap-=1
    print(f"## {title}\nScore: {score}\n" + "\n".join(compact[:80]) + "\n---")
