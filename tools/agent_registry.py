#!/usr/bin/env python3

import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
AGENTS = ROOT / ".claude" / "agents"
NAME_RE = re.compile(r"^name:\s*(.+)$", re.M)

for path in sorted(AGENTS.glob("*.md")):
    text = path.read_text(encoding="utf-8")
    match = NAME_RE.search(text)
    name = match.group(1).strip() if match else path.stem
    print(name)
