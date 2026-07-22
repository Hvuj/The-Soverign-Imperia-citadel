# The Provider Federation — Groq + NVIDIA + consensus

Free/cheap cloud models the Sovereign uses **as a combination, in parallel** — for candidate generation,
cross-validation, vision, and image generation — alongside the local Ollama (zero-token) and Claude tiers.

## Providers & keys (one key each unlocks everything)

| Provider | Endpoint | Env var (in `.env`) | Unlocks |
|---|---|---|---|
| **Groq** | `https://api.groq.com/openai/v1` | `GROK_API_KEY` | ultra-fast text (all Groq models) |
| **NVIDIA Build** | `https://integrate.api.nvidia.com/v1` (chat), `https://ai.api.nvidia.com/v1/genai` (image) | `NVIDIA_API_KEY` (`nvapi-…`) | the whole 100+ model catalog: text · vision · image |

Both are OpenAI-compatible, so one `OpenAICompatExecutor` drives them (and any future OpenAI-shaped API).
Get an NVIDIA key at **build.nvidia.com**; put both keys in a `.env` at the repo root. `citadel doctor` shows
which are present (masked). **TLS behind a corporate proxy is handled** by `truststore` (uses the OS cert
store) — no `verify=False`, no certifi surgery.

## Recommended models (wired defaults)

| Role | Model |
|---|---|
| Fast text (Groq) | `openai/gpt-oss-120b`, `openai/gpt-oss-20b` |
| Text/reasoning (NVIDIA) | `meta/llama-3.3-70b-instruct`, `nvidia/llama-3.3-nemotron-super-49b-v1.5`, `qwen/qwen3.5-122b-a10b`, `deepseek-ai/deepseek-v4-pro` |
| Vision / VLM (NVIDIA) | `nvidia/nemotron-nano-2-vl`, `meta/llama-3.2-90b-vision-instruct` |
| Image gen (NVIDIA genai) | `black-forest-labs/flux.1-schnell`, `stabilityai/stable-diffusion-xl` |
| Embeddings | **local** `nomic-embed-text` (zero-token — never cloud) |

*(Exact IDs evolve; list your account's models with `GET /v1/models`. Image-gen models may need
visual-GenAI access enabled on your NVIDIA account.)*

## Privacy — "redacted, non-sensitive only" (enforced)

Every cloud call is:
1. **Secret-redacted** before send (`citadel_custos.redact` — sk-*, tokens, `.env` values …).
2. **Deny-listed** — a prompt referencing `.env` / private keys / `**/private/**` / `[PRIVATE]` is **blocked**
   (status `blocked`) and the caller falls back to local. It never leaves the machine.
3. **Egress-allowlisted** — clients may only reach `api.groq.com` / `integrate.api.nvidia.com` /
   `ai.api.nvidia.com`.
4. **Audited** — metadata only (`.claude/state/provider-audit.jsonl`): provider, model, bytes, status —
   never the content.
Embeddings stay local.

## The consensus engine — many models, in parallel, map-reduce-shuffle

```bash
citadel consensus "write a function that dedupes a list preserving order" --code
```
- **MAP** — N models (local Ollama + Groq + NVIDIA) write candidates **in parallel**.
- **SHUFFLE + REDUCE** — many validators score every candidate **in parallel** (a validator×candidate
  matrix), plus a deterministic gate (`--code` → `ast.parse`), plus the **Intercessio dual-gate**: a winner
  must be accepted by **≥2 uncorrelated model families**.
- **DECIDE** — pick the highest-consensus verified candidate, or **synthesize** one correct solution from all
  the candidates + critiques and re-verify.

Trust-weighted: families with a long clean streak vote heavier; a family that ever produced an unsafe
(CAPITAL) output drops to zero weight. Budget-guarded: a rate-limited (429) provider is throttled and the
panel falls back.

## Vision & image

```bash
citadel see path/to/image.png "what UI is shown?"      # NVIDIA VLM describes/analyzes an image
citadel image "a glossy red cube on white" --out out.png   # NVIDIA FLUX/SDXL → a PNG
```

## Budget

`BudgetGuard` counts calls per provider, enforces an optional hard cap, and throttles on 429. State in
`.claude/state/provider-budget.json`.

Sources: [Groq API](https://console.groq.com/docs/api-reference) · [NVIDIA Build](https://build.nvidia.com/)
