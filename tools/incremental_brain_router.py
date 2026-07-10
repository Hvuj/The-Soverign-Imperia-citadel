#!/usr/bin/env python3
import argparse
import json
from datetime import UTC, datetime

from _brain_common import STATE, write_json

ap=argparse.ArgumentParser(); ap.add_argument("paths",nargs="*"); ap.add_argument("--json",action="store_true"); args=ap.parse_args()
dirty={"updated_at":datetime.now(UTC).isoformat(),"dirty":[],"by_path":{p:{"path":p,"domains":["general"],"nodes":[]} for p in args.paths}}
write_json(STATE/"dirty-nodes.json", dirty); print(json.dumps(dirty,indent=2) if args.json else "dirty nodes: 0")
