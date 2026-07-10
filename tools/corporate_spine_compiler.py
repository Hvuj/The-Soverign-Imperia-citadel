#!/usr/bin/env python3
"""
Corporate Spine Compiler — Phase 13: The Corporate Spine & Prompt Caching.

Compiles a stable Markdown document (corporate-spine.md) from the project's
governing artifacts:
  - JSON schemas          (.claude/schemas/*.json)
  - Board config/rules    (.claude/legion/board-config.json)
  - Skill playbooks       (.claude/skills/*.md)
  - Workspace map         (.claude/state/workspace-discovery.json)

Output: .claude/state/corporate-spine.md

The output is SHA-256-gated: identical content skips the write, preserving
the stable prefix required for Anthropic prompt-cache hits.
"""


import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()


class CorporateSpineCompiler:
    """Compile and cache-gate the SOVEREIGN-IMPERIA-CITADEL corporate spine document."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root = root_dir or _ROOT
        self.spine_out_path = self.root / ".claude" / "state" / "corporate-spine.md"

    def _ingest_constitution(self) -> str:
        """Read all JSON schemas and format as a Markdown section.

        Files are sorted for deterministic output (cache stability).
        Only top-level JSON keys are emitted — full schema bodies are too
        large to put in a stable prompt prefix.
        """
        schemas_dir = self.root / ".claude" / "schemas"
        try:
            schema_files = sorted(schemas_dir.glob("*.json"))
        except (FileNotFoundError, OSError):
            return ""
        if not schema_files:
            return ""
        sections: list[str] = ["## Constitution: JSON Schemas\n"]
        for schema_path in schema_files:
            try:
                data = json.loads(schema_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                continue
            keys = sorted(data.keys()) if isinstance(data, dict) else []
            sections.append(f"### {schema_path.name}\n```json\n{json.dumps(keys, indent=2)}\n```\n")
        return "\n".join(sections)

    def _ingest_board_rules(self) -> str:
        """Read board-config.json and format directors + precedence rules."""
        board_path = self.root / ".claude" / "legion" / "board-config.json"
        try:
            data = json.loads(board_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return ""
        lines: list[str] = ["## Board Rules\n"]
        directors = data.get("directors", [])
        if directors:
            lines.append(f"- **Directors:** {', '.join(directors)}")
        tie_breaker = data.get("tie_breaker_policy", "")
        if tie_breaker:
            lines.append(f"- **Tie-breaker policy:** {tie_breaker}")
        precedence_rules: dict = data.get("precedence_rules", {})
        if precedence_rules:
            lines.append("\n**Precedence Rules:**")
            for rule, value in sorted(precedence_rules.items()):
                lines.append(f"- `{rule}`: {value}")
        return "\n".join(lines) + "\n"

    def _ingest_playbooks(self) -> str:
        """Read flat skill playbooks (.claude/skills/*.md) and concatenate.

        Only direct *.md files are globbed (not */SKILL.md sub-directories),
        matching the Phase 13 spec literal.
        """
        skills_dir = self.root / ".claude" / "skills"
        try:
            playbook_files = sorted(skills_dir.glob("*.md"))
        except (FileNotFoundError, OSError):
            return ""
        if not playbook_files:
            return ""
        sections: list[str] = []
        for playbook_path in playbook_files:
            try:
                content = playbook_path.read_text(encoding="utf-8").strip()
            except (FileNotFoundError, OSError):
                continue
            sections.append(f"## {playbook_path.stem} Playbook\n\n{content}\n")
        return "\n".join(sections)

    def _ingest_ast_map(self) -> str:
        """Read workspace-discovery.json and emit the framework/language map.

        The real shape nests frameworks/languages under projects[*]; this
        method also checks top-level keys for forward compatibility.
        """
        discovery_path = self.root / ".claude" / "state" / "workspace-discovery.json"
        try:
            data = json.loads(discovery_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return ""
        frameworks: set[str] = set()
        languages: set[str] = set()
        for fw in data.get("frameworks", []):
            if fw:
                frameworks.add(str(fw))
        for lang in data.get("languages", []):
            if lang:
                languages.add(str(lang))
        for project in data.get("projects", []):
            if not isinstance(project, dict):
                continue
            for fw in project.get("frameworks", []):
                if fw:
                    frameworks.add(str(fw))
            for lang in project.get("languages", []):
                if lang:
                    languages.add(str(lang))
        fw_list = sorted(frameworks) or ["none"]
        lang_list = sorted(languages) or ["none"]
        lines: list[str] = [
            "## Active Workspace Frameworks\n",
            f"- **Frameworks:** {', '.join(fw_list)}",
            f"- **Languages:** {', '.join(lang_list)}",
        ]
        return "\n".join(lines) + "\n"

    def compile_spine(self) -> bool:
        """Compile the corporate spine document, skipping writes when unchanged.

        The first line of the output file is an HTML comment containing the
        SHA-256 hash of the content.  If the existing file's hash matches the
        newly computed hash, the write is skipped — keeping the file mtime
        stable and the Anthropic prompt-cache prefix unchanged.

        Returns:
            True on success (write or skip).
        """
        const = self._ingest_constitution()
        rules = self._ingest_board_rules()
        playbooks = self._ingest_playbooks()
        ast = self._ingest_ast_map()

        full_content = (
            f"# SOVEREIGN-IMPERIA-CITADEL Corporate Spine\n\n{const}\n{rules}\n{playbooks}\n{ast}\n"
            "---\n\nWE ARE LEGION, WE ARE MANY\n"
        )
        sha = hashlib.sha256(full_content.encode()).hexdigest()
        hash_comment = f"<!-- spine-sha256: {sha} -->"

        if self.spine_out_path.exists():
            try:
                first_line = self.spine_out_path.read_text(encoding="utf-8").split("\n", 1)[0]
                if first_line.strip() == hash_comment:
                    print("Spine unchanged, skipping write")
                    return True
            except (OSError, IndexError):
                pass

        self.spine_out_path.parent.mkdir(parents=True, exist_ok=True)
        self.spine_out_path.write_text(f"{hash_comment}\n{full_content}", encoding="utf-8")
        print("Corporate Spine compiled successfully")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SOVEREIGN-IMPERIA-CITADEL Corporate Spine Compiler")
    parser.add_argument(
        "--compile",
        action="store_true",
        help="Compile the spine from project artifacts",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run in isolated test mode with ephemeral mocks (no network, no real project files)",
    )
    args = parser.parse_args()

    if args.test:
        with tempfile.TemporaryDirectory() as _tmp:
            tmp = Path(_tmp)
            (tmp / ".claude" / "schemas").mkdir(parents=True)
            (tmp / ".claude" / "skills").mkdir(parents=True)
            (tmp / ".claude" / "state").mkdir(parents=True)
            (tmp / ".claude" / "legion").mkdir(parents=True)
            (tmp / ".claude" / "schemas" / "test.schema.json").write_text(
                json.dumps({"title": "Test Schema", "type": "object", "properties": {}}),
                encoding="utf-8",
            )
            (tmp / ".claude" / "skills" / "test-playbook.md").write_text(
                "# Test Playbook\n\nDo the right thing.",
                encoding="utf-8",
            )
            compiler = CorporateSpineCompiler(root_dir=tmp)
            success = compiler.compile_spine()
            assert success, "compile_spine() returned False"
            assert compiler.spine_out_path.exists(), "corporate-spine.md was not created"
            spine_text = compiler.spine_out_path.read_text(encoding="utf-8")
            assert "<!-- spine-sha256:" in spine_text, "Hash comment missing from spine"
            assert "test.schema.json" in spine_text, "Schema filename not found in spine"
            assert "test-playbook Playbook" in spine_text, "Playbook header not found in spine"
            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                compiler.compile_spine()
            assert "unchanged" in buf.getvalue(), "Second compile should report unchanged"
            print("CorporateSpineCompiler --test passed.")
        sys.exit(0)

    elif args.compile:
        _compiler = CorporateSpineCompiler()
        sys.exit(0 if _compiler.compile_spine() else 1)

    else:
        parser.print_help()
        sys.exit(1)
