#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
G=ROOT/"docs/brain/graph.json"
p=argparse.ArgumentParser(); p.add_argument("query"); p.add_argument("--limit",type=int,default=3); a=p.parse_args()
q=a.query.lower(); data=json.loads(G.read_text(encoding="utf-8")); scored=[]
for n in data.get("nodes",[]):
    hay=" ".join([n.get("id",""),n.get("title",""),n.get("type","")," ".join(n.get("tags",[]))," ".join(n.get("files",[])),n.get("path","")]).lower()
    score=hay.count(q)+sum(hay.count(tok) for tok in q.split())
    if score: scored.append((score,n))
for _,n in sorted(scored,key=lambda x:x[0],reverse=True)[:a.limit]:
    print(f"node: {n['id']}\ntitle: {n.get('title','')}\ntype: {n.get('type','')}\npath: {n.get('path','')}")
    if n.get("files"):
        print("files:"); [print(f"  - {f}") for f in n["files"]]
    print()
