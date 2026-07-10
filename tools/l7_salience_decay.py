#!/usr/bin/env python3
"""
L7 Salience Decay Daemon — Phase 12 Extended Epistemic Engine.

Background maintenance job: iterates the codemod registry and decays the
salience_weight of any entry untouched for more than 90 days by a configurable
decay factor (default 0.5). Prevents index bloat from stale codemods.

Entries without last_accessed_ts or salience_weight are skipped (safe no-op for
registries that pre-date this daemon).

Registry: .claude/brain/codemod-registry.json
"""


import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

CODEMOD_REGISTRY = _ROOT / ".claude" / "brain" / "codemod-registry.json"

_NINETY_DAYS_SEC: int = 90 * 24 * 60 * 60


class SalienceDecayDaemon:
    """Deterministic L7 daemon: decay stale knowledge-graph entries."""

    def __init__(
        self,
        decay_factor: float = 0.5,
        registry_path: Path | None = None,
    ) -> None:
        self.decay_factor = decay_factor
        self.registry_path: Path = registry_path or CODEMOD_REGISTRY
        self._current_time: int = int(time.time())

    def prune_knowledge_graph(self) -> int:
        """Decay salience weights for entries older than 90 days.

        Returns the number of entries decayed (0 means no-op / nothing stale).
        """
        if not self.registry_path.exists():
            return 0

        try:
            registry: dict = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"L7 Registry Read Error: {exc}", file=sys.stderr)
            return 0

        pruned_count = 0
        mutated = False

        for node_id, payload in registry.items():
            last_accessed: int = payload.get("last_accessed_ts", self._current_time)
            current_weight: float = payload.get("salience_weight", 1.0)

            age_sec = self._current_time - last_accessed
            if age_sec > _NINETY_DAYS_SEC and current_weight > 0.1:
                new_weight = round(current_weight * self.decay_factor, 2)
                payload["salience_weight"] = new_weight
                payload["last_accessed_ts"] = self._current_time
                print(f"L7 Decay: Node {node_id} decayed to {new_weight} weight.", file=sys.stdout)
                pruned_count += 1
                mutated = True

        if mutated:
            self.registry_path.write_text(
                json.dumps(registry, indent=2),
                encoding="utf-8",
            )

        return pruned_count


def main() -> None:
    parser = argparse.ArgumentParser(description="L7 Salience Decay Daemon")
    parser.add_argument("--test", action="store_true", help="Run in isolated testing mode")
    args = parser.parse_args()

    if args.test:
        with tempfile.TemporaryDirectory() as _tmp:
            test_registry = Path(_tmp) / "codemod-registry.json"

            stale_time = int(time.time()) - (100 * 24 * 60 * 60)
            mock_data = {
                "cmd_mock1": {
                    "salience_weight": 1.0,
                    "last_accessed_ts": stale_time,
                }
            }
            test_registry.write_text(json.dumps(mock_data, indent=2), encoding="utf-8")

            daemon = SalienceDecayDaemon(registry_path=test_registry)
            pruned = daemon.prune_knowledge_graph()

            result: dict = json.loads(test_registry.read_text(encoding="utf-8"))

        if pruned == 1 and result["cmd_mock1"]["salience_weight"] == 0.5:
            print("L7 Salience Decay Daemon (T0) Test Passed.")
            sys.exit(0)
        else:
            print("L7 Salience Decay Daemon (T0) Test Failed.", file=sys.stderr)
            sys.exit(1)
    else:
        pruned = SalienceDecayDaemon().prune_knowledge_graph()
        sys.exit(0 if pruned >= 0 else 1)


if __name__ == "__main__":
    main()
