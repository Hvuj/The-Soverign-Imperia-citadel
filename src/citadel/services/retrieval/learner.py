"""learner.py — the RetrieverLearner: turns retrieval outcomes into a self-tuned threshold (Phase Z1).

A fixed "0.95 cosine" cutoff is corpus-dependent and silently mis-serves (reference-plan weak-spot #2). The
learner instead watches the served-match hit rate and nudges the cosine threshold toward a target precision:
too many low-quality matches accepted → raise the bar; consistently clean → relax it. Bounded so it can
never collapse to 0 or lock at 1. State is a tiny JSON file so `citadel workers` can show it live.
"""

import json
import os
import tempfile
from pathlib import Path


class RetrieverLearner:
    def __init__(
        self,
        stats_path: str | Path,
        *,
        target_precision: float = 0.7,
        min_samples: int = 20,
        floor: float = 0.15,
        ceil: float = 0.9,
        step: float = 0.02,
    ) -> None:
        self.stats_path = Path(stats_path)
        self._target = target_precision
        self._min_samples = min_samples
        self._floor = floor
        self._ceil = ceil
        self._step = step
        self._queries = 0
        self._hits = 0
        self._threshold = 0.5
        self._load()

    def _load(self) -> None:
        if not self.stats_path.exists():
            return
        try:
            data = json.loads(self.stats_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self._queries = int(data.get("queries", 0))
        self._hits = int(data.get("hits", 0))
        self._threshold = float(data.get("threshold", 0.5))

    def record(self, hit: bool) -> None:
        """Log one served match as useful (hit) or not (miss) and re-tune once enough samples exist."""
        self._queries += 1
        if hit:
            self._hits += 1
        if self._queries >= self._min_samples:
            rate = self._hits / self._queries
            if rate < self._target:
                self._threshold = round(min(self._ceil, self._threshold + self._step), 4)
            elif rate > self._target + 0.1:
                self._threshold = round(max(self._floor, self._threshold - self._step), 4)
        self._save()

    def tuned_threshold(self) -> float:
        return self._threshold

    def stats(self) -> dict:
        """Display view (rounded). The threshold is already quantized, so it round-trips through save/load."""
        rate = (self._hits / self._queries) if self._queries else 0.0
        return {
            "worker": "retriever",
            "queries": self._queries,
            "hits": self._hits,
            "hit_rate": round(rate, 3),
            "threshold": self._threshold,
        }

    def _save(self) -> None:
        self.stats_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.stats_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.stats(), handle)
            os.replace(tmp, self.stats_path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
