#!/usr/bin/env python3

import argparse
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
AGENTS_DIR = ROOT / ".claude" / "agents"

# Agnostic: only generic system domains. Framework/data domain keywords are learned per workspace.
DOMAIN_KEYWORDS = {
    "validation": ["test", "validate", "reproducer", "regression"],
    "data_contract": ["schema", "dtype", "null", "contract", "validate"],
    "memory": ["memory", "what-worked", "what-did-not-work", "ai-context"],
    "graph": ["graph", "brain", "node", "dependency", "routing"],
}

WORKER_FOR_SHARD = {
    "graph_route": "brain-router",
    "dependency_map": "graph-dependency-mapper",
    "pattern_reuse": "pattern-reuse-router",
    "planning": "task-planner",
    "token_audit": "token-efficiency-auditor",
    "effort_gate": "effort-decider",
    "data_contract": "data-contract-validator",
    "validation": "test-validation-runner",
    "feature_learning": "feature-implementation-learner",
    "memory_update": "memory-curator",
    "memory_optimize": "memory-optimizer",
    "cache_audit": "cache-performance-auditor",
    "graph_maintain": "graph-maintainer",
    "reduce": "worker-result-reducer",
    "final_audit": "efficiency-auditor",
}


def discover_agents() -> list[str]:
    return sorted(p.stem for p in AGENTS_DIR.glob("*.md"))


def classify(text: str) -> set[str]:
    t = text.lower()
    found = set()
    for domain, words in DOMAIN_KEYWORDS.items():
        if any(w in t for w in words):
            found.add(domain)
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    task = " ".join(args.task)
    domains = classify(task)
    agents = discover_agents()

    shards = [
        "graph_route", "dependency_map", "pattern_reuse", "planning",
        "token_audit", "effort_gate"
    ]

    if "data_contract" in domains:
        shards.append("data_contract")
    if "validation" in domains or domains - {"memory", "graph"}:
        shards.append("validation")
    if "memory" in domains:
        shards.extend(["memory_update", "memory_optimize"])
    if "graph" in domains:
        shards.append("graph_maintain")

    shards.extend(["cache_audit", "reduce", "final_audit"])

    queue = []
    for i, shard in enumerate(dict.fromkeys(shards), start=1):
        worker = WORKER_FOR_SHARD[shard]
        budget = "standard"
        if shard in {"data_contract", "validation"} and shard.replace("_", " ") in task.lower():
            budget = "deep"
        queue.append({
            "id": f"q{i:02d}",
            "shard": shard,
            "worker": worker,
            "budget": budget,
            "depends_on": [] if i == 1 else [f"q{i-1:02d}"],
            "status": "pending",
        })

    micro_agents = [a for a in agents if a not in {q["worker"] for q in queue}]
    result = {
        "task": task,
        "domains": sorted(domains),
        "queue": queue,
        "micro_agents": micro_agents,
        "expected_agents": agents,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("# Brain Task Schedule")
        print(f"task: {task}")
        print(f"domains: {', '.join(sorted(domains)) or 'general'}")
        print("queue:")
        for q in queue:
            print(f"- {q['id']} {q['shard']} -> {q['worker']} ({q['budget']})")
        print("micro_agents:")
        for a in micro_agents:
            print(f"- {a}")


if __name__ == "__main__":
    main()
