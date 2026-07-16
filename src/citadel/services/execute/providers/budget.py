"""budget.py — a per-provider budget/rate guard for the cloud federation (Phase 4).

Free tiers are finite: NVIDIA gives ~1000 credits, Groq rate-limits. The guard counts calls per provider,
enforces an optional hard cap, and — reactively — **throttles a provider on a rate-limit (429)** so the
router deprioritizes it and falls back to local/another provider. State persists so a cap survives restarts.
Everything degrades gracefully: no cap + no throttle = unlimited (bounded only by the provider itself).
"""

import json
import os
import tempfile
from pathlib import Path


class BudgetGuard:
    def __init__(self, *, path: str | Path | None = None, caps: dict[str, int] | None = None) -> None:
        self._path = Path(path) if path else None
        self._caps = dict(caps or {})
        self._counts: dict[str, int] = {}
        self._throttled: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._counts = dict(data.get("counts", {}))
            self._throttled = set(data.get("throttled", []))
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"counts": self._counts, "throttled": sorted(self._throttled)}
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def allow(self, provider: str) -> bool:
        """False when the provider is throttled (429) or has hit its hard cap."""
        if provider in self._throttled:
            return False
        cap = self._caps.get(provider)
        return cap is None or self._counts.get(provider, 0) < cap

    def record(self, provider: str) -> None:
        self._counts[provider] = self._counts.get(provider, 0) + 1
        self._save()

    def throttle(self, provider: str) -> None:
        """Mark a provider as rate-limited (deprioritized until cleared)."""
        self._throttled.add(provider)
        self._save()

    def clear_throttle(self, provider: str) -> None:
        self._throttled.discard(provider)
        self._save()

    def remaining(self, provider: str) -> int | None:
        cap = self._caps.get(provider)
        return None if cap is None else max(0, cap - self._counts.get(provider, 0))

    def stats(self) -> dict:
        return {
            "counts": dict(self._counts),
            "throttled": sorted(self._throttled),
            "caps": dict(self._caps),
        }
