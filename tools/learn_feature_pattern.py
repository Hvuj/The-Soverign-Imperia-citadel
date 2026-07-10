#!/usr/bin/env python3
import argparse
import os
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
OUT=ROOT/"docs/ai-context/feature-implementation-patterns.md"


def run(cmd):
    try: return subprocess.check_output(cmd,cwd=ROOT,text=True,stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e: return e.output


def slug(s):
    out="".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")
    while "--" in out: out=out.replace("--","-")
    return out


p=argparse.ArgumentParser(); p.add_argument("--title",required=True); p.add_argument("--domain",default="Uncertain"); p.add_argument("--task-type",default="feature"); p.add_argument("--tests",default=""); p.add_argument("--notes",default=""); a=p.parse_args()
changed=run(["git","diff","--name-only"]).strip().splitlines()
stat=run(["git","diff","--stat"]).strip()
pid=slug(a.title) or f"pattern-{date.today().isoformat()}"
OUT.parent.mkdir(parents=True,exist_ok=True)
if not OUT.exists(): OUT.write_text("# Feature Implementation Patterns\n\n",encoding="utf-8")
files="\n".join(f"- {f}" for f in changed) if changed else "- Uncertain"
tests="\n".join(f"- {t.strip()}" for t in a.tests.split(";") if t.strip()) if a.tests else "- Uncertain"
card=f"""
---

## {pid}: {a.title}

Tags: [{a.domain}, {a.task_type}]
Domain: {a.domain}
Task type: {a.task_type}
Files:
{files}
Tests:
{tests}

Problem:
{a.notes or "Uncertain"}

Approach:
Uncertain. Fill after audited implementation summary.

Why it worked:
Uncertain. Add validation evidence.

Data / schema / BI contract:
Uncertain.

Performance notes:
Uncertain.

Pitfalls avoided:
- Uncertain.

Reuse next time:
1. Query this card before similar work.
2. Inspect listed files first.
3. Run listed tests first.

Agents to escalate:
- pattern-reuse-router
- test-validation-runner

Graph links:
- feature-learning-workflow

Diff stat:
```text
{stat}
```
"""
existing=OUT.read_text(encoding="utf-8")
if f"## {pid}:" in existing:
    print(f"Pattern already exists: {pid}"); raise SystemExit
OUT.write_text(existing.rstrip()+card+"\n",encoding="utf-8")
print(f"Added pattern: {pid}")
