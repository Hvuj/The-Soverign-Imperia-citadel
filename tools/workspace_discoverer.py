#!/usr/bin/env python3
"""
Content-based workspace discoverer.

Scans from a start directory, identifies project roots by file-signature markers
(no hardcoded paths), detects languages and frameworks, and writes the result to
.claude/state/workspace-discovery.json.

Design constraints:
  - O(1)-bounded per directory: skip dirs that are noise (node_modules, .venv, etc.)
  - Framework scanning is capped to avoid reading thousands of files in large repos
  - All paths in output are absolute
"""


import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
DISCOVERY_OUTPUT = ROOT / ".claude" / "state" / "workspace-discovery.json"

_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
}

_MARKER_TO_LANGUAGE: dict[str, str] = {
    "pyproject.toml":   "python",
    "requirements.txt": "python",
    "setup.py":         "python",
    "setup.cfg":        "python",
    "package.json":     "typescript",
    "Cargo.toml":       "rust",
    "go.mod":           "go",
    "pom.xml":          "java",
    "build.gradle":     "java",
    ".git":             None,
}

_FRAMEWORK_KEYWORDS = ("orchestration", "schemaval", "configmodel", "parcompute", "fastapi", "flask", "django")
_FRAMEWORK_SCAN_LIMIT = 20


class WorkspaceDiscoverer:
    def __init__(self, start_dir: str = ".") -> None:
        self.start_dir = Path(start_dir).resolve()

    def discover_projects(self) -> list[dict[str, Any]]:
        discovered: list[dict[str, Any]] = []

        for dirpath, dirnames, filenames in os.walk(self.start_dir):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            current = Path(dirpath)

            languages: set[str] = set()
            for marker, lang in _MARKER_TO_LANGUAGE.items():
                if (current / marker).exists():
                    if lang:
                        languages.add(lang)

            if not languages and not (current / ".git").exists():
                continue

            frameworks: set[str] = set()
            py_files = [f for f in filenames if f.endswith(".py")]
            for fname in py_files[:_FRAMEWORK_SCAN_LIMIT]:
                try:
                    content = (current / fname).read_text(encoding="utf-8", errors="ignore")
                    for kw in _FRAMEWORK_KEYWORDS:
                        if kw in content:
                            frameworks.add(kw)
                except OSError:
                    pass

            discovered.append({
                "root_path": str(current),
                "languages": sorted(languages),
                "frameworks": sorted(frameworks),
                "build_system": "detected",
            })

        DISCOVERY_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        DISCOVERY_OUTPUT.write_text(
            json.dumps({"projects": discovered}, indent=2), encoding="utf-8"
        )
        return discovered


if __name__ == "__main__":
    discoverer = WorkspaceDiscoverer(start_dir=str(ROOT))
    results = discoverer.discover_projects()
    print(f"Discovery complete. Found {len(results)} project root(s) → {DISCOVERY_OUTPUT}")
    assert DISCOVERY_OUTPUT.exists(), "output file not written"
    data = json.loads(DISCOVERY_OUTPUT.read_text())
    assert "projects" in data
    print("smoke test: PASS")
    sys.exit(0)
