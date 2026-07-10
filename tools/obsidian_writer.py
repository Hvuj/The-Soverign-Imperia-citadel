#!/usr/bin/env python3
"""obsidian_writer.py — Phase 10.5 Obsidian write-back engine.

Deterministic, LLM-free tool that:
  1. Marks an active task complete (#task/active → #task/complete) and appends
     a resolution callout linking to the knowledge node.
  2. Generates a new graph-linked Obsidian markdown knowledge node in the vault
     inbox/, emitting brain-graph-compatible frontmatter so linked_concepts
     become real graph edges parseable by _brain_common.parse_frontmatter.

Design constraints (mirrors obsidian_task_bridge.py):
  - Never creates docs/obsidian-vault/ if it is absent — strict no-op.
  - Never writes dummy/test data into the live vault.
  - --test mode uses tempfile.TemporaryDirectory for total isolation.
  - Secrets scrubbed before any vault write using the shared pattern.
  - Timestamps injected at call boundaries for determinism.
  - Path anchored to repo root (not CWD).
"""

import argparse
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_VAULT = _ROOT / "docs" / "obsidian-vault"

_TASK_TAG_ACTIVE = "#task/active"
_TASK_TAG_COMPLETE = "#task/complete"
_TASK_ACTIVE_RE = re.compile(r"#task/active")

try:
    _tools_dir = str(Path(__file__).resolve().parent)
    if _tools_dir not in sys.path:
        sys.path.insert(0, _tools_dir)
    from citadel_context_capsule_builder import _SECRET_PATTERNS as _SHARED_SECRET_RE  # type: ignore[import]

    def _scrub(text: str) -> tuple[str, int]:
        scrubbed, count = _SHARED_SECRET_RE.subn("[REDACTED_SECRET]", text)
        return scrubbed, count

except Exception:
    _FALLBACK_SECRET_RE = re.compile(
        r"""(?:password|passwd|secret|api[_-]?key|private[_-]?key|token|credential
            |auth[_-]?token|ssh[_-]?key|access[_-]?key|client[_-]?secret|bearer
            |ANTHROPIC_API_KEY|AWS_SECRET|GOOGLE_API_KEY|OPENAI_API_KEY)
            \s*[:=]\s*\S+""",
        re.VERBOSE | re.IGNORECASE,
    )

    def _scrub(text: str) -> tuple[str, int]:  # type: ignore[misc]
        scrubbed, count = _FALLBACK_SECRET_RE.subn("[REDACTED_SECRET]", text)
        return scrubbed, count


def _slugify(text: str) -> str:
    """Convert a human-readable string to a kebab-case slug for graph node ids."""
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "unknown"


def _safe_filename(title: str) -> str:
    """Strip characters that are unsafe in most filesystems, preserve spaces."""
    return "".join(c for c in title if c.isalnum() or c in " -_").strip()


class ObsidianWriter:
    """Deterministic Obsidian vault write-back engine."""

    def __init__(self, vault_dir: Path | None = None) -> None:
        self.vault_dir = Path(vault_dir) if vault_dir is not None else _DEFAULT_VAULT
        self.inbox_dir = self.vault_dir / "inbox"

    def mark_task_complete(
        self,
        task_file_path: str,
        resolution_link: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Flip #task/active → #task/complete in an existing vault note.

        Optionally appends a callout block linking to a resolution knowledge node.
        Returns True on success, False on any no-op/error condition.
        """
        if not self.vault_dir.exists():
            print(
                f"[obsidian_writer] Vault absent at {self.vault_dir} — no-op.",
                file=sys.stderr,
            )
            return False

        target = Path(task_file_path)
        if not target.exists():
            print(
                f"[obsidian_writer] Write-Back Failed: task file {target} not found.",
                file=sys.stderr,
            )
            return False

        content = target.read_text(encoding="utf-8")
        if not _TASK_ACTIVE_RE.search(content):
            print(
                f"[obsidian_writer] Write-Back Warning: '{_TASK_TAG_ACTIVE}' tag not "
                f"found in {target.name} — no-op.",
                file=sys.stderr,
            )
            return False

        updated = _TASK_ACTIVE_RE.sub(_TASK_TAG_COMPLETE, content)

        if resolution_link:
            ts = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M")
            updated += (
                f"\n\n> [!success] Auto-Resolved on {ts}\n"
                f"> Resolution documented in: [[{resolution_link}]]\n"
            )

        scrubbed, _ = _scrub(updated)
        target.write_text(scrubbed, encoding="utf-8")
        print(
            f"[obsidian_writer] Task {target.name} successfully marked complete.",
            file=sys.stdout,
        )
        return True

    def generate_semantic_node(
        self,
        title: str,
        summary: str,
        linked_concepts: list[str],
        related_files: list[str],
        now: datetime | None = None,
    ) -> str | None:
        """Generate a graph-linked knowledge node in the vault inbox.

        Emits brain-graph-compatible frontmatter (id/title/type/tags/links/files)
        so linked_concepts become real graph edges parseable by
        _brain_common.parse_frontmatter.

        Returns the filesystem-safe title (usable as display link in [[...]])
        or None if the vault root is absent.
        """
        if not self.vault_dir.exists():
            print(
                f"[obsidian_writer] Vault absent at {self.vault_dir} — no-op.",
                file=sys.stderr,
            )
            return None

        self.inbox_dir.mkdir(parents=True, exist_ok=True)

        safe_title = _safe_filename(title)
        node_id = _slugify(title)
        link_slugs = [_slugify(c) for c in linked_concepts]
        ts = (now or datetime.now(UTC)).isoformat()

        if link_slugs:
            links_line = f"links: [{', '.join(link_slugs)}]"
        else:
            links_line = "links: []"

        if related_files:
            files_block = "files:\n" + "\n".join(f"  - {f}" for f in related_files)
        else:
            files_block = "files:"

        frontmatter = (
            f"---\n"
            f"id: {node_id}\n"
            f"title: {safe_title}\n"
            f"type: knowledge\n"
            f"tags: [knowledge]\n"
            f"{links_line}\n"
            f"{files_block}\n"
            f"---"
        )

        scrubbed_summary, _ = _scrub(summary)

        body_lines: list[str] = [
            f"# {safe_title}",
            "",
            "## Summary",
            scrubbed_summary,
            "",
            "## Graph Connections",
        ]
        if linked_concepts:
            for concept in linked_concepts:
                body_lines.append(f"- [[{concept}]]")
        else:
            body_lines.append("- *No explicit structural graph links detected.*")

        body_lines += ["", "## Modified Codebase Boundaries"]
        if related_files:
            for f in related_files:
                body_lines.append(f"- `{f}`")
        else:
            body_lines.append("- *No files modified.*")

        body_lines += ["", f"*Auto-generated: {ts}*"]

        content = frontmatter + "\n\n" + "\n".join(body_lines) + "\n"
        target_path = self.inbox_dir / f"{safe_title}.md"
        target_path.write_text(content, encoding="utf-8")

        print(
            f"[obsidian_writer] Semantic Node '[[{safe_title}]]' generated in "
            f"{self.inbox_dir.relative_to(self.vault_dir)}.",
            file=sys.stdout,
        )
        return safe_title


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="obsidian_writer",
        description="Phase 10.5 Obsidian write-back engine.",
    )
    p.add_argument(
        "--vault",
        metavar="PATH",
        default=None,
        help="Override the Obsidian vault directory (default: docs/obsidian-vault).",
    )
    p.add_argument(
        "--test",
        action="store_true",
        default=False,
        help=(
            "Run a self-contained integration test in a temp directory. "
            "The real vault is never touched."
        ),
    )

    sub = p.add_subparsers(dest="command")

    mc = sub.add_parser("mark-complete", help="Mark a #task/active note complete.")
    mc.add_argument("--task", required=True, metavar="PATH", help="Path to the task note.")
    mc.add_argument(
        "--resolution",
        default=None,
        metavar="LINK",
        help="Title of the resolution knowledge node to append as a [[link]].",
    )

    gn = sub.add_parser("gen-node", help="Generate a semantic knowledge node in the inbox.")
    gn.add_argument("--title", required=True, help="Human-readable node title.")
    gn.add_argument("--summary", required=True, help="One-paragraph architectural summary.")
    gn.add_argument(
        "--concept",
        dest="concepts",
        action="append",
        default=[],
        metavar="CONCEPT",
        help="Linked concept (repeatable). e.g. --concept 'Obsidian Control Plane'",
    )
    gn.add_argument(
        "--file",
        dest="files",
        action="append",
        default=[],
        metavar="FILE",
        help="Related codebase file path (repeatable). e.g. --file tools/obsidian_writer.py",
    )

    return p


def _run_self_test() -> None:
    """Isolated integration test using only tempfile + in-memory structures.

    The real vault (docs/obsidian-vault/) is never created or touched.
    """
    with tempfile.TemporaryDirectory() as tmp_root:
        tmp = Path(tmp_root)

        vault = tmp / "obsidian-vault"
        vault.mkdir()

        writer = ObsidianWriter(vault_dir=vault)

        ts = datetime(2026, 6, 22, 12, 0, 0, tzinfo=UTC)

        node_title = writer.generate_semantic_node(
            title="Obsidian Write-Back Engine",
            summary="Implemented T0 Python daemon to auto-close tasks and build graph nodes.",
            linked_concepts=["Obsidian Control Plane", "Epistemic Engine"],
            related_files=["tools/obsidian_writer.py"],
            now=ts,
        )

        assert node_title == "Obsidian Write-Back Engine", (
            f"expected 'Obsidian Write-Back Engine', got {node_title!r}"
        )
        node_file = vault / "inbox" / "Obsidian Write-Back Engine.md"
        assert node_file.exists(), "node file was not created in inbox/"

        node_content = node_file.read_text(encoding="utf-8")
        assert "id: obsidian-write-back-engine" in node_content, "id field missing"
        assert "title: Obsidian Write-Back Engine" in node_content, "title field missing"
        assert "type: knowledge" in node_content, "type field missing"
        assert "tags: [knowledge]" in node_content, "tags field missing"
        assert "links: [obsidian-control-plane, epistemic-engine]" in node_content, (
            "links field missing or wrong"
        )
        assert "  - tools/obsidian_writer.py" in node_content, "files block missing"
        assert "[[Obsidian Control Plane]]" in node_content, "wikilink missing (Obsidian Control Plane)"
        assert "[[Epistemic Engine]]" in node_content, "wikilink missing (Epistemic Engine)"

        dummy_task = vault / "Task_Test.md"
        dummy_task.write_text(
            "#task/active Validate auto-writer.", encoding="utf-8"
        )

        result = writer.mark_task_complete(
            str(dummy_task), resolution_link=node_title, now=ts
        )
        assert result is True, "mark_task_complete returned False on happy path"

        final = dummy_task.read_text(encoding="utf-8")
        assert "#task/complete" in final, "#task/complete not present after mutation"
        assert "#task/active" not in final, "#task/active still present after mutation"
        assert "[[Obsidian Write-Back Engine]]" in final, "resolution link not appended"

        already_done = vault / "Done.md"
        already_done.write_text("#task/complete Already resolved.", encoding="utf-8")
        r2 = writer.mark_task_complete(str(already_done))
        assert r2 is False, "should return False when #task/active not found"

        r3 = writer.mark_task_complete(str(vault / "nonexistent.md"))
        assert r3 is False, "should return False for absent task file"

        absent_writer = ObsidianWriter(vault_dir=tmp / "does-not-exist")

        r4 = absent_writer.mark_task_complete(str(dummy_task))
        assert r4 is False, "mark_task_complete should return False when vault absent"

        r5 = absent_writer.generate_semantic_node(
            title="X", summary="x", linked_concepts=[], related_files=[]
        )
        assert r5 is None, "generate_semantic_node should return None when vault absent"
        assert not (tmp / "does-not-exist").exists(), (
            "absent vault must not be created by writer"
        )

        assert not _DEFAULT_VAULT.exists() or not (
            _DEFAULT_VAULT / "inbox" / "Obsidian Write-Back Engine.md"
        ).exists(), "real vault must not have been written during self-test"

    print("\n✓ Phase 10.5 LOCKED — obsidian_writer integration test PASS.")
    print("  Auto-Writer Pipeline Verified Successfully.")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.test:
        _run_self_test()
        return 0

    vault_dir = Path(args.vault) if args.vault else _DEFAULT_VAULT
    writer = ObsidianWriter(vault_dir=vault_dir)

    now = datetime.now(UTC)

    if args.command == "mark-complete":
        success = writer.mark_task_complete(
            args.task, resolution_link=args.resolution, now=now
        )
        return 0 if success else 1

    if args.command == "gen-node":
        result = writer.generate_semantic_node(
            title=args.title,
            summary=args.summary,
            linked_concepts=args.concepts,
            related_files=args.files,
            now=now,
        )
        return 0 if result is not None else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
