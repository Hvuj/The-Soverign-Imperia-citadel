"""engine.py — the consensus engine: parallel generate → parallel cross-validate → reduce or synthesize.

MAP: every member (an `Executor` — local or cloud) produces a candidate in parallel. SHUFFLE+REDUCE: every
validator scores every candidate in parallel (a validator×candidate matrix), alongside a deterministic gate
(e.g. sandbox-verify / ast). A candidate wins only if it clears the deterministic gate, reaches the consensus
score, and is accepted by ≥2 **uncorrelated families** (the Intercessio dual-gate). If none qualify, a
synthesizer model merges the candidates + critiques into one solution, which is re-verified. Everything is
I/O-bound cloud/local calls, so a thread pool fans it all out.
"""

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from citadel.services.execute.blueprint import Blueprint
from citadel.services.execute.executor import Executor

_SCORE = re.compile(r"score\s*[:=]\s*(\d+(?:\.\d+)?)", re.I)


def family_of(name: str) -> str:
    """The model family an executor belongs to (for the uncorrelated-family dual-gate)."""
    n = (name or "").lower()
    if n.startswith("provider:"):
        return n.split(":")[1]  # groq / nvidia / …
    if "claude" in n:
        return "claude"
    if "ollama" in n or "local" in n:
        return "ollama"
    return n or "unknown"


@dataclass(slots=True)
class Candidate:
    id: str
    member: str
    family: str
    output: str
    status: str


@dataclass(slots=True)
class Critique:
    validator: str
    family: str
    candidate_id: str
    score: float  # 0..1
    verdict: str  # accept | reject
    note: str = ""


@dataclass(slots=True)
class ConsensusResult:
    method: str  # selected | synthesized | none
    output: str
    winner: Candidate | None
    candidates: list[Candidate] = field(default_factory=list)
    critiques: list[Critique] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)


def _parse_score(text: str) -> float:
    m = _SCORE.search(text or "")
    if not m:
        return 0.0
    try:
        return max(0.0, min(10.0, float(m.group(1)))) / 10.0
    except ValueError:
        return 0.0


class ModelJudge:
    """Wrap an Executor as a validator: it rates a candidate 0-10 for the task (parsed to accept/reject)."""

    def __init__(self, executor: Executor, *, family: str | None = None, accept_at: float = 0.6) -> None:
        self.executor = executor
        self.family = family or family_of(executor.name)
        self.name = f"judge:{executor.name}"
        self._accept_at = accept_at

    def critique(self, task: str, candidate: Candidate) -> Critique:
        prompt = (
            "Rate the candidate solution for the task on correctness, 0-10. "
            "Reply on the first line exactly 'SCORE: <n>' then one short reason.\n\n"
            f"TASK:\n{task}\n\nCANDIDATE:\n{candidate.output}"
        )
        bp = Blueprint(task_id=f"judge-{candidate.id}", instruction=prompt, assigned_tier="cheap")
        result = self.executor.execute(bp)
        score = _parse_score(result.output) if result.status == "pass" else 0.0
        verdict = "accept" if score >= self._accept_at else "reject"
        return Critique(self.name, self.family, candidate.id, score, verdict, (result.output or "")[:160])


class ConsensusEngine:
    def __init__(
        self,
        *,
        members: list[Executor],
        validators: list[ModelJudge],
        verify: Callable[[str], tuple[bool, str]] | None = None,
        synthesizer: Executor | None = None,
        concurrency: int = 8,
        weights: dict[str, float] | None = None,
    ) -> None:
        self.members = members
        self.validators = validators
        self.verify = verify
        self.synthesizer = synthesizer
        self.concurrency = max(1, concurrency)
        self.weights = weights or {}

    # ── MAP ────────────────────────────────────────────────────────────────────────
    def _generate(self, blueprint: Blueprint) -> list[Candidate]:
        def gen(idx_member):
            i, member = idx_member
            r = member.execute(blueprint)
            return Candidate(f"c{i}", member.name, family_of(member.name), (r.output or "").strip(), r.status)

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            raw = list(pool.map(gen, enumerate(self.members)))
        # keep passing, non-empty, de-duplicated candidates
        seen: set[str] = set()
        out: list[Candidate] = []
        for c in raw:
            if c.status == "pass" and c.output and c.output not in seen:
                seen.add(c.output)
                out.append(c)
        return out

    # ── SHUFFLE + REDUCE ────────────────────────────────────────────────────────────
    def _crossvalidate(self, task: str, candidates: list[Candidate]) -> list[Critique]:
        pairs = [(v, c) for v in self.validators for c in candidates]

        def judge(pair):
            v, c = pair
            return v.critique(task, c)

        if not pairs:
            return []
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            return list(pool.map(judge, pairs))

    def _aggregate(self, candidates: list[Candidate], critiques: list[Critique]):
        scores: dict[str, float] = {}
        families: dict[str, set[str]] = {}
        for c in candidates:
            cc = [x for x in critiques if x.candidate_id == c.id]
            if cc:
                total_w = sum(self.weights.get(x.family, 1.0) for x in cc)
                scores[c.id] = sum(x.score * self.weights.get(x.family, 1.0) for x in cc) / (total_w or 1.0)
            else:
                scores[c.id] = 0.0
            families[c.id] = {x.family for x in cc if x.verdict == "accept"}
        return scores, families

    def _verify(self, output: str) -> tuple[bool, str]:
        return self.verify(output) if self.verify else (True, "no verifier")

    def _synthesize(self, blueprint: Blueprint, candidates: list[Candidate], critiques: list[Critique]) -> str:
        blocks = []
        for c in candidates:
            notes = "; ".join(x.note for x in critiques if x.candidate_id == c.id)[:300]
            blocks.append(f"# candidate {c.id} ({c.member})\n{c.output}\n# critiques: {notes}")
        prompt = (
            "Several models attempted this task and were critiqued. Produce ONE correct, minimal solution — "
            "reuse what is good, fix what the critiques flag. Return only the solution.\n\n"
            f"TASK:\n{blueprint.instruction}\n\n" + "\n\n".join(blocks)
        )
        bp = Blueprint(task_id=f"synth-{blueprint.task_id}", instruction=prompt, assigned_tier="strong")
        result = self.synthesizer.execute(bp)
        return (result.output or "").strip() if result.status == "pass" else ""

    # ── DECIDE ──────────────────────────────────────────────────────────────────────
    def run(self, blueprint: Blueprint, *, min_families: int = 2, min_score: float = 0.5) -> ConsensusResult:
        candidates = self._generate(blueprint)
        critiques = self._crossvalidate(blueprint.instruction, candidates)
        scores, families = self._aggregate(candidates, critiques)

        eligible = [
            c for c in candidates
            if self._verify(c.output)[0]
            and scores.get(c.id, 0.0) >= min_score
            and len(families.get(c.id, set())) >= min_families
        ]
        if eligible:
            winner = max(eligible, key=lambda c: scores[c.id])
            return ConsensusResult("selected", winner.output, winner, candidates, critiques, scores)

        if self.synthesizer is not None and candidates:
            synth = self._synthesize(blueprint, candidates, critiques)
            if synth and self._verify(synth)[0]:
                return ConsensusResult("synthesized", synth, None, candidates, critiques, scores)

        return ConsensusResult("none", "", None, candidates, critiques, scores)
