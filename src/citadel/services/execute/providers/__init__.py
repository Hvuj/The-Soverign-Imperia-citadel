"""citadel.services.execute.providers — the free-cloud provider federation (Groq + NVIDIA Build).

Both providers are OpenAI-compatible, so one `OpenAICompatExecutor` (behind the existing `Executor` seam)
covers them and any future OpenAI-shaped endpoint. Keys come from `.env` (never logged), every prompt is
secret-redacted before it leaves the machine, and everything degrades gracefully when a key is absent.
"""

from citadel.services.execute.providers.budget import BudgetGuard
from citadel.services.execute.providers.funditor import ProviderFunditor
from citadel.services.execute.providers.gate import audit_cloud_call, contains_sensitive, egress_allowed
from citadel.services.execute.providers.keys import resolve_provider_key
from citadel.services.execute.providers.openai_compat import OpenAICompatExecutor, build_provider_executor
from citadel.services.execute.providers.image_gen import generate_image
from citadel.services.execute.providers.registry import (
    PROVIDERS,
    ProviderSpec,
    available_providers,
    provider_spec,
)
from citadel.services.execute.providers.vision import describe_image

__all__ = [
    "PROVIDERS",
    "BudgetGuard",
    "OpenAICompatExecutor",
    "ProviderFunditor",
    "ProviderSpec",
    "audit_cloud_call",
    "available_providers",
    "build_provider_executor",
    "contains_sensitive",
    "describe_image",
    "egress_allowed",
    "generate_image",
    "provider_spec",
    "resolve_provider_key",
]
