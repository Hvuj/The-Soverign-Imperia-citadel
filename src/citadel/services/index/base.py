"""base.py — records + abstract contracts for the code-intelligence indexes.

Abstractions only (DIP). Concrete implementations parse source with the stdlib
`ast` module and persist JSON under the workspace state dir; tests target these
interfaces so a future in-memory or DB-backed impl drops in without churn.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Symbol:
    """A defined code symbol with its line span.

    line span is 1-based and inclusive; ``end_line`` is the last line of the
    definition body. ``qualname`` is dotted within its module (e.g. ``Foo.method``).
    """

    repo: str
    path: str
    qualname: str
    kind: str
    start_line: int
    end_line: int

    def contains(self, line: int) -> bool:
        """True if `line` falls inside this symbol's span."""
        return self.start_line <= line <= self.end_line


class SymbolIndex(ABC):
    """qualname -> Symbol (O(1)) plus line -> enclosing Symbol (O(log N))."""

    @abstractmethod
    def lookup(self, repo: str, qualname: str) -> Symbol | None:
        """Exact symbol lookup by (repo, qualname). O(1)."""

    @abstractmethod
    def enclosing(self, repo: str, path: str, line: int) -> Symbol | None:
        """Innermost symbol whose span contains `line`, or None. O(log N)."""

    @abstractmethod
    def symbols(self) -> Iterable[Symbol]:
        """Iterate all indexed symbols."""


class ImportGraphIndex(ABC):
    """Directed module-import graph with traversal and cycle detection."""

    @abstractmethod
    def neighbors(self, module: str) -> list[str]:
        """Modules directly imported by `module`. O(1)."""

    @abstractmethod
    def reverse_neighbors(self, module: str) -> list[str]:
        """Modules that directly import `module`. O(1)."""

    @abstractmethod
    def reachable(self, module: str) -> set[str]:
        """All modules reachable from `module` (BFS/DFS closure)."""

    @abstractmethod
    def cycles(self) -> list[list[str]]:
        """Import cycles as lists of module names (strongly connected components)."""


class CommitGraph(ABC):
    """Bidirectional links among commits, files and functions."""

    @abstractmethod
    def commits_for_file(self, repo: str, path: str) -> list[str]:
        """Commit SHAs that touched a file. O(1)."""

    @abstractmethod
    def commits_for_function(self, repo: str, qualname: str) -> list[str]:
        """Commit SHAs that touched a function/symbol. O(1)."""

    @abstractmethod
    def functions_for_commit(self, sha: str) -> list[str]:
        """Qualified symbol names touched by a commit. O(1)."""
