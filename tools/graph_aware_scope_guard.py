#!/usr/bin/env python3
import json
import re
import sys

bad=[(r"git\\s+rm\\s+-r\\s+--cached\\s+\\.","Blocks full-index untracking."),(r"rm\\s+-rf","Blocks rm -rf."),(r"git\\s+reset\\s+--hard","Blocks reset hard."),(r"claude\\s+-p","Blocks scripted Claude calls.")]
raw=sys.stdin.read()
for pat,reason in bad:
    if re.search(pat,raw):
        print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":reason}})); raise SystemExit
print("{}")
