#!/usr/bin/env python3
"""bi_synthesize.py — per-unit assembly + confidence (Pandidakterion Rhetoric + self-awareness).

Groups the raw evidence atoms into **logic units** and scores each with a confidence that reflects how much
independent support it has: more evidence, from more distinct source files, of a consistent kind → higher
confidence. Every unit carries its provenance (evidence[]) so the Sovereign can see *why* the Citadel
believes it — self-awareness for zero tokens. Deterministic.
"""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field

_NORM = re.compile(r"[^a-z0-9]+")


def _norm(name: str) -> str:
    return _NORM.sub("_", (name or "").lower()).strip("_") or "unnamed"


@dataclass(slots=True)
class Unit:
    name: str
    kind: str
    confidence: float
    evidence: list[dict] = field(default_factory=list)
    content_hash: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "confidence": round(self.confidence, 3),
                "evidence": self.evidence, "content_hash": self.content_hash}


def _confidence(evidence: list) -> tuple[float, str]:
    """Confidence from support: distinct source files (independence) x total weight, saturating. Also returns
    the dominant kind (weighted vote across evidence)."""
    sources = {getattr(e, "source_path", "") for e in evidence}
    total_weight = sum(getattr(e, "weight", 0.5) for e in evidence)
    diversity = min(1.0, len(sources) / 3.0)            # 3+ independent files → full diversity credit
    support = min(1.0, total_weight / 3.0)              # saturate around 3 weighted hits
    confidence = round(0.5 * diversity + 0.5 * support, 3)
    # dominant kind by WEIGHTED vote: a code metric (weight 1.0) outranks a doc mention (term, 0.5)
    kind_weight: Counter[str] = Counter()
    for e in evidence:
        kind_weight[getattr(e, "kind", "term")] += getattr(e, "weight", 0.5)
    kind = kind_weight.most_common(1)[0][0]
    return confidence, kind


def synthesize(evidence, *, min_confidence: float = 0.0) -> list[Unit]:
    """Assemble evidence into confidence-scored units, sorted most-confident first."""
    grouped: dict[str, list] = {}
    for e in evidence:
        grouped.setdefault(_norm(getattr(e, "unit", "")), []).append(e)
    units: list[Unit] = []
    for name, ev in grouped.items():
        confidence, kind = _confidence(ev)
        if confidence < min_confidence:
            continue
        ev_dicts = sorted(
            ({"source_path": getattr(e, "source_path", ""), "line": getattr(e, "line", 0),
              "kind": getattr(e, "kind", "term"), "weight": getattr(e, "weight", 0.5),
              "snippet": getattr(e, "snippet", "")} for e in ev),
            key=lambda d: (-d["weight"], d["source_path"], d["line"]),
        )
        ch = hashlib.blake2b(
            f"{name}|{kind}|{sorted((d['source_path'], d['line']) for d in ev_dicts)}".encode(),
            digest_size=12,
        ).hexdigest()
        units.append(Unit(name=name, kind=kind, confidence=confidence, evidence=ev_dicts, content_hash=ch))
    units.sort(key=lambda u: (-u.confidence, u.name))
    return units


def scorecard(units: list[Unit]) -> dict:
    """A self-awareness summary: how much the Citadel knows about this province and how well."""
    by_kind = Counter(u.kind for u in units)
    confident = sum(1 for u in units if u.confidence >= 0.6)
    avg = round(sum(u.confidence for u in units) / len(units), 3) if units else 0.0
    return {
        "units": len(units),
        "confident_units": confident,
        "avg_confidence": avg,
        "by_kind": dict(by_kind),
        "low_confidence": [u.name for u in units if u.confidence < 0.4][:20],
    }
