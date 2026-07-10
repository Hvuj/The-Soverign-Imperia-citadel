#!/usr/bin/env python3
"""
4-axis bug fingerprinter with O(1) registry lookup.

Fingerprint axes:
  1. error_message_template  — normalized message (hex/UUID/int stripped) → SHA-256
  2. stack_signature         — workspace-agnostic file:function frames → SHA-256
  3. code_locus_signature    — AST node type + enclosing scope at error line
  4. ast_pattern_hash        — child AST type token stream → SHA-256

Registry: .claude/state/bug-registry.json  (keyed by bug_id)
Schema:   .claude/schemas/bug-record.schema.json
"""


import ast
import hashlib
import json
import re
import sys
import threading
import time
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[1] / ".claude" / "state" / "bug-registry.json"

_registry_lock = threading.Lock()

_MSG_CLEANER = re.compile(
    r"0x[a-fA-F0-9]+"
    r"|\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"
    r"|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
    r"|\b\d+\b"
)

_FRAME_RE = re.compile(r'File "([^"]+)", line \d+, in (\w+)')


class BugFingerprinter:
    def extract_message_hash(self, error_message: str) -> tuple[str, str]:
        normalized = _MSG_CLEANER.sub("<LITERAL>", error_message).strip()
        sha = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return normalized, sha

    def extract_stack_hash(self, traceback_str: str) -> str:
        frames = []
        for file_path, func_name in _FRAME_RE.findall(traceback_str):
            frames.append(f"{Path(file_path).name}:{func_name}")
        sig = "->".join(frames)
        return hashlib.sha256(sig.encode("utf-8")).hexdigest()

    def extract_locus_and_ast_hash(
        self, target_file_path: str, error_line: int
    ) -> tuple[str, str]:
        path = Path(target_file_path)
        if not path.exists():
            return "unknown_node:global", hashlib.sha256(b"empty").hexdigest()

        try:
            source = path.read_text(encoding="utf-8")
            root = ast.parse(source)
        except Exception:
            return "parse_error:global", hashlib.sha256(b"error").hexdigest()

        locus = "unknown:global"
        tokens: list[str] = []

        class _LocusWalker(ast.NodeVisitor):
            def __init__(self) -> None:
                self._scope: list[str] = ["global"]

            @property
            def _current_scope(self) -> str:
                return self._scope[-1]

            def _scoped(self, node: ast.AST, name: str) -> None:
                self._scope.append(name)
                self.generic_visit(node)
                self._scope.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._scoped(node, node.name)

            visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self._scoped(node, node.name)

            def generic_visit(self, node: ast.AST) -> None:
                lineno = getattr(node, "lineno", None)
                if lineno == error_line:
                    nonlocal locus, tokens
                    locus = f"{type(node).__name__}:{self._current_scope}"
                    tokens = [type(c).__name__ for c in ast.iter_child_nodes(node)]
                super().generic_visit(node)

        _LocusWalker().visit(root)
        ast_hash = hashlib.sha256("-".join(tokens).encode("utf-8")).hexdigest()
        return locus, ast_hash

    def process_failure(
        self,
        error_msg: str,
        traceback_str: str,
        file_path: str,
        line: int,
    ) -> str:
        template, msg_hash = self.extract_message_hash(error_msg)
        stack_hash = self.extract_stack_hash(traceback_str)
        locus, ast_hash = self.extract_locus_and_ast_hash(file_path, line)

        error_class = error_msg.split(":")[0].strip() if ":" in error_msg else "Exception"

        fingerprints: dict[str, str] = {
            "error_class": error_class,
            "error_message_template": template,
            "stack_signature": stack_hash,
            "code_locus_signature": locus,
            "ast_pattern_hash": ast_hash,
        }

        bug_id = f"bug_{hashlib.sha256((msg_hash + stack_hash).encode('utf-8')).hexdigest()[:12]}"

        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)

        with _registry_lock:
            registry: dict = {}
            if REGISTRY_PATH.exists():
                try:
                    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
                except Exception:
                    registry = {}

            now = int(time.time())
            if bug_id in registry:
                registry[bug_id]["occurrence_count"] += 1
                registry[bug_id]["last_seen"] = now
            else:
                registry[bug_id] = {
                    "bug_id": bug_id,
                    "first_seen": now,
                    "last_seen": now,
                    "occurrence_count": 1,
                    "fingerprints": fingerprints,
                    "status": "captured",
                }

            REGISTRY_PATH.write_text(
                json.dumps(registry, indent=2), encoding="utf-8"
            )

        return bug_id


if __name__ == "__main__":
    fp = BugFingerprinter()
    mock_tb = (
        'Traceback (most recent call last):\n'
        '  File "/home/user/project/auth.py", line 45, in check_session\n'
        '    token = session.get_token()\n'
        '  File "/home/user/project/models.py", line 12, in get_token\n'
        '    raise ValueError("token expired")\n'
        'ValueError: session 0x7f81a token expired at 1542000'
    )
    bid = fp.process_failure(
        "ValueError: session token expired",
        mock_tb,
        str(Path(__file__)),
        1,
    )
    print(f"bug_id : {bid}")
    assert bid.startswith("bug_") and len(bid) == 4 + 12, f"bad id: {bid!r}"
    assert REGISTRY_PATH.exists(), "registry not written"
    record = json.loads(REGISTRY_PATH.read_text())
    assert record[bid]["status"] == "captured"
    assert len(record[bid]["fingerprints"]["stack_signature"]) == 64
    assert len(record[bid]["fingerprints"]["ast_pattern_hash"]) == 64
    print("smoke test: PASS")
    sys.exit(0)
