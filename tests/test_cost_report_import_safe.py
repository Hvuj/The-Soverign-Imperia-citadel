"""Regression test: importing claude_usage_cost_report must have NO side effects.

Before the main() guard, importing it (for its pricing helpers) scanned ~/.claude/projects
and wrote a PDF into the repo. This asserts import is silent, fast, side-effect-free, and
still exposes the helper names / main().
"""

import importlib
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def test_import_is_side_effect_free(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    sys.modules.pop("claude_usage_cost_report", None)

    buf = io.StringIO()
    with redirect_stdout(buf):
        mod = importlib.import_module("claude_usage_cost_report")

    assert buf.getvalue() == "", "import produced stdout (ran the report body)"
    assert not list(tmp_path.glob("**/*.pdf")), "import wrote a PDF"
    assert hasattr(mod, "main")
    assert hasattr(mod, "compute_cost")
