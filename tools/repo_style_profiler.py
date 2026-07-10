#!/usr/bin/env python3
"""repo_style_profiler.py — per-repo Python-version style profile (item 7).

Legion workers author code to each TARGET repo's own latest best-practice idioms,
not a single global assumption. For every repo discovered via workspace-discovery.json
(workspace_discoverer.py / build_workspace_intelligence_index.py), read its own
`requires-python` (pyproject.toml) or `.python-version`, and derive which modern
Python idioms that version unlocks.

Output: .claude/state/workspace-intelligence/style-profiles.json
  {"<repo_name>": {"py_version": "3.11", "source": "pyproject.toml:requires-python",
                    "idioms": [...]}}

Safety contract:
  never_call_claude: true
  never_edit_production_code: true — read-only probing of sibling repos.

CLI: (default: build once) | --json | --quiet
"""

import argparse
import json
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
STATE = ROOT / ".claude" / "state"
DISCOVERY_PATH = STATE / "workspace-discovery.json"
OUTPUT_PATH = STATE / "workspace-intelligence" / "style-profiles.json"

_REQUIRES_PYTHON_RE = re.compile(r'requires-python\s*=\s*"([^"]+)"')
_VERSION_RE = re.compile(r"(\d+)\.(\d+)")

_IDIOMS_FROM = {
    (3, 8): ["walrus operator (:=)", "f-string = debugging (f'{x=}')"],
    (3, 9): ["PEP 585 builtin generics: list[str]/dict[str,int], not typing.List/Dict"],
    (3, 10): ["PEP 604 unions: X | Y, not typing.Union/Optional", "structural pattern matching (match/case)"],
    (3, 11): ["typing.Self for fluent/classmethod returns", "except* for exception groups"],
    (3, 12): ["PEP 695 generic syntax (type Alias = ...)", "from __future__ import annotations is redundant"],
}


def _parse_version_tuple(spec: str) -> tuple[int, int] | None:
    m = _VERSION_RE.search(spec)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _idioms_for(version: tuple[int, int] | None) -> list[str]:
    if version is None:
        return []
    idioms: list[str] = []
    for min_version in sorted(_IDIOMS_FROM):
        if version >= min_version:
            idioms.extend(_IDIOMS_FROM[min_version])
    return idioms


def profile_repo(repo_path: Path) -> dict:
    py_version: str | None = None
    source: str | None = None

    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        m = _REQUIRES_PYTHON_RE.search(text)
        if m:
            py_version = m.group(1)
            source = "pyproject.toml:requires-python"

    if py_version is None:
        version_file = repo_path / ".python-version"
        if version_file.exists():
            try:
                py_version = version_file.read_text(encoding="utf-8").strip()
                source = ".python-version"
            except OSError:
                pass

    return {
        "py_version": py_version,
        "source": source,
        "idioms": _idioms_for(_parse_version_tuple(py_version) if py_version else None),
    }


def load_discovered_repos() -> list[dict]:
    try:
        data = json.loads(DISCOVERY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [p for p in data.get("projects", []) if p.get("root_path")]


def build_profiles() -> dict[str, dict]:
    profiles: dict[str, dict] = {}
    for proj in load_discovered_repos():
        repo_path = Path(proj["root_path"])
        if not repo_path.is_dir():
            continue
        profiles[repo_path.name] = profile_repo(repo_path)
    return profiles


def write_profiles(profiles: dict[str, dict]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(profiles, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Per-repo Python-version style profiler.")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    profiles = build_profiles()
    write_profiles(profiles)

    if args.as_json:
        print(json.dumps(profiles, indent=2, sort_keys=True))
    elif not args.quiet:
        rel = OUTPUT_PATH.relative_to(ROOT)
        print(f"repo_style_profiler: wrote {len(profiles)} repo profile(s) -> {rel}")


if __name__ == "__main__":
    main()
