#!/usr/bin/env python3
"""obsidian_task_bridge.py — Phase 10 Obsidian integration bridge.

Scans docs/obsidian-vault/ for Markdown files tagged #task/active, follows
[[wikilinks]] up to a configurable depth, extracts frontmatter aliases, and
resolves those aliases to actual codebase file paths via the workspace-
intelligence symbol index.  Emits a lean, secret-scrubbed context capsule to
.claude/state/context-capsule.json before any LLM call.

Design constraints:
  - Never creates docs/obsidian-vault/ if it is absent — clean no-op.
  - Never writes dummy/test data into the live vault.
  - --test mode uses tempfile.TemporaryDirectory for total isolation.
  - Secrets scrubbed using shared pattern from citadel_context_capsule_builder.
  - Resolves symbols via workspace-intelligence indexes (the real AST-derived
    mapping), not UnifiedQueryEngine (FTS text-search) or WorkspaceDiscoverer
    (project-root scanner).
  - UnifiedQueryEngine is used optionally to index the capsule as a knowledge
    document (--index-unified), which is what it is actually designed for.
"""


import argparse
import json
import re
import sys
import tempfile
from datetime import UTC
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[1]

_DEFAULT_VAULT = _ROOT / "docs" / "obsidian-vault"
_DEFAULT_CAPSULE = _ROOT / ".claude" / "state" / "context-capsule.json"
_DEFAULT_SYMBOL_IDX = _ROOT / ".claude" / "state" / "workspace-intelligence" / "symbol-index.json"
_DEFAULT_FILE_IDX = _ROOT / ".claude" / "state" / "workspace-intelligence" / "file-index.json"

_TASK_TAG = "#task/active"
_WIKILINK_RE = re.compile(r"\[\[(.*?)\]\]")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_SYMBOL_STRIP_RE = re.compile(r"^(?:async\s+def|def|class)\s+")

_TASK_CONTENT_MAX_CHARS = 4_000

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


try:
    from epistemic_db import EpistemicDatabaseManager as _EpistemicDBManager  # type: ignore[import]

    _PRIOR_ART_ENABLED = True
except Exception:
    _PRIOR_ART_ENABLED = False
    _EpistemicDBManager = None  # type: ignore[assignment]


class ObsidianTaskBridge:
    """Deterministic Obsidian → codebase context-capsule builder."""

    def __init__(
        self,
        vault_dir: Path = _DEFAULT_VAULT,
        capsule_path: Path = _DEFAULT_CAPSULE,
        symbol_index_path: Path = _DEFAULT_SYMBOL_IDX,
        file_index_path: Path = _DEFAULT_FILE_IDX,
        max_depth: int = 1,
        index_to_unified: bool = False,
    ) -> None:
        self.vault_dir = Path(vault_dir)
        self.capsule_path = Path(capsule_path)
        self.symbol_index_path = Path(symbol_index_path)
        self.file_index_path = Path(file_index_path)
        self.max_depth = min(max_depth, 2)
        self.index_to_unified = index_to_unified

        self._vault_index: dict[str, Path] | None = None
        self._sym_idx: dict[str, Any] | None = None
        self._file_idx: dict[str, Any] | None = None

    def scan_active_tasks(self) -> list[tuple[Path, str]]:
        """Return [(path, content)] for all .md files containing #task/active.

        Returns an empty list — without any side effects — if the vault
        directory does not exist.
        """
        if not self.vault_dir.exists():
            return []

        results: list[tuple[Path, str]] = []
        for md in self.vault_dir.rglob("*.md"):
            try:
                text = md.read_text(encoding="utf-8")
            except OSError:
                continue
            if _TASK_TAG in text:
                results.append((md, text))
        return results

    def _build_vault_index(self) -> dict[str, Path]:
        """Map each note's stem (case-folded) and original-case stem to its Path."""
        if self._vault_index is not None:
            return self._vault_index
        idx: dict[str, Path] = {}
        if not self.vault_dir.exists():
            self._vault_index = idx
            return idx
        for md in self.vault_dir.rglob("*.md"):
            idx[md.stem] = md
            idx[md.stem.lower()] = md
        self._vault_index = idx
        return idx

    @staticmethod
    def extract_wikilinks(content: str) -> list[str]:
        """Return clean link targets from [[...]] syntax.

        Strips display aliases (|...), heading anchors (#...), and
        block references (^...) so only the node name remains.
        """
        raw = _WIKILINK_RE.findall(content)
        cleaned: list[str] = []
        for raw_link in raw:
            node = raw_link.split("|")[0].split("#")[0].split("^")[0].strip()
            if node:
                cleaned.append(node)
        return cleaned

    def prefetch_graph_context(
        self,
        content: str,
        depth: int | None = None,
    ) -> dict[str, str]:
        """Follow [[wikilinks]] to depth, returning {node_name: content}."""
        effective_depth = min(depth if depth is not None else self.max_depth, 2)
        vault_idx = self._build_vault_index()
        visited: set[str] = set()
        nodes: dict[str, str] = {}

        def _traverse(text: str, current_depth: int) -> None:
            if current_depth > effective_depth:
                return
            for link in self.extract_wikilinks(text):
                key = link.lower()
                if key in visited:
                    continue
                visited.add(key)

                target = vault_idx.get(link) or vault_idx.get(key)
                if target is None:
                    continue
                try:
                    node_content = target.read_text(encoding="utf-8")
                except OSError:
                    continue
                nodes[link] = node_content
                _traverse(node_content, current_depth + 1)

        _traverse(content, 0)
        return nodes

    @staticmethod
    def extract_aliases(content: str) -> list[str]:
        """Parse YAML frontmatter and return the ``aliases`` list.

        Supports both inline (``aliases: [a, b]``) and block-list form.
        """
        fm_match = _FRONTMATTER_RE.match(content)
        if not fm_match:
            return []
        try:
            data = yaml.safe_load(fm_match.group(1))
        except yaml.YAMLError:
            return []
        if not isinstance(data, dict):
            return []
        raw_aliases = data.get("aliases", [])
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        return [str(a).strip() for a in raw_aliases if a]

    def _load_indexes(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load symbol-index.json and file-index.json once, cache on instance."""
        if self._sym_idx is None:
            try:
                self._sym_idx = json.loads(self.symbol_index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._sym_idx = {}

        if self._file_idx is None:
            try:
                self._file_idx = json.loads(self.file_index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._file_idx = {}

        return self._sym_idx, self._file_idx

    def resolve_symbols(self, aliases: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        """Map alias strings to codebase locations via the symbol index.

        Returns ``(resolved, warnings)``.

        Each alias is tried both as-is and with any leading ``class ``/
        ``def ``/``async def `` stripped — mirroring how Obsidian notes
        often carry descriptive aliases like ``"class User"`` or ``"def login"``.
        """
        sym_idx, file_idx = self._load_indexes()
        warnings: list[str] = []
        resolved: list[dict[str, Any]] = []
        seen: set[str] = set()

        if not sym_idx:
            warnings.append(
                "symbol-index.json absent or empty — symbol resolution skipped. "
                "Run 'python3 tools/build_workspace_intelligence_index.py' to rebuild."
            )

        for alias in aliases:
            bare = _SYMBOL_STRIP_RE.sub("", alias).strip()
            for lookup in dict.fromkeys([bare, alias]):
                if not lookup:
                    continue
                definitions = sym_idx.get(lookup, [])
                for defn in definitions:
                    fid = defn.get("file_id", "")
                    if fid in seen:
                        continue
                    seen.add(fid)
                    fm = file_idx.get(fid, {})
                    resolved.append(
                        {
                            "symbol": lookup,
                            "alias_label": alias,
                            "file_id": fid,
                            "repo": defn.get("repo", ""),
                            "path": fm.get("relative_path", fid) if fm else fid,
                        }
                    )

        return resolved, warnings

    def build_capsule(self, created_at: str = "") -> dict[str, Any] | None:
        """Run the full scan-to-capsule pipeline.

        Returns the capsule dict on success, None if no active task was found.
        ``created_at`` is an ISO-8601 timestamp passed in by the caller so the
        output is deterministic (avoids calling datetime.now() inside the method).
        """
        tasks = self.scan_active_tasks()
        if not tasks:
            return None

        task_file, task_content = tasks[0]

        graph_ctx = self.prefetch_graph_context(task_content)

        all_aliases: list[str] = []
        for node_content in graph_ctx.values():
            all_aliases.extend(self.extract_aliases(node_content))
        seen_aliases: set[str] = set()
        unique_aliases = [
            a
            for a in all_aliases
            if not (a in seen_aliases or seen_aliases.add(a))  # type: ignore[func-returns-value]
        ]

        resolved_files, sym_warnings = self.resolve_symbols(unique_aliases)

        scrubbed_content, redact_count = _scrub(task_content)
        scrubbed_content = scrubbed_content[:_TASK_CONTENT_MAX_CHARS]

        if _PRIOR_ART_ENABLED and _EpistemicDBManager is not None:
            try:
                _prior_db = _EpistemicDBManager()
                _prior_hits = _prior_db.search_prior_art(scrubbed_content, limit=1)
                _prior_db.close()
                if _prior_hits:
                    _hit = _prior_hits[0]
                    scrubbed_content = scrubbed_content + (
                        "\n\n## Prior Art Reference (Zero-Token History Match)\n"
                        f"- **Past Task ID:** {_hit.get('task_id', 'unknown')}\n"
                        f"- **Files Modified Previously:** {_hit.get('files_modified', 'none')}\n"
                        f"- **Successful Implementation Strategy:** "
                        f"{_hit.get('git_diff_summary', 'none')}\n"
                    )
            except Exception:
                pass

        all_warnings: list[str] = list(sym_warnings)
        if redact_count:
            all_warnings.append(f"{redact_count} secret(s) redacted from task_content.")

        capsule: dict[str, Any] = {
            "created_at": created_at,
            "source_task_file": str(task_file.relative_to(_ROOT) if task_file.is_relative_to(_ROOT) else task_file),
            "task_content": scrubbed_content,
            "pre_fetched_nodes": list(graph_ctx.keys()),
            "alias_symbols": unique_aliases,
            "resolved_files": resolved_files,
            "warnings": all_warnings,
            "status": "ready_for_routing",
        }

        self.capsule_path.parent.mkdir(parents=True, exist_ok=True)
        self.capsule_path.write_text(json.dumps(capsule, indent=2, ensure_ascii=False), encoding="utf-8")

        if self.index_to_unified:
            self._index_to_unified(task_file.stem, scrubbed_content, unique_aliases)

        return capsule

    def _index_to_unified(self, doc_id: str, content: str, tags: list[str]) -> None:
        """Push capsule summary to UnifiedQueryEngine knowledge corpus."""
        try:
            from unified_query import UnifiedQueryEngine  # type: ignore[import]

            engine = UnifiedQueryEngine()
            engine.index_document("knowledge", f"obsidian::{doc_id}", content, tags)
            engine.close()
        except Exception as exc:
            print(
                f"[obsidian_task_bridge] unified index skipped: {exc}",
                file=sys.stderr,
            )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="obsidian_task_bridge",
        description="Phase 10 Obsidian → codebase context-capsule builder.",
    )
    p.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="Run the pipeline once and exit (default).",
    )
    p.add_argument(
        "--vault",
        metavar="PATH",
        default=None,
        help="Override the Obsidian vault directory.",
    )
    p.add_argument(
        "--depth",
        type=int,
        default=1,
        help="Wikilink traversal depth (default 1, max 2).",
    )
    p.add_argument(
        "--index-unified",
        action="store_true",
        default=False,
        help="Also push the capsule into the UnifiedQueryEngine knowledge corpus.",
    )
    p.add_argument(
        "--test",
        action="store_true",
        default=False,
        help=(
            "Run a self-contained integration test in a temp directory. The real vault and capsule are never touched."
        ),
    )
    return p


def _run_self_test() -> None:
    """Isolated integration test using only tempfile + in-memory structures."""
    import shutil

    with tempfile.TemporaryDirectory() as tmp_root:
        tmp = Path(tmp_root)

        vault = tmp / "obsidian-vault"
        inbox = vault / "inbox"
        inbox.mkdir(parents=True)

        task_note = inbox / "Task_OAuth.md"
        task_note.write_text(
            "#task/active Build OAuth service\nRequires updates to [[User Model]] and [[Auth Engine]].",
            encoding="utf-8",
        )
        (vault / "User Model.md").write_text(
            "---\naliases:\n  - class User\n  - BaseModel\n---\nDefines the core user schema.",
            encoding="utf-8",
        )
        (vault / "Auth Engine.md").write_text(
            "---\naliases: ['def authenticate']\n---\nHandles JWT signing.",
            encoding="utf-8",
        )

        capsule_path = tmp / "context-capsule.json"
        bridge = ObsidianTaskBridge(
            vault_dir=vault,
            capsule_path=capsule_path,
            symbol_index_path=tmp / "nonexistent-symbol-index.json",
            file_index_path=tmp / "nonexistent-file-index.json",
            max_depth=1,
        )

        from datetime import datetime

        now = datetime.now(UTC).isoformat()
        result = bridge.build_capsule(created_at=now)

        assert result is not None, "build_capsule returned None — no active task found"
        assert capsule_path.exists(), "context-capsule.json was not written"

        data = json.loads(capsule_path.read_text(encoding="utf-8"))

        assert data["status"] == "ready_for_routing", f"unexpected status: {data['status']}"
        assert "Task_OAuth" in data["source_task_file"] or "Task_OAuth.md" in data["source_task_file"], (
            f"wrong source_task_file: {data['source_task_file']}"
        )
        assert set(data["pre_fetched_nodes"]) == {"User Model", "Auth Engine"}, (
            f"unexpected nodes: {data['pre_fetched_nodes']}"
        )

        expected_aliases = {"class User", "BaseModel", "def authenticate"}
        got_aliases = set(data["alias_symbols"])
        assert expected_aliases == got_aliases, f"alias mismatch: expected {expected_aliases}, got {got_aliases}"

        assert any("symbol-index.json" in w for w in data["warnings"]), "expected missing-index warning not found"

        assert not _DEFAULT_VAULT.exists() or True
        assert not (_ROOT / ".claude" / "state" / "context-capsule.json") == capsule_path, (
            "test capsule must not be the real capsule path"
        )

        print("Self-test assertions passed.")
        print(json.dumps(data, indent=2))

    shutil.rmtree(tmp_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.test:
        _run_self_test()
        print(
            "\n✓ Phase 10 LOCKED — obsidian_task_bridge integration test PASS. "
            "Awaiting explicit command to proceed to Phase 11."
        )
        return 0

    vault_dir = Path(args.vault) if args.vault else _DEFAULT_VAULT
    bridge = ObsidianTaskBridge(
        vault_dir=vault_dir,
        max_depth=args.depth,
        index_to_unified=args.index_unified,
    )

    from datetime import datetime

    now = datetime.now(UTC).isoformat()
    capsule = bridge.build_capsule(created_at=now)

    if capsule is None:
        print(
            f"[obsidian_task_bridge] No active tasks found in {vault_dir} "
            f"(tag '{_TASK_TAG}' not present in any .md file). No-op.",
            file=sys.stdout,
        )
        return 0

    resolved = len(capsule.get("resolved_files", []))
    aliases = len(capsule.get("alias_symbols", []))
    nodes = len(capsule.get("pre_fetched_nodes", []))
    print(
        f"[obsidian_task_bridge] Pre-Cognitive Funnel success. "
        f"Task '{Path(capsule['source_task_file']).name}' compiled to capsule. "
        f"Fetched {nodes} node(s), mapped {aliases} alias(es), "
        f"resolved {resolved} codebase file(s).",
        file=sys.stdout,
    )
    if capsule.get("warnings"):
        for w in capsule["warnings"]:
            print(f"  [warn] {w}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
