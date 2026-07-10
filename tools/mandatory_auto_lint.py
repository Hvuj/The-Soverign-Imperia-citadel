#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
req=[".claude/brain/graph-aware-config.json",".claude/brain/workflow-manifest-config.json",".claude/brain/artifact-policy.json",".claude/brain/memory-policy.json",".claude/brain/model-effort-config.json",".claude/brain/scheduler-config.json",".claude/daemon/incremental-brain-config.json",".claude/hooks/session-start-brain-preflight.sh",".claude/hooks/user-prompt-brain-search.sh",".claude/hooks/user-prompt-execution-manifest.sh",".claude/hooks/subagent-context-injector.sh",".claude/hooks/post-tool-batch-incremental-sync.sh",".claude/hooks/audit-gate.sh",".claude/hooks/graph-aware-scope-guard.sh","scripts/claude-start-smart.sh","scripts/incremental-brain-daemon-start.sh","tools/build_brain_search_index.py","tools/brain_search.py","tools/brain_context_builder.py","tools/incremental_brain_daemon.py","tools/graph_brain_lint.py","tools/build_execution_manifest.py","tools/execution_manifest_lint.py","tools/manifest_status.py","tools/claude_memory_lint.py","tools/model_effort_scheduler.py","tools/scheduler_lint.py","tools/daemon_health_check.py",
".claude/brain/workspace-index-config.json","tools/_workspace_intel_common.py","tools/build_workspace_intelligence_index.py","tools/workspace_intelligence_query.py","tools/workspace_intelligence_lint.py","tools/workspace_intelligence_daemon.py","scripts/workspace-intelligence-build.sh","scripts/workspace-intelligence-query.sh","scripts/workspace-intelligence-lint.sh","scripts/workspace-intelligence-daemon-start.sh","scripts/workspace-intelligence-daemon-status.sh","scripts/workspace-intelligence-daemon-stop.sh",
".claude/schemas/ask-response.schema.json",".claude/schemas/system-health.schema.json",".claude/schemas/execution-manifest.schema.json",".claude/rules/grounding.md",".claude/rules/output-consistency.md",".claude/rules/prompt-leak-policy.md",".claude/brain/prompt-template-registry.json","tools/grounding_quote_extractor.py","tools/grounding_claim_verifier.py","tools/output_normalizer.py","tools/prompt_leak_output_filter.py","tools/grounding_lint.py","tools/output_schema_lint.py","tools/prompt_leak_lint.py","tools/best_practices_lint.py","scripts/mandatory-auto-lint.sh",
"tools/brand_lint.py"]
ok=True
for rel in req:
    p=ROOT/rel
    if not p.exists(): print(f"MISSING {rel}"); ok=False
    elif p.suffix in {".sh",".py"} and not os.access(p, os.X_OK): print(f"NOT EXECUTABLE {rel}"); ok=False
cfg=json.loads((ROOT/".claude/brain/graph-aware-config.json").read_text())
if cfg.get("automation_mode")!="mandatory" or cfg.get("daemon_required") is not True: print("BAD CONFIG"); ok=False
wf_cfg_path=ROOT/".claude/brain/workflow-manifest-config.json"
if wf_cfg_path.exists():
    wf_cfg=json.loads(wf_cfg_path.read_text())
    if "workflows" not in wf_cfg: print("BAD MANIFEST CONFIG: missing workflows"); ok=False
mem_policy_path=ROOT/".claude/brain/memory-policy.json"
if mem_policy_path.exists():
    mem_policy=json.loads(mem_policy_path.read_text())
    if "memory_policy_rules" not in mem_policy: print("BAD MANIFEST CONFIG: missing memory_policy_rules in memory-policy.json"); ok=False
else:
    if wf_cfg_path.exists() and "memory_policy_rules" not in json.loads(wf_cfg_path.read_text()):
        print("BAD MANIFEST CONFIG: missing memory_policy_rules"); ok=False
settings=json.loads((ROOT/".claude/settings.json").read_text()) if (ROOT/".claude/settings.json").exists() else {}
for ev in ["SessionStart","UserPromptSubmit","SubagentStart","PostToolBatch","Stop"]:
    if ev not in settings.get("hooks",{}): print(f"MISSING HOOK {ev}"); ok=False
try:
    import subprocess
    _bl = subprocess.run([sys.executable, str(ROOT/"tools/brand_lint.py")], capture_output=True, text=True)
    if _bl.returncode != 0:
        print("BRAND LINT FAIL:"); print(_bl.stdout.strip()); ok=False
except Exception as _e:
    print(f"BRAND LINT ERROR: {_e}"); ok=False
if ok: print("Status: Pass"); print("normal_start_command: scripts/claude-start-smart.sh")
else: sys.exit(1)
