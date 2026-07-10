#!/usr/bin/env python3
"""Memory and rules compliance checker.

Checks (warn vs fail):
  WARN (non-fatal): CLAUDE.md > 200 lines, large imports, MEMORY.md bloat,
                    duplicate giant memory entries
  FAIL (fatal):     missing required memory files, missing rules, missing
                    manifest memory_policy_rules, skills copied into CLAUDE.md,
                    no hook enforcement for mandatory behaviors
"""
import json
import sys
from pathlib import Path

from _brain_common import ROOT, load_json, load_memory_policy

MANIFEST_CFG = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"
MEMORY_POLICY_PATH = ROOT / ".claude" / "brain" / "memory-policy.json"
ARTIFACTS_DIR = ROOT / ".claude" / "state" / "artifacts" / "current"
AI_CONTEXT_DIR = ROOT / "docs" / "ai-context"

REQUIRED_AI_CONTEXT = [
    "docs/ai-context/active-memory.md",
    "docs/ai-context/what-worked.md",
    "docs/ai-context/what-did-not-work.md",
    "docs/ai-context/bi-logic.md",
]
REQUIRED_RULES = [
    ".claude/rules/architecture.md",
    ".claude/rules/code-style.md",
    ".claude/rules/testing.md",
]
REQUIRED_HOOKS = [
    ".claude/hooks/session-start-brain-preflight.sh",
    ".claude/hooks/user-prompt-brain-search.sh",
    ".claude/hooks/subagent-context-injector.sh",
    ".claude/hooks/post-tool-batch-incremental-sync.sh",
    ".claude/hooks/audit-gate.sh",
]
REQUIRED_SETTINGS_HOOKS = ["SessionStart", "UserPromptSubmit", "SubagentStart", "PostToolBatch", "Stop"]

CLAUDE_MD_LINE_WARN = 200
MEMORY_MD_LINE_WARN = 100


def _claude_project_memory_md(root: Path) -> Path:
    """Return the Claude Code per-project memory index for whatever workspace `root` is.

    Claude Code slugs a project's per-user memory dir as its absolute path with every
    path separator replaced by `-` — derived from `root`, never a hardcoded workspace name.
    """
    slug = str(root.resolve()).replace("/", "-")
    return Path.home() / ".claude" / "projects" / slug / "memory" / "MEMORY.md"


def main() -> None:
    warnings: list[str] = []
    errors: list[str] = []

    claude_md = ROOT / "CLAUDE.md"
    if not claude_md.exists():
        errors.append("MISSING CLAUDE.md")
    else:
        lines = claude_md.read_text().splitlines()
        if len(lines) > CLAUDE_MD_LINE_WARN:
            large_sections = [
                l.strip() for l in lines
                if l.startswith("## ") and any(
                    kw in l.lower() for kw in
                    ["agent", "budget", "memory", "workflow", "bi logic", "token", "validation", "planning"]
                )
            ]
            warnings.append(
                f"WARN: CLAUDE.md is {len(lines)} lines (>{CLAUDE_MD_LINE_WARN}). "
                f"Consider moving to .claude/rules/ or graph capsules: {large_sections[:4]}"
            )

    for rel in REQUIRED_AI_CONTEXT:
        if not (ROOT / rel).exists():
            errors.append(f"MISSING {rel}")

    for rel in REQUIRED_RULES:
        if not (ROOT / rel).exists():
            errors.append(f"MISSING {rel}")

    memory_md = ROOT / "docs" / "ai-context" / "memory-index.md"
    user_memory_md = _claude_project_memory_md(ROOT)
    for mp in [memory_md, user_memory_md]:
        if mp.exists():
            ml = mp.read_text().splitlines()
            if len(ml) > MEMORY_MD_LINE_WARN:
                warnings.append(
                    f"WARN: {mp.name} is {len(ml)} lines. It should stay an index, not a knowledge dump."
                )

    mem_pol = load_memory_policy()
    if not mem_pol.get("memory_policy_rules"):
        errors.append(
            "memory_policy_rules not found in memory-policy.json or workflow-manifest-config.json"
        )
    cfg = load_json(MANIFEST_CFG, None)
    if cfg is None:
        errors.append(f"MISSING {MANIFEST_CFG.relative_to(ROOT)}")
    else:
        if "workflows" not in cfg:
            errors.append("workflow-manifest-config.json missing workflows block")

    if ARTIFACTS_DIR.exists() and AI_CONTEXT_DIR.exists():
        artifact_names = {f.name for f in ARTIFACTS_DIR.iterdir() if f.is_file() and f.suffix == ".md"}
        ai_names = {f.name for f in AI_CONTEXT_DIR.iterdir() if f.is_file() and f.suffix == ".md"}
        overlap = artifact_names & ai_names
        for name in sorted(overlap):
            warnings.append(
                f"WARN: artifact {name} also appears in docs/ai-context/ — "
                "runtime artifacts must not be copied directly to durable memory without compression"
            )

    skills_dir = ROOT / ".claude" / "skills"
    if claude_md.exists() and skills_dir.exists():
        claude_text = claude_md.read_text()
        for skill_dir in skills_dir.iterdir():
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                skill_text = skill_file.read_text().strip()
                if len(skill_text) > 200 and skill_text[:100] in claude_text:
                    warnings.append(f"WARN: skill {skill_dir.name} content may be copied into CLAUDE.md")

    settings_path = ROOT / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
            hooks = settings.get("hooks", {})
            for ev in REQUIRED_SETTINGS_HOOKS:
                if ev not in hooks:
                    errors.append(f"MISSING hook wiring: {ev} in settings.json")
        except json.JSONDecodeError:
            errors.append("settings.json is not valid JSON")
    else:
        errors.append("MISSING .claude/settings.json")

    for rel in REQUIRED_HOOKS:
        if not (ROOT / rel).exists():
            errors.append(f"MISSING hook: {rel}")

    ai_context = ROOT / "docs" / "ai-context"
    nodes_memory = ROOT / "docs" / "brain" / "nodes" / "memory"
    if ai_context.exists() and nodes_memory.exists():
        ai_files = {f.stem: len(f.read_text()) for f in ai_context.glob("*.md") if f.is_file()}
        node_files = {f.stem: len(f.read_text()) for f in nodes_memory.glob("*.md") if f.is_file()}
        for stem in set(ai_files) & set(node_files):
            if ai_files[stem] > 2000 and node_files[stem] > 2000:
                warnings.append(
                    f"WARN: Large duplicate content in docs/ai-context/{stem}.md and "
                    f"docs/brain/nodes/memory/{stem}.md — compress one"
                )

    ok = not errors
    all_msgs = warnings + ([f"ERROR: {e}" for e in errors])
    for msg in all_msgs:
        print(msg)

    if ok:
        print("Status: Pass")
    else:
        print(f"Status: Fail ({len(errors)} error(s), {len(warnings)} warning(s))")
        sys.exit(1)


if __name__ == "__main__":
    main()
