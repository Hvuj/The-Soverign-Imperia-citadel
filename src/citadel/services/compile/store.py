"""store.py — the on-disk `__legion__` cache: content-addressed facts + a mirror index.

Layout under ``.citadel/state/__legion__/``:
  facts/<key[:2]>/<key>.legion   compiled unit, keyed by (source_sha ⊕ relpath) → dedup
  facts/index.bloom              Bloom filter for O(1) "have we compiled this?" probes
  mirror/<repo>/<relpath>.ptr    per-(repo,path) pointer to the current key (locality)

``get()`` is the hot path: compute the key from the source bytes, Bloom-probe, load the
unit if fresh, else compile once and cache. Reuses ``tools/_content_address.BloomFilter``.
Fail-soft: a corrupt/stale unit is simply recompiled.
"""

import threading
from dataclasses import dataclass
from pathlib import Path

from citadel.paths import state_dir
from citadel.services._tools_bridge import import_tool
from citadel.services.compile.compiler import LegionCompiler, compute_keys
from citadel.services.compile.unit import LegionUnit, StaleUnit


@dataclass
class CompileStats:
    hits: int = 0
    compiles: int = 0
    stale: int = 0


class LegionStore:
    """Compile-once, read-many cache for per-file source facts."""

    def __init__(self, base: Path | None = None, compiler: LegionCompiler | None = None) -> None:
        self.base = base or (state_dir() / "state" / "__legion__")
        self.facts_dir = self.base / "facts"
        self.mirror_dir = self.base / "mirror"
        self.compiler = compiler or LegionCompiler()
        self.stats = CompileStats()
        self._lock = threading.Lock()
        bloom_cls = import_tool("_content_address").BloomFilter
        self._bloom_path = self.facts_dir / "index.bloom"
        if self._bloom_path.exists():
            self._bloom = bloom_cls.load(self._bloom_path)
        else:
            self._bloom = bloom_cls(capacity=500_000, fp_rate=0.0001)

    def _facts_path(self, key: str) -> Path:
        return self.facts_dir / key[:2] / f"{key}.legion"

    def _mirror_path(self, repo: str, relpath: str) -> Path:
        return self.mirror_dir / repo / f"{relpath}.ptr"

    def _write_mirror(self, repo: str, relpath: str, key: str) -> None:
        path = self._mirror_path(repo, relpath)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(key, encoding="utf-8")
        tmp.replace(path)

    def get(self, repo: str, relpath: str, source_bytes: bytes) -> LegionUnit:
        """Return the compiled unit for (repo, relpath, source), compiling on miss."""
        _source_sha, key = compute_keys(relpath, source_bytes)
        facts_path = self._facts_path(key)

        with self._lock:
            maybe_seen = self._bloom.contains_hash(key)
        if maybe_seen and facts_path.exists():
            try:
                unit = LegionUnit.loads(facts_path.read_bytes(), expected_key=key)
                self.stats.hits += 1
                self._write_mirror(repo, relpath, key)
                return unit
            except (StaleUnit, OSError):
                self.stats.stale += 1

        unit = self.compiler.compile(relpath, source_bytes)
        facts_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = facts_path.with_suffix(facts_path.suffix + ".tmp")
        tmp.write_bytes(unit.dumps())
        tmp.replace(facts_path)
        with self._lock:
            self._bloom.add_hash(key)
            self._bloom.save(self._bloom_path)
        self.stats.compiles += 1
        self._write_mirror(repo, relpath, key)
        return unit

    def get_path(self, repo: str, relpath: str, abs_path: Path) -> LegionUnit | None:
        """Convenience: read the file and compile/serve. None if unreadable."""
        try:
            return self.get(repo, relpath, Path(abs_path).read_bytes())
        except OSError:
            return None
