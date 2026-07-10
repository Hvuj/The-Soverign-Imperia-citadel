"""
Content-addressed storage primitives for SOVEREIGN-IMPERIA-CITADEL.

Core guarantees:
  - Same content → same hash, idempotent writes, O(1) Bloom probe before any disk I/O.
  - Canonical form strips encoding/whitespace variance so trivially-different
    representations of the same document get the same hash.
  - ByteSpan ties every claim back to an exact char range in an immutable Bronze source.

All heavy data-structure operations (MinHash, HNSW, FTS5) live in their respective daemon
modules. This module owns only: canonicalization, hashing, byte-span bookkeeping, and
the Bloom filter that gates those paths.
"""


import hashlib
import json
import math
import struct
import threading
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


def canonicalize(text: str) -> bytes:
    """
    Normalize text to a deterministic byte representation.

    Steps (order matters):
      1. Unicode NFC normalization — composed form is canonical.
      2. Strip leading/trailing whitespace.
      3. Normalize line endings to LF.
      4. Collapse runs of whitespace within lines to a single space.
      5. Encode as UTF-8.

    The resulting bytes are used as the canonical form for content-addressing.
    Any two strings that differ only in encoding, whitespace, or line endings
    will produce the same canonical bytes and therefore the same hash.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(lines).encode("utf-8")


def canonicalize_bytes(data: bytes, encoding: str = "utf-8") -> bytes:
    """Decode bytes to str and re-canonicalize."""
    return canonicalize(data.decode(encoding, errors="replace"))


def content_hash(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes. Use canonical bytes for text."""
    return hashlib.sha256(data).hexdigest()


def text_hash(text: str) -> str:
    """Convenience: canonicalize + SHA-256 hex."""
    return content_hash(canonicalize(text))


@dataclass(frozen=True, slots=True)
class ByteSpan:
    """
    Immutable pointer to a character range inside a Bronze source.

    source_hash  : SHA-256 of the Bronze source canonical bytes
    char_start   : inclusive start offset in the canonical bytes
    char_end     : exclusive end offset (char_end > char_start)
    source_path  : informational relative path (hash is authoritative)
    """
    source_hash: str
    char_start: int
    char_end: int
    source_path: str = ""

    def __post_init__(self) -> None:
        if len(self.source_hash) != 64:
            raise ValueError(f"source_hash must be 64-char SHA-256 hex, got {len(self.source_hash)}")
        if self.char_start < 0:
            raise ValueError(f"char_start must be ≥ 0, got {self.char_start}")
        if self.char_end <= self.char_start:
            raise ValueError(f"char_end ({self.char_end}) must be > char_start ({self.char_start})")

    def extract(self, canonical_bytes: bytes) -> bytes:
        """Slice the referenced span out of canonical source bytes."""
        return canonical_bytes[self.char_start:self.char_end]

    def verify(self, canonical_bytes: bytes, claimed_text: str) -> bool:
        """
        L1 provenance check: confirm the span actually contains the claimed text
        when extracted from the canonical source.
        """
        extracted = self.extract(canonical_bytes)
        return extracted == canonicalize(claimed_text)

    def to_dict(self) -> dict:
        return {
            "source_hash": self.source_hash,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "source_path": self.source_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ByteSpan":
        return cls(
            source_hash=d["source_hash"],
            char_start=d["char_start"],
            char_end=d["char_end"],
            source_path=d.get("source_path", ""),
        )


def find_span(source_canonical: bytes, snippet: str) -> ByteSpan | None:
    """
    Find the byte range of snippet within canonical source bytes.
    Returns None if not found.
    Used by silver_structurer to anchor extracted claims.
    """
    source_hash = content_hash(source_canonical)
    needle = canonicalize(snippet)
    idx = source_canonical.find(needle)
    if idx == -1:
        return None
    return ByteSpan(
        source_hash=source_hash,
        char_start=idx,
        char_end=idx + len(needle),
    )


class BloomFilter:
    """
    Space-efficient probabilistic set with configurable false-positive rate.

    Persistence: serialised as a compact binary header + bit array so it survives
    daemon restarts. Call save(path) / BloomFilter.load(path) for persistence.

    Thread-safety: _lock guards all mutating operations.

    Target: false-positive rate < 0.01% at the configured capacity.
    """

    _MAGIC = b"VBFX"
    _VERSION = 1

    def __init__(self, capacity: int = 1_000_000, fp_rate: float = 0.0001) -> None:
        if capacity < 1:
            raise ValueError("capacity must be ≥ 1")
        if not (0 < fp_rate < 1):
            raise ValueError("fp_rate must be in (0, 1)")

        self.capacity = capacity
        self.fp_rate = fp_rate
        self._n_bits = self._optimal_bits(capacity, fp_rate)
        self._n_hashes = self._optimal_hashes(self._n_bits, capacity)
        self._bits = bytearray(math.ceil(self._n_bits / 8))
        self._count = 0
        self._lock = threading.Lock()

    def add(self, item: str) -> None:
        """Add item (string) to the filter."""
        with self._lock:
            for idx in self._hash_indices(item):
                self._bits[idx >> 3] |= 1 << (idx & 7)
            self._count += 1

    def __contains__(self, item: str) -> bool:
        """
        Return False if item is definitely not in the set.
        Return True if item *might* be in the set (with low false-positive rate).
        """
        for idx in self._hash_indices(item):
            if not (self._bits[idx >> 3] & (1 << (idx & 7))):
                return False
        return True

    def add_hash(self, sha256_hex: str) -> None:
        """Convenience: add a pre-computed SHA-256 hash string."""
        self.add(sha256_hex)

    def contains_hash(self, sha256_hex: str) -> bool:
        return sha256_hex in self

    @property
    def count(self) -> int:
        return self._count

    def estimated_fp_rate(self) -> float:
        """Actual FP rate given current fill level."""
        if self._n_bits == 0:
            return 1.0
        fill_ratio = self._count / self._n_bits
        return (1 - math.exp(-self._n_hashes * fill_ratio)) ** self._n_hashes

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            header = struct.pack(
                ">4sBIIIIQ",
                self._MAGIC,
                self._VERSION,
                self._n_bits,
                self._n_hashes,
                self.capacity,
                len(self._bits),
                self._count,
            )
            with path.open("wb") as f:
                f.write(header)
                f.write(self._bits)

    @classmethod
    def load(cls, path: Path | str) -> "BloomFilter":
        path = Path(path)
        with path.open("rb") as f:
            raw = f.read(struct.calcsize(">4sBIIIIQ"))
            magic, version, n_bits, n_hashes, capacity, bits_len, count = struct.unpack(
                ">4sBIIIIQ", raw
            )
        if magic != cls._MAGIC:
            raise ValueError(f"Not a Citadel Bloom filter file: {path}")
        obj = cls.__new__(cls)
        obj.capacity = capacity
        obj.fp_rate = cls._optimal_fp_rate(n_bits, capacity, n_hashes)
        obj._n_bits = n_bits
        obj._n_hashes = n_hashes
        obj._count = count
        obj._lock = threading.Lock()
        with path.open("rb") as f:
            f.seek(struct.calcsize(">4sBIIIIQ"))
            obj._bits = bytearray(f.read(bits_len))
        return obj

    def _hash_indices(self, item: str) -> Iterator[int]:
        """
        Double-hashing scheme: two independent SHA-256 digests combine to
        produce k independent hash indices without calling SHA-256 k times.
        """
        h = hashlib.sha256(item.encode("utf-8")).digest()
        h1 = int.from_bytes(h[:8], "big")
        h2 = int.from_bytes(h[8:16], "big")
        for i in range(self._n_hashes):
            yield (h1 + i * h2) % self._n_bits

    @staticmethod
    def _optimal_bits(capacity: int, fp_rate: float) -> int:
        return max(1, math.ceil(-capacity * math.log(fp_rate) / (math.log(2) ** 2)))

    @staticmethod
    def _optimal_hashes(n_bits: int, capacity: int) -> int:
        return max(1, round((n_bits / capacity) * math.log(2)))

    @staticmethod
    def _optimal_fp_rate(n_bits: int, capacity: int, n_hashes: int) -> float:
        try:
            return (1 - math.exp(-n_hashes * capacity / n_bits)) ** n_hashes
        except ZeroDivisionError:
            return 1.0


class ContentStore:
    """
    Thread-safe content-addressed file store.

    Layout:  <root>/<prefix2>/<hash>.json  (2-char prefix sharding)
    Index:   <root>/index.bloom  (Bloom filter for O(1) negative lookups)

    write_addressed(content_bytes, meta)  →  sha256_hex
      - Bloom probe first: if definitely not seen, compute hash, write, add to Bloom.
      - If Bloom says maybe-seen, confirm with file existence (rare).
      - If already exists: no-op, returns existing hash.

    lookup(sha256_hex)  →  Path | None
    """

    def __init__(
        self,
        root: Path | str,
        capacity: int = 500_000,
        fp_rate: float = 0.0001,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._bloom_path = self.root / "index.bloom"
        self._bloom = (
            BloomFilter.load(self._bloom_path)
            if self._bloom_path.exists()
            else BloomFilter(capacity=capacity, fp_rate=fp_rate)
        )
        self._lock = threading.Lock()

    def write_addressed(self, content_bytes: bytes, meta: dict | None = None) -> str:
        """
        Write content_bytes under its SHA-256 hash. Returns hash hex.
        Idempotent: if hash already exists, returns existing hash without writing.
        meta is stored as sidecar JSON; pass None to skip.
        """
        sha = content_hash(content_bytes)
        with self._lock:
            if sha in self._bloom:
                if self._path_for(sha).exists():
                    return sha
            dest = self._path_for(sha)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content_bytes)
            if meta is not None:
                dest.with_suffix(".meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            self._bloom.add_hash(sha)
            self._bloom.save(self._bloom_path)
        return sha

    def lookup(self, sha256_hex: str) -> Path | None:
        """Return path to content file if it exists, else None."""
        if sha256_hex not in self._bloom:
            return None
        p = self._path_for(sha256_hex)
        return p if p.exists() else None

    def read(self, sha256_hex: str) -> bytes | None:
        p = self.lookup(sha256_hex)
        return p.read_bytes() if p else None

    def _path_for(self, sha256_hex: str) -> Path:
        return self.root / sha256_hex[:2] / f"{sha256_hex}.bin"

    @property
    def bloom_fp_rate(self) -> float:
        return self._bloom.estimated_fp_rate()


def claim_id(text: str) -> str:
    """
    Stable ID for an atomic claim: SHA-256 of the normalized (lowercased, stripped) text.
    Lowercasing is intentional — claim identity is semantic, not orthographic.
    """
    normalized = canonicalize(text.lower())
    return content_hash(normalized)


if __name__ == "__main__":
    import tempfile

    print("=== _content_address smoke test ===")

    a = canonicalize("  Hello   World\r\n  ")
    b = canonicalize("Hello World\n")
    assert a == b, "canonicalize must collapse whitespace variants"
    print(f"  canonicalize: OK  ({a!r})")

    h1 = content_hash(a)
    h2 = text_hash("Hello World")
    assert h1 == h2, "hash must be deterministic over canonical form"
    print(f"  content_hash: OK  ({h1[:16]}...)")

    src = "The quick brown fox jumps over the lazy dog."
    src_bytes = canonicalize(src)
    src_hash = content_hash(src_bytes)
    span = find_span(src_bytes, "brown fox")
    assert span is not None, "find_span must locate the snippet"
    assert span.verify(src_bytes, "brown fox"), "verify must confirm the span"
    print(f"  ByteSpan: OK  (chars {span.char_start}–{span.char_end})")

    bf = BloomFilter(capacity=1000, fp_rate=0.001)
    bf.add("alpha")
    bf.add("beta")
    assert "alpha" in bf, "alpha must be in filter"
    assert "gamma" not in bf, "gamma must not be in filter"
    print(f"  BloomFilter: OK  (fp_rate ~{bf.estimated_fp_rate():.6f})")

    with tempfile.NamedTemporaryFile(suffix=".bloom", delete=False) as tmp:
        bloom_path = tmp.name
    bf.save(bloom_path)
    bf2 = BloomFilter.load(bloom_path)
    assert "alpha" in bf2
    assert "gamma" not in bf2
    print(f"  BloomFilter persistence: OK")

    with tempfile.TemporaryDirectory() as tmpdir:
        store = ContentStore(tmpdir)
        data = b"Hello, SOVEREIGN-IMPERIA-CITADEL content store"
        sha = store.write_addressed(data, meta={"source": "test"})
        assert store.read(sha) == data, "stored content must round-trip"
        sha2 = store.write_addressed(data)
        assert sha == sha2, "same content must produce same hash"
        print(f"  ContentStore: OK  (hash={sha[:16]}...)")

    print("=== All checks passed ===")
