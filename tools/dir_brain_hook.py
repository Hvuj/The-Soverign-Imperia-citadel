#!/usr/bin/env python3

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parents[1]))
STATE = ROOT / ".claude" / "state"
LOG = STATE / "directory-access-log.ndjson"
INDEX_JSON = ROOT / "docs" / "brain" / "directories" / "index.json"
MAPPER = ROOT / "tools" / "dir_brain_mapper.py"

IGNORE_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules", ".claude/state"}
PATH_RE = re.compile(r"((?:[A-Za-z]:[\\/]|/(?:Users|home)/)[^\\s'\"`]+|\\./[^\\s'\"`]+|[A-Za-z0-9_./-]+\\.(?:py|md|yaml|yml|json|toml|sql))")


def load_input() -> dict:
    raw = sys.stdin.read()
    try:
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {"raw": raw}


def extract_paths(payload: dict) -> list[Path]:
    text = json.dumps(payload)
    paths = []
    for m in PATH_RE.findall(text):
        if m.startswith("/"):
            p = Path(m)
        else:
            p = (ROOT / m).resolve()
        if p.exists():
            if p.is_file():
                p = p.parent
            paths.append(p)
    seen = set()
    out = []
    for p in paths:
        s = str(p.resolve())
        if s not in seen:
            seen.add(s)
            out.append(p.resolve())
    return out[:5]


def is_ignored(p: Path) -> bool:
    return bool(set(p.parts) & IGNORE_PARTS)


def mapped_paths() -> set[str]:
    if not INDEX_JSON.exists():
        return set()
    try:
        data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {d.get("path") for d in data.get("directories", [])}


def main() -> None:
    payload = load_input()
    STATE.mkdir(parents=True, exist_ok=True)
    paths = [p for p in extract_paths(payload) if not is_ignored(p)]
    mapped = mapped_paths()
    events = []

    for p in paths:
        now = datetime.now(UTC).isoformat()
        event = {"ts": now, "path": str(p), "mapped_before": str(p) in mapped}
        if str(p) not in mapped and MAPPER.exists():
            try:
                subprocess.run(
                    [sys.executable, str(MAPPER), str(p), "--max-depth", "2", "--max-files", "80", "--auto-hook"],
                    cwd=ROOT,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                )
                event["auto_mapped"] = True
            except Exception as exc:
                event["auto_mapped"] = False
                event["error"] = str(exc)[:200]
        events.append(event)

    with LOG.open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, sort_keys=True) + "\n")

    print("{}")


if __name__ == "__main__":
    main()
