"""citadel consensus — run many models on one task in parallel, cross-validate, reduce to one verified answer.

Assembles a panel from whatever is available (local Ollama + Groq + NVIDIA), validators from ≥2 uncorrelated
families, an optional deterministic verify (Python ast for --code), and a strong synthesizer. Prints the
candidates, the consensus scores, and the winning (or synthesized) solution. Cloud members are budget-guarded
and redaction-gated; missing keys simply shrink the panel (never a crash).
"""

import ast
from pathlib import Path


def _verify_python(output: str):
    from citadel.services.execute.coding import extract_code

    code = extract_code(output)
    try:
        ast.parse(code)
        return True, "parses"
    except SyntaxError as exc:
        return False, str(exc)


def run(args) -> int:
    from citadel.services.consensus import ConsensusEngine, ModelJudge
    from citadel.services.execute import LocalExecutor, OllamaEngine
    from citadel.services.execute.providers import BudgetGuard, build_provider_executor

    ws = Path(getattr(args, "workspace", None) or ".").resolve()
    task = " ".join(args.task).strip()
    budget = BudgetGuard(path=ws / ".claude" / "state" / "provider-budget.json")
    audit = str(ws / ".claude" / "state" / "provider-audit.jsonl")
    kw = {"budget": budget, "audit_path": audit}

    # ── panel: local Ollama + Groq (2 models) + NVIDIA — whatever has a key/engine ──
    members = []
    if not getattr(args, "no_local", False):
        members.append(LocalExecutor(engine=OllamaEngine(), model_override=getattr(args, "local_model", None) or ""))
    members += [
        build_provider_executor("groq", model="openai/gpt-oss-120b", **kw),
        build_provider_executor("groq", model="openai/gpt-oss-20b", **kw),
        build_provider_executor("nvidia", model="meta/llama-3.3-70b-instruct", **kw),
    ]
    members = [m for m in members if m is not None]

    validators = []
    gj = build_provider_executor("groq", model="openai/gpt-oss-20b", **kw)
    nj = build_provider_executor("nvidia", model="meta/llama-3.3-70b-instruct", **kw)
    if gj:
        validators.append(ModelJudge(gj, family="groq"))
    if nj:
        validators.append(ModelJudge(nj, family="nvidia"))

    synth = build_provider_executor("nvidia", model="nvidia/llama-3.3-nemotron-super-49b-v1.5", **kw) \
        or build_provider_executor("groq", model="openai/gpt-oss-120b", **kw)

    if len(members) < 2 or len(validators) < 1:
        print("◆ The Sovereign — not enough models for consensus "
              f"(members={len(members)}, validators={len(validators)}). Set GROK_API_KEY / NVIDIA_API_KEY "
              "and/or run Ollama.")
        return 1

    verify = _verify_python if getattr(args, "code", False) else None
    min_families = 2 if len(validators) >= 2 else 1

    from citadel.services.execute.blueprint import Blueprint
    engine = ConsensusEngine(members=members, validators=validators, verify=verify, synthesizer=synth)
    print(f"◆ The Sovereign — consensus across {len(members)} models, {len(validators)} validators…")
    result = engine.run(Blueprint(task_id="consensus", instruction=task), min_families=min_families)

    print(f"\nmethod: {result.method}   families: {sorted({c.family for c in result.candidates})}")
    for c in result.candidates:
        print(f"  [{result.scores.get(c.id, 0):.2f}] {c.member}")
    if result.winner:
        print(f"winner: {result.winner.member}")
    print("\n" + (result.output or "(no safe answer reached)"))
    return 0 if result.method != "none" else 1
