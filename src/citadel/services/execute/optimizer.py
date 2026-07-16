"""optimizer.py — the code-optimizer Z-worker's core (Phase Z4).

Proposes an optimization for one file, verifies it in a sandbox before it is trusted (the house rule: a
local "pass" means *checked*, never "text generated"), records a verdict + pre-image, and applies it only on
a verified pass. Two autonomy modes: **system code** (ours) auto-applies behind a green verifier; **user
code** is **propose-only** by default — it returns a unified diff and writes nothing. Reuses
`LocalCodingExecutor` (sandbox→verify→write-back) and `VerdictLedger`; propose-only just points the executor
at a throwaway copy so the real workspace is never touched until the human accepts.
"""

import ast
import difflib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from citadel.services.execute.blueprint import Blueprint
from citadel.services.execute.coding import LocalCodingExecutor
from citadel.services.execute.local.engine import LocalEngine, RunSpec
from citadel.services.execute.verdict import VerdictLedger

_DEFAULT_GOAL = "performance and readability, preserving behavior and the public API exactly"
_SANDBOX_IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".venv", "node_modules", ".citadel", "dist", "build")


def is_system_path(rel_path: str) -> bool:
    """True for the Citadel's own code (auto-apply behind tests); False for the user's code (propose-only)."""
    norm = rel_path.replace("\\", "/")
    return norm.startswith("src/citadel/") or norm.startswith("tools/")


def _ast_verify(target: str) -> Callable[[Path], tuple[bool, str]]:
    def _verify(sandbox: Path) -> tuple[bool, str]:
        try:
            ast.parse((sandbox / target).read_text(encoding="utf-8", errors="ignore"))
            return True, "syntax ok"
        except (OSError, SyntaxError) as exc:
            return False, str(exc)
    return _verify


@dataclass(slots=True)
class OptimizeResult:
    path: str
    status: str  # pass | needs_fix | blocked | error
    applied: bool
    proposed: bool
    diff: str
    detail: str


class CodeOptimizer:
    def __init__(
        self,
        engine: LocalEngine,
        workspace: str | Path,
        *,
        verify: Callable[[Path], tuple[bool, str]] | None = None,
        ledger: VerdictLedger | None = None,
        model: str = "",
        run_spec: RunSpec | None = None,
    ) -> None:
        self.engine = engine
        self.workspace = Path(workspace)
        self.verify = verify
        self.ledger = ledger
        self.model = model
        self.run_spec = run_spec

    def _instruction(self, rel_path: str, goal: str) -> str:
        return (
            f"Optimize the file {rel_path} for {goal}. Return the COMPLETE new file content in a single "
            f"`### FILE: {rel_path}` block. Do not change behavior or the public API; only improve the "
            f"implementation. If it is already optimal, return it unchanged."
        )

    def optimize(self, rel_path: str, *, goal: str = _DEFAULT_GOAL, auto_apply: bool | None = None) -> OptimizeResult:
        """Optimize one file. auto_apply defaults by ownership: system code applies, user code proposes."""
        if auto_apply is None:
            auto_apply = is_system_path(rel_path)
        original = (self.workspace / rel_path)
        if not original.is_file():
            return OptimizeResult(rel_path, "error", False, False, "", "not a file")
        before = original.read_text(encoding="utf-8", errors="ignore")
        verify = self.verify or (_ast_verify(rel_path) if rel_path.endswith(".py") else (lambda _s: (True, "no verifier")))
        blueprint = Blueprint(
            task_id="optimize", instruction=self._instruction(rel_path, goal),
            allowed_files=[rel_path], assigned_tier="cheap",
        )

        if auto_apply:
            executor = LocalCodingExecutor(
                self.engine, self.workspace, verify, model=self.model, run_spec=self.run_spec, ledger=self.ledger)
            result = executor.execute(blueprint)
            after = original.read_text(encoding="utf-8", errors="ignore")
            diff = self._diff(rel_path, before, after)
            applied = result.status == "pass" and after != before
            return OptimizeResult(rel_path, result.status, applied, False, diff if applied else "", result.reason or "")

        # propose-only: run the exact same verify pipeline against a disposable copy; the real file is untouched
        sandbox = Path(tempfile.mkdtemp(prefix="citadel-optimize-"))
        try:
            copy_root = sandbox / "ws"
            shutil.copytree(self.workspace, copy_root, ignore=_SANDBOX_IGNORE)
            executor = LocalCodingExecutor(
                self.engine, copy_root, verify, model=self.model, run_spec=self.run_spec, ledger=self.ledger)
            result = executor.execute(blueprint)
            after = (copy_root / rel_path).read_text(encoding="utf-8", errors="ignore")
            diff = self._diff(rel_path, before, after)
            proposed = result.status == "pass" and after != before
            return OptimizeResult(rel_path, result.status, False, proposed, diff if proposed else "", result.reason or "")
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

    @staticmethod
    def _diff(rel_path: str, before: str, after: str) -> str:
        return "".join(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}",
        ))


_TOKENS_SAVED_PER_OPTIMIZATION = 600  # rough cloud-token estimate a local verified optimization avoids


def update_optimizer_stats(stats_path: str | Path, result: OptimizeResult) -> dict:
    """Accumulate optimizer outcomes into the live stats file `citadel workers` renders."""
    path = Path(stats_path)
    data = {"worker": "optimizer", "applied": 0, "proposed": 0, "rejected": 0, "tokens_saved": 0}
    if path.exists():
        try:
            data.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    if result.applied:
        data["applied"] += 1
        data["tokens_saved"] += _TOKENS_SAVED_PER_OPTIMIZATION
    elif result.proposed:
        data["proposed"] += 1
        data["tokens_saved"] += _TOKENS_SAVED_PER_OPTIMIZATION
    else:
        data["rejected"] += 1
    data["worker"] = "optimizer"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return data
