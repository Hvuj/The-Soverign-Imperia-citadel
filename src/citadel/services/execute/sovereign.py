"""The Sovereign runner — the live local-first entry point.

Classifies a prompt, routes it (cheap work runs free on the local Ollama tier, complex work goes to the
cloud), tries the free local tier first and escalates to the cloud (Sonnet) only on failure, and records
the outcome so the local tier self-improves. Executors and the classifier are injectable; the defaults use
the real Ollama local tier and the cloud tier.
"""

import re
from collections.abc import Callable
from pathlib import Path

from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor, sovereign_run
from citadel.services.execute.policy import LocalConfidence

_INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("architecture", re.compile(r"\b(refactor|architect|migrat|redesign|rewrite|overhaul)\w*", re.I)),
    ("security", re.compile(r"\b(security|auth|credential|secret|vulnerab)\w*", re.I)),
    ("search", re.compile(r"\b(search|find|locate|which file|look ?up)\b|where is\b", re.I)),
    ("check", re.compile(r"\b(check|verify|validate|lint|run the tests?)\b", re.I)),
    ("simple_function", re.compile(r"\b(add|write|create|implement|generate)\b.*\b(function|helper|method|util|script)\b", re.I)),
    ("question", re.compile(r"^\s*(what|how|why|who|when|where|is|are|can|does|do|should|could|would)\b|\?\s*$", re.I)),
]

_COMPLEX_INTENTS = frozenset({"architecture", "security"})


def classify_intent(prompt: str) -> str:
    """Lightweight, dependency-free intent heuristic. Swap in the workspace classifier via SovereignRunner."""
    text = prompt or ""
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(text):
            return intent
    return "question"


class SovereignRunner:
    def __init__(
        self,
        local: Executor | None = None,
        cloud: Executor | None = None,
        confidence: LocalConfidence | None = None,
        classify: Callable[[str], str] | None = None,
        model_override: str | None = None,
    ) -> None:
        self._local = local
        self._cloud = cloud
        self._confidence = confidence
        self._classify = classify or classify_intent
        self._model_override = model_override

    def _local_executor(self) -> Executor:
        if self._local is None:
            from citadel.services.execute.local.engine import OllamaEngine
            from citadel.services.execute.local.executor import LocalExecutor
            self._local = LocalExecutor(engine=OllamaEngine(), model_override=self._model_override)
        return self._local

    def _cloud_executor(self) -> Executor:
        if self._cloud is None:
            from citadel.services.execute.cloud import CloudClaudeExecutor
            self._cloud = CloudClaudeExecutor()
        return self._cloud

    def run(self, prompt: str, *, context: str = "", task_id: str = "task") -> ExecutionResult:
        intent = self._classify(prompt)
        complexity = "high" if intent in _COMPLEX_INTENTS else "low"
        blueprint = Blueprint(task_id=task_id, instruction=prompt, context=context, assigned_tier="cheap")
        return sovereign_run(
            blueprint,
            intent,
            local=self._local_executor(),
            cloud=self._cloud_executor(),
            confidence=self._confidence,
            complexity=complexity,
        )
