"""injection.py — brain-for-all (System 4): every model reads the one brain, redacted at the cloud boundary.

A Decorator over the `Executor` seam injects a **cited context capsule** (the brain's cheap-first cascade)
into a blueprint before the model runs — so local Ollama, Groq, NVIDIA and Claude all reason over the same
shared brain without any of them coupling to storage (Dependency Inversion). The boundary is a Strategy:

- **local** members receive the **full** capsule (trusted, on-machine),
- **cloud** members receive it through a **redaction Decorator** — every chunk is secret-masked
  (`sk-…`/`ghp_…`/bearer/private-key/`KEY=value`) and any chunk that references sensitive material
  (`.env`, private keys, `**/private/**`, `[PRIVATE]`) is **dropped entirely** (deny-list — it never leaves,
  even redacted). Same brain; one Strategy switches the boundary.

`attach_brain(executor, brain, store=…)` composes the whole loop: brain-context injection (redacted per
boundary) wrapped by the learning Decorator (recall-before / record-after) — the model both reads from and
writes to the brain, transparently.
"""

from collections.abc import Callable
from dataclasses import replace

from citadel.services.brain.access import BrainAccess
from citadel.services.brain.learning import LearningStore
from citadel.services.brain.learning_executor import LearningExecutor
from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor


def _default_redact() -> Callable[[str], str]:
    try:
        from citadel.services._tools_bridge import import_tool

        return import_tool("citadel_custos").redact
    except Exception:
        return lambda text: text


def _default_deny() -> Callable[[str], str | None]:
    try:
        from citadel.services.execute.providers.gate import contains_sensitive

        return contains_sensitive
    except Exception:
        return lambda _text: None


def is_cloud(name: str) -> bool:
    """A member is a cloud boundary unless it is the local Ollama family."""
    n = (name or "").lower()
    if "ollama" in n or "local" in n:
        return False
    return n.startswith("provider:") or "claude" in n or "groq" in n or "nvidia" in n


def render_capsule(
    capsule: dict,
    *,
    boundary: str = "local",
    redact: Callable[[str], str] | None = None,
    deny: Callable[[str], str | None] | None = None,
) -> str:
    """Render a brain capsule into a cited context block. At the cloud boundary, drop sensitive chunks and
    mask secrets in the rest; at the local boundary, pass the full text through."""
    chunks = capsule.get("chunks", [])
    if not chunks:
        return ""
    cloud = boundary == "cloud"
    redact = redact or (_default_redact() if cloud else (lambda t: t))
    deny = deny or (_default_deny() if cloud else (lambda _t: None))
    blocks: list[str] = []
    for ch in chunks:
        path = ch.get("path", "?")
        snippet = ch.get("snippet", "")
        if cloud and (deny(path) or deny(snippet)):
            continue  # private material never leaves, even redacted (deny-list)
        text = redact(snippet) if cloud else snippet
        span = f"{path}#{ch.get('start_byte', 0)}-{ch.get('end_byte', 0)}"
        blocks.append(f"# {span}\n{text}")
    if not blocks:
        return ""
    return "Cited context from the brain:\n" + "\n\n".join(blocks)


class BrainContextExecutor(Executor):
    def __init__(
        self,
        inner: Executor,
        brain: BrainAccess,
        *,
        boundary: str | None = None,
        top_k: int = 6,
        budget_bytes: int = 16 * 1024,
        redact: Callable[[str], str] | None = None,
        deny: Callable[[str], str | None] | None = None,
        capsule: dict | None = None,
    ) -> None:
        self.inner = inner
        self.brain = brain
        self.name = inner.name
        self.boundary = boundary if boundary in ("cloud", "local") else ("cloud" if is_cloud(inner.name) else "local")
        self._top_k = top_k
        self._budget_bytes = budget_bytes
        self._redact = redact
        self._deny = deny
        self._capsule = capsule  # precomputed capsule to reuse (query the brain once, render per member)

    def execute(self, blueprint: Blueprint) -> ExecutionResult:
        bp = blueprint
        try:
            capsule = self._capsule if self._capsule is not None else self.brain.context(
                blueprint.instruction, top_k=self._top_k, budget_bytes=self._budget_bytes
            )
            block = render_capsule(capsule, boundary=self.boundary, redact=self._redact, deny=self._deny)
        except Exception:
            block = ""  # the brain is advisory — never let a retrieval hiccup block execution
        if block:
            merged = f"{blueprint.context}\n\n{block}" if blueprint.context else block
            bp = replace(blueprint, context=merged)
        return self.inner.execute(bp)

    def healthcheck(self) -> bool:
        return self.inner.healthcheck()


def attach_brain(
    executor: Executor,
    brain: BrainAccess,
    *,
    store: LearningStore | None = None,
    boundary: str | None = None,
    top_k: int = 6,
) -> Executor:
    """Compose the full brain loop onto a member: redacted context injection + (optionally) the learning
    Decorator. Returns a drop-in `Executor` — callers pass it wherever a plain member went."""
    wrapped: Executor = BrainContextExecutor(executor, brain, boundary=boundary, top_k=top_k)
    if store is not None:
        wrapped = LearningExecutor(wrapped, store)
    return wrapped
