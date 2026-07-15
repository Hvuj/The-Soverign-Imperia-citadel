"""The Auxilia — uncorrelated validators drawn from a different model family (masterplan §7).

Intercessio's dual-gate is only meaningful if the second gate shares no blind spots with the first. A second
Claude instance does not qualify; a Gemini validator does. GeminiFunditor (funditor = the auxiliary slinger)
emits a `Gate(family="gemini", ...)` that composes directly with `dual_gate`. The judgement call is injected,
so the gate is exercised in tests and in the chaos drills without a live API — and swapped for a real Gemini
call in production without touching the control-plane logic.
"""

from collections.abc import Callable
from typing import Any

from citadel.services.authority.intercessio import Gate


class GeminiFunditor:
    family = "gemini"

    def __init__(self, validate: Callable[[Any], bool]) -> None:
        self._validate = validate

    def gate(self, artifact: Any) -> Gate:
        """Judge an artifact and return this auxiliary's Gate — the uncorrelated 2nd vote for the dual-gate."""
        return Gate(self.family, bool(self._validate(artifact)))
