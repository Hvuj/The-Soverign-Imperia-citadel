"""registry.py — the provider catalog: endpoints, key env vars, and recommended models by modality.

One `nvapi-` NVIDIA key unlocks the whole NVIDIA catalog; one xAI key unlocks Grok; one Groq key unlocks
Groq's models. `egress_domain` is the single host each provider is allowed to talk to (the cloud-egress
allowlist). NOTE: `GROK_API_KEY` is an **xAI** key (api.x.ai) — the `grok` provider — NOT Groq
(api.groq.com), which uses its own `GROQ_API_KEY`. Model IDs evolve on the providers' catalogs — these are
the recommended defaults; override per call or in config.
"""

from dataclasses import dataclass, field

from citadel.services.execute.providers.keys import resolve_provider_key


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    name: str
    base_url: str
    key_env: str
    egress_domain: str
    text_models: tuple[str, ...] = ()
    vision_models: tuple[str, ...] = ()
    image_models: tuple[str, ...] = ()

    def default_model(self, modality: str = "text") -> str | None:
        models = {"text": self.text_models, "vision": self.vision_models, "image": self.image_models}.get(modality, ())
        return models[0] if models else None


GROK = ProviderSpec(
    name="grok",
    base_url="https://api.x.ai/v1",  # xAI's OpenAI-compatible endpoint
    key_env="GROK_API_KEY",          # the xAI grok-developer-program key in the user's .env
    egress_domain="api.x.ai",
    # Valid current model IDs (verified against api.x.ai: grok-2/grok-beta are retired, grok-3/grok-4 exist).
    text_models=("grok-4-latest", "grok-3", "grok-3-mini"),
)

GROQ = ProviderSpec(
    name="groq",
    base_url="https://api.groq.com/openai/v1",
    key_env="GROQ_API_KEY",  # distinct from GROK_API_KEY (xAI); absent → groq stays unavailable
    egress_domain="api.groq.com",
    text_models=("openai/gpt-oss-120b", "openai/gpt-oss-20b"),
)

NVIDIA = ProviderSpec(
    name="nvidia",
    base_url="https://integrate.api.nvidia.com/v1",
    key_env="NVIDIA_API_KEY",
    egress_domain="integrate.api.nvidia.com",
    # Verified against the live NVIDIA Build catalog (GET /v1/models).
    text_models=(
        "meta/llama-3.3-70b-instruct",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "qwen/qwen3.5-122b-a10b",
        "deepseek-ai/deepseek-v4-pro",
    ),
    vision_models=("nvidia/nemotron-nano-12b-v2-vl", "meta/llama-3.2-90b-vision-instruct"),
    # Image generation uses NVIDIA's separate genai endpoint (wired in Phase 5, not the chat catalog).
    image_models=("black-forest-labs/flux.1-dev", "stabilityai/stable-diffusion-xl"),
)

PROVIDERS: dict[str, ProviderSpec] = {"grok": GROK, "groq": GROQ, "nvidia": NVIDIA}


def provider_spec(name: str) -> ProviderSpec | None:
    return PROVIDERS.get(name)


def available_providers() -> list[str]:
    """Providers whose API key is present (in .env/env) — the ones we can actually call."""
    return [name for name, spec in PROVIDERS.items() if resolve_provider_key(spec.key_env)]
