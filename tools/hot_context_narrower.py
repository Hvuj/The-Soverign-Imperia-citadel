#!/usr/bin/env python3
"""
Hot Context Narrower — token optimizer via usage-pattern learning.

Analyzes which files were loaded into a context capsule but never accessed,
and writes per-task exclusion patterns to .claude/legion/routing-rules.json.
Future capsule builders read these rules to skip provably-useless files,
reducing input token cost before a prompt is ever sent.
"""


import json
import sys
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
ROUTING_RULES_PATH = _ROOT / ".claude" / "legion" / "routing-rules.json"

_lock = threading.Lock()

_UTILIZATION_THRESHOLD = 0.50
_HISTORY_MAX = 50


class HotContextNarrower:
    def optimize_task_capsule(
        self,
        task_type: str,
        loaded_files: list[str],
        accessed_files: list[str],
    ) -> bool:
        if not loaded_files:
            return False

        loaded_set  = set(loaded_files)
        accessed_set = set(accessed_files)
        wasted       = loaded_set - accessed_set
        utilization  = len(accessed_set) / len(loaded_set)

        with _lock:
            rules: dict = {}
            if ROUTING_RULES_PATH.exists():
                try:
                    rules = json.loads(ROUTING_RULES_PATH.read_text(encoding="utf-8"))
                except Exception:
                    rules = {}

            capsules: dict = rules.setdefault("capsules", {})
            capsule:  dict = capsules.setdefault(
                task_type,
                {"exclude_patterns": [], "utilization_history": []},
            )

            history: list = capsule["utilization_history"]
            history.append(round(utilization, 4))
            if len(history) > _HISTORY_MAX:
                capsule["utilization_history"] = history[-_HISTORY_MAX:]

            if utilization < _UTILIZATION_THRESHOLD and wasted:
                existing: set = set(capsule["exclude_patterns"])
                for fp in wasted:
                    ext = Path(fp).suffix
                    if ext:
                        pattern = f"*{ext}"
                        if pattern not in existing:
                            capsule["exclude_patterns"].append(pattern)
                            existing.add(pattern)

            ROUTING_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
            ROUTING_RULES_PATH.write_text(
                json.dumps(rules, indent=2), encoding="utf-8"
            )

        print(
            f"Capsule '{task_type}' optimized. "
            f"utilization={utilization:.0%}, "
            f"wasted={len(wasted)}/{len(loaded_set)} files."
        )
        return True


if __name__ == "__main__":
    narrower = HotContextNarrower()

    loaded   = ["src/main.py", "tests/test_main.py", "docs/api.md", "src/utils.py"]
    accessed = ["src/main.py"]

    ok = narrower.optimize_task_capsule("feature_implementation", loaded, accessed)
    assert ok, "optimization returned False"

    rules = json.loads(ROUTING_RULES_PATH.read_text())
    capsule = rules["capsules"]["feature_implementation"]
    assert capsule["utilization_history"] == [0.25]
    assert "*.md" in capsule["exclude_patterns"] or "*.py" in capsule["exclude_patterns"]
    assert len(capsule["utilization_history"]) == 1

    narrower.optimize_task_capsule("feature_implementation", ["a.py", "b.py"], ["a.py", "b.py"])
    rules2 = json.loads(ROUTING_RULES_PATH.read_text())
    assert 1.0 in rules2["capsules"]["feature_implementation"]["utilization_history"]

    print("smoke test: PASS")
    sys.exit(0)
