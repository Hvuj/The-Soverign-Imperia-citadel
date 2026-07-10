#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
req=[".claude/hooks/user-prompt-classifier.sh",".claude/hooks/agent-run-ledger.sh",".claude/hooks/task-ledger.sh",".claude/hooks/post-tool-batch-summarizer.sh",".claude/hooks/pre-compact-state-save.sh",".claude/hooks/post-compact-state-restore.sh",".claude/hooks/session-end-ledger.sh",".claude/hooks/pre-edit-scope-guard.sh",".claude/statusline.sh",".claude/statusline.py",".claude/agents/scope-guard-agent.md",".claude/agents/telemetry-auditor.md",".claude/agents/prompt-classifier-agent.md",".claude/agents/context-preservation-agent.md",".claude/agents/code-symbol-indexer.md",".claude/agents/import-dependency-agent.md",".claude/agents/lsp-diagnostics-agent.md",".claude/rules/observability-scope-telemetry.md","tools/classify_prompt.py","tools/agent_run_ledger.py","tools/task_ledger.py","tools/post_tool_batch_summarizer.py","tools/compact_state.py","tools/session_end_ledger.py","tools/scope_guard.py","tools/symbol_index.py","tools/import_graph.py","tools/state_report.py"]
ok=True
for r in req:
    if not (ROOT/r).exists(): print("MISSING",r); ok=False
for rel in [".claude/settings.json",".claude/settings.local.json"]:
    p=ROOT/rel
    if p.exists():
        try: json.loads(p.read_text())
        except Exception as e: print("BAD JSON",rel,e); ok=False
for h in ["user-prompt-classifier.sh","agent-run-ledger.sh","task-ledger.sh","post-tool-batch-summarizer.sh","pre-compact-state-save.sh","post-compact-state-restore.sh","session-end-ledger.sh","pre-edit-scope-guard.sh"]:
    p=ROOT/".claude/hooks"/h
    if p.exists() and subprocess.run(["bash","-n",str(p)],cwd=ROOT).returncode!=0: ok=False; print("BAD SHELL",h)
if ok: print("Status: Pass"); print("Claude legion observability/scope additions present")
else: sys.exit(1)
