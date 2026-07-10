#!/usr/bin/env python3
"""
Codemod Promoter — bridges T2 (hosted LLM) one-time fixes to T1 deterministic codemods.

When Claude fixes a novel bug, this daemon:
  1. Reads the 4-axis fingerprint from bug-registry.json.
  2. Derives a stable codemod_id from the AST pattern hash.
  3. Writes a schema-conformant entry to codemod-registry.json.
  4. Stores the mutation_lambda in a sidecar codemod-mutations.json
     (mutation_lambda is not in the codemod schema; kept separate).
  5. Flips the bug status to "codemod_promoted".

Next time the same fingerprint appears, codemod_runner.py applies the fix
for 0 hosted-token cost.
"""


import hashlib
import json
import sys
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
BUG_REGISTRY       = _ROOT / ".claude" / "state"  / "bug-registry.json"
CODEMOD_REGISTRY   = _ROOT / ".claude" / "brain"  / "codemod-registry.json"
CODEMOD_MUTATIONS  = _ROOT / ".claude" / "brain"  / "codemod-mutations.json"

_lock = threading.Lock()


class CodemodPromoter:
    def __init__(self) -> None:
        CODEMOD_REGISTRY.parent.mkdir(parents=True, exist_ok=True)

    def promote_t2_fix_to_t1_codemod(
        self,
        bug_id: str,
        language: str,
        error_class: str,
        mutation_logic: str,
        source_task: str,
    ) -> bool:
        if not BUG_REGISTRY.exists():
            print("Promotion failed: bug registry missing.", file=sys.stderr)
            return False

        with _lock:
            bugs: dict = json.loads(BUG_REGISTRY.read_text(encoding="utf-8"))

            if bug_id not in bugs:
                print(f"Promotion failed: bug '{bug_id}' not in registry.", file=sys.stderr)
                return False

            bug = bugs[bug_id]
            fp = bug.get("fingerprints", {})
            ast_hash: str = fp.get("ast_pattern_hash", "")
            locus: str    = fp.get("code_locus_signature", "unknown")
            bug_class: str = fp.get("error_class", error_class)

            codemod_id = f"cmd_{hashlib.sha256(ast_hash.encode('utf-8')).hexdigest()[:8]}"

            registry: dict = {}
            if CODEMOD_REGISTRY.exists():
                try:
                    registry = json.loads(CODEMOD_REGISTRY.read_text(encoding="utf-8"))
                except Exception:
                    registry = {}

            registry[codemod_id] = {
                "codemod_id": codemod_id,
                "target_language": language,
                "error_classes": list({error_class, bug_class}),
                "precondition_ast": {
                    "required_pattern_hash": ast_hash,
                    "locus": locus,
                },
                "applied_count": 0,
                "success_count": 0,
                "rollback_count": 0,
                "status": "active",
                "registered_from_task": source_task,
            }
            CODEMOD_REGISTRY.write_text(
                json.dumps(registry, indent=2), encoding="utf-8"
            )

            mutations: dict = {}
            if CODEMOD_MUTATIONS.exists():
                try:
                    mutations = json.loads(CODEMOD_MUTATIONS.read_text(encoding="utf-8"))
                except Exception:
                    mutations = {}
            mutations[codemod_id] = mutation_logic
            CODEMOD_MUTATIONS.write_text(
                json.dumps(mutations, indent=2), encoding="utf-8"
            )

            bugs[bug_id]["status"] = "codemod_promoted"
            BUG_REGISTRY.write_text(json.dumps(bugs, indent=2), encoding="utf-8")

        print(
            f"Promoted: {codemod_id} ← bug {bug_id} "
            f"(future fixes cost 0 hosted tokens)."
        )
        return True


if __name__ == "__main__":
    promoter = CodemodPromoter()

    dummy_id = "bug_aabbccddeeff"
    dummy_registry = {
        dummy_id: {
            "bug_id": dummy_id,
            "first_seen": 1000000,
            "last_seen": 1000000,
            "occurrence_count": 1,
            "fingerprints": {
                "error_class": "KeyError",
                "error_message_template": "key not found",
                "stack_signature": "a" * 64,
                "code_locus_signature": "Subscript:get_value",
                "ast_pattern_hash": "b" * 64,
            },
            "status": "patch_testing",
        }
    }
    BUG_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    BUG_REGISTRY.write_text(json.dumps(dummy_registry, indent=2), encoding="utf-8")

    mutation = "output = source.replace('dict[key]', 'dict.get(key, None)')"
    ok = promoter.promote_t2_fix_to_t1_codemod(
        dummy_id, "python", "KeyError", mutation, "task_p8_smoke"
    )
    assert ok, "promotion failed"

    reg = json.loads(CODEMOD_REGISTRY.read_text())
    cid = f"cmd_{hashlib.sha256(('b' * 64).encode()).hexdigest()[:8]}"
    assert cid in reg, f"{cid} not in codemod registry"
    assert reg[cid]["status"] == "active"

    mut = json.loads(CODEMOD_MUTATIONS.read_text())
    assert cid in mut

    bugs = json.loads(BUG_REGISTRY.read_text())
    assert bugs[dummy_id]["status"] == "codemod_promoted"

    print("smoke test: PASS")
    sys.exit(0)
