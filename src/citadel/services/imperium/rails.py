"""rails.py — jurisdiction rails: what a family of models is allowed / not allowed to do (System 2).

An Imperium's jurisdiction is expressed as allow / deny **op-patterns** — strings like `write:src/**`,
`delete:**`, `net:api.groq.com`, `shell:rm`. They are compiled once into a **segment trie** so a check is
**O(L)** in the op string (a bounded walk over its `:`/`/`-separated segments), never O(#patterns). Semantics
are **default-deny** (allowlist) with **deny-precedence**: an op is permitted iff it matches an allow pattern
AND no deny pattern — so a family opens capabilities explicitly and a deny always wins (Chain of
Responsibility: deny gate first, then allow gate). `*` matches one segment, `**` matches the rest.

An op also carries a **capability class** (`op_capability`) mapping its verb to a fasces bit, so rails
(is this op in my jurisdiction?) compose with capability tokens (do I hold the right to do it?) — the two
independent gates the registry enforces together.
"""

import re

from citadel.services.authority.fasces import (
    APPLY_PATCH,
    DELETE_PATH,
    DROP_TABLE,
    FORCE_PUSH,
    INDEX_WRITE,
    KILL_PID,
    RESTART_SVC,
    WRITE_FILE,
)

_SEP = re.compile(r"[:/]+")

# op-verb → required fasces capability bit (0 = no mutate right needed; rails alone govern it)
_VERB_CAPABILITY = {
    "write": WRITE_FILE,
    "patch": APPLY_PATCH,
    "index": INDEX_WRITE,
    "restart": RESTART_SVC,
    "delete": DELETE_PATH,
    "drop_table": DROP_TABLE,
    "force_push": FORCE_PUSH,
    "kill": KILL_PID,
}


def _segments(text: str) -> list[str]:
    return [seg for seg in _SEP.split((text or "").strip()) if seg]


def op_capability(op: str) -> int:
    """The fasces bit an op requires (by its leading verb); 0 for read/net/shell-class ops governed by rails only."""
    segs = _segments(op)
    return _VERB_CAPABILITY.get(segs[0], 0) if segs else 0


class _Node:
    __slots__ = ("children", "dstar", "leaf", "star")

    def __init__(self) -> None:
        self.children: dict[str, _Node] = {}
        self.star: _Node | None = None   # '*' — matches exactly one segment
        self.dstar: bool = False         # '**' — matches all remaining segments (terminal)
        self.leaf: bool = False          # a pattern ends here


class _Trie:
    def __init__(self, patterns) -> None:
        self.root = _Node()
        self._empty = True
        for pattern in patterns or ():
            self._add(pattern)

    def _add(self, pattern: str) -> None:
        node = self.root
        for seg in _segments(pattern):
            self._empty = False
            if seg == "**":
                node.dstar = True
                return
            if seg == "*":
                node.star = node.star or _Node()
                node = node.star
            else:
                node = node.children.setdefault(seg, _Node())
        node.leaf = True

    def matches(self, op: str) -> bool:
        if self._empty:
            return False
        return self._walk(self.root, _segments(op), 0)

    def _walk(self, node: _Node, segs: list[str], i: int) -> bool:
        if node.dstar:
            return True
        if i == len(segs):
            return node.leaf
        seg = segs[i]
        child = node.children.get(seg)
        if child is not None and self._walk(child, segs, i + 1):
            return True
        return node.star is not None and self._walk(node.star, segs, i + 1)


class Rails:
    """Compiled jurisdiction: default-deny allowlist with deny-precedence. O(L) per check."""

    def __init__(self, *, allow=None, deny=None) -> None:
        self._allow = _Trie(allow)
        self._deny = _Trie(deny)

    def permits(self, op: str) -> bool:
        if self._deny.matches(op):
            return False
        return self._allow.matches(op)

    def check(self, op: str) -> tuple[bool, str]:
        if self._deny.matches(op):
            return False, f"'{op}' is explicitly denied by jurisdiction"
        if self._allow.matches(op):
            return True, "within jurisdiction"
        return False, f"'{op}' is outside jurisdiction (no allow rule; default-deny)"
