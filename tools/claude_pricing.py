#!/usr/bin/env python3
"""claude_pricing.py — shared Claude API list-price table + cost/token helpers.

Extracted out of `claude_usage_cost_report.py`, which defines these alongside
~700 lines of module-level (unguarded — no `if __name__ == "__main__":`) script
that scans `~/.claude/projects/**` and writes a PDF report as a SIDE EFFECT OF
IMPORT. `token_ledger.py` needs only the pricing math, not the report; importing
it from that script would have silently triggered a full report generation (and
PDF write into the repo) every time `token_ledger.py` — and therefore
`legion_orchestrator.py` — was imported. This module has zero side effects.
"""

PRICING = {
    "opus": {
        "input":    5.00,
        "output":  25.00,
        "write5m":  6.25,
        "write1h": 10.00,
        "read":     0.50,
    },
    "sonnet": {
        "input":    3.00,
        "output":  15.00,
        "write5m":  3.75,
        "write1h":  6.00,
        "read":     0.30,
    },
    "haiku": {
        "input":    1.00,
        "output":   5.00,
        "write5m":  1.25,
        "write1h":  2.00,
        "read":     0.10,
    },
}


def tier(model: str) -> str | None:
    """Map model ID → pricing tier, or None to skip."""
    m = model.lower()
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return None


def compute_cost(usage: dict, model: str) -> float:
    """Compute notional USD cost for one assistant message's usage block."""
    t = tier(model)
    if t is None:
        return 0.0
    p = PRICING[t]

    input_tok  = usage.get("input_tokens", 0) or 0
    output_tok = usage.get("output_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0

    cc = usage.get("cache_creation") or {}
    cw1h = (cc.get("ephemeral_1h_input_tokens") or 0)
    cw5m = (cc.get("ephemeral_5m_input_tokens") or 0)
    if cw1h == 0 and cw5m == 0:
        cw5m = usage.get("cache_creation_input_tokens", 0) or 0

    cost = (
        input_tok  * p["input"]   +
        output_tok * p["output"]  +
        cw5m       * p["write5m"] +
        cw1h       * p["write1h"] +
        cache_read * p["read"]
    ) / 1_000_000
    return cost


def total_tokens(usage: dict) -> int:
    """Sum all token types for one usage block."""
    fields = [
        "input_tokens", "output_tokens",
        "cache_creation_input_tokens", "cache_read_input_tokens",
    ]
    return sum((usage.get(f) or 0) for f in fields)
