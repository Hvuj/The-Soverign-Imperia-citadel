"""corporate.py — the legion-as-corporate domain model.

The legion IS the corporate; each workspace repo is a Company inside it. This is a
thin, typed façade over the existing discovery logic (tools/build_workspace_intelligence
_index.discover_repos) and the unified scope config (paths.workspace_config) — it adds
structure and a single object callers talk to (Law of Demeter), not new behaviour.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from citadel.paths import workspace_config
from citadel.services._tools_bridge import import_tool


@dataclass(frozen=True, slots=True)
class Company:
    """One workspace repo, seen as a company of the corporate legion."""

    repo_id: str
    path: Path
    is_git: bool
    python_root: str

    @property
    def python_path(self) -> Path:
        """Absolute path to the company's Python source root."""
        return self.path / self.python_root


class Legion:
    """The corporate. Aggregates Company objects discovered under the scan root."""

    def __init__(self, companies: list[Company]) -> None:
        self._companies = list(companies)
        self._by_id = {c.repo_id: c for c in self._companies}

    @classmethod
    def discover(cls) -> Self:
        """Discover companies from the unified scope config (SSOT)."""
        scope = workspace_config()
        cfg = {
            "repo_include_globs": scope["repo_include_globs"],
            "repo_include_paths": scope.get("repo_include_paths"),
            "repo_exclude_globs": scope["repo_exclude_globs"],
        }
        intel = import_tool("build_workspace_intelligence_index")
        raw = intel.discover_repos(scope["scan_root"], cfg)
        companies = [
            Company(
                repo_id=r["repo_id"],
                path=Path(r["path"]),
                is_git=bool(r["is_git"]),
                python_root=r.get("python_root", "."),
            )
            for r in raw
        ]
        return cls(companies)

    def companies(self) -> list[Company]:
        """All companies, in discovery order."""
        return list(self._companies)

    def git_companies(self) -> list[Company]:
        """Companies that are git working trees (mineable for history)."""
        return [c for c in self._companies if c.is_git]

    def company(self, repo_id: str) -> Company | None:
        """O(1) lookup of a company by id."""
        return self._by_id.get(repo_id)

    def __len__(self) -> int:
        return len(self._companies)
