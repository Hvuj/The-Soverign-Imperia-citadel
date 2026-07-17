"""citadel consensus — run many models on one task in parallel, cross-validate, reduce to one verified answer.

Assembles a panel from whatever is available (local Ollama + Groq + NVIDIA), validators from ≥2 uncorrelated
families, an optional deterministic verify (Python ast for --code), and a strong synthesizer. Every member is
**brain-armed** (reads the shared brain, redacted at the cloud boundary), **every model learns** its outcome
into the shared ledger, and a verified winner backed by a **distinct not-self quorum** is **auto-promoted**
through the Cursus Honorum into a durable Senatus Consultum. Prints the candidates, the consensus scores, and
the winning (or synthesized) solution. Cloud members are budget-guarded and redaction-gated; missing keys
simply shrink the panel (never a crash).
"""

import ast
from pathlib import Path

from citadel.services.brain.bus import event_hash
from citadel.services.consensus.identity import distinct_witnesses, identity_of


def _verify_python(output: str):
    from citadel.services.execute.coding import extract_code

    code = extract_code(output)
    try:
        ast.parse(code)
        return True, "parses"
    except SyntaxError as exc:
        return False, str(exc)


def _first_line(text: str) -> str:
    lines = (text or "").strip().splitlines()
    return lines[0][:120] if lines else ""


def _critique_gist(result, candidate_id: str) -> str:
    for cr in result.critiques:
        if cr.candidate_id == candidate_id and cr.verdict == "reject":
            return (cr.note or "rejected")[:120]
    return ""


def _learn_from_result(rep, task: str, result) -> int:
    """Every participating model records its outcome into the shared ledger — winner as a best-practice,
    valid alternatives as 'worked', rejected candidates as 'failed' with the critique that sank them."""
    winner_id = result.winner.id if result.winner else None
    for c in result.candidates:
        passed = c.status == "pass"
        if c.id == winner_id:
            category, summary = "best_practice", f"chosen solution: {_first_line(c.output)}"
        elif passed:
            category, summary = "worked", f"valid alternative: {_first_line(c.output)}"
        else:
            category, summary = "failed", _critique_gist(result, c.id) or "did not pass the gate"
        rep.ledger.record(task, c.member, success=passed, category=category, summary=summary)
    return len(result.candidates)


def _maybe_promote(rep, task: str, result):
    """Automatic promotion: a verified winner accepted by ≥2 DISTINCT not-self validators climbs the Cursus
    Honorum to consul and is enacted as a Senatus Consultum. Idempotent — a re-run with the same winning
    solution does not mint a new version."""
    from citadel.services.brain.learning import task_signature
    from citadel.services.senate.cursus import Proposal

    if result.method == "none" or result.winner is None:
        return None
    winner = result.winner
    accepting = [cr.validator for cr in result.critiques
                 if cr.candidate_id == winner.id and cr.verdict == "accept"]
    witnesses = distinct_witnesses(identity_of(winner.member), [identity_of(v) for v in accepting])
    if len(witnesses) < 2:
        return None  # no distinct not-self quorum → nothing authoritative to enact

    key = task_signature(task)
    content = {"task": task, "solution": winner.output, "winner": winner.member}
    prev = rep.consulta.latest(key)
    if prev is not None and prev.is_binding and prev.content_hash == event_hash(content):
        return prev  # same solution already enacted — idempotent

    proposal = Proposal(id=key, author=winner.member, content=content)
    rep.cursus.run_to_consul(proposal, validators=accepting, accepting=accepting)
    return rep.consulta.latest(key) if proposal.is_consul else None


def run(args) -> int:
    from citadel.services.brain.injection import BrainContextExecutor
    from citadel.services.consensus import ConsensusEngine, ModelJudge
    from citadel.services.execute import LocalExecutor, OllamaEngine
    from citadel.services.execute.providers import BudgetGuard, build_provider_executor
    from citadel.services.republic import build_republic

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

    # ── Republic: query the brain once, brain-arm every member (redacted for cloud), learn + promote ──
    rep = build_republic(ws)
    try:
        capsule = rep.brain.context(task)
    except Exception:
        capsule = {"chunks": []}
    members = [BrainContextExecutor(m, rep.brain, capsule=capsule) for m in members]

    verify = _verify_python if getattr(args, "code", False) else None
    min_families = 2 if len(validators) >= 2 else 1

    from citadel.services.execute.blueprint import Blueprint
    engine = ConsensusEngine(members=members, validators=validators, verify=verify, synthesizer=synth)
    print(f"◆ The Sovereign — consensus across {len(members)} models, {len(validators)} validators…")
    if capsule.get("chunks"):
        print(f"  brain: {len(capsule['chunks'])} cited chunks injected (secret-stripped for cloud members)")
    result = engine.run(Blueprint(task_id="consensus", instruction=task), min_families=min_families)

    print(f"\nmethod: {result.method}   families: {sorted({c.family for c in result.candidates})}")
    for c in result.candidates:
        print(f"  [{result.scores.get(c.id, 0):.2f}] {c.member}")
    if result.winner:
        print(f"winner: {result.winner.member}")
    print("\n" + (result.output or "(no safe answer reached)"))

    recorded = _learn_from_result(rep, task, result)
    print(f"\nlearning: recorded {recorded} model outcomes to the shared brain")
    consultum = _maybe_promote(rep, task, result)
    if consultum is not None:
        print(f"senate: enacted Senatus Consultum '{consultum.key}' v{consultum.version} "
              f"(not-self quorum: {list(consultum.quorum)})")
    return 0 if result.method != "none" else 1
