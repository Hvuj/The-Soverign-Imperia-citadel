#!/usr/bin/env python3
"""Debug-only: report which CLAUDE.md/rules/memory/skills/manifest are active.

NOT wired in settings.json. Run manually for debugging only:
    python tools/instructions_loaded_report.py
"""
from _brain_common import ROOT, STATE, load_json

MANIFEST_CFG = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"


def main() -> None:
    print("# Instructions Loaded Report (debug only)\n")

    print("## CLAUDE.md files")
    for p in [ROOT / "CLAUDE.md"]:
        if p.exists():
            lines = p.read_text().splitlines()
            print(f"  {p.relative_to(ROOT)}: {len(lines)} lines")
        else:
            print(f"  {p.relative_to(ROOT)}: MISSING")

    print("\n## .claude/rules/")
    rules_dir = ROOT / ".claude" / "rules"
    if rules_dir.exists():
        for f in sorted(rules_dir.glob("*.md")):
            text = f.read_text()
            has_paths = "paths:" in text
            print(f"  {f.name}: {len(text.splitlines())} lines {'(path-scoped)' if has_paths else ''}")
    else:
        print("  (none)")

    print("\n## docs/ai-context/ memory files")
    ai_ctx = ROOT / "docs" / "ai-context"
    if ai_ctx.exists():
        for f in sorted(ai_ctx.glob("*.md")):
            print(f"  {f.name}: {len(f.read_text().splitlines())} lines")

    print("\n## .claude/skills/ (on-demand, not auto-loaded)")
    skills_dir = ROOT / ".claude" / "skills"
    if skills_dir.exists():
        for d in sorted(skills_dir.iterdir()):
            sf = d / "SKILL.md"
            if sf.exists():
                print(f"  {d.name}")

    manifest_path = STATE / "execution-manifest.json"
    print("\n## Active execution manifest")
    if manifest_path.exists():
        m = load_json(manifest_path, {})
        print(f"  task_type:        {m.get('task_type')}")
        print(f"  selected_workflow:{m.get('selected_workflow')}")
        print(f"  required_agents:  {m.get('required_agents', [])}")
        print(f"  memory_policy:    {m.get('memory_policy')}")
        print(f"  created_at:       {m.get('created_at')}")
    else:
        print("  (no manifest found)")

    next_ctx = STATE / "next-context.json"
    print("\n## Latest context capsule (next-context.json)")
    if next_ctx.exists():
        cap = load_json(next_ctx, {})
        print(f"  intent:           {cap.get('intent')}")
        print(f"  recommended_agents:{cap.get('recommended_agents', [])[:5]}")
        print(f"  selected_nodes:   {[n.get('id') for n in cap.get('selected_nodes', [])[:5]]}")
        print(f"  created_at:       {cap.get('created_at')}")
    else:
        print("  (none)")

    print("\n## workflow-manifest-config.json")
    if MANIFEST_CFG.exists():
        cfg = load_json(MANIFEST_CFG, {})
        print(f"  version:          {cfg.get('version')}")
        print(f"  task_types:       {cfg.get('task_types', [])}")
        print(f"  workflows:        {list(cfg.get('workflows', {}).keys())}")
    else:
        print("  MISSING")

    print("\n# End of instructions loaded report")


if __name__ == "__main__":
    main()
