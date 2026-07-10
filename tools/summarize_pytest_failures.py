#!/usr/bin/env python3
import re
import sys

txt=sys.stdin.read(); lines=txt.splitlines(); pats=[r"=+ FAILURES =+",r"FAILED .*",r"E\s+.*",r"AssertionError.*",r"Traceback.*",r"short test summary"]
out=[]
for i,l in enumerate(lines):
    if any(re.search(p,l) for p in pats):
        out += lines[max(0,i-3):min(len(lines),i+12)] + ["---"]
seen=set()
for l in out[:400]:
    if l not in seen:
        seen.add(l); print(l)
