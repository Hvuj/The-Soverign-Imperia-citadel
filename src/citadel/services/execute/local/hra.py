"""Hardware Resource Arbitrator — local-tier arbitration that auto-discovers the GPU and budgets VRAM
(model weights + KV cache) before dispatch.

Reuses tools/model_backend's hardware detection and tier ladder, and implements the same
``arbitrate(blueprint) -> ArbitrationDecision`` contract as the cloud ResourceArbitrator, so
``orchestrate()`` accepts either. When a GPU is detected the selected spec offloads to it
(``n_gpu_layers`` > 0); when weights + KV would overflow VRAM the arbitrator shrinks the context or,
if even a minimal context will not fit, rejects with a reason (no silent CPU fallback).
"""

import re
from dataclasses import replace

from citadel.services.execute.arbitrator import ArbitrationDecision
from citadel.services.execute.blueprint import Blueprint
from citadel.services.execute.local._backend import load_model_backend
from citadel.services.execute.local.engine import RunSpec

_GB = 1024 ** 3
_QUANT_BYTES_PER_PARAM = {"Q4_K_M": 0.55, "Q5_K_M": 0.68, "Q8_0": 1.06, "F16": 2.0}
_KV_BYTES_PER_TOKEN = 512 * 1024
_MIN_CTX = 256


def _params_billion(model_name: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)\s*[bB]\b", model_name)
    return float(match.group(1)) if match else 7.0


def _weight_gb(model_name: str, quant: str) -> float:
    per_param = _QUANT_BYTES_PER_PARAM.get(quant, 0.55)
    return _params_billion(model_name) * 1e9 * per_param / _GB


def _kv_gb(n_ctx: int) -> float:
    return n_ctx * _KV_BYTES_PER_TOKEN / _GB


class HardwareResourceArbitrator:
    def __init__(self, profile=None, max_tokens: int = 512) -> None:
        self._profile = profile
        self._max_tokens = max_tokens

    def _hardware(self):
        if self._profile is not None:
            return self._profile
        mb = load_model_backend()
        if mb is None:
            return None
        return mb.detect_hardware()

    def arbitrate(self, blueprint: Blueprint) -> ArbitrationDecision:
        mb = load_model_backend()
        profile = self._hardware()
        if mb is None or profile is None:
            return ArbitrationDecision(admit=False, tier=blueprint.assigned_tier, reason="model_backend_unavailable")

        spec = mb._select_model_spec(profile)
        n_ctx = spec.max_context_tokens
        if blueprint.context_token_budget:
            n_ctx = min(n_ctx, blueprint.context_token_budget)
        run = RunSpec(
            model=spec.general_model,
            quantization=spec.quantization,
            n_gpu_layers=spec.n_gpu_layers,
            n_ctx=n_ctx,
            threads=spec.thread_count,
            max_tokens=self._max_tokens,
        )

        vram = getattr(profile, "vram_gb", 0.0) or 0.0
        if vram > 0.0:
            weight_gb = _weight_gb(run.model, run.quantization)
            if weight_gb + _kv_gb(run.n_ctx) > vram:
                kv_budget_gb = vram - weight_gb
                fit_ctx = int(kv_budget_gb * _GB / _KV_BYTES_PER_TOKEN) if kv_budget_gb > 0 else 0
                if fit_ctx < _MIN_CTX:
                    return ArbitrationDecision(
                        admit=False,
                        tier=blueprint.assigned_tier,
                        reason=f"model_too_large_for_vram: weights {weight_gb:.1f}GB > {vram:.1f}GB VRAM",
                    )
                run = replace(run, n_ctx=min(run.n_ctx, fit_ctx))

        return ArbitrationDecision(admit=True, tier=blueprint.assigned_tier, run_spec=run)
