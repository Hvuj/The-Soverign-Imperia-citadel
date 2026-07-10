#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1]); idx=ROOT/".claude/state/brain-search/index.json"
if idx.exists():
    d=json.loads(idx.read_text()); print(f"brain-search nodes: {len(d.get('nodes',{}))}"); print(f"brain-search edges: {len(d.get('edges',[]))}"); print("Status: Pass")
else:
    print("brain-search index missing"); sys.exit(1)
