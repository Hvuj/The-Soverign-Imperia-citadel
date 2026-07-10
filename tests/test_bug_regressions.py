"""Regression test for the legion_companies CLI arg bug.

B2: `citadel companies <file>` passed --file but legion_companies.py read positional sys.argv[1]
    → analyzed a file named "--file" → every score 1.0.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def test_companies_cli_scores_the_named_file(tmp_path):
    """B2: --file must actually score that file (not analyze a file called '--file' → all 1.0)."""
    messy = tmp_path / "messy.py"
    body = "".join(f"    if x == {i}:\n        x += 1\n" for i in range(12))
    messy.write_text(f"def f(x):\n{body}    return x\n", encoding="utf-8")
    (tmp_path / ".claude" / "state").mkdir(parents=True)

    env = {**os.environ, "CITADEL_WORKSPACE": str(tmp_path)}
    tool = TOOLS / "legion_companies.py"
    r = subprocess.run(
        [sys.executable, str(tool), "--file", str(messy), "--task-id", "t1", "--json"],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=30,
    )
    out = json.loads(r.stdout)
    assert out["task_id"] == "t1"
    assert out["companies"]["simplicity"] < 1.0  # the messy file must not score a perfect 1.0
