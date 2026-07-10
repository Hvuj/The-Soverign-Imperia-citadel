"""Tests for the __legion__ compiled cache: unit serialization, invalidation, store, dedup."""

import pytest

from citadel.services.compile import LegionStore, LegionUnit, StaleUnit
from citadel.services.compile.compiler import LegionCompiler, compute_keys
from citadel.services.compile.unit import MAGIC, PY_TAG, SCHEMA_VERSION

SRC = b'''\
import os
from .helpers import thing


def top():
    return 1


class C:
    def m(self):
        return 2
'''


def test_compiler_matches_extractors():
    from citadel.services.index.symbols import extract_symbols

    unit = LegionCompiler().compile("pkg/mod.py", SRC)
    assert unit.module == "pkg.mod"
    assert unit.line_count > 0
    quals = {s["qualname"] for s in unit.symbols}
    direct = {s.qualname for s in extract_symbols(SRC.decode(), "", "pkg/mod.py")}
    assert quals == direct
    assert "pkg.helpers" in unit.imports or "pkg.helpers.thing" in unit.imports


def test_unit_roundtrip_and_symbols_for():
    unit = LegionCompiler().compile("pkg/mod.py", SRC)
    reloaded = LegionUnit.loads(unit.dumps(), expected_key=unit.cache_key)
    assert reloaded.module == unit.module
    syms = reloaded.symbols_for("repoX")
    assert all(s.repo == "repoX" for s in syms)
    assert any(s.qualname == "C.m" and s.kind == "method" for s in syms)


def test_invalidation_paths():
    unit = LegionCompiler().compile("pkg/mod.py", SRC)
    blob = unit.dumps()

    with pytest.raises(StaleUnit):
        LegionUnit.loads(b"XXXX" + blob[4:])
    with pytest.raises(StaleUnit):
        LegionUnit.loads(MAGIC + b"\x00\x01\x02not-marshal")
    with pytest.raises(StaleUnit):
        LegionUnit.loads(blob, expected_key="deadbeef")
    bad = LegionUnit.loads(blob)
    import marshal
    payload = marshal.loads(blob[4:])
    payload["v"] = SCHEMA_VERSION + 99
    with pytest.raises(StaleUnit):
        LegionUnit.loads(MAGIC + marshal.dumps(payload))
    payload["v"] = SCHEMA_VERSION
    payload["py"] = PY_TAG + "-alien"
    with pytest.raises(StaleUnit):
        LegionUnit.loads(MAGIC + marshal.dumps(payload))
    assert bad.module == "pkg.mod"


def test_compute_keys_folds_relpath():
    sha_a, key_a = compute_keys("a/x.py", SRC)
    sha_b, key_b = compute_keys("b/x.py", SRC)
    assert sha_a == sha_b
    assert key_a != key_b


def test_store_compile_then_hit(tmp_path):
    store = LegionStore(base=tmp_path / "__legion__")
    u1 = store.get("repoA", "pkg/mod.py", SRC)
    assert store.stats.compiles == 1
    assert store.stats.hits == 0
    u2 = store.get("repoA", "pkg/mod.py", SRC)
    assert store.stats.hits == 1
    assert store.stats.compiles == 1
    assert u1.cache_key == u2.cache_key


def test_store_cross_repo_dedup(tmp_path):
    store = LegionStore(base=tmp_path / "__legion__")
    store.get("repoA", "pkg/mod.py", SRC)
    store.get("repoB", "pkg/mod.py", SRC)
    assert store.stats.compiles == 1
    assert store.stats.hits == 1


def test_store_recompiles_on_change(tmp_path):
    store = LegionStore(base=tmp_path / "__legion__")
    store.get("repoA", "pkg/mod.py", SRC)
    changed = SRC + b"\n\ndef added():\n    return 3\n"
    unit = store.get("repoA", "pkg/mod.py", changed)
    assert store.stats.compiles == 2
    assert any(s["qualname"] == "added" for s in unit.symbols)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
