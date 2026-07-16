"""Local coding executor — the piece that lets the local tier do REAL, VERIFIED work for free.

`LocalExecutor` only generates text; its `pass` means "the model answered". `LocalCodingExecutor` closes
that gap: it asks the local model for the complete new content of a target file, applies it to an isolated
sandbox copy of the workspace, runs a deterministic verification command (tests/lint — zero model tokens),
and reports `pass` — and writes the change back to the real workspace — ONLY when verification passes. An
unverified change never reaches the repo, so a `pass` here genuinely means the work is correct.
"""

import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor
from citadel.services.execute.local.engine import LocalEngine, RunSpec
from citadel.services.execute.verdict import FAIL, PASS, VerdictLedger, artifact_hash

_CODE_FENCE = re.compile(r"```(?:[a-zA-Z0-9_+-]*)\s*\n(.*?)```", re.S)
_SANDBOX_IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".venv", "node_modules", ".citadel", "dist", "build")


_FILE_BLOCK = re.compile(r"###\s*FILE:\s*(\S+)\s*\n```(?:[a-zA-Z0-9_+-]*)\s*\n(.*?)```", re.S)


def extract_code(text: str) -> str:
    """Return the first fenced code block, or the whole stripped text when there is no fence."""
    match = _CODE_FENCE.search(text or "")
    return match.group(1).strip() if match else (text or "").strip()


def extract_files(text: str, targets: list[str]) -> dict[str, str]:
    """Parse per-file content from the model output. `### FILE: <path>` blocks are keyed by path (restricted
    to `targets`); with no tags and a single target, the whole fenced block is that file's content."""
    allowed = set(targets)
    tagged = {path: body.strip() for path, body in _FILE_BLOCK.findall(text or "") if path in allowed}
    if tagged:
        return tagged
    if len(targets) == 1:
        code = extract_code(text)
        return {targets[0]: code} if code else {}
    return {}


def verify_by_command(command: list[str], timeout: float = 300.0) -> Callable[[Path], tuple[bool, str]]:
    """Build a verifier that runs `command` in the sandbox and passes iff it exits 0. Zero model tokens."""
    def _verify(sandbox: Path) -> tuple[bool, str]:
        try:
            proc = subprocess.run(command, cwd=str(sandbox), capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        return proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    return _verify


class LocalCodingExecutor(Executor):
    name = "local-coding"

    def __init__(
        self,
        engine: LocalEngine,
        workspace: str | Path,
        verify: Callable[[Path], tuple[bool, str]],
        *,
        model: str = "",
        run_spec: RunSpec | None = None,
        ledger: VerdictLedger | None = None,
    ) -> None:
        self._engine = engine
        self._ws = Path(workspace)
        self._verify = verify
        self._run_spec = run_spec or RunSpec(model=model, n_ctx=4096, max_tokens=1024)
        self._ledger = ledger

    def execute(self, blueprint: Blueprint) -> ExecutionResult:
        targets = list(blueprint.allowed_files)
        if not targets:
            return ExecutionResult(blueprint.task_id, "blocked", tier_used="local", reason="no_target_file")
        if not self._engine.available():
            return ExecutionResult(
                blueprint.task_id, "blocked", tier_used="local", reason=f"engine_unavailable:{self._engine.name}"
            )
        try:
            raw = self._engine.generate(self._build_prompt(blueprint, targets), self._run_spec)
        except Exception as exc:
            return ExecutionResult(blueprint.task_id, "error", tier_used="local", reason=str(exc))
        files = extract_files(raw, targets)
        missing = [t for t in targets if not files.get(t)]
        if missing:
            return ExecutionResult(
                blueprint.task_id, "needs_fix", tier_used="local",
                reason=f"incomplete_generation: missing {', '.join(missing)}",
            )
        if self._ledger is not None:
            condemned = next((p for p, c in files.items() if self._ledger.is_condemned(artifact_hash(c))), None)
            if condemned is not None:
                return ExecutionResult(
                    blueprint.task_id, "blocked", tier_used="local", reason=f"condemned:{condemned}"
                )
        ok, detail = self._apply_and_verify(files)
        if not ok:
            if self._ledger is not None:
                for content in files.values():
                    self._ledger.record(artifact_hash(content), FAIL)
            return ExecutionResult(
                blueprint.task_id, "needs_fix", tier_used="local", reason=f"verification_failed: {detail[:200]}"
            )
        for path, content in files.items():
            dest = self._ws / path
            if self._ledger is not None:
                self._ledger.backup(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            if self._ledger is not None:
                self._ledger.record(artifact_hash(content), PASS)
        return ExecutionResult(
            blueprint.task_id, "pass",
            output=f"applied+verified {len(files)} file(s): {', '.join(files)}", tier_used="local",
        )

    def _apply_and_verify(self, files: dict[str, str]) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp) / "ws"
            shutil.copytree(self._ws, sandbox, ignore=_SANDBOX_IGNORE)
            for path, content in files.items():
                dest = sandbox / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
            return self._verify(sandbox)

    def _build_prompt(self, blueprint: Blueprint, targets: list[str]) -> str:
        sections = []
        for target in targets:
            path = self._ws / target
            existing = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
            body = f"Current content:\n{existing}" if existing else f"{target} does not exist yet."
            sections.append(f"### FILE: {target}\n{body}")
        context = f"{blueprint.context}\n\n" if blueprint.context else ""
        return (
            f"{context}Task: {blueprint.instruction}\n\n"
            f"Files to write: {', '.join(targets)}\n\n"
            + "\n\n".join(sections)
            + "\n\nOutput the complete new content for EACH file, each in this exact form:\n"
            "### FILE: <path>\n```\n<full file content>\n```"
        )
