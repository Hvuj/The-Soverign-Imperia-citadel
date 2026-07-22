"""identity.py — model identity + the not-self validation rule (System 1).

A model may NOT validate its exact self, but a *different configuration of the same family is a valid
independent validator*: opus-4.8-low may validate opus-4.8-medium; sonnet-5 may validate sonnet-4.6; haiku
may validate sonnet. So uncorrelation keys on **model identity = (vendor, family, model_id, effort)**, not
vendor family alone. `ModelIdentity` is an immutable Value Object; `can_validate` is a pure Specification.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    vendor: str
    family: str
    model_id: str
    effort: str = ""

    def self_key(self) -> tuple[str, str]:
        """The identity for the not-self rule: same model_id AND effort = the same validator."""
        return (self.model_id.lower(), self.effort.lower())


def _family_from_model(model_id: str, vendor: str) -> str:
    m = model_id.lower()
    for fam in ("gpt-oss", "llama", "nemotron", "qwen", "deepseek", "mixtral", "claude", "gemini", "flux"):
        if fam in m:
            return fam
    return vendor


def identity_of(name: str) -> ModelIdentity:
    """Derive a ModelIdentity from an executor/judge/funditor name.

    Handles `judge:…`/`funditor:…` prefixes, `provider:<vendor>:<model_id>`, `cloud-claude`, and local
    (`local`, `ollama`, `local-coding`). An explicit `#effort` suffix on the model id is parsed out.
    """
    n = (name or "").strip()
    for prefix in ("judge:", "funditor:"):
        if n.startswith(prefix):
            n = n[len(prefix):]
    effort = ""
    if "#" in n:
        n, effort = n.rsplit("#", 1)

    if n.startswith("provider:"):
        parts = n.split(":", 2)
        vendor = parts[1] if len(parts) > 1 else "unknown"
        model_id = parts[2] if len(parts) > 2 else vendor
        return ModelIdentity(vendor, _family_from_model(model_id, vendor), model_id, effort)
    if "claude" in n.lower():
        return ModelIdentity("anthropic", "claude", re.sub(r"[^a-z0-9._:/-]", "", n.lower()) or "claude", effort)
    if "ollama" in n.lower() or "local" in n.lower():
        return ModelIdentity("ollama", "local", n.lower() or "local", effort)
    return ModelIdentity("unknown", "unknown", n.lower() or "unknown", effort)


def can_validate(author: ModelIdentity, validator: ModelIdentity) -> bool:
    """True unless the validator is the author's EXACT self (same model_id + effort)."""
    return author.self_key() != validator.self_key()


def distinct_witnesses(author: ModelIdentity, validators: list[ModelIdentity]) -> set[tuple[str, str]]:
    """The set of distinct validator identities that are allowed to witness `author` (not its self)."""
    return {v.self_key() for v in validators if can_validate(author, v)}
