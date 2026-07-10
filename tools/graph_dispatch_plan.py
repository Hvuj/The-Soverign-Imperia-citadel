#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
SCHEDULER = ROOT / "tools" / "brain_task_scheduler.py"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="+")
    args = parser.parse_args()

    cmd = [sys.executable, str(SCHEDULER), *args.task, "--json"]
    data = json.loads(subprocess.check_output(cmd, cwd=ROOT, text=True))

    print("# Dispatch Plan")
    print("## Standard/deep workers")
    for q in data["queue"]:
        print(f"- {q['worker']}: {q['budget']} ({q['shard']})")
    print("## Micro workers")
    for a in data["micro_agents"]:
        print(f"- {a}: micro")
    print("## Expected agents")
    print(len(data["expected_agents"]))


if __name__ == "__main__":
    main()
