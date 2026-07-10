#!/usr/bin/env python3
"""Dryness Co. (DRY) — detects duplicate code blocks via sliding window hashing."""


import sys
from pathlib import Path

_WINDOW = 3
_MIN_BLOCK_LEN = 10


def analyze_file(file_path: str) -> float:
    path = Path(file_path)
    if not path.exists():
        return 1.0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) < _WINDOW:
            return 1.0

        seen: set[str] = set()
        duplicated = 0
        for i in range(len(lines) - _WINDOW + 1):
            block = "".join(lines[i : i + _WINDOW]).strip().replace(" ", "")
            if len(block) < _MIN_BLOCK_LEN:
                continue
            if block in seen:
                duplicated += 1
            else:
                seen.add(block)

        return max(0.0, min(1.0, 1.0 - duplicated / len(lines)))
    except Exception:
        return 0.5


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else __file__
    print(round(analyze_file(target), 4))
