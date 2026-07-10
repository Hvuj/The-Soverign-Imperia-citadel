"""Tests for the AST symbol index — extraction, O(1) lookup, O(log N) enclosing."""

from citadel.services.index.symbols import AstSymbolIndex, extract_symbols

SAMPLE = '''\
import os


def top_level():
    x = 1
    return x


class Widget:
    def method_a(self):
        return 1

    async def method_b(self):
        def inner():
            return 2
        return inner()


async def afunc():
    return 3
'''


def test_extract_symbols_kinds_and_spans():
    syms = extract_symbols(SAMPLE, repo="demo", relpath="w.py")
    by_name = {s.qualname: s for s in syms}

    assert by_name["top_level"].kind == "function"
    assert by_name["Widget"].kind == "class"
    assert by_name["Widget.method_a"].kind == "method"
    assert by_name["Widget.method_b"].kind == "method"
    assert by_name["Widget.method_b.inner"].kind == "function"
    assert by_name["afunc"].kind == "async_function"

    tl = by_name["top_level"]
    assert tl.start_line == 4
    assert tl.end_line == 6
    assert tl.contains(5)
    assert not tl.contains(7)


def test_syntax_error_yields_empty():
    assert extract_symbols("def broken(:\n", "demo", "bad.py") == []


def test_lookup_is_exact():
    idx = AstSymbolIndex(extract_symbols(SAMPLE, "demo", "w.py"))
    assert idx.lookup("demo", "Widget.method_a") is not None
    assert idx.lookup("demo", "does.not.exist") is None
    assert idx.lookup("other", "top_level") is None


def test_enclosing_returns_innermost():
    idx = AstSymbolIndex(extract_symbols(SAMPLE, "demo", "w.py"))

    inner = idx.lookup("demo", "Widget.method_b.inner")
    hit = idx.enclosing("demo", "w.py", inner.start_line)
    assert hit is not None
    assert hit.qualname == "Widget.method_b.inner"

    method_a = idx.lookup("demo", "Widget.method_a")
    hit2 = idx.enclosing("demo", "w.py", method_a.start_line + 1)
    assert hit2 is not None
    assert hit2.qualname == "Widget.method_a"

    assert idx.enclosing("demo", "w.py", 1) is None
    assert idx.enclosing("demo", "nope.py", 5) is None


def test_roundtrip_save_load(tmp_path):
    idx = AstSymbolIndex(extract_symbols(SAMPLE, "demo", "w.py"))
    out = tmp_path / "symbols.json"
    idx.save(out)
    reloaded = AstSymbolIndex.load(out)
    assert len(reloaded) == len(idx)
    assert reloaded.lookup("demo", "afunc") is not None
