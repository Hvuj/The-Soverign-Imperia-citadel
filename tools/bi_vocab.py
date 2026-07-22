#!/usr/bin/env python3
"""bi_vocab.py — agnostic per-province vocabulary learning (the core anti-hardcoding fix).

The old BI code shipped an airline term list. The Cartographer instead **learns** each province's vocabulary
from its own evidence: the domain nouns that name and describe its logic units. Nothing domain-specific is
shipped — two provinces learn two different vocabularies. Deterministic, zero-token.
"""

import re
from collections import Counter

# generic English + programming stopwords — NOT domain terms (those are what we're learning)
_STOP_WORDS = (
    "a an the of to in on for with and or is are be this that it its as at by from into we you i "
    "def class return self value data get set new list dict str int float bool none true false if "
    "else elif for while try except with import name type object result output input func fn util "
    "helper method args kwargs param params test tests main run make build compute calc calculate"
)
_STOP = frozenset(_STOP_WORDS.split())
_SPLIT = re.compile(r"[^a-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _terms(text: str) -> list[str]:
    words = _SPLIT.split(_CAMEL.sub(" ", text or "").lower())
    return [w for w in words if len(w) >= 3 and not w.isdigit() and w not in _STOP]


def learn_vocab(evidence, *, top: int = 200) -> dict:
    """Learn the province vocabulary: frequency-ranked domain terms drawn from unit names + snippets, and
    the kinds each term associates with. Returns {"terms": {term: {"count", "kinds"}}, "size"}."""
    counts: Counter[str] = Counter()
    kinds: dict[str, set[str]] = {}
    for e in evidence:
        toks = _terms(getattr(e, "unit", "")) + _terms(getattr(e, "snippet", ""))
        for t in toks:
            counts[t] += 1
            kinds.setdefault(t, set()).add(getattr(e, "kind", "term"))
    terms = {
        t: {"count": c, "kinds": sorted(kinds.get(t, set()))}
        for t, c in counts.most_common(top)
    }
    return {"terms": terms, "size": len(terms)}


def vocab_terms(vocab: dict) -> set[str]:
    return set(vocab.get("terms", {}))
