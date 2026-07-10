"""Tests for the 4 new principle analyzers (decoupling/encapsulation/convention/craft).

Each must honor the existing contract: analyze_file(path)->float in [0,1],
missing file → 1.0, unparseable → 0.5, and score good code higher than bad code.
"""

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from principles import convention, craft, decoupling, encapsulation  # noqa: E402

ANALYZERS = [decoupling, encapsulation, convention, craft]


def _write(tmp_path: Path, body: str) -> str:
    p = tmp_path / "sample.py"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_all_return_one_for_missing_file():
    for mod in ANALYZERS:
        assert mod.analyze_file("/nonexistent/xyz.py") == 1.0


def test_all_return_half_for_unparseable(tmp_path):
    bad = _write(tmp_path, "def (:::\n")
    for mod in ANALYZERS:
        assert mod.analyze_file(bad) == 0.5


def test_all_return_in_unit_range(tmp_path):
    src = _write(tmp_path, "import os\n\n\nclass A:\n    def m(self) -> int:\n        return os.getpid()\n")
    for mod in ANALYZERS:
        score = mod.analyze_file(src)
        assert 0.0 <= score <= 1.0


def test_decoupling_penalizes_train_wrecks(tmp_path):
    clean = _write(tmp_path, "def f(a):\n    return a\n")
    wreck_body = "def f(a):\n    return " + ".".join(["a"] * 8) + "\n"
    wreck = tmp_path / "wreck.py"
    wreck.write_text(wreck_body, encoding="utf-8")
    assert decoupling.analyze_file(clean) > decoupling.analyze_file(str(wreck))


def test_encapsulation_rewards_private_over_public(tmp_path):
    public = _write(tmp_path, "class A:\n    def __init__(self):\n        self.x = 1\n        self.y = 2\n")
    private = tmp_path / "priv.py"
    private.write_text(
        "class A:\n    def __init__(self):\n        self._x = 1\n        self._y = 2\n", encoding="utf-8",
    )
    assert encapsulation.analyze_file(str(private)) > encapsulation.analyze_file(public)


def test_convention_penalizes_bad_names(tmp_path):
    good = _write(tmp_path, "class MyThing:\n    def do_work(self, some_arg):\n        return some_arg\n")
    bad = tmp_path / "bad.py"
    bad.write_text("class my_thing:\n    def DoWork(self, SomeArg):\n        return SomeArg\n", encoding="utf-8")
    assert convention.analyze_file(good) > convention.analyze_file(str(bad))


def test_craft_rewards_docstrings_and_hints(tmp_path):
    crafted = _write(
        tmp_path,
        '"""Module."""\n\n\ndef f(a: int) -> int:\n    """Doc."""\n    return a\n',
    )
    bare = tmp_path / "bare.py"
    bare.write_text("def f(a):\n    return a\n", encoding="utf-8")
    assert craft.analyze_file(crafted) > craft.analyze_file(str(bare))


def test_empty_module_is_high(tmp_path):
    empty = _write(tmp_path, "")
    for mod in (encapsulation, convention, craft):
        assert mod.analyze_file(empty) >= 0.9
